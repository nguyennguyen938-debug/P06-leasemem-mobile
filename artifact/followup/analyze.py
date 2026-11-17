#!/usr/bin/env python3
"""Deterministic follow-up summaries. Reads only recorded outcomes; no invented cells."""
from pathlib import Path
from collections import defaultdict,Counter
import json,statistics as st,re,math,random,csv,hashlib
ROOT=Path(__file__).resolve().parents[2];D=ROOT/'artifact/results/followup-20261116';G=ROOT/'manuscript/generated'
def load(p):return [json.loads(l)for l in p.read_text().splitlines()if l.strip()] if p.exists() else []
def fmt(ms):return f'{ms/1000:.1f}\\,s' if ms>=1000 else f'{ms:.0f}\\,ms'
def spread(ms):return f'{ms/1000:.3f}\\,s' if ms>=1000 else f'{ms:.0f}\\,ms'
def stats(xs):return {'n':len(xs),'median':st.median(xs),'min':min(xs),'max':max(xs)} if xs else {'n':0,'median':None,'min':None,'max':None}
DEPLOY_STAR=True  # one column does not fit the per-row ranges legibly
def table(path,caption,label,cols,header,lines,star=False):
 cols=re.sub(r'^@\{\}|@\{\}$','',cols)
 env='table*'if star else'table';(G/path).write_text('\n'.join([f'\\begin{{{env}}}[t]',r'\centering\mtab',r'\caption{'+caption+'}',r'\label{'+label+'}',r'\begin{tabular}{'+cols+r'}\toprule',r'\mhead '+header+r'\\\midrule',*lines,r'\bottomrule\end{tabular}',f'\\end{{{env}}}'])+'\n')
def audit_task(r):
 # Independent recomputation from saved Android content and provider reads.
 old={k:r['anchor']['values'][k]for k in r['keys']};truths=[]
 for arm,x in r.get('arms',{}).items():
  if 'task_success'not in x:continue
  truth=x['truth_after'];truths.append(truth)
  assert {k:x['read']['values'][k]for k in r['keys']}==truth, 'source changed during resumed arm'
  action=x['generation']['action'];saved=x.get('saved')
  dispatched=isinstance(action,dict) and action.get('action')=='save_draft'
  assert x['dispatchable']==dispatched
  if dispatched:
   assert saved==action
   assert hashlib.sha256(json.dumps(saved,sort_keys=True).encode()).hexdigest()==x['effect_sha256']
  supplied=action.get('inputs')if isinstance(action,dict)else None
  stale=bool(dispatched and old!=truth and supplied==old)
  wrong=bool(dispatched and supplied!=truth)
  success=bool(dispatched and saved.get('inputs')==truth and saved.get('task')==r['task'] and isinstance(saved.get('text'),str) and saved['text'].strip())
  assert (stale,wrong,success)==(x['stale_action'],x['wrong_inputs'],x['task_success'])
  if x['reused']:
   assert arm=='memo' and old==truth and action==r['cached']['action']
  else:assert x['suffix_wall_s']>=x['generation']['wall_s']
  if arm=='evidence':
   assert not x['reused'] and x['certified_reuses']==0
   assert all(v['verdict']=='UNKNOWN'for v in x['read']['verdicts'].values())
 assert all(t==truths[0]for t in truths), 'paired arms saw different states'
 return True

