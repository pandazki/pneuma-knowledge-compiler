#!/usr/bin/env python3
"""Synthetic coverage for the attributable budget guard, without keys or datasets."""
import importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import runtime

class BudgetGuardTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  (self.root/'build-record/answers').mkdir(parents=True)
  (self.root/'results').mkdir()
  self.root_patch=patch.object(runtime,'ROOT',self.root);self.root_patch.start()
 def tearDown(self):self.root_patch.stop();self.tmp.cleanup()
 def write_compile(self,inputs,outputs):
  (self.root/'build-record/snapshot-00.json').write_text(json.dumps({'jobs':[{'job_id':'synthetic','kind':'compile','input_tokens':inputs,'output_tokens':outputs}]}))
 def test_uses_own_compile_and_answer_without_provider(self):
  self.write_compile(1_000_000,100_000)
  (self.root/'build-record/answers/test.json').write_text(json.dumps({'input_tokens':2_000_000,'output_tokens':50_000}))
  with patch.object(runtime,'provider_spend',side_effect=AssertionError('shared key must not gate')):
   self.assertAlmostEqual(runtime.check_budget(),.78)
  record=json.loads((self.root/'results/own-cost.json').read_text())
  self.assertTrue(record['undercounts']);self.assertEqual(record['hard_ceiling_usd'],60)
 def test_preserves_reserve_soft_and_hard_stops(self):
  for amount,limit in [(45,45),(50,50),(60,100)]:
   with self.subTest(amount=amount):
    self.write_compile(int(amount/.2*1e6),0)
    with self.assertRaisesRegex(RuntimeError,'budget'):
     runtime.check_budget(limit)
 def test_snapshot_replacement_does_not_double_count(self):
  self.write_compile(1_000_000,0);self.assertAlmostEqual(runtime.check_budget(),.2)
  self.write_compile(2_000_000,0);self.assertAlmostEqual(runtime.check_budget(),.4)
if __name__=='__main__':unittest.main()
