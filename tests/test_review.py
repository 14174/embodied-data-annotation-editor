import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from storage import AnnotationStore, next_episode


class ReviewTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root=Path(directory.name)
        self.store=AnnotationStore(self.root/'episode_000009', 100)

    def test_note_and_signature_required(self):
        for author,kind,note in [('甲','subtask','  '),('甲','subtask',None),
                                 ('','subtask','异常'),('甲','other','异常'),
                                 ('甲','subtask','x'*2001)]:
            with self.assertRaises(ValueError):
                self.store.flag(author,kind,note)
        self.assertEqual(self.store.flags(),[])

    def test_reports_are_episode_scoped_and_preserve_each_submission(self):
        first=self.store.flag(' 甲 ','subtask',' 指令和执行对象不一致 ',
                              {'dataset_name':'sample','episode_index':9,'original_instruction':'Pick orange'})
        second=self.store.flag('乙','fine_action','目标身份需核实')
        third=self.store.flag('甲','subtask','补充说明')
        flags=self.store.flags()
        self.assertEqual(len(flags),3)
        self.assertEqual(len({row['report_id'] for row in flags}),3)
        self.assertEqual(first['annotator'],'甲')
        self.assertEqual(first['note'],'指令和执行对象不一致')
        self.assertEqual(first['status'],'needs_review')
        self.assertEqual(first['original_instruction'],'Pick orange')
        self.assertEqual({row['annotation_type'] for row in flags},{'subtask','fine_action'})
        self.assertGreaterEqual(third['created_at'],second['created_at'])
        self.assertEqual(AnnotationStore(self.root/'episode_000010',100).flags(),[])

    def test_flags_do_not_count_as_annotations_or_change_existing_captions(self):
        segments=[{'start_frame':0,'end_frame':100,'caption':'Pick green'}]
        saved=self.store.save('甲','subtask',segments)
        self.store.flag('甲','subtask','需要核对指令')
        self.assertEqual(self.store.list(),[saved])
        self.assertEqual(self.store.get('甲','subtask'),saved)
        self.store.flag('乙','fine_action','需要核对')
        self.assertEqual(next_episode(self.root,[0,9],0,'fine_action'),
                         {'episode_index':9,'unannotated':True})
