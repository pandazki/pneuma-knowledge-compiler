#!/usr/bin/env python3
"""Synthetic protocol invariants; never needs evaluation data."""
import unittest,json
from project_structure import project,test
from to_material import render,verify
class ProtocolTests(unittest.TestCase):
 def test_whitelist(self):test()
 def test_roundtrip_paragraphs_and_caption_only(self):
  c={'conversation_idx':0};s={'session_index':1,'date_time':'1:00 pm on 1 May, 2023','messages':[{'speaker':'Synthetic A','text':'First\n\nSecond: exact text','images':[],'blip_caption':'independent caption','query':''}]}
  verify(c,s,render(c,s))
 def test_roundtrip_rejects_lost_caption(self):
  c={'conversation_idx':0};s={'session_index':1,'date_time':'1:00 pm on 1 May, 2023','messages':[{'speaker':'Synthetic','text':'Text','images':[],'blip_caption':'important','query':''}]}
  with self.assertRaises(ValueError):verify(c,s,render(c,s).replace('  [caption: BLIP derived] important\n',''))
if __name__=='__main__':unittest.main()
