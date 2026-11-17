"""Release checks on independently counted trials and measured policy semantics."""
import csv,json,unittest,re,io,copy
from analyze import audit_task
from pathlib import Path
P=Path(__file__).resolve().parents[2];D=P/'artifact/results/followup-20261116';G=P/'manuscript/generated'
class ResultsTests(unittest.TestCase):
 def test_fgs_sigkill_in_denominator(self):
  rows=list(csv.DictReader(io.StringIO((P/'artifact/results/derived/e2_policy.csv').read_text())))
  rows=[r for r in rows if r['platform']=='api33'and r['protocol']=='v3'and r['client']=='fg'and r['policy']=='lm'and r['phase']=='early']
  ending={'unregister','sigkill','forcestop','reboot'}
  self.assertEqual(sum(int(r['n_trials'])for r in rows if r['gap']in ending),60)
  self.assertEqual(sum(int(r['n_trials'])for r in rows if r['gap']=='sigkill'),15)
  block=(G/'tab_summary.tex').read_text().split('foreground-service client')[1]
  self.assertNotIn('bucket',block);self.assertNotIn('revoke',block)
  self.assertIn('Unregister, SIGKILL, force-stop, reboot & 60',block)
 def test_deployment_completeness(self):
  s=json.loads((D/'summary.json').read_text());self.assertEqual(len(s['deployment']),9)
  for r in s['deployment']:
   self.assertEqual(r['attempted'],20);self.assertEqual(r['valid'],20)
   if r['mode']=='bg_freezer':self.assertEqual(r['frozen'],20);self.assertEqual(r['before_thaw'],0);self.assertEqual(r['after_thaw'],20)
   if r['mode']=='assistant':self.assertEqual(r['bound'],20)
 def test_agent_pairs_and_fallback(self):
  rows=[json.loads(l)for l in (D/'agent-tasks.jsonl').read_text().splitlines()];self.assertEqual(len(rows),144)
  for r in rows:
   self.assertNotIn('error',r);self.assertEqual(set(r['arms']),{'refresh','memo','evidence'})
   for k,x in r['arms'].items():
    self.assertGreater(x['suffix_wall_s'],0)
    if k=='evidence':
     self.assertFalse(x['reused']);self.assertEqual(x['certified_reuses'],0)
     self.assertTrue(all(z['verdict']=='UNKNOWN'for z in x['read']['verdicts'].values()))
 def test_task_oracle_rejects_falsified_effect(self):
  r=json.loads((D/'agent-tasks.jsonl').read_text().splitlines()[0]);audit_task(r)
  changed=copy.deepcopy(r);changed['arms']['refresh']['saved']['inputs']={'fake':'value'}
  with self.assertRaises(AssertionError):audit_task(changed)
 def test_task_oracle_rejects_false_success(self):
  r=json.loads((D/'agent-tasks.jsonl').read_text().splitlines()[0]);r['arms']['refresh']['task_success']=not r['arms']['refresh']['task_success']
  with self.assertRaises(AssertionError):audit_task(r)
 def test_pair_ci_available(self):
  s=(G/'tab_checks_host.tex').read_text();self.assertNotIn('Inputs &',s);self.assertIn('95\\%',s)
 def test_body_provenance_names(self):
  for p in (P/'manuscript/sections').glob('*.tex'):
   self.assertIsNone(re.search(r'\b(historical|revision|repaired|archived|earlier|v3)\b',p.read_text(),re.I),p.name)
if __name__=='__main__':unittest.main()
