"""Independent SQL/request/score readback for the frozen multi-schema pilot."""
from __future__ import annotations
import argparse,collections,hashlib,json,sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'))

def oracle(db,family):
    with sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True) as c:
        if family=='booking':
            eligible=c.execute('SELECT (SELECT COALESCE(SUM(b.seats),0) FROM bookings b WHERE b.task_id<>r.task_id AND b.room_id=r.room_id AND b.start<r.end+p.buffer_minutes AND b.end>r.start-p.buffer_minutes)+r.seats<=p.capacity FROM request r CROSS JOIN policy p').fetchone()[0]
            count,exact=c.execute('SELECT COUNT(*),SUM(b.room_id=r.room_id AND b.start=r.start AND b.end=r.end AND b.seats=r.seats) FROM bookings b JOIN request r ON b.task_id=r.task_id').fetchone()
            return bool(count==1 and exact==1) if eligible else count==0
        if family=='inventory':
            eligible=not c.execute('SELECT EXISTS(SELECT1 FROM request r JOIN stock s USING(sku) CROSS JOIN policy p WHERE s.before_qty-r.packages*p.units_per_package<p.reserve_floor)'.replace('SELECT1','SELECT 1')).fetchone()[0]
            if not eligible:return c.execute('SELECT (SELECT COUNT(*) FROM shipments)=0 AND NOT EXISTS(SELECT1 FROM stock WHERE before_qty<>after_qty)'.replace('SELECT1','SELECT 1')).fetchone()[0]==1
            count=c.execute('SELECT COUNT(*) FROM shipments').fetchone()[0];requested=c.execute('SELECT COUNT(*) FROM request').fetchone()[0]
            bad=c.execute('SELECT EXISTS(SELECT1 FROM request r JOIN stock s USING(sku) CROSS JOIN policy p WHERE (SELECT COUNT(*) FROM shipments h WHERE h.task_id=r.task_id AND h.sku=r.sku AND h.units=r.packages*p.units_per_package)<>1 OR s.after_qty<>s.before_qty-r.packages*p.units_per_package)'.replace('SELECT1','SELECT 1')).fetchone()[0]
            return count==requested and not bad
        eligible=c.execute('SELECT customer_tier>=minimum_tier FROM request CROSS JOIN policy').fetchone()[0]
        n=c.execute('SELECT COUNT(*) FROM escalations').fetchone()[0]
        correct=c.execute('SELECT COUNT(*) FROM escalations e JOIN request r USING(task_id) CROSS JOIN policy p WHERE e.queue=p.required_queue AND e.deadline_minute<=r.opened_minute+p.sla_minutes').fetchone()[0]
        return bool(n==correct==1) if eligible else n==0

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run.resolve()
    protocol=read(run/'frozen_protocol.json');packets=read(run/'frozen_packets_and_labels.json');worlds=read(run/'private_world_manifest.json');cpu=read(run/'cpu_result.json')
    assert protocol['source_sha256']==sha(run/'executed_evidence_contracts.py')==sha(ROOT/'pilots/strengthening/evidence_contracts.py')
    assert cpu['frozen_packets_sha256']==sha(run/'frozen_packets_and_labels.json')
    assert protocol['independent_plan_review']['plan_sha256']==sha(ROOT/'work/strengthening/01_plan.json')
    byworld={r['world_id']:r for r in worlds};bypacket={r['packet_id']:r for r in packets};assert len(worlds)==48 and len(packets)==84
    for row in worlds:
        assert sha(run/row['database'])==row['database_sha256']
        assert oracle(run/row['database'],row['family'])==row['gold_correct']
    for row in packets:
        assert hashlib.sha256(canonical(row['packet']).encode()).hexdigest()==row['packet_id']
        if row['channel']=='incomplete':
            assert len(row['world_ids'])==2 and byworld[row['world_ids'][0]]['gold_correct']!=byworld[row['world_ids'][1]]['gold_correct']
            assert row['expected_verdict']=='review'
        elif row['channel']=='complete':assert (row['expected_verdict']=='accept')==byworld[row['world_ids'][0]]['gold_correct']
        else:assert row['expected_verdict']=='review'
    typed=read(run/'typed_decisions.json');assert len(typed)==84 and all(r['verdict']==bypacket[r['packet_id']]['expected_verdict'] for r in typed)
    models={};calls_checked=0
    for folder in sorted(run.glob('model_*')):
        result=read(folder/'result.json');model=result['model'];calls=[json.loads(s) for s in (folder/'model_calls.jsonl').read_text().splitlines()];saved=read(folder/'decisions.json')
        assert len(calls)==len(saved)==84 and result['status']=='completed' and result['actual_model_calls']==84
        assert len({r['packet_id'] for r in calls})==84
        assert read(folder/'model_provenance.json')['digest']==protocol['model_records'][model]['digest']
        rows=[]
        for call,decision in zip(calls,saved):
            item=bypacket[call['packet_id']];packet=item['packet'];request=call['request'];family=item['family']
            expected=protocol['general_prompt']+'Workflow contract: '+protocol['family_contracts'][family]+'\nEvidence packet:\n'+canonical(packet)
            assert request['messages']==[{'role':'system','content':protocol['system_prompt']},{'role':'user','content':expected}]
            assert all(token not in expected for token in ['"gold_correct"','"expected_verdict"','"world_ids"','"pair_id"'])
            assert request['model']==model and request['think'] is False and request['format']=='json'
            assert request['options']=={k:v for k,v in protocol['generation'].items() if k!='think'}
            raw=call['response']['message']['content'];verdict='invalid'
            try:
                parsed=json.loads(raw)
                if isinstance(parsed,dict) and parsed.get('verdict') in ['accept','reject','review']:verdict=parsed['verdict']
            except json.JSONDecodeError:pass
            assert decision['raw_verdict']==verdict
            assert decision['validity_gated_verdict']==(verdict if item['channel']=='complete' else 'review')
            rows.append(dict(decision,expected_verdict=item['expected_verdict']));calls_checked+=1
        summary={}
        for channel in ['incomplete','complete','invalid_probe']:
            rr=[r for r in rows if r['channel']==channel]
            summary[channel]={'packets':len(rr),'raw_correct':sum(r['raw_verdict']==r['expected_verdict'] for r in rr),
               'raw_false_accepts':sum(r['raw_verdict']=='accept' and r['expected_verdict']=='reject' for r in rr),
               'raw_unsupported_determinate_decisions':sum(r['raw_verdict'] in ['accept','reject'] and r['expected_verdict']=='review' for r in rr),
               'invalid_outputs':sum(r['raw_verdict']=='invalid' for r in rr),
               'correct_case_accepts':sum(r['raw_verdict']=='accept' and r['expected_verdict']=='accept' for r in rr),
               'correct_cases':sum(r['expected_verdict']=='accept' for r in rr),'review_on_complete':sum(r['raw_verdict']=='review' and channel=='complete' for r in rr)}
            for key in ['packets','raw_correct','raw_false_accepts','raw_unsupported_determinate_decisions','invalid_outputs']:
                assert summary[channel][key]==result['channels'][channel][key]
        models[model]={'actual_calls':84,'channels':summary,'raw_log_sha256':sha(folder/'model_calls.jsonl'),'result_sha256':sha(folder/'result.json'),
          'native_token_caps':dict(collections.Counter(r['response'].get('done_reason') for r in calls)),
          'families':{family:{'complete_packets':len(rr),'correct_determinate':sum(r['raw_verdict']==r['expected_verdict'] for r in rr),
              'false_accepts':sum(r['raw_verdict']=='accept' and r['expected_verdict']=='reject' for r in rr)} for family in protocol['families'] for rr in [[r for r in rows if r['family']==family and r['channel']=='complete']]}}
    assert calls_checked==168
    review={'status':'passed','review_source_sha256':sha(__file__),'independent_SQL_worlds_checked':48,'unique_packets_checked':84,'actual_native_calls_checked':168,
      'source_sha256':protocol['source_sha256'],'packet_manifest_sha256':sha(run/'frozen_packets_and_labels.json'),'models':models,
      'checks':['Separate SQL evaluator reproduces every private task label.','Every direct complete-packet label and incomplete twin equivalence class matches its oracle relation.','No private labels/latent IDs enter any native user prompt; all168frozen prompts/options/model digests match.','Every raw verdict and aggregate score is recomputed without repair.'],
      'limits':[protocol['trust_boundary'],protocol['sampler_boundary'],'No arbitrary malformed-payload, malicious provenance-capture, real agent-rollout or learned-confidence calibration test is included.']}
    write=lambda p,v:Path(p).write_text(json.dumps(v,indent=2)+'\n')
    write(run/'independent_readback.json',review)
    report={'experiment_id':'01','status':'completed','run_directory':str(run),'evidence_level':'Three authored held-out workflow schemas with actual SQL oracles and an authoritative-read intervention',
      'actual_native_calls':168,'logical_pairs':24,'SQLite_worlds':48,'unique_native_packets_per_model':84,
      'typed_complete_correct':48,'typed_complete_total':48,'typed_incomplete_reviews':24,'typed_invalid_source_reviews':12,
      'models':models,'independent_readback':str(run/'independent_readback.json'),'independent_readback_sha256':sha(run/'independent_readback.json'),
      'proposal_readiness':'Substantially stronger support for the revised evidence-contract/observability benchmark on three authored schemas. Learned complete-evidence judging remains mixed; the original calibrated-autonomy promise is unsupported.',
      'information_intervention':'Identical incomplete packets support incompatible worlds; actual authoritative policy+state reads add the information needed for typed decisions. This is not equal-information algorithmic superiority.',
      'limits':review['limits'],'executor':'Saurav K. Aryal, with Codex-assisted implementation and execution.'}
    write(ROOT/'work/strengthening_01.json',report);print(json.dumps({'status':'passed','SQL_worlds':48,'requests':168,'models':models},indent=2))

if __name__=='__main__':main()
