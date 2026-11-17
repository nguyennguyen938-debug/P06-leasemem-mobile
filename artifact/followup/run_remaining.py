"""Wait for owned deployment collector, then run disjoint campaigns on its AVD."""
import subprocess,time,os,sys
from pathlib import Path
A=Path(__file__).resolve().parents[1];D=A/'results/followup-20261116'
pid=int(sys.argv[1])
while True:
 try:os.kill(pid,0)
 except ProcessLookupError:break
 time.sleep(5)
# Compatibility harness is reused verbatim except its output directory; preserve prior result.
s=(A/'revision/fgs35.py').read_text().replace('from run import D,ROOT,lmdrv',"import sys\nfrom pathlib import Path\nsys.path.insert(0,str(Path(__file__).resolve().parents[1]/'revision'))\nfrom run import ROOT,lmdrv\nD=ROOT/'artifact/results/followup-20261116'")
p=A/'followup/fgs35.py';p.write_text(s)
with (D/'fgs35.log').open('w')as f:subprocess.run([sys.executable,str(p)],stdout=f,stderr=subprocess.STDOUT,check=True)
with (D/'agent-tasks.log').open('w')as f:subprocess.run([sys.executable,str(A/'followup/agent_tasks.py')],stdout=f,stderr=subprocess.STDOUT,check=True)
