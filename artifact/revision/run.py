#!/usr/bin/env python3
"""Live revision campaign; fresh output path required. Never consumes historical outputs."""
import argparse,json,os,random,socket,sys,time,threading,traceback,hashlib,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'artifact/driver'))
import lmdrv
D=ROOT/'artifact/results/revision-20261115'
class Client:
 def __init__(self,serial):
  # P06 emulators keep their historical ports; any other device (the test phone) uses $P06_PORT (default 18764).
  self.d=lmdrv.Dev(serial);self.port={'emulator-5620':18760,'emulator-5622':18762}.get(serial,int(os.environ.get('P06_PORT','18764')))
  self.d.adb('forward',f'tcp:{self.port}','tcp:8766')
 def call(self,op,**kw):
  data=(json.dumps({'op':op,**kw})+'\n').encode();t=time.perf_counter_ns()
  with socket.create_connection(('127.0.0.1',self.port),timeout=60) as s:
   s.sendall(data); f=s.makefile('rb'); b=f.readline()
  r=json.loads(b);r['_host_ns']=time.perf_counter_ns()-t;r['_request_bytes']=len(data);r['_response_bytes']=len(b)
  if 'error' in r:raise RuntimeError(r['error'])
  return r

def setup(serial,out_dir=None):
 # `adb root` is refused on a production phone and then changes nothing; lmdrv falls back to run-as.
 d=lmdrv.Dev(serial);d.adb('root');d.adb('wait-for-device');d.wait_boot()
 # install in the test user, grant there, and write each app's excluded sources (lmdrv.Dev.provision)
 records=d.provision([('org.leasemem.client',ROOT/'artifact/app/client/build/LeaseMemClient-v4.apk'),('org.leasemem.mut',ROOT/'artifact/app/mut/build/LeaseMemMut.apk')])
 d.sh('device_config set_sync_disabled_for_tests until_reboot');d.sh('device_config put activity_manager_native_boot freeze_debounce_timeout 600000')
 d.launch();d.sh(d.u('am start-foreground-service -n org.leasemem.client/.FgService'))
 w=lmdrv.World(d,random.Random(20261115));w.ensure_base()
 meta={**d.meta(),'serial':serial,'install':records,'fingerprint':d.sh('getprop ro.build.fingerprint'),'sdk':d.sh('getprop ro.build.version.sdk'),'device_config':d.sh('dumpsys activity settings'),'apks':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'artifact/app/client/build/LeaseMemClient-v4.apk',ROOT/'artifact/app/mut/build/LeaseMemMut.apk']}}
 out_dir=Path(out_dir or D);out_dir.mkdir(parents=True,exist_ok=True)
 with (out_dir/(serial.replace(':','_')+'-setup-'+str(time.time_ns())+'.json')).open('x',encoding='utf-8') as f:f.write(json.dumps(meta,indent=2))
 return Client(serial),w

def main():
 ap=argparse.ArgumentParser();ap.add_argument('serial');ap.add_argument('campaign',choices=['reference','stock','host','tick']);ap.add_argument('--n',type=int,default=20);ap.add_argument('--suffix',default='')
 # --out-dir: physical-phone runs write to results/physical-<date>/; --arms: host campaign arms (B6 adds 'stamp').
 ap.add_argument('--out-dir',default=str(D));ap.add_argument('--arms',default='refresh,validate,memo,relay');a=ap.parse_args();arms=a.arms.split(',')
 c,w=setup(a.serial,a.out_dir);rng=random.Random(20261115);out=Path(a.out_dir)/f"{a.campaign}-{a.serial.replace(':','_')}{a.suffix}.jsonl"
 with lmdrv.open_new(out) as f:
  def emit(r):f.write(json.dumps({**c.d.meta(),**r})+'\n');f.flush();print(r['trial'],r.get('case'),r.get('error','ok'),flush=True)
  for i in range(a.n):
   cases={'reference':['control','observation','reanchor','concurrent','exhaust','delete','reuse','reset','restore','aba','before_query','support','delta','action'],'stock':['contacts','calllog','media','files','sms','calendar','settings'],'host':['none','one','continuous'],'tick':['same_tick']}[a.campaign]
   if a.campaign=='stock':cases=[x for x in cases if x not in w.d.excluded]   # SMS (and an unproven call log) never on the phone
   for case in cases:
    r={'trial':i,'case':case,'serial':a.serial,'seed':20261115,'campaign':a.campaign,'start':time.time()}
    try:
     if a.campaign=='reference':r['result']=c.call('reference',scenario=case)
     elif a.campaign=='tick':r['result']=c.call('tick')
     elif a.campaign=='stock':
      w.ensure_base();c.call('install_historical_anchor');r['before']=c.call('stock_evidence',source=case)
      kind=['update','delete','insert'][i%3] if case!='settings' else 'update'
      r['mutation']=w.mutate(case,kind);c.call('overwrite_historical_wm',source=case)
      r['after']=c.call('stock_evidence',source=case);r['historical']=c.call('historical_validate')
      r['repaired']={fid:c.call('validate',fact=fid,certificate={'schema':4}) for fid in r['before']['values']}
     else:
      w.ensure_base();c.call('resetcache');r['anchor']={arm:c.call('batch',mode=arm) for arm in arms};r['mutations']=[]
      if case=='one':r['mutations'].append(w.mutate('contacts','update'))
      # Same fixture initial state for all arms; common continuous writer runs throughout all arm intervals.
      stop=threading.Event();errors=[]
      def writer():
       try:
        while not stop.is_set():r['mutations'].append(w.mutate('contacts','update'))
       except Exception as e:errors.append(str(e))
      thread=None
      if case=='continuous':thread=threading.Thread(target=writer);thread.start()
      order=list(arms);rng.shuffle(order);r['order']=order;r['arms']={}
      try:
       for arm in order:r['arms'][arm]=c.call('batch',mode=arm)
      finally:
       stop.set()
       if thread:thread.join(60)
      r['writer_errors']=errors;r['truth_after']=c.call('batch',mode='refresh')
    except Exception as e:r['error']=str(e);r['trace']=traceback.format_exc()
    r['end']=time.time();emit(r)
if __name__=='__main__':main()
