import subprocess,sys,hashlib
from pathlib import Path
root=Path(__file__).resolve().parents[2]
def outputs():
 paths=[*(root/'manuscript/generated').glob('*'),*(root/'artifact/results/derived').glob('*.csv'),root/'artifact/results/derived/summary.json',root/'artifact/results/revision-20261115/summary.json',root/'artifact/results/revision-20261115/deployment-summary.json']
 return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}
subprocess.run(['make','analyze','render'],cwd=root/'artifact',check=True,stdout=subprocess.DEVNULL);a=outputs()
subprocess.run(['make','analyze','render'],cwd=root/'artifact',check=True,stdout=subprocess.DEVNULL);b=outputs()
assert a==b,[k for k in a if a[k]!=b.get(k)]
print('DETERMINISTIC',len(a),'outputs')
