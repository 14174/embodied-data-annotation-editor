import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class IndexedFixture:
    def __init__(self, root):
        self.root = root
        data = json.loads((root/'meta/info.json').read_text())
        self.fps = data['fps']
        self.rows = {i:{'length':20} for i in data['indexes']}
        self.episodes = [{'episode_index':i,'frame_count':20} for i in self.rows]
    def info(self,index):
        return {'dataset_name':self.root.name,'episode_index':index,'fps':self.fps,
                'frame_count':20,'cameras':['scene'],'episodes':self.episodes}
    def source(self,index):return {'result':{'segments':[]},'source_annotation':None}
    def signals(self,index):return {'names':[],'values':[]}
    def video(self,index,camera):return self.root/f'{index}.mp4'


class DatasetCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name).resolve()
        self.legacy=self.make('legacy',[0,2])
        self.output=self.base/'human'
    def make(self,name,indexes):
        root=self.base/name;(root/'meta').mkdir(parents=True)
        (root/'meta/info.json').write_text(json.dumps({'fps':30,'indexes':indexes}))
        return root
    def catalog(self):
        from dataset_catalog import DatasetCatalog
        return DatasetCatalog(self.legacy,self.output,reader_factory=IndexedFixture)
    def test_catalog_exists(self):
        self.assertTrue(callable(self.catalog))
        self.assertTrue(self.catalog().default_id)
    def test_scan_nested_episode_layout_confirm_and_reload(self):
        self.make('laundry/2026-11-18/episode_000000',[0])
        self.make('laundry/2026-11-18/episode_000003',[0])
        self.make('laundry/2026-11-19',[0,1])
        (self.base/'laundry/notes').mkdir()
        catalog=self.catalog();rows=catalog.scan(str(self.base/'laundry'))
        self.assertEqual([(r['name'],r['available'],r['episode_count']) for r in rows],
                         [('2026-11-18',True,2),('2026-11-19',True,2),('notes',False,0)])
        collection=catalog.add('洗衣',str(self.base/'laundry'),['2026-11-18'])
        self.assertEqual(len(collection['datasets']),1)
        item=collection['datasets'][0]
        reader,output=catalog.open(item['id'])
        self.assertEqual(list(reader.rows),[0,3])
        self.assertEqual(reader.video(3,'scene'),self.base/'laundry/2026-11-18/episode_000003/0.mp4')
        self.assertNotEqual(output,self.output)
        reopened=self.catalog();self.assertEqual(reopened.open(item['id'])[1],output)
        self.assertEqual(reopened.default_id,catalog.default_id)
        self.assertEqual(catalog.open(catalog.default_id)[1],self.output)
        refreshed=catalog.refresh(collection['id'])
        self.assertEqual(len(refreshed['datasets']),2)
        self.assertEqual(refreshed['datasets'][0]['id'],item['id'])
    def test_same_date_in_two_collections_is_isolated_and_duplicates_rejected(self):
        for root in ['one','two']:self.make(f'{root}/2026-11-18',[0])
        catalog=self.catalog()
        first=catalog.add('一',str(self.base/'one'),['2026-11-18'])['datasets'][0]
        second=catalog.add('二',str(self.base/'two'),['2026-11-18'])['datasets'][0]
        self.assertNotEqual(first['id'],second['id'])
        self.assertNotEqual(catalog.open(first['id'])[1],catalog.open(second['id'])[1])
        with self.assertRaises(ValueError):catalog.add('重复',str(self.base/'one'),['2026-11-18'])
        with self.assertRaises(ValueError):catalog.add('穿越',str(self.base/'two'),['../legacy'])
    def test_missing_source_remains_registered_and_no_original_files_written(self):
        self.make('one/2026-11-18',[0]);catalog=self.catalog()
        collection=catalog.add('一',str(self.base/'one'),['2026-11-18'])
        before=sorted(str(p.relative_to(self.base/'one')) for p in (self.base/'one').rglob('*'))
        catalog.open(collection['datasets'][0]['id'])
        self.assertEqual(before,sorted(str(p.relative_to(self.base/'one')) for p in (self.base/'one').rglob('*')))
        (self.base/'one').rename(self.base/'offline')
        rows=catalog.refresh(collection['id'])['datasets']
        self.assertEqual(len(rows),1);self.assertFalse(rows[0]['available'])
        self.assertTrue(rows[0]['reason'])
    def test_output_must_be_outside_any_source_and_failed_add_does_not_persist(self):
        from dataset_catalog import DatasetCatalog
        with self.assertRaises(ValueError):DatasetCatalog(self.legacy,self.legacy/'labels',reader_factory=IndexedFixture)
        catalog=self.catalog()
        with self.assertRaises(ValueError):catalog.add('未知',str(self.base/'absent'),['2026-11-18'])
        with self.assertRaises(ValueError):catalog.open('unknown')
