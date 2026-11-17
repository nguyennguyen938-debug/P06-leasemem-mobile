"""Expanded Contacts-only persistent-system cohort on owned writable-system overlay."""
import sys,json,time,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'artifact/revision'))
from run import setup,lmdrv
D=ROOT/'artifact/results/followup-20261116';serial='emulator-5620';pkg='org.leasemem.persist'
boot=lmdrv.Dev(serial);boot.wait_boot();boot.adb('root');boot.adb('wait-for-device');assert 'uid=0'in boot.sh('id')
c,w=setup(serial);d=c.d
for permission in ['READ_CONTACTS','READ_CALENDAR','READ_MEDIA_IMAGES','READ_SMS']:
 d.sh('pm grant '+pkg+' android.permission.'+permission)
d.sh('am force-stop org.leasemem.client')
pid=d.pid(pkg);assert pid,'persistent app not installed at boot'
d.sh('kill -9 '+pid);time.sleep(2) # register observers only after grants
assert d.pid(pkg) and d.pid(pkg)!=pid
meta={'package':d.sh('dumpsys package '+pkg),'fingerprint':d.sh('getprop ro.build.fingerprint'),'setup':'read-only userdata overlay with writable temporary system; persistent priv-app; post-permission restart'}
(D/'persist-setup.json').write_text(json.dumps(meta,indent=2)+'\n')
assert 'PERSISTENT'in meta['package'] and 'SYSTEM'in meta['package']
def state():
 p=d.pid(pkg);cg=d.sh('cat /proc/'+p+'/cgroup');r={'pid':p,'activity':d.sh('dumpsys activity processes '+pkg),'adj':d.sh('cat /proc/'+p+'/oom_score_adj').strip(),'cgroup':cg}
 for line in cg.splitlines():
  if line.startswith('0::'):r['frozen']=d.sh('cat /sys/fs/cgroup'+line[3:]+'/cgroup.freeze').strip()
 return r
def memory():return json.loads(d.sh(f'cat /data/data/{pkg}/files/mem.json'))
w.ensure_base();time.sleep(1)
with (D/'deploy-emulator-5620-persist.jsonl').open('x')as f:
 for i in range(20):
  r={'mode':'persist','serial':serial,'trial':i,'host_load':os.getloadavg(),'target_sdk':33}
  try:
   d.home();time.sleep(.5);r['before']=state();assert r['before']['adj']=='-800' and r['before']['frozen']=='0',r['before']
   r['mutation']=w.mutate('contacts','update');time.sleep(1);r['states']=[{'after_s':1,**state()}];r['memory_before_thaw']=memory()
   d.sh(f'am start -W -n {pkg}/org.leasemem.client.Main');time.sleep(.3);r['memory_after_thaw']=memory()
  except Exception as e:r['error']=repr(e)
  f.write(json.dumps(r)+'\n');f.flush();print(i,r.get('error','ok')[:250],flush=True)
