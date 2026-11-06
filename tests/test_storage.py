import unittest, tempfile
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from storage import AnnotationStore

class StorageTests(unittest.TestCase):
 def test_person_type_isolation_and_overwrite(self):
  with tempfile.TemporaryDirectory() as d:
   s=AnnotationStore(Path(d),100)
   def body(c): return [{'start_frame':0,'end_frame':100,'caption':c,'category':''}]
   s.save('甲','subtask',body('one'))
   s.save('甲','fine_action',body('fine'))
   s.save('乙','subtask',body('other'))
   s.save('甲','subtask',body('new'))
   self.assertEqual(s.get('甲','subtask')['result']['segments'][0]['caption'],'new')
   self.assertEqual(s.get('甲','fine_action')['result']['segments'][0]['caption'],'fine')
   self.assertEqual(s.get('乙','subtask')['result']['segments'][0]['caption'],'other')
   self.assertEqual(len(s.list()),3)
 def test_reject_gaps_overlaps_and_fractional_frames(self):
  with tempfile.TemporaryDirectory() as d:
   s=AnnotationStore(Path(d),100)
   for segments in [[],[{'start_frame':1,'end_frame':100,'caption':'x'}],[{'start_frame':0,'end_frame':50,'caption':'x'},{'start_frame':49,'end_frame':100,'caption':'y'}],[{'start_frame':0,'end_frame':99.5,'caption':'x'}]]:
    with self.assertRaises(ValueError): s.save('甲','subtask',segments)
 def test_no_silent_wrong_type_or_blank_author(self):
  with tempfile.TemporaryDirectory() as d:
   s=AnnotationStore(Path(d),100)
   for name,kind in [('', 'subtask'),('甲','oops')]:
    with self.assertRaises(ValueError): s.save(name,kind,[{'start_frame':0,'end_frame':100,'caption':'x'}])
if __name__=='__main__': unittest.main()
