#!/usr/bin/env python3
import json,sys,time,random
from pathlib import Path
from run import ROOT,D,Client,setup,lmdrv
serial=sys.argv[1];d=lmdrv.Dev(serial);w=lmdrv.World(d,random.Random(20261115));c=Client(serial)
# All reads of callback records below are root-side file reads, avoiding a client wake-up during the hold.
def state(pkg):
 pid=d.pid(pkg);o={'pid':pid,'activity':d.sh('dumpsys activity processes '+pkg)}
 if pid:
  o['cgroup']=d.sh(f'cat /proc/{pid}/cgroup');o['oom_adj']=d.sh(f'cat /proc/{pid}/oom_score_adj')
  for ln in o['cgroup'].splitlines():
   if ln.startswith('0::'):o['frozen']=d.sh('cat /sys/fs/cgroup'+ln[3:]+'/cgroup.freeze').strip()
 return o
with (D/f'deploy-{serial}.jsonl').open('x') as f:
 for mode in ['bg_unfrozen','bg_freezer','fg','assistant']:
  pkg='org.leasemem.assist' if mode=='assistant' else 'org.leasemem.client'
  if mode=='assistant':
   d.sh('am force-stop org.leasemem.client');d.adb('install','-r','-g',str(ROOT/'artifact/app/assist/build/LeaseMemAssist.apk'))
   d.sh('cmd role add-role-holder android.app.role.ASSISTANT '+pkg+' 0');time.sleep(3)
  d.sh('am stopservice -n org.leasemem.client/.FgService');d.sh('device_config set_sync_disabled_for_tests until_reboot')
  d.sh('device_config put activity_manager_native_boot freeze_debounce_timeout '+('10000' if mode=='bg_freezer' else '600000'))
  for i in range(10):
   r={'mode':mode,'serial':serial,'trial':i}
   try:
    d.sh(f'am start -W -n {pkg}/org.leasemem.client.Main');time.sleep(.3)
    if mode=='fg':d.sh('am start-foreground-service -n org.leasemem.client/.FgService')
    w.ensure_base();time.sleep(1)
    # Drain old callbacks in foreground, then move to HOME without touching the client.
    d.sh('input keyevent KEYCODE_HOME');time.sleep(1)
    r['before']=state(pkg);r['config']=d.sh('dumpsys activity settings');r['binding']=d.sh('dumpsys voiceinteraction') if mode=='assistant' else None
    r['mutation']=w.mutate('contacts','update');r['states']=[]
    for delay in [3,8,14]:
     time.sleep(max(0,r['mutation']['t_dev']/1000+delay-time.time())) if False else None
     # Wall time on host is not device clock: wait relative to monotonic host duration.
     if delay==3:base=time.monotonic();time.sleep(3)
     else:time.sleep(max(0,delay-(time.monotonic()-base)))
     r['states'].append({'after_s':delay,**state(pkg)})
    text=d.sh(f'cat /data/data/{pkg}/files/mem.json');r['memory_before_thaw']=json.loads(text)
    d.sh(f'am start -W -n {pkg}/org.leasemem.client.Main');time.sleep(1)
    r['memory_after_thaw']=json.loads(d.sh(f'cat /data/data/{pkg}/files/mem.json'))
   except Exception as e:r['error']=str(e)
   f.write(json.dumps(r)+'\n');f.flush();print(mode,i,r.get('error','ok'),flush=True)
 d.sh('cmd role remove-role-holder android.app.role.ASSISTANT org.leasemem.assist 0');d.sh('am force-stop org.leasemem.assist')
