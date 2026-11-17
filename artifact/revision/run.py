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
  self.d=lmdrv.Dev(serial);self.port=18760 if serial.endswith('5620') else 18762
  self.d.adb('forward',f'tcp:{self.port}','tcp:8766')
 def call(self,op,**kw):
  data=(json.dumps({'op':op,**kw})+'\n').encode();t=time.perf_counter_ns()
  with socket.create_connection(('127.0.0.1',self.port),timeout=60) as s:
   s.sendall(data); f=s.makefile('rb'); b=f.readline()
  r=json.loads(b);r['_host_ns']=time.perf_counter_ns()-t;r['_request_bytes']=len(data);r['_response_bytes']=len(b)
  if 'error' in r:raise RuntimeError(r['error'])
  return r

def setup(serial):
 d=lmdrv.Dev(serial);d.adb('root');d.adb('wait-for-device');d.wait_boot()
 records=[]
 for apk in ('client/build/LeaseMemClient-v4.apk','mut/build/LeaseMemMut.apk'):
  result=d.adb('install','-r','-g',str(ROOT/'artifact/app'/apk));records.append({'apk':apk,'result':result})
  if 'Success' not in result:raise RuntimeError(records)
 for pkg in ('org.leasemem.client','org.leasemem.mut'):
  d.sh(f'appops set {pkg} MANAGE_EXTERNAL_STORAGE allow');d.sh(f'appops set {pkg} WRITE_SMS allow')
  for permission in ('READ_CALL_LOG','READ_SMS','READ_CONTACTS','READ_CALENDAR','READ_MEDIA_IMAGES','WRITE_CALL_LOG','WRITE_CONTACTS','WRITE_SECURE_SETTINGS'):
   d.sh(f'pm grant {pkg} android.permission.{permission}')
 d.sh('device_config set_sync_disabled_for_tests until_reboot');d.sh('device_config put activity_manager_native_boot freeze_debounce_timeout 600000')
 d.launch();d.sh('am start-foreground-service -n org.leasemem.client/.FgService')
 w=lmdrv.World(d,random.Random(20261115));w.ensure_base()
 meta={'serial':serial,'install':records,'fingerprint':d.sh('getprop ro.build.fingerprint'),'sdk':d.sh('getprop ro.build.version.sdk'),'device_config':d.sh('dumpsys activity settings'),'apks':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'artifact/app/client/build/LeaseMemClient-v4.apk',ROOT/'artifact/app/mut/build/LeaseMemMut.apk']}}
 (D/(serial+'-setup-'+str(time.time_ns())+'.json')).write_text(json.dumps(meta,indent=2));return Client(serial),w

def main():
 ap=argparse.ArgumentParser();ap.add_argument('serial');ap.add_argument('campaign',choices=['reference','stock','host','tick']);ap.add_argument('--n',type=int,default=20);ap.add_argument('--suffix',default='');a=ap.parse_args()
 c,w=setup(a.serial);rng=random.Random(20261115);out=D/f'{a.campaign}-{a.serial}{a.suffix}.jsonl'
 with out.open('x') as f:
  def emit(r):f.write(json.dumps(r)+'\n');f.flush();print(r['trial'],r.get('case'),r.get('error','ok'),flush=True)
  for i in range(a.n):
   cases={'reference':['control','observation','reanchor','concurrent','exhaust','delete','reuse','reset','restore','aba','before_query','support','delta','action'],'stock':['contacts','calllog','media','files','sms','calendar','settings'],'host':['none','one','continuous'],'tick':['same_tick']}[a.campaign]
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
      w.ensure_base();c.call('resetcache');r['anchor']={arm:c.call('batch',mode=arm) for arm in ['refresh','validate','memo','relay']};r['mutations']=[]
      if case=='one':r['mutations'].append(w.mutate('contacts','update'))
      # Same fixture initial state for all arms; common continuous writer runs throughout all arm intervals.
      stop=threading.Event();errors=[]
      def writer():
       try:
        while not stop.is_set():r['mutations'].append(w.mutate('contacts','update'))
       except Exception as e:errors.append(str(e))
      thread=None
      if case=='continuous':thread=threading.Thread(target=writer);thread.start()
      order=['refresh','validate','memo','relay'];rng.shuffle(order);r['order']=order;r['arms']={}
      try:
       for arm in order:r['arms'][arm]=c.call('batch',mode=arm)
      finally:
       stop.set()
       if thread:thread.join(60)
      r['writer_errors']=errors;r['truth_after']=c.call('batch',mode='refresh')
    except Exception as e:r['error']=str(e);r['trace']=traceback.format_exc()
    r['end']=time.time();emit(r)
if __name__=='__main__':main()
