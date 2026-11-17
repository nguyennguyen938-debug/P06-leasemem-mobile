#!/usr/bin/env python3
"""Independent audit of logged intervals/values; never treats later values as earlier truth."""
import json,math,csv,statistics,random
from pathlib import Path
from collections import defaultdict,Counter
ROOT=Path(__file__).resolve().parents[2];D=ROOT/'artifact/results/revision-20261115';G=ROOT/'manuscript/generated';G.mkdir(exist_ok=True)
def rows(pattern):
 return [dict(json.loads(l),_file=p.name) for p in sorted(D.glob(pattern)) for l in p.read_text().splitlines() if l.strip()]
def wilson(k,n):
 if not n:return [None,None]
 z=1.959963984540054;c=(k/n+z*z/(2*n))/(1+z*z/n);h=z*math.sqrt(k/n*(1-k/n)/n+z*z/(4*n*n))/(1+z*z/n);return [max(0,c-h),min(1,c+h)]
def interval(old,attempt):
 b,q,s,d,e=[attempt[x] for x in ['before','query','support','delta','after']]
 def tok(x):return x['epoch'],x['revision']
 if tok(b)!=tok(e):return 'UNKNOWN'
 assert all(tok(x)==tok(b) for x in [q,s,d]),'stable boundary contradicts intermediate revision'
 assert b['snapshot_ns']<=q['snapshot_ns']<=s['snapshot_ns']<=d['snapshot_ns']<=e['snapshot_ns']
 assert all(x['start_ns']<=x['snapshot_ns']<=x['end_ns'] for x in [b,q,s,d,e])
 if old is None:return 'FRESH'
 if old['epoch']!=q['epoch']:return 'UNKNOWN'
 return 'FRESH' if old['rows']==q['rows'] else 'CHANGED'
def reference(r):
 x=r['result'];v=x['repaired'];attempts=v['attempts'];assert 1<=len(attempts)<=3
 anchor=r['case'] in ['observation','reanchor'];expected='UNKNOWN'
 for i,a in enumerate(attempts):
  outcome=interval(None if anchor else x['old'],a)
  stable=(a['before']['epoch'],a['before']['revision'])==(a['after']['epoch'],a['after']['revision'])
  if stable:
   assert i==len(attempts)-1;expected=outcome
   assert v['certificate']['rows']==a['query']['rows']
   assert v['certified_ns']==a['query']['snapshot_ns']
 assert v['verdict']==expected,(r['case'],v['verdict'],expected)
 if r['case']=='exhaust':assert len(attempts)==3 and expected=='UNKNOWN'
 if r['case']=='action':
  assert v['certified_ns']<x['mutation_after_check']['snapshot_ns']<=x['effect_start_ns']<=x['effect_end_ns']
  assert x['effect_uri'].startswith('content:')
 historical=anchor and x['historical_value']!=x['truth']['value'] and x['historical_stamp']['revision']==x['truth']['revision']
 return {'verdict':expected,'historical_stale':historical}
def boot(values):
 rng=random.Random(20261115);n=len(values);means=sorted(statistics.mean(rng.choices(values,k=n)) for _ in range(10000));return [means[249],means[9749]] if n else [None,None]
