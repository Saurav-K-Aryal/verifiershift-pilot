#!/usr/bin/env python3
"""Controlled typed-evidence replay; not a tau2 agent leaderboard evaluation."""
from __future__ import annotations
import argparse, collections, copy, hashlib, itertools, json, platform, statistics, sys, time, types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'work/repair01_20261101'
UP = WORK / 'upstream_tau'
sys.path.insert(0, str(WORK / 'deps'))
# Avoid tau2's package-level runner/paid-model imports. Every domain model,
# tool method, decorator and utility below is still loaded unmodified upstream.
package = types.ModuleType('tau2'); package.__path__ = [str(UP / 'src/tau2')]
sys.modules['tau2'] = package
from tau2.domains.retail.tools import RetailTools
from tau2.domains.retail.data_model import RetailDB
import z3

DATA = UP / 'data/tau2/domains/retail'
ATOMS = ('auth', 'owner', 'status', 'request', 'amount')
METHODS = ('always_fresh','dependency_validity','cached_projection','semantic_z3','compiled_capsule')
EDITS = ('policy_equivalent','policy_weaken_request','policy_decision_change',
         'policy_new_amount_cap_500','source_relevant_status','source_relevant_owner','source_irrelevant_address',
         'unsupported_external_risk','unknown_tool_semantics')
ORDER_WRITES = {'cancel_pending_order','exchange_delivered_order_items',
                'modify_pending_order_address','modify_pending_order_items',
                'modify_pending_order_payment','return_delivered_order_items'}
def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str)+'\n')
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def encoded(x): return json.dumps(x,sort_keys=True,separators=(',',':')).encode()
def scalar_count(x):
    if isinstance(x,dict): return sum(scalar_count(v) for v in x.values())
    if isinstance(x,list): return sum(scalar_count(v) for v in x)
    return 1

def formula(edit, v):
    a,o,s,r,m = (v[k] for k in ATOMS)
    AND = z3.And if isinstance(a,z3.BoolRef) else lambda *x: all(x)
    NOT = z3.Not if isinstance(a,z3.BoolRef) else lambda x: not x
    if edit == 'policy_weaken_request': return AND(a,o,s)
    if edit == 'policy_decision_change': return AND(a,o,NOT(s),r)
    if edit == 'policy_new_amount_cap_500': return AND(a,o,s,r,m)
    if edit == 'policy_equivalent': return AND(r,s,o,a)
    return AND(a,o,s,r)

def field_facts(order, action, authenticated):
    """A deliberately restricted, documented fragment of retail preconditions."""
    name, args = action['name'], action['arguments']
    status = 'delivered' if name.startswith(('return','exchange')) else 'pending'
    if name == 'cancel_pending_order':
        request = args.get('reason') in {'ordered by mistake','no longer needed'}
    elif 'item_ids' in args:
        wanted = args['item_ids']; present = {i.item_id for i in order.items}
        request = bool(wanted) and set(wanted).issubset(present)
    elif name == 'modify_pending_order_address':
        request = all(bool(args.get(k)) for k in ('address1','city','country','state','zip'))
    else:
        request = bool(args.get('payment_method_id'))
    return {'auth':authenticated is not None, 'owner':order.user_id == authenticated,
            'status':order.status == status, 'request':request,
            'amount':sum(i.price for i in order.items) <= 500}

def native_postcondition(name, order):
    expected = {'cancel_pending_order':'cancelled',
                'return_delivered_order_items':'return requested',
                'exchange_delivered_order_items':'exchange requested',
                'modify_pending_order_items':'pending (item modified)',
                'modify_pending_order_address':'pending',
                'modify_pending_order_payment':'pending'}
    return order.status == expected[name]

