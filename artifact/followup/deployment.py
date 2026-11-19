#!/usr/bin/env python3
"""Verified freezer-state callback campaign; isolated P06 overlays only, never overwrite.
Usage: deployment.py SERIAL [--out PATH.jsonl] [--modes bg_unfrozen,bg_freezer,fg,assistant] [--source contacts] [--n 20]
Defaults reproduce the emulator campaign; B1 on the test phone also runs --source media and --source calllog."""
import sys,json,time,random,os,hashlib,argparse,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'artifact/revision'))
from run import setup,lmdrv
OUT=ROOT/'artifact/results/followup-20261116'
ap=argparse.ArgumentParser();ap.add_argument('serial');ap.add_argument('--out');ap.add_argument('--modes',default='bg_unfrozen,bg_freezer,fg,assistant')
ap.add_argument('--source',default='contacts',choices=['contacts','media','calllog']);ap.add_argument('--n',type=int,default=20)
ap.add_argument('--freeze-diag',type=int,default=0,help='B1 bg_freezer diagnosis on the phone: N trials per launch variant a, b, c, d (no mutation, no decision)')
a=ap.parse_args()
serial=a.serial;out=Path(a.out) if a.out else OUT/f'deploy-{serial}.jsonl'
c,w=setup(serial,out.parent if a.out else None);d=c.d
if a.source in d.excluded:raise SystemExit('source %s is excluded on this device (PHYS-PROTOCOL.md section 4)'%a.source)

def diag_sample(pkg):
 """What ActivityManager says about the client's freezer state: cgroup freeze, the process record's freezer fields,
 its oom line, connected providers and /proc status (B1 bg_freezer never froze on Device Farm's Pixel 8, run 106d9bc0)."""
 p=d.pid(pkg);s={'pid':p,'frozen':d.frozen(pkg) if p else 'dead'}
 blk=d.sh('dumpsys activity processes '+pkg);i=blk.find('*APP*');blk=blk[i:i+3500] if i>=0 else blk[:500]
 for k in ('isFrozen','isPendingFreeze','isFreezeExempt','earliestFreezableTimeMs','pendingUiClean','curProcState','hasShownUi','cached','empty'):
  m=re.search(k+r'=(\S+)',blk);s[k]=m.group(1) if m else None
 m=re.search(r'oom adj: ([^\n]*)',blk);s['oom_adj']=m.group(1) if m else None
 s['providers']=re.findall(r'- (\S+)->',blk)
 s['oom_line']=[l.strip() for l in d.sh('dumpsys activity oom | grep -m3 leasemem').splitlines()]
 s['proc_status']=d.sh('grep -E "^(State|voluntary_ctxt|nonvoluntary_ctxt)" /proc/%s/status'%p).strip() if p else None
 # every cgroup line: a vendor may freeze through the v1 freezer controller (Galaxy S25 B0 run 9f8a842d: v2 freeze 0 after 25 s)
 s['cgroup']=d.sh('cat /proc/%s/cgroup'%p).strip() if p else None
 s['block']=blk
 return s

