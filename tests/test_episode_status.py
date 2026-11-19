import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import storage


class EpisodeStatusTests(unittest.TestCase):
    def test_counts_only_submitted_current_type_and_preserves_episode_wide_flags(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = storage.AnnotationStore(root/'episode_000000', 10)
            segs = [{'start_frame': 0, 'end_frame': 10, 'caption': 'Pick up toy.'}]
            first.save('甲', 'subtask', segs)
            first.save('甲', 'subtask', segs)
            first.save('乙', 'subtask', segs)
            first.save('甲', 'fine_action', segs)
            first.flag('甲', 'subtask', 'Instruction mismatch')
            flora = root/'output/flora/episode_000002'
            flora.mkdir(parents=True)
            (flora/'caption.json').write_text('{}')
            self.assertEqual(storage.episode_statuses(root,[2,0],'subtask'), [
                {'episode_index':0,'human_count':2,'needs_review':True},
                {'episode_index':2,'human_count':0,'needs_review':False},
            ])
            self.assertEqual(storage.episode_statuses(root,[0],'fine_action')[0],
                {'episode_index':0,'human_count':1,'needs_review':True})
            # No cached zero after a different user submits.
            second = storage.AnnotationStore(root/'episode_000002',10)
            second.save('丙','subtask',segs)
            self.assertEqual(storage.episode_statuses(root,[2],'subtask')[0]['human_count'],1)

    def test_invalid_type_cannot_change_directory_scope(self):
        with self.assertRaises(ValueError):
            storage.episode_statuses(Path('/tmp'),[0],'../review_flags')