def replay(task, base_db):
    """Use expected trace only to exercise real tools, never to score an actor."""
    tools = RetailTools(base_db.model_copy(deep=True))
    authenticated = None; history=[]
    for action in (task.get('evaluation_criteria') or {}).get('actions',[]):
        name,args = action['name'],action['arguments']
        if name in ORDER_WRITES:
            # Snapshot is taken before the first actual public order write.
            oid=args['order_id']; order=tools.get_order_details(oid).model_copy(deep=True)
            before=tools.db.model_copy(deep=True)
            try:
                result=getattr(tools,name)(**args)
                return {'task_id':task['id'],'family':name,'action':action,
                        'observed_authentication_witness':authenticated,
                        'authenticated':order.user_id,'order_id':oid,
                        'session_assumption':'trusted post-authenticated caller context fixed to original fixture owner; not observed actor authentication',
                        'initial_order':order,'db':before,'history':history,
                        'native_write_success':True,
                        'native_postcondition':native_postcondition(name,result),
                        'capture_bytes':len(encoded(order.model_dump())),
                        'capture_raw_scalars':scalar_count(order.model_dump())}
            except Exception as e:
                return {'task_id':task['id'],'family':name,'excluded':'native_write_error',
                        'error':f'{type(e).__name__}: {e}','history':history}
        try:
            result=getattr(tools,name)(**args)
            history.append({'name':name,'arguments':args,'success':True})
            if name.startswith('find_user_id_'): authenticated=result
        except Exception as e:
            return {'task_id':task['id'],'family':name,'excluded':'prefix_tool_error',
                    'error':f'{type(e).__name__}: {e}','history':history}
    return {'task_id':task['id'],'excluded':'no_order_write','history':history}

class Compiled:
    """Exact finite-domain LUT, ordinary compilation; not new logic theory."""
    def __init__(self,edit):
        self.rows=[(dict(zip(ATOMS,bits)),formula(edit,dict(zip(ATOMS,bits))))
                   for bits in itertools.product((False,True),repeat=len(ATOMS))]
    def decide(self,known):
        outcomes={out for vals,out in self.rows
                  if all(vals[k]==v for k,v in known.items())}
        return next(iter(outcomes)) if len(outcomes)==1 else None

class Semantic:
    def __init__(self,edit):
        self.v={k:z3.Bool(k) for k in ATOMS}; self.f=formula(edit,self.v)
        self.s=z3.Solver()
    def decide(self,known):
        self.s.push()
        self.s.add(*[self.v[k]==v for k,v in known.items()])
        self.s.push(); self.s.add(self.f); pos=self.s.check()==z3.sat;self.s.pop()
        self.s.push(); self.s.add(z3.Not(self.f)); neg=self.s.check()==z3.sat;self.s.pop()
        self.s.pop()
        return True if pos and not neg else False if neg and not pos else None

def required(edit):
    return set(ATOMS) if edit=='policy_new_amount_cap_500' else set(ATOMS[:3]) if edit=='policy_weaken_request' else set(ATOMS[:4])

def ordinary_partial(edit,known):
    # Ordinary strong Kleene evaluation of these conjunctions, including NOT
    # of status. A false known conjunct rejects without fetching other inputs.
    terms=[]
    for k in required(edit):
        v=known.get(k,None)
        if k=='status' and edit=='policy_decision_change' and v is not None:v=not v
        terms.append(v)
    if False in terms:return False
    return True if all(v is True for v in terms) else None

