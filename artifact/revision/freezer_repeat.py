import sys,time,json,random
from run import D,lmdrv
serial=sys.argv[1];d=lmdrv.Dev(serial);w=lmdrv.World(d,random.Random(20261115));pkg='org.leasemem.client'
def state():
 pid=d.pid(pkg);r={'pid':pid,'activity':d.sh('dumpsys activity processes '+pkg)}
 if pid:
  cg=d.sh(f'cat /proc/{pid}/cgroup');r['cgroup']=cg
  for line in cg.splitlines():
   if line.startswith('0::'):r['frozen']=d.sh('cat /sys/fs/cgroup'+line[3:]+'/cgroup.freeze').strip()
 return r
with (D/f'freezer-restarted-{serial}.jsonl').open('x') as f:
 for i in range(10):
  r={'serial':serial,'trial':i}
  try:
   d.sh('device_config set_sync_disabled_for_tests until_reboot');d.sh('device_config put activity_manager_native_boot freeze_debounce_timeout 10000')
   d.sh('am force-stop '+pkg);w.ensure_base();d.launch();time.sleep(1);d.home();time.sleep(1)
   r['config']=d.sh('dumpsys activity settings');r['before']=state();r['mutation']=w.mutate('contacts','update');r['states']=[];start=time.monotonic()
   for delay in [3,8,14]:
    time.sleep(max(0,delay-(time.monotonic()-start)));r['states'].append({'after_s':delay,**state()})
   r['memory_before_thaw']=json.loads(d.sh(f'cat /data/data/{pkg}/files/mem.json'))
   d.launch();time.sleep(1);r['memory_after_thaw']=json.loads(d.sh(f'cat /data/data/{pkg}/files/mem.json'))
  except Exception as e:r['error']=str(e)
  f.write(json.dumps(r)+'\n');f.flush();print(i,r.get('error','ok'),flush=True)
