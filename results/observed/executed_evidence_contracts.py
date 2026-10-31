"""Multi-schema authoritative-evidence intervention with independent SQL labels."""
from __future__ import annotations
import argparse,copy,hashlib,json,random,shutil,sqlite3,time
from pathlib import Path
from contextlib import closing
from pilots.common import local_request

ROOT=Path(__file__).resolve().parents[2]
FAMILIES=('booking','inventory','escalation')
SEED=2026103101
SYSTEM='You verify task outcomes from supplied evidence only. Never invent a missing policy or state read. Return strict JSON only.'
CONTRACTS={
 'booking':'A request is eligible if existing other bookings plus the requested seats fit capacity. Other booking [start,end) overlaps request [s,e) if start < e+buffer_minutes and end > s-buffer_minutes. Sum seats of these other bookings. If eligible require exactly one booking for task_id matching room_id,start,end,seats. If ineligible require no booking for task_id. Sources policy and state must both meet the evidence requirements.',
 'inventory':'Convert each requested package quantity to units using current policy units_per_package. Eligible means before_qty minus converted requested units >= reserve_floor for EVERY SKU. If eligible require exactly one shipment per requested SKU with the converted quantity and each after_qty=before_qty-converted_quantity. If ineligible require zero shipments and every after_qty=before_qty. Sources policy and state must both meet evidence requirements.',
 'escalation':'A task is eligible if customer_tier >= policy minimum_tier. If eligible require exactly one escalation for task_id, its queue equal policy required_queue and its deadline_minute <= request opened_minute+policy sla_minutes. If ineligible require zero escalations. Sources policy and state must both meet evidence requirements.'}
GENERAL=('First validate evidence: require one policy source and one state source, each for the requested entity_id, schema_version1, capture_epoch equal metadata.capture_epoch; policy revision must equal metadata.current_policy_revision and state revision metadata.current_state_revision. A missing current revision, missing source, multiple conflicting sources, wrong entity/schema/epoch/revision means review. Source hashes are captured by a trusted adapter; do not treat cached_policy as current authority. With valid complete evidence decide accept if the postcondition holds, otherwise reject. Return JSON {"verdict":"accept|reject|review","reason":"short reason"}. Confidence is not requested.\n')

def read(p):return json.loads(Path(p).read_text())
def write(p,v):p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2,allow_nan=False)+'\n')
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'))
def digest(x):return hashlib.sha256(canonical(x).encode()).hexdigest()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def rows(c,table):return [dict(x) for x in c.execute('SELECT * FROM '+table)]

