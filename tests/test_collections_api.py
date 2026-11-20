"""Integration tests require the server's existing FastAPI/Parquet environment."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
DEPENDENCIES=all(importlib.util.find_spec(name) for name in ['fastapi','pandas','pyarrow','httpx'])


@unittest.skipUnless(DEPENDENCIES,'requires server FastAPI, pandas, pyarrow and httpx')
class CollectionApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        import pandas as pd
        from full_server import create_app
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name).resolve()
        self.pd=pd
        self.make(self.base/'legacy')
        self.make(self.base/'laundry/2026-11-18/episode_000000')
        self.make(self.base/'laundry/2026-11-18/episode_000003')
        self.make(self.base/'laundry/2026-11-19')
        self.app=create_app(self.base/'legacy',self.base/'human')
        self.client=TestClient(self.app)
    def make(self,root):
        (root/'meta/episodes').mkdir(parents=True)
        (root/'meta/info.json').write_text(json.dumps({'fps':30,'video_path':'videos/{video_key}/file-{file_index:03d}.mp4'}))
        row={'episode_index':0,'length':20,'tasks':['Wash clothes'],'viewer/cameras_json':json.dumps(['scene']),
             'videos/scene/chunk_index':0,'videos/scene/file_index':0,
             'videos/scene/from_timestamp':0.,'videos/scene/to_timestamp':20/30}
        self.pd.DataFrame([row]).to_parquet(root/'meta/episodes/index.parquet')
        (root/'videos/scene').mkdir(parents=True);(root/'videos/scene/file-000.mp4').write_bytes(b'fixture-video')
    def register(self):
        response=self.client.post('/editor-api/collections',json={'name':'洗衣','path':str(self.base/'laundry'),'dates':['2026-11-18','2026-11-19']})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()
    def test_collection_routes_are_available(self):
        response=self.client.get('/editor-api/collections')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['default_dataset_id'],'default')
    def test_fixed_collection_detects_uploads_and_reloads_changed_episode_readers(self):
        from full_server import create_app
        from fastapi.testclient import TestClient
        fixed=self.base/'uploads';fixed.mkdir()
        app=create_app(self.base/'legacy',self.base/'fixed-human',collection_root=fixed)
        app.state.catalog.scan_interval=0
        client=TestClient(app)
        self.assertEqual(client.get('/editor-api/collections').json()['collections'][0]['datasets'],[])
        source=fixed/'20261120_120000';self.make(source)
        catalog=client.get('/editor-api/collections').json()
        item=catalog['collections'][0]['datasets'][0]
        self.assertTrue(item['available'])
        self.assertEqual(client.get('/editor-api/info',params={'dataset':item['id']}).status_code,200)
        path=source/'meta/episodes/index.parquet'
        table=self.pd.read_parquet(path)
        extra=table.iloc[0].to_dict();extra['episode_index']=3
        self.pd.concat([table,self.pd.DataFrame([extra])],ignore_index=True).to_parquet(path)
        updated=client.get('/editor-api/collections').json()['collections'][0]['datasets'][0]
        self.assertEqual(updated['episode_count'],2)
        response=client.get('/editor-api/info',params={'dataset':item['id'],'episode':3})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['episode_index'],3)
        response=client.post('/editor-api/collections/scan',json={'path':str(self.base/'laundry')})
        self.assertEqual(response.status_code,422)
        pending=fixed/'20261120_130000';(pending/'meta').mkdir(parents=True)
        (pending/'meta/info.json').write_text(json.dumps({'fps':30,'total_episodes':100,'features':{'image':{'dtype':'image'}}}))
        items=client.get('/editor-api/collections').json()['collections'][0]['datasets']
        row=next(r for r in items if r['name']==pending.name)
        self.assertFalse(row['available']);self.assertEqual(row['episode_count'],100)
        self.assertIn('Parquet',row['reason'])
    def test_request_context_and_submissions_are_isolated(self):
        collection=self.register();ids=[row['id'] for row in collection['datasets']]
        payload={'dataset_id':ids[0],'episode_index':0,'annotation_type':'subtask','annotator':'tester',
                 'result':{'segments':[{'start_frame':0,'end_frame':20,'caption':'Open washer'}]}}
        self.assertEqual(self.client.post('/editor-api/annotation',params={'dataset':ids[0]},json=payload).status_code,200)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda key:self.client.get('/editor-api/info',params={'dataset':key}).json(),ids*5))
        self.assertEqual([r['dataset_id'] for r in results],ids*5)
        self.assertEqual(len(self.client.get('/editor-api/annotations',params={'dataset':ids[0]}).json()),1)
        self.assertEqual(self.client.get('/editor-api/annotations',params={'dataset':ids[1]}).json(),[])
        self.assertEqual(self.client.get('/editor-api/annotations').json(),[])
        mismatch=self.client.post('/editor-api/annotation',params={'dataset':ids[1]},json=payload)
        self.assertEqual(mismatch.status_code,422)
        info=self.client.get('/editor-api/info',params={'dataset':ids[0],'episode':3}).json()
        self.assertEqual(info['episode_index'],3)
        self.assertEqual(self.client.get('/editor-api/video',params={'dataset':ids[0],'episode':3,'camera':'scene'}).content,b'fixture-video')
        self.assertEqual(self.client.get('/editor-api/info',params={'dataset':'unknown'}).status_code,404)
        self.assertEqual(self.client.get('/editor-api/info',params={'dataset':ids[1],'episode':3}).status_code,404)
    def test_legacy_output_and_preset_are_preserved_and_default_vocab_is_global(self):
        collection=self.register();first,second=[row['id'] for row in collection['datasets']]
        legacy=self.client.get('/editor-api/info').json()
        self.assertEqual(legacy['dataset_id'],'default');self.assertEqual(legacy['legacy_dataset_name'],'legacy')
        payload={'episode_index':0,'annotation_type':'subtask','annotator':'old-user',
                 'result':{'segments':[{'start_frame':0,'end_frame':20,'caption':'Legacy'}]}}
        self.assertEqual(self.client.post('/editor-api/annotation',json=payload).status_code,200)
        self.assertEqual(len(list((self.base/'human/episode_000000/subtask').glob('*.json'))),1)
        vocab={'id':'date-vocab','name':'专用','version':'1','items':[{'id':'open','caption':'Open washer'}]}
        (self.base/'laundry/2026-11-18/caption-vocabulary.json').write_text(json.dumps(vocab))
        default=self.client.get('/editor-api/vocabulary').json()
        self.assertTrue(default['items'])
        self.assertEqual(self.client.get('/editor-api/vocabulary',params={'dataset':first}).json(),default)
        self.assertEqual(self.client.get('/editor-api/vocabulary',params={'dataset':second}).json(),default)
        self.assertIsNone(self.client.get('/editor-api/model-preset',params={'dataset':first}).json())
        rows=self.client.get('/editor-api/collections',params={'kind':'subtask'}).json()['collections']
        self.assertEqual(rows[0]['datasets'][0]['annotated_count'],1)
    def test_offline_collection_refresh_preserves_entries_and_archived_is_readonly(self):
        collection=self.register();first=collection['datasets'][0]['id']
        response=self.client.post('/editor-api/datasets/archive',json={'dataset_id':first,'archived':True})
        self.assertEqual(response.status_code,200,response.text)
        response=self.client.post('/editor-api/annotation',params={'dataset':first},json={})
        self.assertEqual(response.status_code,403)
        self.assertEqual(self.client.get('/editor-api/info',params={'dataset':first}).status_code,200)
        (self.base/'laundry').rename(self.base/'offline')
        response=self.client.post('/editor-api/collections/refresh',json={'collection_id':collection['id']})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(len(response.json()['datasets']),2)
        self.assertTrue(all(not row['available'] for row in response.json()['datasets']))
