#!/usr/bin/env python3
"""Verified freezer-state callback campaign; isolated P06 overlays only, never overwrite.
Usage: deployment.py SERIAL [--out PATH.jsonl] [--modes bg_unfrozen,bg_freezer,fg,assistant] [--source contacts] [--n 20]
Defaults reproduce the emulator campaign; B1 on the test phone also runs --source media and --source calllog."""
import sys,json,time,random,os,hashlib,argparse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'artifact/revision'))
from run import setup,lmdrv
OUT=ROOT/'artifact/results/followup-20261116'
ap=argparse.ArgumentParser();ap.add_argument('serial');ap.add_argument('--out');ap.add_argument('--modes',default='bg_unfrozen,bg_freezer,fg,assistant')
ap.add_argument('--source',default='contacts',choices=['contacts','media','calllog']);ap.add_argument('--n',type=int,default=20);a=ap.parse_args()
serial=a.serial;out=Path(a.out) if a.out else OUT/f'deploy-{serial}.jsonl'
c,w=setup(serial,out.parent if a.out else None);d=c.d

def state(pkg):
 p=d.pid(pkg);r={'pid':p,'activity':d.sh('dumpsys activity processes '+pkg)}
 if p:
  r['adj']=d.sh('cat /proc/'+p+'/oom_score_adj').strip()
  r['cgroup']=d.sh('cat /proc/'+p+'/cgroup 2>/dev/null')
  r['frozen']=d.frozen(pkg);r['frozen_method']=d.frozen_method
 return r

def memory(pkg):return json.loads(d.cat(pkg,'files/mem.json'))
with lmdrv.open_new(out) as f:
 for mode in a.modes.split(','):
  pkg='org.leasemem.assist' if mode=='assistant' else 'org.leasemem.client'
  d.sh('cmd role remove-role-holder android.app.role.ASSISTANT org.leasemem.assist 0');d.sh('am force-stop org.leasemem.assist')
  d.sh('am force-stop org.leasemem.client')
  if mode=='assistant':
   result=d.adb('install','-r','-g',str(ROOT/'artifact/app/assist/build/LeaseMemAssist.apk'));assert 'Success' in result,result
   d.sh('cmd role add-role-holder android.app.role.ASSISTANT '+pkg+' 0');time.sleep(2)
  d.sh('device_config set_sync_disabled_for_tests until_reboot');d.sh('device_config put activity_manager_native_boot freeze_debounce_timeout '+('2000' if mode=='bg_freezer' else '600000'))
  for i in range(a.n):
   r={**d.meta(),'serial':serial,'mode':mode,'source':a.source,'trial':i,'host_load':lmdrv.host_load(),'target_sdk':35 if mode=='assistant' else 33}
   try:
    # Restart AFTER config change; a previous eligibility deadline must not survive.
    if mode!='assistant':d.sh('am force-stop '+pkg)
    d.sh(f'am start -W -n {pkg}/org.leasemem.client.Main');time.sleep(.4)
    if mode=='fg':d.sh('am start-foreground-service -n org.leasemem.client/.FgService')
    w.ensure_base();time.sleep(.5);d.home();time.sleep(3 if mode=='bg_freezer' else .5)
    r['before']=state(pkg);r['config']=d.sh('dumpsys activity settings');r['binding']=d.sh('dumpsys voiceinteraction') if mode=='assistant' else None
    assert r['before'].get('frozen')==('1' if mode=='bg_freezer' else '0'),r['before']
    if mode=='assistant':assert 'mBound=true' in r['binding']
    r['mutation']=w.mutate(a.source,'update');r['states']=[];start=time.monotonic()
    for delay in ([3,8,14] if mode.startswith('bg') else [1]):
     time.sleep(max(0,delay-(time.monotonic()-start)));r['states'].append({'after_s':delay,**state(pkg)})
    r['memory_before_thaw']=memory(pkg)
    d.sh(f'am start -W -n {pkg}/org.leasemem.client.Main');time.sleep(.5);r['memory_after_thaw']=memory(pkg)
   except Exception as e:r['error']=repr(e)
   f.write(json.dumps(r)+'\n');f.flush();print(mode,i,r.get('error','ok')[:150],flush=True)
 d.sh('cmd role remove-role-holder android.app.role.ASSISTANT org.leasemem.assist 0');d.sh('am force-stop org.leasemem.assist');d.sh('am force-stop org.leasemem.client')
