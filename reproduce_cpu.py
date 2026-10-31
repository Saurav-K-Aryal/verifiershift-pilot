"""Reconstruct every observed logical SQL world without model/server access."""
import argparse,hashlib,json,random
from pathlib import Path
from pilots.strengthening.evidence_contracts import FAMILIES,SEED,make_database,atomic_capture,typed_check
from pilots.strengthening.review_evidence_contracts import oracle

HERE=Path(__file__).resolve().parent
def read(p):return json.loads(p.read_text())
def reconstruct(out):
 if out.exists() and any(out.iterdir()):raise FileExistsError('Choose a fresh output directory.')
 out.mkdir(parents=True,exist_ok=True)
 source=HERE/'results/observed';packets=read(source/'frozen_packets_and_labels.json');worlds={r['world_id']:r for r in read(source/'private_world_manifest.json')}
 complete={r['world_ids'][0]:r for r in packets if r['channel']=='complete'};rng=random.Random(SEED);checked=[]
 for family in FAMILIES:
  for index in range(8):
   pair_seed=rng.randrange(10**9)
   for world in [0,1]:
    ident=hashlib.sha256(f'{pair_seed}:{world}'.encode()).hexdigest()[:20];db=out/(ident+'.sqlite')
    _,_,tables=make_database(db,family,index,world,random.Random(pair_seed));capture=atomic_capture(db,family,tables)
    assert capture==complete[ident]['packet']
    assert oracle(db,family)==worlds[ident]['gold_correct']
    assert typed_check(capture)['verdict']==complete[ident]['expected_verdict']
    checked.append(ident)
 result={'status':'passed','reconstructed_SQL_worlds':len(checked),'typed_complete_correct':len(checked),
  'model_calls':0,'boundary':'Logical captured content and independent SQL labels are compared; physical SQLite file hashes may differ across SQLite versions.'}
 (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');return result
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args();print(json.dumps(reconstruct(a.out.resolve()),indent=2))
