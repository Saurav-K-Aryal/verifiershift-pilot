"""Generate current manuscript figures from frozen recorded outcomes."""
import hashlib,json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 source=ROOT/'runs/repair01-confirm-v2/summary.json';s=json.loads(source.read_text());f=ROOT/'figures';f.mkdir(exist_ok=True)
 labels=['Always fresh','Dependency + validity','Sufficient statistics','Semantic Z3','Compiled capsule'];keys=['always_fresh','dependency_validity','cached_projection','semantic_z3','compiled_capsule']
 values=[s['methods'][k]['verification_reads'] for k in keys]
 plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
 fig,ax=plt.subplots(figsize=(7.1,2.8),layout='constrained');bars=ax.barh(labels,values,color=['#87929b','#497b9b','#49a08b','#497b9b','#497b9b']);ax.bar_label(bars,padding=4);ax.invert_yaxis();ax.set(xlim=(0,245),xlabel='Native verification reads across 279 repeated task/edit pairs');ax.grid(axis='x',alpha=.15);ax.set_axisbelow(True);fig.savefig(f/'verification_reads.png',dpi=230);plt.close(fig)
 r=s['retention_means'];vals=[r['raw_bytes'],r['projection_bytes'],r['capsule_bytes']]
 fig,ax=plt.subplots(figsize=(7.1,2.8),layout='constrained');bars=ax.barh(['Raw response','Sufficient statistics','Predicate capsule'],vals,color=['#87929b','#49a08b','#497b9b']);ax.bar_label(bars,fmt='%.0f bytes',padding=4);ax.invert_yaxis();ax.set(xlim=(0,1650),xlabel='Mean serialized retained bytes per task, including common metadata');ax.grid(axis='x',alpha=.15);ax.set_axisbelow(True);fig.savefig(f/'retained_bytes.png',dpi=230);plt.close(fig)
 data={'study':'restricted-evidence-native-retail-replay','tasks':31,'task_edit_pairs':279,'method_decisions':1395,'reads':dict(zip(keys,values)),'retention_means':r,'sources':[{'path':str(source.relative_to(ROOT)),'sha256':sha(source)}],'generator_sha256':sha(Path(__file__))}
 (ROOT/'figure_data.json').write_text(json.dumps(data,indent=2)+'\n')
 print(json.dumps({'figures':2,'reads':data['reads']}))
if __name__=='__main__':main()
