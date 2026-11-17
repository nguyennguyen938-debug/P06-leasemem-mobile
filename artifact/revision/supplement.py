#!/usr/bin/env python3
"""Supplemental negative-contract tests on owned read-only-overlay AVDs only."""
import sys,time,json,random
from run import ROOT,D,setup
serial=sys.argv[1];c,w=setup(serial);d=c.d
with (D/f'supplement-final-{serial}.jsonl').open('x') as f:
 for i in range(20):
  for case in ['legacy','missing','permission','clock_restore','files_same_tick','sms_reuse','contacts_reset']:
   r={'serial':serial,'trial':i,'case':case}
   try:
    w.ensure_base()
    if case in ['legacy','missing']:
     cert={'schema':3} if case=='legacy' else None;r['verdict']=c.call('validate',fact='c.dana',certificate=cert)
    elif case=='permission':
     d.sh('pm revoke org.leasemem.client android.permission.READ_CONTACTS');d.launch();time.sleep(.2)
     try:
      r['verdict']=c.call('validate',fact='c.dana',certificate={'schema':4});r['read']=c.call('read',fact='c.dana')
     finally:
      d.sh('pm grant org.leasemem.client android.permission.READ_CONTACTS');d.sh('am start-foreground-service -n org.leasemem.client/.FgService')
    elif case=='clock_restore':
     r['before']=c.call('stock_evidence',source='calllog');wall=int(d.sh('date +%s'));t=time.monotonic()
     r['auto_time']=d.sh('settings get global auto_time');d.sh('settings put global auto_time 0')
     try:
      r['set_back']=d.sh(f'date @{wall-3600}');r['mutation']=w.mutate('calllog','update');r['during']=c.call('stock_evidence',source='calllog')
     finally:
      r['restore']=d.sh(f'date @{wall+int(time.monotonic()-t)}');d.sh('settings put global auto_time '+r['auto_time'].strip())
     r['after']=c.call('stock_evidence',source='calllog');r['verdict']=c.call('validate',fact='l.missed',certificate={'schema':4})
    elif case=='files_same_tick':
     r['before']=c.call('stock_evidence',source='files');r['mutation']=d.mut('file_touch_same_second',extra='--es tag revision');r['after']=c.call('stock_evidence',source='files');r['verdict']=c.call('validate',fact='f.todo',certificate={'schema':4})
    elif case=='sms_reuse':
     r['mutation']=d.mut('sms_reuse');r['verdict']=c.call('validate',fact='s.tracked',certificate={'schema':4})
    else:
     r['before']=c.call('stock_evidence',source='contacts');r['reset_result']=d.sh('pm clear com.android.providers.contacts');time.sleep(.3);w.ensure_base();d.launch();time.sleep(.2);d.sh('am start-foreground-service -n org.leasemem.client/.FgService');r['after']=c.call('stock_evidence',source='contacts');r['verdict']=c.call('validate',fact='c.dana',certificate={'schema':4})
   except Exception as e:r['error']=str(e)
   f.write(json.dumps(r)+'\n');f.flush();print(i,case,r.get('error','ok'),flush=True)