def make_database(path,family,index,world,rng):
    """Create real relational state; no gold labels or latent flags are stored."""
    entity=f'resource-{rng.randrange(10**8,10**9)}';task_id=f'task-{rng.randrange(10**8,10**9)}'
    with closing(sqlite3.connect(path)) as c:
        c.executescript('CREATE TABLE meta(entity_id TEXT,policy_revision INT,state_revision INT,capture_epoch INT);')
        revisions=rng.sample(range(10000,100000),2)
        c.execute('INSERT INTO meta VALUES(?,?,?,?)',(entity,revisions[world],7,1000))
        if family=='booking':
            start=rng.randrange(500,900);end=start+rng.randrange(30,91);seats=rng.randrange(1,5);occupied=rng.randrange(1,5)
            # Half the pairs change capacity; half change temporal buffer semantics.
            if index<4:
                other_start=start+5;other_end=end+10;capacity=occupied+seats+(2 if world==0 else -1);buffer=0
            else:
                other_start=end+5;other_end=end+35;capacity=max(occupied,seats);buffer=0 if world==0 else 10
            present=(index%2==0)
            c.executescript('CREATE TABLE policy(capacity INT,buffer_minutes INT);CREATE TABLE request(task_id TEXT,room_id TEXT,start INT,end INT,seats INT);CREATE TABLE bookings(task_id TEXT,room_id TEXT,start INT,end INT,seats INT);')
            c.execute('INSERT INTO policy VALUES(?,?)',(capacity,buffer));c.execute('INSERT INTO request VALUES(?,?,?,?,?)',(task_id,entity,start,end,seats))
            c.execute('INSERT INTO bookings VALUES(?,?,?,?,?)',('other',entity,other_start,other_end,occupied))
            if present:c.execute('INSERT INTO bookings VALUES(?,?,?,?,?)',(task_id,entity,start,end,seats))
            tables=['request','bookings']
        elif family=='inventory':
            packs=[rng.randrange(1,5),rng.randrange(1,5)];unit=2 if index<4 or world==0 else 3
            floor=1 if index>=4 or world==0 else 100
            present=(index%2==0) if index<4 else True
            c.executescript('CREATE TABLE policy(units_per_package INT,reserve_floor INT);CREATE TABLE request(task_id TEXT,sku TEXT,packages INT);CREATE TABLE stock(sku TEXT,before_qty INT,after_qty INT);CREATE TABLE shipments(task_id TEXT,sku TEXT,units INT);')
            c.execute('INSERT INTO policy VALUES(?,?)',(unit,floor))
            for j,qty in enumerate(packs):
                sku=f'sku-{j}';before=qty*4+20;actual=qty*2 if present else 0
                c.execute('INSERT INTO request VALUES(?,?,?)',(task_id,sku,qty));c.execute('INSERT INTO stock VALUES(?,?,?)',(sku,before,before-actual))
                if present:c.execute('INSERT INTO shipments VALUES(?,?,?)',(task_id,sku,actual))
            tables=['request','stock','shipments']
        else:
            tier=rng.randrange(1,4);opened=rng.randrange(100,800);delay=rng.randrange(20,40);queue=f'queue-{rng.randrange(20,90)}'
            if index%3==0:minimum=tier+(0 if world==0 else 1);required=queue;sla=delay+10;present=(index%2==0)
            elif index%3==1:minimum=tier;required=queue if world==0 else queue+'-alternate';sla=delay+10;present=True
            else:minimum=tier;required=queue;sla=delay+(5 if world==0 else -5);present=True
            c.executescript('CREATE TABLE policy(minimum_tier INT,required_queue TEXT,sla_minutes INT);CREATE TABLE request(task_id TEXT,customer_tier INT,opened_minute INT);CREATE TABLE escalations(task_id TEXT,queue TEXT,deadline_minute INT);')
            c.execute('INSERT INTO policy VALUES(?,?,?)',(minimum,required,sla));c.execute('INSERT INTO request VALUES(?,?,?)',(task_id,tier,opened))
            if present:c.execute('INSERT INTO escalations VALUES(?,?,?)',(task_id,queue,opened+delay))
            tables=['request','escalations']
        c.commit()
    return entity,task_id,tables

