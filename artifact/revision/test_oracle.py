import copy,unittest
from oracle import interval
class OracleTests(unittest.TestCase):
 def attempt(self):
  a={}
  for i,k in enumerate(['before','query','support','delta','after']):a[k]={'epoch':'e','revision':1,'rows':[[1,'A']],'start_ns':i*3,'snapshot_ns':i*3+1,'end_ns':i*3+2}
  return a
 def test_unchanged(self):
  a=self.attempt();self.assertEqual(interval(a['before'],a),'FRESH')
 def test_changed(self):
  a=self.attempt();old=copy.deepcopy(a['before']);old['rows']=[[1,'old']];self.assertEqual(interval(old,a),'CHANGED')
 def test_epoch(self):
  a=self.attempt();old=copy.deepcopy(a['before']);old['epoch']='old';self.assertEqual(interval(old,a),'UNKNOWN')
 def test_intervening_commit(self):
  a=self.attempt();a['after']['revision']=2;self.assertEqual(interval(a['before'],a),'UNKNOWN')
 def test_inconsistent_middle_rejected(self):
  a=self.attempt();a['support']['revision']=2
  with self.assertRaises(AssertionError):interval(a['before'],a)
 def test_bad_timestamp_rejected(self):
  a=self.attempt();a['query']['snapshot_ns']=999
  with self.assertRaises(AssertionError):interval(a['before'],a)
if __name__=='__main__':unittest.main()
