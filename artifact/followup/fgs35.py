import sys,json,time
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'revision'))
from run import ROOT,lmdrv
D=ROOT/'artifact/results/followup-20261116'
serial='emulator-5622';d=lmdrv.Dev(serial)
assert d.sh('getprop ro.build.version.sdk').strip()=='35'
results=[]
for variant in ['missing','typed']:
 d.sh('am force-stop org.leasemem.client');d.sh('am force-stop org.leasemem.assist')
 r={'variant':variant,'target_sdk':35,'runtime_sdk':35,'install':d.adb('install','-r','-g',str(ROOT/f'artifact/app/fgs35/build/FGS35-{variant}.apk'))}
 d.sh('logcat -c');r['activity']=d.sh('am start -W -n org.leasemem.fgs35/org.leasemem.client.Main');time.sleep(1)
 r['start']=d.sh('am start-foreground-service -n org.leasemem.fgs35/org.leasemem.client.FgService');time.sleep(2)
 r['services']=d.sh('dumpsys activity services org.leasemem.fgs35');r['logcat']=d.sh('logcat -d -t 1000');r['package']=d.sh('dumpsys package org.leasemem.fgs35')
 d.sh('am force-stop org.leasemem.fgs35');results.append(r)
(D/'fgs35.json').write_text(json.dumps(results,indent=2)+'\n')
print([(r['variant'],'MissingForegroundServiceTypeException' in r['logcat'],'isForeground=true' in r['services'])for r in results])