def main():
 out={};groups=defaultdict(list)
 for p in sorted(D.glob('deploy-emulator-*.jsonl')):
  for r in load(p):groups[(r['serial'],r['mode'])].append(r)
 results=[];lines=[];mac=[];seen=set()
 for (serial,mode),rs in sorted(groups.items()):
  valid=[];delays=[];frozen=before=after=bound=0;adjs=[];states=[]
  for r in rs:
   if 'error'in r:continue
   target='1'if mode=='bg_freezer'else'0'
   if r['before'].get('frozen')!=target or any(x.get('frozen')!=target for x in r['states']):continue
   valid.append(r);t=r['mutation']['t_pre'];frozen+=target=='1';bound+='mBound=true'in(r.get('binding')or'')
   ev=[e['t']-t for e in r['memory_before_thaw'].get('events',[])if e['src']=='contacts'and e['t']>=t]
   later=[e['t']-t for e in r['memory_after_thaw'].get('events',[])if e['src']=='contacts'and e['t']>=t]
   before+=bool(ev);after+=bool(later)
   if ev:delays.append(min(ev))
   adjs.append(r['before'].get('adj','?'))
  z={'serial':serial,'mode':mode,'attempted':len(rs),'valid':len(valid),'excluded':len(rs)-len(valid),'frozen':frozen,'bound':bound,'before_thaw':before,'after_thaw':after,'delay_ms':stats(delays),'delays_ms':delays,'oom_adj':dict(Counter(adjs))};results.append(z)
  api='13'if serial.endswith('5620')else'15';names={'bg_unfrozen':'Background, unfrozen','bg_freezer':'Background, frozen','fg':'Foreground service','assistant':'Bound assistant (target 35)','persist':'Persistent system app'}
  v=z['delay_ms'];lat=fmt(v['median']) if v['n']else'held';rng=(spread(v['min'])+'--'+spread(v['max'])) if v['n']else'--'
  if f'Android {api}'not in seen:seen.add(f'Android {api}');lines.append(r'\mgroup{6}{Android '+api+'}')
  lines.append(f'{names[mode]} & {len(valid)}/{len(rs)} & {lat} & {rng} & {before}/{len(valid)} & {after}/{len(valid)}'+r'\\')
  if mode in ['bg_unfrozen','fg','assistant','persist'] and v['n']:
   key=('A'if api=='13'else'B')+{'bg_unfrozen':'Bg','fg':'Fg','assistant':'Assist','persist':'Persist'}[mode]
   mac.append('\\newcommand{\\Follow'+key+'}{'+lat+'\\xspace}')
 out['deployment']=results
 if groups:
  table('tab_deploy.tex','Verified-state Contacts callbacks: median and range, with valid/attempted trials. Frozen trials hold 14 seconds after mutation; root-side reads do not wake the client. Callback counts are before/after foreground thaw. Each source change is one independent trial; this is not a handset replication.','tab:deploy','@{}lrllrr@{}','Deployment & Trials & Median & Range & Before & After',lines,DEPLOY_STAR)
  (G/'followup_macros.tex').write_text('\n'.join(mac)+'\n')
 # Sensitivity model: a single write, quiescent writers, unfrozen process, deterministic 10s deferral.
 out['hold_sensitivity']=[{'hold_uniform_0_to_s':h,'decision_offset_s':2,'assumed_delay_s':10,'probability_not_delivered':min(1,8/h)}for h in [4,10,30,60]]
 records=load(D/'agent-tasks.jsonl');ag=defaultdict(list)
 for r in records:
  audit_task(r)
  for arm,x in r.get('arms',{}).items():
   if 'task_success'in x:ag[(r['model'],arm)].append((r,x))
 agent=[];lines=[];seen=set()
 for (model,arm),pairs in sorted(ag.items()):
  xs=[x for _,x in pairs];z={'model':model,'arm':arm,'n':len(xs),'stale_actions':sum(x['stale_action']for x in xs),'wrong_inputs':sum(x['wrong_inputs']for x in xs),'task_success':sum(x['task_success']for x in xs),'reused':sum(x['reused']for x in xs),'changed_input_trials':sum(r['changed_inputs']for r,_ in pairs),'wall_s':stats([x['suffix_wall_s']for x in xs]),'per_condition':dict(Counter(f"{r['gap']}/{r['p_change']}"for r,_ in pairs))};agent.append(z)
  v=z['wall_s']
  if model not in seen:seen.add(model);lines.append(r'\mgroup{7}{'+model.replace(':',' ')+'}')
  lines.append(f"{arm} & {z['n']} & {z['stale_actions']} & {z['task_success']}/{z['n']} & {v['median']:.2f} & [{v['min']:.2f}, {v['max']:.2f}] & {z['reused']}"+r'\\')
 if records:
  table('tab_agent_tasks.tex','Resumed Android draft tasks: stale actions, exact structured-goal success and measured wall latency through file write/readback (seconds; median and range). Each model has 24 paired trials per force-stop/0.1, force-stop/0.3 and no-gap/0.3 schedule, with three tasks rotated. Memoization reuses model outputs only after reading equal current inputs.','tab:agent-tasks','@{}lrrrrrr@{}','Policy & $n$ & Stale & Success & Median & Range & Reuses',lines,False)
 if agent:
  for z in agent:
   model='Qwen'if z['model'].startswith('qwen')else'Llama'
   mac.append('\\newcommand{\\Task'+model+z['arm'].capitalize()+'}{'+f"{z['wall_s']['median']:.2f}"+'\\xspace}')
  n=min(z['n']for z in agent);mac.append('\\newcommand{\\TaskN}{'+str(n)+'\\xspace}')
  upper=100*1.959963984540054**2/(n+1.959963984540054**2)
  mac.append('\\newcommand{\\TaskZeroBound}{'+f'{upper:.1f}'+'\\xspace}')
  (G/'followup_macros.tex').write_text('\n'.join(mac)+'\n')
 out['agent']={'oracle_verified_trials':sum(audit_task(r) for r in records),'attempted':len(records),'errors':[{'model':r['model'],'trial':r['trial'],'error':r['error']}for r in records if 'error'in r],'groups':agent}
 (D/'summary.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps({'deployment_groups':len(results),'agent_trials':len(records),'agent_errors':len(out['agent']['errors'])}))
if __name__=='__main__':main()
