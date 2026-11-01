"""Verify recorded typed-evidence outcomes without dependencies or a model."""
import collections,hashlib,itertools,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
RUN=ROOT/'runs/repair01-confirm-v2'
EDITS=('policy_equivalent','policy_weaken_request','policy_decision_change','policy_new_amount_cap_500','source_relevant_status','source_relevant_owner','source_irrelevant_address','unsupported_external_risk','unknown_tool_semantics')
METHODS=('always_fresh','dependency_validity','cached_projection','semantic_z3','compiled_capsule')
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 frozen=read(ROOT/'work/repair01_20261101/confirmation_freeze.json')
 for name,value in frozen['files_sha256'].items():assert sha(ROOT/name)==value,(name,'frozen hash')
 native=read(RUN/'native_replay.json');ret=read(RUN/'retention.json');summary=read(RUN/'summary.json')
 rows=list(map(json.loads,(RUN/'episodes.jsonl').read_text().splitlines()))
 eligible={r['task_id'] for r in native if 'excluded' not in r}
 assert len(native)==40 and len(eligible)==31 and len(ret)==31 and len(rows)==1395
 assert collections.Counter(r.get('excluded','eligible') for r in native)=={'eligible':31,'no_order_write':4,'prefix_tool_error':4,'native_write_error':1}
 assert all(r['native_write_success'] and r['native_postcondition'] for r in native if r['task_id'] in eligible)
 groups=collections.defaultdict(dict)
 for r in rows:
  assert r['task_id'] in eligible and r['edit'] in EDITS and r['method'] in METHODS
  key=(r['task_id'],r['edit']);assert r['method'] not in groups[key];groups[key][r['method']]=r
  if r['edit'] in ('unsupported_external_risk','unknown_tool_semantics'):expected=None
  else:
   # Fixed controlled fragment: unchanged valid facts start true. Relevant
   # status/owner changes negate the corresponding obligation. The new cap
   # uses the separately retained raw projection amount truth.
   if r['edit'] in ('policy_decision_change','source_relevant_status','source_relevant_owner'):expected=False
   elif r['edit']=='policy_new_amount_cap_500':expected=next(x for x in rows if x['task_id']==r['task_id'] and x['edit']==r['edit'] and x['method']=='cached_projection')['known_before_read']['amount']
   else:expected=True
  assert r['truth']==expected and r['decision']==expected and r['correct'] and not r['false_accept']
 assert len(groups)==279 and set(groups)==set(itertools.product(eligible,EDITS))
 for g in groups.values():
  assert set(g)==set(METHODS)
  assert (g['dependency_validity']['decision'],g['dependency_validity']['reads'])==(g['semantic_z3']['decision'],g['semantic_z3']['reads'])==(g['compiled_capsule']['decision'],g['compiled_capsule']['reads'])
 reads={m:sum(r['reads'] for r in rows if r['method']==m) for m in METHODS}
 assert reads=={'always_fresh':217,'dependency_validity':93,'cached_projection':62,'semantic_z3':93,'compiled_capsule':93}
 for m in METHODS:
  rr=[r for r in rows if r['method']==m];assert len(rr)==279
  assert sum(r['supported'] for r in rr)==217 and sum(r['decision'] is None for r in rr)==62
  assert summary['methods'][m]['verification_reads']==reads[m]
 for field in ret[0]:
  if field!='task_id':assert abs(sum(r[field] for r in ret)/len(ret)-summary['retention_means'][field])<1e-10
 assert read(RUN/'independent_audit.json')['all_correct'] and read(ROOT/'audits/raw_fixture_readback.json')['errors']==[]
 assert read(ROOT/'audits/native_replay_comparison.json')['all_native_replay_decisions_and_reads_equal']
 print(json.dumps({'status':'passed','provider_tasks':40,'eligible_tasks':31,'task_edit_pairs':279,'method_decisions':1395,'native_postconditions':31,'reads':reads,'frozen_hashes':'passed','boundary':'Saved-result arithmetic and reported audits; run.sh additionally obtains pinned upstream fixtures and executes the independent raw-fixture oracle.'},indent=2))
if __name__=='__main__':main()
