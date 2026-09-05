#!/usr/bin/env python3
import unittest
from answer import project,parse
class AnswerTests(unittest.TestCase):
 def test_gold_never_projected(self):
  p=project({'qa_id':'synthetic','conversation_idx':0,'question':'Synthetic question','answer':'BAIT','evidence':'BAIT','evidence_messages':'BAIT','category':'BAIT'})
  self.assertEqual(set(p),{'qa_id','conversation_idx','question'});self.assertNotIn('BAIT',str(p))
 def test_cli_parse(self):
  answer,usage=parse("Q: Synthetic\nA: value [cite: s01 ¶1]\n  (2.0s, 1→1 claims / 0 episode summaries / 1→1 source windows, tokens {'input_tokens': 12, 'output_tokens': 3, 'total_tokens': 15})\n  stages: synthetic\n")
  self.assertEqual(answer,'value');self.assertEqual(usage['total_tokens'],15)
if __name__=='__main__':unittest.main()
