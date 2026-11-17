from pathlib import Path
import json,statistics
from collections import defaultdict
D=Path(__file__).resolve().parents[1]/'results/revision-20261115'
groups=defaultdict(list)
for p in sorted(D.glob('deploy-emulator-*.jsonl')):
 for line in p.read_text().splitlines():
  r=json.loads(line);groups[(r['serial'],r['mode'])].append(r)
summary=[]
for (serial,mode),rs in sorted(groups.items()):
 lat=[];before_thaw=0;after=0;frozen=0;bound=0;errors=0
 for r in rs:
  if 'error'in r:errors+=1;continue
  t=r['mutation']['t_pre'];frozen+=any(x.get('frozen')=='1' for x in r['states']);bound+='mBound=true' in (r.get('binding') or '')
  ev=[e['t']-t for e in r['memory_before_thaw'].get('events',[]) if e['src']=='contacts' and e['t']>=t]
  later=[e['t']-t for e in r['memory_after_thaw'].get('events',[]) if e['src']=='contacts' and e['t']>=t]
  before_thaw+=bool(ev);after+=bool(later)
  if ev:lat.append(min(ev))
 summary.append({'serial':serial,'mode':mode,'n':len(rs),'errors':errors,'observed_frozen_trials':frozen,'bound_trials':bound,'callback_before_thaw_trials':before_thaw,'callback_after_thaw_trials':after,'median_callback_ms_when_observed':statistics.median(lat) if lat else None,'callback_ms':lat})
repeats=[]
for p in sorted(D.glob('freezer-restarted-*.jsonl')):
 rs=[json.loads(line)for line in p.read_text().splitlines()]
 repeats.append({'serial':rs[0]['serial'],'n':len(rs),'errors':sum('error'in r for r in rs),'frozen_trials':sum(any(x.get('frozen')=='1'for x in r.get('states',[]))for r in rs)})
(D/'freezer-repeat-summary.json').write_text(json.dumps(repeats,indent=2)+'\n',newline='\n')
(D/'deployment-summary.json').write_text(json.dumps(summary,indent=2)+'\n',newline='\n')
print(json.dumps(summary,indent=2))

G=D.parents[2]/'manuscript/generated'
macros={}
for x in summary:
 if x['mode'] in ['bg_unfrozen','fg','assistant']:
  name='RevDeploy'+('A' if x['serial'].endswith('5620') else 'B')+{'bg_unfrozen':'Bg','fg':'Fg','assistant':'Assist'}[x['mode']]
  v=x['median_callback_ms_when_observed'];macros[name]=(f'{v/1000:.1f}\\,s' if v>=1000 else f'{v:.0f}\\,ms') if v is not None else 'n/a'
(G/'revision_deploy_macros.tex').write_text(''.join('\\newcommand{\\'+k+'}{'+str(v)+'\\xspace}\n' for k,v in macros.items()),newline='\n')