def main():
 summary={'seed':20261115,'notes':['One host and one AVD per Android version in revision runs.','Continuous-arm later-value differences are ambiguous, not confirmed stale uses.','Stock strict adapters are disabled; UNKNOWN is not a successful freshness certificate.']}
 initial=rows('reference-emulator-5620.jsonl')+rows('reference-emulator-5622.jsonl')
 for r in initial: reference(r)
 summary['initial_reference_audited_trials']=len(initial)
 ref=rows('reference-emulator-*-final.jsonl');assert len(ref)==560, 'incomplete final reference matrix';rr=[]
 for r in ref:
  assert 'error' not in r,r
  rr.append(reference(r))
 summary['reference']={'action_residual_trials':sum(r['case']=='action' and r['result']['used']!=r['result']['truth_after']['value'] for r in ref),'trials':len(rr),'historical_stale':sum(x['historical_stale'] for x in rr),'verdicts':dict(Counter(x['verdict'] for x in rr)),'oracle_failures':0}
 stock=rows('stock-emulator-*.jsonl');by=defaultdict(list)
 for r in stock:
  assert 'error' not in r,r
  assert all(x['verdict']=='UNKNOWN' for x in r['repaired'].values())
  stale=[f for f,v in r['before']['values'].items() if v!=r['after']['values'][f] and r['historical']['verdicts'][f]=='FRESH']
  by[(r['serial'],r['case'])].append(bool(stale))
 summary['stock']=[{'serial':s,'source':c,'trials':len(v),'historical_stale_trials':sum(v),'ci':wilson(sum(v),len(v)),'strict_unknown_trials':len(v)} for (s,c),v in sorted(by.items())]
 tick=rows('tick-emulator-*.jsonl');summary['tick']={'trials':len(tick),'pairs':sum(len(r['result']['pairs']) for r in tick),'equal_tick_changed_trials':sum(any(p['before']==p['after'] and p['value_before']!=p['value_after'] for p in r['result']['pairs']) for r in tick)}
 host=rows('host-emulator-*.jsonl');out=[]
 for serial in ['emulator-5620','emulator-5622']:
  for case in ['none','one','continuous']:
   rs=[r for r in host if r['serial']==serial and r['case']==case];assert len(rs)==30
   assert all('error' not in r and not r['writer_errors'] for r in rs)
   for arm in ['refresh','validate','memo','relay']:
    vals=[r['arms'][arm]['_host_ns']/1e6 for r in rs];diff=[(r['arms'][arm]['_host_ns']-r['arms']['refresh']['_host_ns'])/1e6 for r in rs]
    mismatches=sum(r['arms'][arm]['values']!=r['truth_after']['values'] for r in rs)
    out.append({'serial':serial,'case':case,'arm':arm,'n':len(rs),'median_ms':statistics.median(vals),'mean_difference_ms':statistics.mean(diff),'difference_ci_ms':boot(diff),'later_value_mismatch_trials':mismatches,'mismatch_interpretation':'ambiguous' if case=='continuous' else 'quiescent_value_comparison','mean_fact_reads':statistics.mean(r['arms'][arm]['fact_reads'] for r in rs),'mean_bytes':statistics.mean(r['arms'][arm]['_response_bytes']+r['arms'][arm]['_request_bytes'] for r in rs)})
 supplement=rows('supplement-final-emulator-*.jsonl')
 assert len(supplement)==280,'incomplete supplemental matrix'
 for r in supplement:
  assert 'error' not in r,r
  assert r['verdict']['verdict']=='UNKNOWN',r
  if r['case']=='permission':assert r['read']['reason']=='query_error' and r['read']['verdict']=='UNKNOWN'
  if r['case']=='contacts_reset':assert r['reset_result'].strip()=='Success'
 summary['supplement']={'trials':len(supplement),'cases':dict(Counter(r['case']for r in supplement)),'unknown':len(supplement),'permission_errors_fail_closed':sum(r['case']=='permission'for r in supplement),'successful_contacts_resets':sum(r['case']=='contacts_reset'for r in supplement),'file_same_metadata_value_changes':sum(r['case']=='files_same_tick' and r['before']['watermark']==r['after']['watermark'] and r['before']['values']!=r['after']['values'] for r in supplement),'sms_id_reuse':sum(r['case']=='sms_reuse' and len(r['mutation']['did'].split('->'))==2 and r['mutation']['did'].split('->')[0]==r['mutation']['did'].split('->')[1] for r in supplement)}
 summary['host']=out
 # Historical main-body table: independent trial, one early decision, protocol v3 only.
 hist=list(csv.DictReader((ROOT/'artifact/results/derived/e2_policy.csv').open()));groups=defaultdict(lambda:defaultdict(lambda:[0,0]))
 ending={'kill','sigkill','forcestop','reboot','perm','unregister'}
 for r in hist:
  if r['protocol']!='v3' or r['phase']!='early' or r['policy'] not in ['evr','lm']:continue
  group='epoch break' if r['gap'] in ending else 'in epoch'
  key=(r['platform'],r['client'],group);z=groups[key][r['policy']];z[0]+=int(r['trials_stale']);z[1]+=int(r['n_trials'])
 hrows=[]
 for key,pol in sorted(groups.items()):
  hrows.append({'platform':key[0],'client':key[1],'group':key[2],**{p:{'k':kn[0],'n':kn[1],'ci':wilson(*kn)} for p,kn in pol.items()}})
 summary['historical_trial_groups']=hrows
 (D/'summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n',newline='\n')
 lines=[r'\begin{table}[t]',r'\centering\mtab',r'\caption{Staged-schedule early decisions: stale trials/total and Wilson 95\% intervals. Facts within a trial are not independent observations.}',r'\label{tab:checks-trials}',r'\begin{tabular}{lllrr}\toprule',r'\mhead API & Client & Gap group & Restart-aware & StampCheck\\\midrule']
 for r in hrows:
  cells=[]
  for p in ['evr','lm']:
   z=r[p];cells.append(f"{z['k']}/{z['n']} [{100*z['ci'][0]:.1f},{100*z['ci'][1]:.1f}]\\%")
  lines.append(f"{r['platform'].replace('api','')} & {r['client']} & {r['group']} & "+' & '.join(cells)+r'\\')
 lines += [r'\bottomrule\end{tabular}',r'\end{table}'];(G/'tab_checks_trials.tex').write_text('\n'.join(lines)+'\n',newline='\n')
 lines=[r'\begin{table*}[t]',r'\centering\mtab',r'\caption{Matched host helper: median batch latency in milliseconds and paired mean differences versus refresh with trial-bootstrap 95\% CIs (30 trials per row). The validate arm re-reads every fact like refresh and adds a strict check that returns \Unknown without reading the provider, so its difference measures that call, not a validation strategy. The input-read arm equals refresh and is omitted. Continuous writes overlap arm execution.}',r'\label{tab:checks-host}',r'\begin{tabular}{llrrrrr}\toprule',r'\mhead API & Writes & Refresh & Validate & Relay & Validate $- $ refresh [CI] & Relay $- $ refresh [CI]\\\midrule']
 for serial in ['emulator-5620','emulator-5622']:
  for case in ['none','one','continuous']:
   v={x['arm']:x for x in out if x['serial']==serial and x['case']==case}
   cells=[f"{v[k]['median_ms']:.1f}" for k in ['refresh','validate','relay']]
   for k in ['validate','relay']:
    x=v[k];lo,hi=x['difference_ci_ms'];cells.append(f"{x['mean_difference_ms']:.1f} [{lo:.1f}, {hi:.1f}]")
   lines.append(('33' if serial.endswith('5620') else '35')+' & '+case+' & '+' & '.join(cells)+r'\\')
 lines += [r'\bottomrule\end{tabular}',r'\end{table*}'];(G/'tab_checks_host.tex').write_text('\n'.join(lines)+'\n',newline='\n')
 prov=json.loads((ROOT/'artifact/revision/provenance/sample.json').read_text())['rows'];per=Counter(r['task_class'] for r in prov)
 macros={'RevProvTasks':len(prov),'RevProvPerClass':min(per.values()),'RevProvClasses':len(per),'RevReference':len(ref),'RevStock':len(stock),'RevAnchoringRace':sum(sum(v) for v in by.values()),'RevTickPairs':summary['tick']['pairs'],'RevTickTrials':len(tick),'RevTickHits':summary['tick']['equal_tick_changed_trials'],'RevHost':len(host),'RevReferenceRace':summary['reference']['historical_stale'],'RevActionResidual':summary['reference']['action_residual_trials'],'RevSupplement':len(supplement)}
 (G/'revision_macros.tex').write_text(''.join('\\newcommand{\\'+k+'}{'+str(v)+'\\xspace}\n' for k,v in macros.items()),newline='\n')
 print(json.dumps({k:summary[k] for k in ['reference','tick']},indent=2))
if __name__=='__main__':main()