def run_episode(record,edit,method,compiled,semantic):
    # Isolate the order being edited; the public read tool does not mutate any
    # other source. Initial trace replay above still uses a full independent DB.
    db=record['db'].model_copy(deep=False)
    db.orders=dict(db.orders)
    oid=record['order_id']; old=record['initial_order']
    db.orders[oid]=db.orders[oid].model_copy(deep=True)
    oldfacts=field_facts(old,record['action'],record['authenticated'])
    changed=[]
    if edit=='source_relevant_status':
        db.orders[oid].status='processed'; changed=['order.status']
    if edit=='source_relevant_owner':
        db.orders[oid].user_id=next(uid for uid in db.users if uid != record['authenticated'])
        changed=['order.user_id']
    if edit=='source_irrelevant_address':
        db.orders[oid].address.zip='00000'; changed=['order.address.zip']
    # Ground truth is a separate audit of the current public source, never
    # passed to the policy under evaluation before its explicit read request.
    current=field_facts(db.orders[oid],record['action'],record['authenticated'])
    supported=edit not in {'unsupported_external_risk','unknown_tool_semantics'}
    truth=formula(edit,current) if supported else None
    known={k:oldfacts[k] for k in ATOMS[:4]}
    if method=='cached_projection': known['amount']=oldfacts['amount']
    if 'order.status' in changed: known.pop('status',None)
    if 'order.user_id' in changed: known.pop('owner',None)
    notices={'changed_paths':changed,'tool_semantics_known':edit!='unknown_tool_semantics',
             'policy_fragment_known':edit!='unsupported_external_risk'}
    reads=0; transport_ns=0
    start=time.perf_counter_ns()
    if not supported:
        decision=None
    else:
        if method=='always_fresh':
            decision=None
        elif method in ('dependency_validity','cached_projection'):
            # Strong selective baseline: recompute only when declared inputs
            # survive validity checks and suffice for the new formula.
            decision=ordinary_partial(edit,known)
        else:
            tick=time.perf_counter_ns()
            decision=(semantic if method=='semantic_z3' else compiled).decide(known)
            transport_ns=time.perf_counter_ns()-tick
        if decision is None:
            observed=RetailTools(db).get_order_details(oid)
            reads+=1
            # Auth and request evidence remains captured in the trusted test
            # harness; this read only resolves order-sourced missing facts.
            fresh=field_facts(observed,record['action'],record['authenticated'])
            decision=formula(edit,fresh)
    elapsed=time.perf_counter_ns()-start
    return {'task_id':record['task_id'],'family':record['family'],'edit':edit,'method':method,
            'decision':decision,'truth':truth,'supported':supported,
            'correct':decision==truth,'false_accept':decision is True and truth is False,
            'reads':reads,'online_ns':elapsed,'transport_ns':transport_ns,
            'notices':notices,'known_before_read':known}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--split',choices=['train','test'],required=True)
    ap.add_argument('--output',required=True); args=ap.parse_args()
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    started=time.time()
    tasks=json.loads((DATA/'tasks.json').read_text())
    splits=json.loads((DATA/'split_tasks.json').read_text())
    selected=[t for t in tasks if t['id'] in set(splits[args.split])]
    base=RetailDB.load(DATA/'db.json')
    compilation={}; compiled={}; semantic={}
    for e in EDITS:
        t=time.perf_counter_ns();compiled[e]=Compiled(e)
        compilation[e]={'lut_compile_ns':time.perf_counter_ns()-t}
        t=time.perf_counter_ns();semantic[e]=Semantic(e)
        compilation[e]['solver_setup_ns']=time.perf_counter_ns()-t
    records=[];rows=[];retention=[]
    for task in selected:
        rec=replay(task,base);records.append(rec)
        if 'excluded' in rec: continue
        facts=field_facts(rec['initial_order'],rec['action'],rec['authenticated'])
        # Provenance included in serialized retention comparison; versions are
        # local trusted wrappers, not signatures or native tau2 capabilities.
        meta={'source_record_sha256':hashlib.sha256(encoded(rec['initial_order'].model_dump())).hexdigest(),
              'policy_sha256':hashlib.sha256(b'four-predicate-fragment-v1').hexdigest(),
              'adapter_sha256':sha(Path(__file__)), 'source_version':0}
        capsule={'facts':{k:facts[k] for k in ATOMS[:4]},'provenance':meta,
                 'dependencies':{'auth':['auth_event'],'owner':['order.user_id','auth_event'],
                                 'status':['order.status'],'request':['action.arguments','order.items']}}
        projection={'status':rec['initial_order'].status,'owner_id':rec['initial_order'].user_id,
                    'item_ids':[x.item_id for x in rec['initial_order'].items],
                    'total':sum(x.price for x in rec['initial_order'].items),'provenance':meta}
        raw={'payload':rec['initial_order'].model_dump(),'provenance':meta}
        retention.append({'task_id':task['id'],'raw_bytes':len(encoded(raw)),
                          'projection_bytes':len(encoded(projection)),
                          'capsule_bytes':len(encoded(capsule)),
                          'raw_scalar_fields':rec['capture_raw_scalars'],
                          'projection_raw_scalar_fields':3+len(projection['item_ids']),
                          'capsule_raw_scalar_fields':0,
                          'capsule_predicate_bits':4})
        for edit in EDITS:
            for method in METHODS: rows.append(run_episode(rec,edit,method,compiled[edit],semantic[edit]))
    audit=[]
    for rec in records:
        audit.append({k:v for k,v in rec.items() if k not in {'initial_order','db'}})
    dump(out/'native_replay.json',audit);dump(out/'retention.json',retention)
    with (out/'episodes.jsonl').open('w') as f:
        for row in rows:f.write(json.dumps(row,sort_keys=True)+'\n')
    summary={'protocol_id':'repair01-capsule-v2','split':args.split,
             'source_task_groups':len(selected),'eligible_task_groups':len(retention),
             'exclusions':dict(collections.Counter(r.get('excluded','eligible') for r in records)),
             'family_counts':dict(collections.Counter(r['family'] for r in records if 'excluded' not in r)),
             'native_write_success':sum(r.get('native_write_success',False) for r in records),
             'native_postcondition_pass':sum(r.get('native_postcondition',False) for r in records),
             'observed_auth_witness_groups':sum(bool(r.get('observed_authentication_witness')) for r in records if 'excluded' not in r),
             'post_authenticated_session_assumption':True,
             'methods':{},'by_edit':{},'compilation':compilation,
             'elapsed_seconds':time.time()-started,'python':sys.version,
             'platform':platform.platform(),'z3':z3.get_version_string(),
             'files_sha256':{'experiment.py':sha(Path(__file__)),'protocol':sha(WORK/'protocol_v2.json'),
                             'upstream_tools':sha(UP/'src/tau2/domains/retail/tools.py'),
                             'upstream_tasks':sha(DATA/'tasks.json'),'upstream_db':sha(DATA/'db.json')}}
    for method in METHODS:
        rr=[r for r in rows if r['method']==method];ss=[r for r in rr if r['supported']]
        summary['methods'][method]={'episodes':len(rr),'supported':len(ss),
            'correct':sum(r['correct'] for r in rr),'supported_correct':sum(r['correct'] for r in ss),
            'false_accepts':sum(r['false_accept'] for r in rr),
            'review':sum(r['decision'] is None for r in rr),'verification_reads':sum(r['reads'] for r in rr),
            'online_median_us':statistics.median(r['online_ns'] for r in rr)/1000,
            'online_total_seconds':sum(r['online_ns'] for r in rr)/1e9}
        summary['by_edit'][method]={e:{'groups':len([r for r in rr if r['edit']==e]),
            'correct':sum(r['correct'] for r in rr if r['edit']==e),
            'reads':sum(r['reads'] for r in rr if r['edit']==e),
            'true_decisions':sum(r['decision'] is True for r in rr if r['edit']==e)} for e in EDITS}
    summary['retention_means']={k:statistics.mean(x[k] for x in retention)
                                for k in retention[0] if k!='task_id'} if retention else {}
    dump(out/'summary.json',summary)
    print(json.dumps({k:summary[k] for k in ['split','source_task_groups','eligible_task_groups','exclusions','native_write_success','native_postcondition_pass','methods','retention_means','elapsed_seconds']},indent=2))

if __name__=='__main__':main()
