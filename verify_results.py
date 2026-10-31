"""Standard-Python verification of observed SQL content and168 native responses."""
import hashlib,json,tempfile
from pathlib import Path
from reproduce_cpu import reconstruct

HERE=Path(__file__).resolve().parent
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 run=HERE/'results/observed';protocol=read(run/'frozen_protocol.json');packets={r['packet_id']:r for r in read(run/'frozen_packets_and_labels.json')}
 assert protocol['source_sha256']==sha(HERE/'pilots/strengthening/evidence_contracts.py')
 scratch=HERE/'work';scratch.mkdir(exist_ok=True)
 with tempfile.TemporaryDirectory(dir=scratch) as temp:cpu=reconstruct(Path(temp))
 calls_checked=0;models={}
 for folder in sorted(run.glob('model_*')):
  result=read(folder/'result.json');model=result['model'];calls=[json.loads(line) for line in (folder/'model_calls.jsonl').read_text().splitlines()];decisions=read(folder/'decisions.json')
  assert len(calls)==len(decisions)==84 and len({r['packet_id'] for r in calls})==84
  assert read(folder/'model_provenance.json')['digest']==protocol['model_records'][model]['digest']
  for call,saved in zip(calls,decisions):
   item=packets[call['packet_id']];packet=item['packet'];expected=protocol['general_prompt']+'Workflow contract: '+protocol['family_contracts'][item['family']]+'\nEvidence packet:\n'+json.dumps(packet,sort_keys=True,separators=(',',':'))
   assert call['request']['messages']==[{'role':'system','content':protocol['system_prompt']},{'role':'user','content':expected}]
   assert call['request']['options']=={k:v for k,v in protocol['generation'].items() if k!='think'}
   verdict='invalid'
   try:
    obj=json.loads(call['response']['message']['content'])
    if isinstance(obj,dict) and obj.get('verdict') in ['accept','reject','review']:verdict=obj['verdict']
   except json.JSONDecodeError:pass
   assert saved['raw_verdict']==verdict
   assert saved['validity_gated_verdict']==(verdict if item['channel']=='complete' else 'review')
   assert saved['raw_matches_expected']==(verdict==item['expected_verdict']);calls_checked+=1
  for channel,metrics in result['channels'].items():
   rows=[r for r in decisions if r['channel']==channel]
   assert metrics['packets']==len(rows)
   assert metrics['raw_correct']==sum(r['raw_verdict']==r['expected_verdict'] for r in rows)
   assert metrics['raw_false_accepts']==sum(r['raw_verdict']=='accept' and r['expected_verdict']=='reject' for r in rows)
   assert metrics['invalid_outputs']==sum(r['raw_verdict']=='invalid' for r in rows)
  models[model]=result['channels']
 assert calls_checked==168
 print(json.dumps({'status':'passed','logical_SQL_worlds':cpu['reconstructed_SQL_worlds'],'raw_calls_checked':calls_checked,'models':models},indent=2))
if __name__=='__main__':main()
