import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dataset_catalog import DatasetCatalog
from fixed_collection import FixedDatasetCatalog
from test_dataset_catalog import IndexedFixture


class FixedCollectionTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.base=Path(temporary.name)
        self.raw=self.base/'raw';self.raw.mkdir()
        self.review=self.base/'review';self.review.mkdir()
        self.output=self.base/'human'
        self.source=self.make(self.raw/'20261118_144854',[0,5])
        self.legacy=self.make(self.review/self.source.name,[0,5])
        (self.legacy/'preparation.json').write_text(json.dumps({'source':str(self.source)}))
    def make(self,root,indexes):
        (root/'meta').mkdir(parents=True,exist_ok=True)
        (root/'meta/info.json').write_text(json.dumps({'fps':30,'indexes':indexes}))
        return root
    def catalog(self):
        return FixedDatasetCatalog(self.legacy,self.output,self.raw,self.review,
                                   reader_factory=IndexedFixture,scan_interval=0)
    def test_fixed_root_discovers_new_dates_without_registration_and_preserves_default_id(self):
        catalog=self.catalog()
        initial=catalog.view()
        self.assertEqual(initial['fixed_root'],str(self.raw))
        self.assertEqual(len(initial['collections']),2)
        fixed=next(c for c in initial['collections'] if c.get('fixed'))
        self.assertEqual(fixed['datasets'][0]['id'],'default')
        self.make(self.raw/'20261120_120000',[0,2])
        rows=next(c for c in catalog.view()['collections'] if c.get('fixed'))['datasets']
        self.assertEqual(len(rows),2)
        self.assertTrue(rows[0]['available'])
        self.assertEqual(catalog.open('default')[1],self.output)
    def test_existing_prepared_dataset_id_output_and_offline_entries_are_preserved(self):
        date='20261119_172411'
        source=self.make(self.raw/date,[0])
        prepared=self.make(self.review/date,[0])
        (prepared/'preparation.json').write_text(json.dumps({'source':str(source)}))
        old=DatasetCatalog(self.legacy,self.output,reader_factory=IndexedFixture)
        collection=old.add('Old',str(self.review),[date])
        old_id=collection['datasets'][0]['id'];old_output=old.open(old_id)[1]
        catalog=self.catalog()
        view=catalog.view()
        row=next(r for r in view['collections'][0]['datasets'] if r['name']==date)
        self.assertEqual(row['id'],old_id)
        self.assertEqual(catalog.open(old_id)[1],old_output)
        previous=next(c for c in view['collections'] if c['id']==collection['id'])
        self.assertEqual(previous['root'],str(self.review.resolve()))
        self.assertEqual(previous['datasets'][0]['id'],old_id)
        self.make(self.review/'20261120_120000',[0,3])
        refreshed=catalog.refresh(collection['id'])
        self.assertEqual(refreshed['id'],collection['id'])
        self.assertIn('20261120_120000',[row['name'] for row in refreshed['datasets']])
        self.raw.rename(self.base/'offline')
        view=catalog.view()
        self.assertEqual(len(view['collections'][0]['datasets']),2)
        self.assertTrue(view['collections'][0]['scan_error'])
    def test_partial_upload_becomes_available_and_changed_metadata_invalidates_cache(self):
        date='20261120_123000'
        (self.raw/date).mkdir()
        catalog=self.catalog()
        row=next(r for r in catalog.view()['collections'][0]['datasets'] if r['name']==date)
        self.assertFalse(row['available'])
        self.make(self.raw/date,[0])
        row=next(r for r in catalog.view()['collections'][0]['datasets'] if r['name']==date)
        self.assertTrue(row['available'])
        first=catalog.open(row['id'])[0]
        self.make(self.raw/date,[0,3])
        row=next(r for r in catalog.view()['collections'][0]['datasets'] if r['name']==date)
        self.assertEqual(row['episode_count'],2)
        self.assertIsNot(catalog.open(row['id'])[0],first)
    def test_other_roots_and_escaping_symlinks_cannot_be_registered(self):
        catalog=self.catalog()
        with self.assertRaises(ValueError):catalog.add('Other',str(self.review),['20261118_144854'])
        (self.raw/'20261121_120000').symlink_to(self.legacy,target_is_directory=True)
        row=next(r for r in catalog.view()['collections'][0]['datasets'] if r['name']=='20261121_120000')
        self.assertFalse(row['available'])


if __name__=='__main__':unittest.main()