def sql_oracle(path,family):
    """Separate evaluator reads SQL relations, never the public JSON checker."""
    with closing(sqlite3.connect(path)) as c:
        if family=='booking':
            task,room,start,end,seats=c.execute('SELECT * FROM request').fetchone();capacity,buffer=c.execute('SELECT * FROM policy').fetchone()
            other=c.execute('SELECT COALESCE(SUM(seats),0) FROM bookings WHERE task_id<>? AND room_id=? AND start<? AND end>?',(task,room,end+buffer,start-buffer)).fetchone()[0]
            eligible=other+seats<=capacity;count=c.execute('SELECT COUNT(*) FROM bookings WHERE task_id=?',(task,)).fetchone()[0]
            exact=c.execute('SELECT COUNT(*) FROM bookings WHERE task_id=? AND room_id=? AND start=? AND end=? AND seats=?',(task,room,start,end,seats)).fetchone()[0]
            return bool((count==exact==1) if eligible else count==0)
        if family=='inventory':
            unit,floor=c.execute('SELECT * FROM policy').fetchone();task=c.execute('SELECT task_id FROM request LIMIT1'.replace('LIMIT1','LIMIT 1')).fetchone()[0]
            eligible=c.execute('SELECT COUNT(*) FROM request r JOIN stock s USING(sku) WHERE s.before_qty-r.packages*?<?',(unit,floor)).fetchone()[0]==0
            n=c.execute('SELECT COUNT(*) FROM request').fetchone()[0]
            if not eligible:
                return c.execute('SELECT COUNT(*) FROM shipments WHERE task_id=?',(task,)).fetchone()[0]==0 and c.execute('SELECT COUNT(*) FROM stock WHERE after_qty<>before_qty').fetchone()[0]==0
            matches=c.execute('SELECT COUNT(*) FROM request r JOIN stock s USING(sku) JOIN shipments h ON h.sku=r.sku AND h.task_id=r.task_id WHERE h.units=r.packages*? AND s.after_qty=s.before_qty-h.units',(unit,)).fetchone()[0]
            return matches==n and c.execute('SELECT COUNT(*) FROM shipments WHERE task_id=?',(task,)).fetchone()[0]==n
        task,tier,opened=c.execute('SELECT * FROM request').fetchone();minimum,queue,sla=c.execute('SELECT * FROM policy').fetchone()
        count=c.execute('SELECT COUNT(*) FROM escalations WHERE task_id=?',(task,)).fetchone()[0]
        matches=c.execute('SELECT COUNT(*) FROM escalations WHERE task_id=? AND queue=? AND deadline_minute<=?',(task,queue,opened+sla)).fetchone()[0]
        return bool((count==matches==1) if tier>=minimum else count==0)

def atomic_capture(path,family,tables):
    with closing(sqlite3.connect(path,isolation_level=None)) as c:
        c.row_factory=sqlite3.Row;c.execute('BEGIN')
        meta=dict(c.execute('SELECT * FROM meta').fetchone())
        policy=rows(c,'policy');state={table:rows(c,table) for table in tables}
        c.execute('COMMIT')
    snapshots=[]
    for source,payload,revision in [('policy',policy,meta['policy_revision']),('state',state,meta['state_revision'])]:
        item={'source':source,'entity_id':meta['entity_id'],'schema_version':1,'capture_epoch':meta['capture_epoch'],'revision':revision,'payload':payload}
        item['capture_sha256']=digest(item);snapshots.append(item)
    return {'family':family,'entity_id':meta['entity_id'],'evidence':{'metadata':{'capture_epoch':meta['capture_epoch'],'current_policy_revision':meta['policy_revision'],'current_state_revision':meta['state_revision']},'snapshots':snapshots}}

def validity(packet):
    evidence=packet['evidence'];meta=evidence['metadata'];sources=evidence['snapshots']
    if any(type(meta.get(k)) is not int for k in ['capture_epoch','current_policy_revision','current_state_revision']):return False,'missing_current_revision'
    for name,revision in [('policy',meta['current_policy_revision']),('state',meta['current_state_revision'])]:
        selected=[s for s in sources if s.get('source')==name]
        if len(selected)!=1:return False,'missing_or_conflicting_source'
        s=selected[0]
        if s.get('entity_id')!=packet['entity_id']:return False,'entity_mismatch'
        if s.get('schema_version')!=1 or s.get('capture_epoch')!=meta['capture_epoch'] or s.get('revision')!=revision:return False,'schema_epoch_revision_mismatch'
        if digest({k:v for k,v in s.items() if k!='capture_sha256'})!=s.get('capture_sha256'):return False,'capture_integrity_mismatch'
    return True,'valid_under_trusted_capture_assumptions'

