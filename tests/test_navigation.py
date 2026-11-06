import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import storage


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def submit(self, index, kind='subtask'):
        storage.AnnotationStore(self.root / f'episode_{index:06d}', 100).save(
            '甲', kind, [{'start_frame': 0, 'end_frame': 100, 'caption': '动作'}])

    def next(self, current, kind='subtask', indexes=(0, 2, 5, 9)):
        return storage.next_episode(self.root, indexes, current, kind)

    def test_skips_submitted_episodes_and_counts_any_annotator(self):
        self.submit(2)
        self.assertEqual(self.next(0), {'episode_index': 5, 'unannotated': True})

    def test_search_wraps_and_never_selects_current_episode(self):
        self.submit(9)
        self.assertEqual(self.next(5), {'episode_index': 0, 'unannotated': True})

    def test_types_are_independent_and_flora_is_not_a_human_submission(self):
        self.submit(2, 'fine_action')
        flora = self.root / 'output/flora/episode_000002'
        flora.mkdir(parents=True)
        (flora / 'caption.json').write_text('{}')
        self.assertEqual(self.next(0), {'episode_index': 2, 'unannotated': True})
        self.assertEqual(self.next(0, 'fine_action'), {'episode_index': 5, 'unannotated': True})

    def test_each_click_reads_new_submissions(self):
        self.assertEqual(self.next(0)['episode_index'], 2)
        self.submit(2)
        self.assertEqual(self.next(0)['episode_index'], 5)

    def test_all_submitted_falls_back_to_next_in_order(self):
        for index in (0, 2, 5, 9):
            self.submit(index)
        self.assertEqual(self.next(5), {'episode_index': 9, 'unannotated': False})
        self.assertEqual(self.next(9), {'episode_index': 0, 'unannotated': False})

    def test_single_episode_has_no_destination_and_invalid_type_is_rejected(self):
        self.assertEqual(self.next(0, indexes=(0,)), {'episode_index': None, 'unannotated': False})
        with self.assertRaises(ValueError):
            self.next(0, '../subtask')
