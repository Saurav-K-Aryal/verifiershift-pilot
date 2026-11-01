"""Compare scientific outputs with frozen confirmation, excluding timings."""
import argparse,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
FIELDS=('task_id','family','edit','method','decision','truth','supported','correct','false_accept','reads','notices','known_before_read')
def rows(p):return [{k:r[k] for k in FIELDS} for r in map(json.loads,(p/'episodes.jsonl').read_text().splitlines())]
def main():
 p=argparse.ArgumentParser();p.add_argument('reproduction',type=Path);a=p.parse_args()
 expected=ROOT/'runs/repair01-confirm-v2';assert rows(expected)==rows(a.reproduction)
 assert json.loads((expected/'retention.json').read_text())==json.loads((a.reproduction/'retention.json').read_text())
 x=json.loads((a.reproduction/'summary.json').read_text());assert x['native_postcondition_pass']==31
 print(json.dumps({'status':'passed','episodes':1395,'native_replays':31,'retention_exact':True,'timings_compared':False},indent=2))
if __name__=='__main__':main()