def typed_check(packet):
    valid,reason=validity(packet)
    if not valid:return {'verdict':'review','reason':reason}
    payload={s['source']:s['payload'] for s in packet['evidence']['snapshots']};p=payload['policy'][0];s=payload['state'];family=packet['family']
    if family=='booking':
        r=s['request'][0];effects=[b for b in s['bookings'] if b['task_id']==r['task_id']]
        other=sum(b['seats'] for b in s['bookings'] if b['task_id']!=r['task_id'] and b['room_id']==r['room_id'] and b['start']<r['end']+p['buffer_minutes'] and b['end']>r['start']-p['buffer_minutes'])
        eligible=other+r['seats']<=p['capacity'];ok=(len(effects)==1 and all(effects[0][k]==r[k] for k in ['room_id','start','end','seats'])) if eligible else not effects
    elif family=='inventory':
        stocks={r['sku']:r for r in s['stock']};request=s['request'];task=request[0]['task_id'];effects=[h for h in s['shipments'] if h['task_id']==task]
        eligible=all(stocks[r['sku']]['before_qty']-r['packages']*p['units_per_package']>=p['reserve_floor'] for r in request)
        if eligible:
            ok=len(effects)==len(request) and all(len([h for h in effects if h['sku']==r['sku'] and h['units']==r['packages']*p['units_per_package']])==1 and stocks[r['sku']]['after_qty']==stocks[r['sku']]['before_qty']-r['packages']*p['units_per_package'] for r in request)
        else:ok=not effects and all(v['before_qty']==v['after_qty'] for v in stocks.values())
    else:
        r=s['request'][0];effects=[h for h in s['escalations'] if h['task_id']==r['task_id']]
        eligible=r['customer_tier']>=p['minimum_tier'];ok=(len(effects)==1 and effects[0]['queue']==p['required_queue'] and effects[0]['deadline_minute']<=r['opened_minute']+p['sla_minutes']) if eligible else not effects
    return {'verdict':'accept' if ok else 'reject','reason':'typed_postcondition'}

def prompt(packet):return GENERAL+'Workflow contract: '+CONTRACTS[packet['family']]+'\nEvidence packet:\n'+canonical(packet)

