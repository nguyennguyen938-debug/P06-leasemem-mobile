#!/usr/bin/env python3
"""Paired resumed draft-writing tasks, real local LLMs and Android file effects.
Shared prefix: read inputs, create cached action, kill/no-gap, seeded writes.
Measured suffix per arm: read/validate inputs, optionally invoke model, write draft,
read it back. No messages are transmitted. No timing sum stands in for suffix wall time.
"""
import sys,json,time,random,urllib.request,tempfile,hashlib,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'artifact/revision'))
from run import setup,lmdrv,Client
D=ROOT/'artifact/results/followup-20261116'
serial='emulator-5622'
TASKS=[('contact_card',['c.dana']),('photo_draft',['c.dana','m.latest']),('meeting_draft',['c.dana','k.standup'])]
MODELS=['qwen2.5:7b','llama3.2:3b']

def generate(model,task,inputs):
 prompt='Create an Android draft, not a transmitted message. Return only a JSON object with keys action, task, inputs, text. action must be "save_draft". Copy task and all inputs exactly. Write text as one useful sentence using these inputs. '+json.dumps({'task':task,'inputs':inputs})
 body={'model':model,'prompt':prompt,'format':'json','stream':False,'keep_alive':'20m','options':{'temperature':0,'seed':20261116,'num_predict':220,'num_ctx':2048}}
 t=time.perf_counter();req=urllib.request.Request('http://127.0.0.1:11434/api/generate',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=180) as f:response=json.load(f)
 try:action=json.loads(response['response'])
 except Exception:action=None
 return {'request':body,'response':response,'action':action,'wall_s':time.perf_counter()-t}

def inputs(v,keys):return {k:v[k] for k in keys}

def main():
 c,w=setup(serial);d=c.d;rng=random.Random(20261116)
 inventory=json.load(urllib.request.urlopen('http://127.0.0.1:11434/api/tags'));(D/'agent-models.json').write_text(json.dumps(inventory,indent=2))
 d.sh('mkdir -p /sdcard/Documents/lm-agent-drafts')
 with (D/'agent-tasks.jsonl').open('x') as f:
  for model in MODELS:
   generate(model,'warmup',{'value':'ready'})
   for gap,prob in [('force-stop',.1),('force-stop',.3),('none',.3)]:
    for i in range(24):
     task,keys=TASKS[i%len(TASKS)];r={'model':model,'gap':gap,'p_change':prob,'trial':i,'task':task,'keys':keys,'seed':20261116,'host_load':os.getloadavg()}
     try:
      if not d.pid():d.launch();d.sh('am start-foreground-service -n org.leasemem.client/.FgService')
      w.ensure_base();c.call('resetcache');r['anchor']=c.call('batch',mode='refresh');old=inputs(r['anchor']['values'],keys);r['cached']=generate(model,task,old)
      d.home();r['pid_before']=d.pid()
      if gap=='force-stop':
       d.sh('am force-stop org.leasemem.client');assert not d.pid()
      r['mutations']=[]
      for src in ['contacts','media','calendar']:
       if rng.random()<prob:r['mutations'].append(w.mutate(src,'update'))
      time.sleep(.2)
      if gap=='force-stop':d.launch();d.sh('am start-foreground-service -n org.leasemem.client/.FgService')
      r['pid_after']=d.pid();order=['refresh','memo','evidence'];rng.shuffle(order);r['order']=order;r['arms']={}
      for arm in order:
       t=time.perf_counter();x={};r['arms'][arm]=x
       x['read']=c.call('batch',mode='validate' if arm=='evidence' else 'refresh');current=inputs(x['read']['values'],keys)
       # Strict stock evidence is UNKNOWN: rederive. Memo compares complete current inputs.
       reuse=arm=='memo' and old==current and r['cached']['action'] is not None
       x['reused']=reuse
       x['generation']=r['cached'] if reuse else generate(model,task,current)
       action=x['generation']['action'];x['dispatchable']=isinstance(action,dict) and action.get('action')=='save_draft'
       x['submitted_inputs']=action.get('inputs') if isinstance(action,dict) else None
       if x['dispatchable']:
        payload=json.dumps(action,sort_keys=True).encode();target=f'/sdcard/Documents/lm-agent-drafts/result-{arm}.json'
        with tempfile.NamedTemporaryFile() as tmp:
         tmp.write(payload);tmp.flush();x['push']=d.adb('push',tmp.name,target)
        actual=d.sh('cat '+target);x['saved']=json.loads(actual);x['effect_sha256']=hashlib.sha256(actual.strip().encode()).hexdigest()
       x['suffix_wall_s']=time.perf_counter()-t
       truth=inputs(c.call('batch',mode='refresh')['values'],keys);x['truth_after']=truth
       x['stale_action']=x['dispatchable'] and old!=truth and x['submitted_inputs']==old
       x['wrong_inputs']=x['dispatchable'] and x['submitted_inputs']!=truth
       x['task_success']=bool(x['dispatchable'] and x.get('saved',{}).get('inputs')==truth and x.get('saved',{}).get('task')==task and isinstance(x.get('saved',{}).get('text'),str) and x['saved']['text'].strip())
       x['certified_reuses']=0 # stock adapters cannot certify; fallback is explicit.
      r['changed_inputs']=old!=r['arms']['refresh']['truth_after']
     except Exception as e:r['error']=repr(e)
     f.write(json.dumps(r)+'\n');f.flush();print(model,gap,prob,i,r.get('error','ok'),flush=True)
if __name__=='__main__':main()