if a.freeze_diag:
 # (a) no force-stop; (b) ensure before the app starts; (c) the B0 probe's sequence (stopservice, launch, home, no
 # ensure); (d) this driver's own bg_freezer sequence (force-stop, start, ensure, home), the negative control.
 pkg='org.leasemem.client'
 d.sh('device_config set_sync_disabled_for_tests until_reboot');d.sh('device_config put activity_manager_native_boot freeze_debounce_timeout 2000')
 start=lambda:d.sh(d.u(f'am start -W -n {pkg}/org.leasemem.client.Main'))
 with lmdrv.open_new(out) as f:
  for v in ('a','b','c','d'):
   for i in range(a.freeze_diag):
    r={**d.meta(),'serial':serial,'exp':'freeze_diag','variant':v,'trial':i,'source':a.source,'debounce_ms':2000}
    try:
     if v=='a':start();time.sleep(.4);w.ensure_base();time.sleep(.5)
     elif v=='b':d.sh(d.u('am force-stop '+pkg));w.ensure_base();start();time.sleep(.4)
     elif v=='c':d.sh(d.u('am stopservice -n %s/.FgService'%pkg));d.launch();time.sleep(1)
     else:d.sh(d.u('am force-stop '+pkg));start();time.sleep(.4);w.ensure_base();time.sleep(.5)
     t0=time.monotonic();d.home();r['samples']=[]
     for at in (3,10,25):
      time.sleep(max(0,at-(time.monotonic()-t0)))
      smp=diag_sample(pkg);smp['t_s']=round(time.monotonic()-t0,1);r['samples'].append(smp)
     r['froze']=any(x['frozen']=='1' for x in r['samples'])
    except Exception as e:
     r['error']=repr(e)
    f.write(json.dumps(r)+'\n');f.flush();print('freeze_diag',v,i,r.get('froze'),r.get('error','')[:100],flush=True)
 d.sh('device_config put activity_manager_native_boot freeze_debounce_timeout 600000')
 sys.exit(0)

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
  d.sh(d.u('cmd role remove-role-holder android.app.role.ASSISTANT org.leasemem.assist 0'));d.sh(d.u('am force-stop org.leasemem.assist'))
  d.sh(d.u('am force-stop org.leasemem.client'))
  if mode=='assistant':
   d.provision([(lmdrv.APKG,ROOT/'artifact/app/assist/build/LeaseMemAssist.apk')])
   d.sh(d.u('cmd role add-role-holder android.app.role.ASSISTANT '+pkg+' 0'));time.sleep(2)
  d.sh('device_config set_sync_disabled_for_tests until_reboot');d.sh('device_config put activity_manager_native_boot freeze_debounce_timeout '+('2000' if mode=='bg_freezer' else '600000'))
  for i in range(a.n):
   r={**d.meta(),'serial':serial,'mode':mode,'source':a.source,'trial':i,'host_load':lmdrv.host_load(),'target_sdk':35 if mode=='assistant' else 33}
   try:
    # Restart AFTER config change; a previous eligibility deadline must not survive.
    if mode!='assistant':d.sh(d.u('am force-stop '+pkg))
    d.sh(d.u(f'am start -W -n {pkg}/org.leasemem.client.Main'));time.sleep(.4)
    if mode=='fg':d.sh(d.u('am start-foreground-service -n org.leasemem.client/.FgService'))
    w.ensure_base();time.sleep(.5);d.home();time.sleep(3 if mode=='bg_freezer' else .5)
    # Pixel 8 on Device Farm froze 3.9 s after going home with a 2 s debounce (B0 run 1c18f498), so 3 s was too
    # short there (pilot B1 run 5ec38290): wait until frozen, at most 25 s as in b0_probe
    t_home=time.monotonic()
    while mode=='bg_freezer' and d.frozen(pkg)!='1' and time.monotonic()-t_home<22:time.sleep(.5)
    r['before']=state(pkg);r['config']=d.sh('dumpsys activity settings');r['binding']=d.sh("dumpsys voiceinteraction | grep -E 'leasemem|mBound'") if mode=='assistant' else None
    assert r['before'].get('frozen')==('1' if mode=='bg_freezer' else '0'),r['before']
    if mode=='assistant':assert 'mBound=true' in r['binding']
    r['mutation']=w.mutate(a.source,'update');r['states']=[];start=time.monotonic()
    for delay in ([3,8,14] if mode.startswith('bg') else [1]):
     time.sleep(max(0,delay-(time.monotonic()-start)));r['states'].append({'after_s':delay,**state(pkg)})
    r['memory_before_thaw']=memory(pkg)
    d.sh(d.u(f'am start -W -n {pkg}/org.leasemem.client.Main'));time.sleep(.5);r['memory_after_thaw']=memory(pkg)
   except Exception as e:r['error']=repr(e)
   f.write(json.dumps(r)+'\n');f.flush();print(mode,i,r.get('error','ok')[:150],flush=True)
 d.sh(d.u('cmd role remove-role-holder android.app.role.ASSISTANT org.leasemem.assist 0'));d.sh(d.u('am force-stop org.leasemem.assist'));d.sh(d.u('am force-stop org.leasemem.client'))