def prepare(out):
    if out.exists() and any(out.iterdir()):raise FileExistsError('Use a fresh output directory.')
    out.mkdir(parents=True,exist_ok=True);(out/'databases').mkdir()
    plan=read(ROOT/'work/strengthening/01_plan.json');review=read(ROOT/'work/strengthening/01_plan_review.json')
    assert review['status']=='approved_before_locked_inference' and review['plan_sha256']==sha(ROOT/'work/strengthening/01_plan.json')
    tags=local_request('http://127.0.0.1:11434/api/tags',timeout=15)
    model_records={m:next(x for x in tags['models'] if x['name']==m) for m in ['gemma4:26b','qwen3.5:4b']}
    protocol={'status':'frozen_before_locked_case_generation_and_model_calls','model_records':model_records,'seed':SEED,'source_sha256':sha(__file__),
       'plan_sha256':sha(ROOT/'work/strengthening/01_plan.json'),'independent_plan_review':review,
       'families':FAMILIES,'pairs_per_family':8,'models':['gemma4:26b','qwen3.5:4b'],'max_native_calls':168,
       'system_prompt':SYSTEM,'general_prompt':GENERAL,'family_contracts':CONTRACTS,
       'generation':{'temperature':0,'seed':SEED,'think':False,'num_ctx':4096,'num_predict':160},
       'trust_boundary':'The local adapter and SQLite state are trusted and the source read is transaction-consistent. Digests detect capture changes; they do not authenticate arbitrary forged sources. Typed contracts are authored per schema, not inferred zero-shot.',
       'sampler_boundary':'Three newly authored families with24logical parameterized pairs. Twin worlds and replay conditions are dependent; no population risk bound or real agent rollout is tested.',
       'development':'Previous refund-only studies motivated the design; no new development model calls or prompt/threshold search.'}
    write(out/'frozen_protocol.json',protocol);shutil.copy2(__file__,out/'executed_evidence_contracts.py')
    packets=[];worlds=[];pairs=[];rng=random.Random(SEED)
    for family in FAMILIES:
        for index in range(8):
            pair_seed=rng.randrange(10**9);pair_id=hashlib.sha256(str(pair_seed).encode()).hexdigest()[:16];twins=[]
            for world in [0,1]:
                case_id=hashlib.sha256(f'{pair_seed}:{world}'.encode()).hexdigest()[:20];db=out/'databases'/f'{case_id}.sqlite'
                _,_,tables=make_database(db,family,index,world,random.Random(pair_seed));truth=sql_oracle(db,family)
                full=atomic_capture(db,family,tables);low=copy.deepcopy(full)
                low['evidence']['metadata']['current_policy_revision']=None;low['evidence']['snapshots']=[s for s in low['evidence']['snapshots'] if s['source']!='policy']
                # Cached policy is exactly the first world's published policy in both twins.
                if world==0:cached=next(s['payload'] for s in full['evidence']['snapshots'] if s['source']=='policy')
                low['cached_policy']=cached
                twins.append({'world_id':case_id,'gold_correct':truth,'full':full,'low':low})
                packets.append({'packet_id':digest(full),'channel':'complete','family':family,'pair_id':pair_id,'world_ids':[case_id],'packet':full,'expected_verdict':'accept' if truth else 'reject'})
                worlds.append({'world_id':case_id,'pair_id':pair_id,'family':family,'database':str(db.relative_to(out)),'database_sha256':sha(db),'gold_correct':truth})
            assert twins[0]['gold_correct']!=twins[1]['gold_correct']
            assert canonical(twins[0]['low'])==canonical(twins[1]['low'])
            low=twins[0]['low'];packets.append({'packet_id':digest(low),'channel':'incomplete','family':family,'pair_id':pair_id,'world_ids':[x['world_id'] for x in twins],'packet':low,'expected_verdict':'review'})
            pairs.append({'pair_id':pair_id,'family':family,'world_ids':[x['world_id'] for x in twins],'opposite_SQL_labels':True,'byte_identical_incomplete_packets':True,'incomplete_packet_sha256':digest(low)})
            if index==0:
                for fault in ['missing_policy','stale_revision','conflicting_policy','wrong_entity']:
                    broken=copy.deepcopy(twins[0]['full']);sources=broken['evidence']['snapshots'];policy=next(s for s in sources if s['source']=='policy')
                    if fault=='missing_policy':sources.remove(policy)
                    elif fault=='stale_revision':policy['revision']-=1
                    elif fault=='wrong_entity':policy['entity_id']='unrelated-resource'
                    else:sources.append(copy.deepcopy(policy));sources[-1]['payload'][0][next(iter(policy['payload'][0]))]='conflicting-value'
                    for item in sources:item['capture_sha256']=digest({k:v for k,v in item.items() if k!='capture_sha256'})
                    packets.append({'packet_id':digest(broken),'channel':'invalid_probe','family':family,'fault':fault,'pair_id':pair_id,'world_ids':[twins[0]['world_id']],'packet':broken,'expected_verdict':'review'})
    rng.shuffle(packets);assert len(packets)==84 and len({x['packet_id'] for x in packets})==84
    write(out/'private_world_manifest.json',worlds);write(out/'paired_information_controls.json',pairs);write(out/'frozen_packets_and_labels.json',packets)
    decisions=[]
    for item in packets:
        decision=typed_check(item['packet']);decisions.append({k:item[k] for k in ['packet_id','channel','family','expected_verdict']}|decision)
    mismatches=[r for r in decisions if r['verdict']!=r['expected_verdict']]
    write(out/'typed_decisions.json',decisions)
    result={'experiment_id':'01','status':'cpu_preflight_passed' if not mismatches else 'cpu_preflight_failed','actual_model_calls':0,
       'typed_checks':len(decisions),'typed_mismatches':mismatches,'logical_pairs':24,'SQLite_worlds':48,
       'unique_packets':84,'channels':{k:sum(x['channel']==k for x in packets) for k in ['incomplete','complete','invalid_probe']},
       'source_sha256':sha(__file__),'frozen_packets_sha256':sha(out/'frozen_packets_and_labels.json'),'executor':'Saurav K. Aryal, with Codex-assisted implementation and execution.'}
    write(out/'cpu_result.json',result);print(json.dumps(result,indent=2));return result

