#!/usr/bin/env python3
"""Independent arithmetic/Boolean oracle from fixture state, not method labels."""
import argparse, hashlib, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
DATA=ROOT/'work/repair01_20261101/upstream_tau/data/tau2/domains/retail'
WRITES={'cancel_pending_order','exchange_delivered_order_items','modify_pending_order_address',
        'modify_pending_order_items','modify_pending_order_payment','return_delivered_order_items'}

def expected(task,db,edit):
    action=next(a for a in task['evaluation_criteria']['actions'] if a['name'] in WRITES)
    args=action['arguments'];name=action['name'];order=db['orders'][args['order_id']]
    # Initial trace includes only non-order writes before this first order
    # write. Address/profile updates do not affect these four obligations.
    status=order['status'];owner=True
    if edit=='source_relevant_status':status='processed'
    if edit=='source_relevant_owner':owner=False
    needed='delivered' if name in {'return_delivered_order_items','exchange_delivered_order_items'} else 'pending'
    status_ok=status==needed
    if name=='cancel_pending_order':request=args.get('reason') in ('ordered by mistake','no longer needed')
    elif 'item_ids' in args:
        request=bool(args['item_ids']) and all(x in {i['item_id'] for i in order['items']} for x in args['item_ids'])
    elif name=='modify_pending_order_address':
        request=all(args.get(k) for k in ['address1','city','country','state','zip'])
    else:request=bool(args.get('payment_method_id'))
    if edit in ('unsupported_external_risk','unknown_tool_semantics'):return None
    if edit=='policy_weaken_request':return bool(owner and status_ok)
    if edit=='policy_decision_change':return bool(owner and not status_ok and request)
    if edit=='policy_new_amount_cap_500':
        return bool(owner and status_ok and request and sum(i['price'] for i in order['items'])<=500)
    return bool(owner and status_ok and request)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('run');args=ap.parse_args();run=Path(args.run)
    db=json.loads((DATA/'db.json').read_text());tasks={t['id']:t for t in json.loads((DATA/'tasks.json').read_text())}
    episodes=[json.loads(l) for l in (run/'episodes.jsonl').read_text().splitlines()]
    errors=[];methods={};joint={}
    for r in episodes:
        truth=expected(tasks[r['task_id']],db,r['edit'])
        if truth!=r['truth'] or truth!=r['decision']:errors.append({'task':r['task_id'],'edit':r['edit'],'method':r['method'],'expected':truth,'reported_truth':r['truth'],'decision':r['decision']})
        methods[r['method']]=methods.get(r['method'],0)+1
        joint.setdefault((r['task_id'],r['edit']),{})[r['method']]=(r['decision'],r['reads'])
    parity=sum(v['semantic_z3']==v['compiled_capsule']==v['dependency_validity'] for v in joint.values())
    result={'independent_oracle':'raw public JSON fixture + separately written Boolean/arithmetic implementation',
            'episodes_checked':len(episodes),'unique_task_edit_pairs':len(joint),
            'task_groups':len({r['task_id'] for r in episodes}),
            'errors':errors,'all_correct':not errors,
            'dependency_solver_compiled_decision_and_read_parity_pairs':parity,
            'audit_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (run/'independent_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    if errors:raise SystemExit(1)
if __name__=='__main__':main()
