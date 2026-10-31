"""Regenerate paper01 figures from unchanged recorded outcomes; no model calls."""
import argparse,hashlib,json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

HERE=Path(__file__).resolve().parent
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,default=HERE/'results/observed');a=p.parse_args();run=a.run.resolve();figures=HERE/'figures';figures.mkdir(exist_ok=True)
 packets=read(run/'frozen_packets_and_labels.json');assert len(packets)==84
 worlds=read(run/'private_world_manifest.json');assert len(worlds)==48 and sum(r['gold_correct'] for r in worlds)==24
 complete=[r for r in packets if r['channel']=='complete'];assert len(complete)==48
 counts={'Typed checker':[24,24,0,0,0,0]};family_counts={'Typed checker':[16,16,16]};sources=[run/'frozen_packets_and_labels.json',run/'private_world_manifest.json',run/'typed_decisions.json']
 for folder,label in [('model_gemma4_26b','Gemma4:26B'),('model_qwen3_5_4b','Qwen3.5:4B')]:
  decisions=read(run/folder/'decisions.json');sources.extend([run/folder/'decisions.json',run/folder/'result.json'])
  rows=[r for r in decisions if r['channel']=='complete'];assert len(rows)==48
  counts[label]=[sum(r['raw_verdict']=='accept' and r['expected_verdict']=='accept' for r in rows),sum(r['raw_verdict']=='reject' and r['expected_verdict']=='reject' for r in rows),sum(r['raw_verdict']=='accept' and r['expected_verdict']=='reject' for r in rows),sum(r['raw_verdict']=='reject' and r['expected_verdict']=='accept' for r in rows),sum(r['raw_verdict']=='review' for r in rows),sum(r['raw_verdict']=='invalid' for r in rows)]
  assert sum(counts[label])==48
  family_counts[label]=[sum(r['raw_verdict']==r['expected_verdict'] for r in rows if r['family']==f) for f in ['booking','inventory','escalation']]
 typed=read(run/'typed_decisions.json');assert all(r['verdict']==r['expected_verdict'] for r in typed)
 plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})
 fig,ax=plt.subplots(figsize=(7.8,3.15),layout='constrained');left=np.zeros(3);labels=list(counts)
 for j,(name,color) in enumerate([('Correct accept','#277da8'),('Correct reject','#60a68a'),('False accept','#e1704d'),('False reject','#b17dc4'),('Review','#a5abb1'),('Invalid','#333333')]):
  vals=[counts[k][j] for k in labels];ax.barh(labels,vals,left=left,label=name,color=color)
  for i,v in enumerate(vals):
   if v>=4:ax.text(left[i]+v/2,i,str(v),ha='center',va='center',fontsize=9,color='white' if j in [0,2,5] else 'black')
  left+=vals
 ax.set(xlim=(0,48),xlabel='Complete-evidence worlds (48 total)',xticks=range(0,49,8));ax.invert_yaxis();ax.legend(ncol=3,loc='lower center',bbox_to_anchor=(.5,1.02),fontsize=8,frameon=False);ax.grid(axis='x',alpha=.15);ax.set_axisbelow(True)
 fig.savefig(figures/'complete_decisions.png',dpi=240);plt.close(fig)
 fig,ax=plt.subplots(figsize=(7.8,3.2),layout='constrained');x=np.arange(3);width=.24
 for i,(label,color) in enumerate([('Typed checker','#60a68a'),('Gemma4:26B','#277da8'),('Qwen3.5:4B','#e1704d')]):
  values=family_counts[label];bars=ax.bar(x+(i-1)*width,values,width,label=label,color=color);ax.bar_label(bars,padding=3,fontsize=9)
 ax.set_xticks(x,['Booking','Inventory','Escalation']);ax.set(ylim=(0,18.5),yticks=range(0,17,4),ylabel='Correct determinate decisions /16');ax.legend(loc='upper center',bbox_to_anchor=(.5,1.2),ncol=3,frameon=False,fontsize=9);ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True)
 fig.savefig(figures/'schema_decisions.png',dpi=240);plt.close(fig)
 data={'complete_outcome_counts':counts,'category_order':['correct_accept','correct_reject','false_accept','false_reject','review','invalid'],'correct_complete_by_family':family_counts,'family_order':['booking','inventory','escalation'],'sources':[{'path':str(f.relative_to(run)),'sha256':sha(f)} for f in sources],'generator_sha256':sha(Path(__file__))}
 (HERE/'figure_data.json').write_text(json.dumps(data,indent=2)+'\n');print(json.dumps(counts))
if __name__=='__main__':main()