def infer(out,model):
    protocol=read(out/'frozen_protocol.json');assert protocol['source_sha256']==sha(__file__)
    pre=read(out/'cpu_result.json');assert pre['status']=='cpu_preflight_passed'
    assert pre['frozen_packets_sha256']==sha(out/'frozen_packets_and_labels.json')
    folder=out/('model_'+model.replace(':','_').replace('.','_'));folder.mkdir(exist_ok=False)
    tags=local_request('http://127.0.0.1:11434/api/tags');record=next(x for x in tags['models'] if x['name']==model);assert record['digest']==protocol['model_records'][model]['digest'];write(folder/'model_provenance.json',record)
    packets=read(out/'frozen_packets_and_labels.json');decisions=[];started=time.perf_counter()
    write(folder/'model_protocol.json',{'status':'frozen_before_calls','model':model,'model_digest':record['digest'],'planned_calls':84,'frozen_packet_sha256':pre['frozen_packets_sha256'],'provider':protocol['generation'],'keep_alive':'5m within finite model block; explicit keep_alive0 unload after completion'})
    for i,item in enumerate(packets,1):
        request={'model':model,'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':prompt(item['packet'])}],
         'stream':False,'think':False,'keep_alive':0,'format':'json','options':{k:v for k,v in protocol['generation'].items() if k!='think'}}
        # Keeping a model resident across its finite study avoids reloading weights per call.
        request['keep_alive']='5m'
        response=local_request('http://127.0.0.1:11434/api/chat',request,timeout=180)
        raw=response['message']['content'];error=None;verdict='invalid'
        try:
            parsed=json.loads(raw)
            if not isinstance(parsed,dict) or parsed.get('verdict') not in ['accept','reject','review']:raise ValueError('Invalid verdict schema')
            verdict=parsed['verdict']
        except Exception as exc:error=f'{type(exc).__name__}: {exc}'
        logged={'call':i,'packet_id':item['packet_id'],'request':request,'response':response,'parse_error':error}
        with (folder/'model_calls.jsonl').open('a') as stream:stream.write(json.dumps(logged,ensure_ascii=False)+'\n')
        valid,_=validity(item['packet']);gated=verdict if valid else 'review'
        decisions.append({k:item[k] for k in ['packet_id','channel','family','expected_verdict']}|{'raw_verdict':verdict,'validity_gated_verdict':gated,'raw_matches_expected':verdict==item['expected_verdict'],'gated_matches_expected':gated==item['expected_verdict'],'parse_error':error})
        if i%12==0:print(f'{model}: {i}/84',flush=True)
    result={'experiment_id':'01','status':'completed','model':model,'actual_model_calls':len(decisions),'seconds':time.perf_counter()-started,
      'channels':{channel:{'packets':len(rows),'raw_correct':sum(r['raw_matches_expected'] for r in rows),'gated_correct':sum(r['gated_matches_expected'] for r in rows),
        'invalid_outputs':sum(r['raw_verdict']=='invalid' for r in rows),'raw_accepts':sum(r['raw_verdict']=='accept' for r in rows),'raw_false_accepts':sum(r['raw_verdict']=='accept' and r['expected_verdict']=='reject' for r in rows),
        'raw_unsupported_determinate_decisions':sum(r['raw_verdict'] in ['accept','reject'] and r['expected_verdict']=='review' for r in rows)}
        for channel in ['incomplete','complete','invalid_probe'] for rows in [[r for r in decisions if r['channel']==channel]]},
      'limits':[protocol['trust_boundary'],protocol['sampler_boundary'],'Added source information is an explicit intervention. Confidence calibration and real agent rollouts are not measured.'],
      'executor':'Saurav K. Aryal, with Codex-assisted implementation and execution.'}
    write(folder/'decisions.json',decisions);write(folder/'result.json',result)
    local_request('http://127.0.0.1:11434/api/generate',{'model':model,'keep_alive':0},timeout=30)
    print(json.dumps(result,indent=2))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--stage',choices=['prepare','infer'],required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--model',choices=['gemma4:26b','qwen3.5:4b']);a=p.parse_args()
    if a.stage=='prepare':prepare(a.out.resolve())
    else:
        if not a.model:p.error('--model required')
        infer(a.out.resolve(),a.model)
if __name__=='__main__':main()
