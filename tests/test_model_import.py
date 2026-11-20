import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
from fastapi.testclient import TestClient
from annotation_workflow import import_result
from full_server import create_app


class ModelImportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.dataset = self.root/'sample'
        (self.dataset/'meta/episodes').mkdir(parents=True)
        (self.dataset/'meta/info.json').write_text(json.dumps({'fps':30}))
        pd.DataFrame([{'episode_index':0,'length':60,'viewer/cameras_json':'["scene"]'}]).to_parquet(self.dataset/'meta/episodes/index.parquet')
        self.record = dict(dataset_id='sample',episode_id='0',fps=30,frame_count=60,
            source_annotation='TempSeg-SFT-v2-epoch07',annotation_type='subtask',
            result={'segments':[{'start_frame':0,'end_frame':59,'caption':'','category':''}]})
        self.path = self.root/'raw.json'
    def write(self):
        self.path.write_text(json.dumps(self.record))
    def test_explicit_tail_repair_preserves_raw_result_and_is_idempotent(self):
        self.write(); before = self.path.read_bytes()
        with self.assertRaises(ValueError): import_result(self.dataset,self.path)
        report = import_result(self.dataset,self.path,repair_tail=True)
        import_result(self.dataset,self.path,repair_tail=True)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(Path(report['raw_result']).read_bytes(),before)
        bundle = json.loads((self.dataset/'model-preannotations.json').read_text())
        self.assertEqual(len(bundle['episodes']),1)
        record = bundle['episodes'][0]
        self.assertEqual(record['result']['segments'][-1]['end_frame'],60)
        self.assertTrue(record['warning'])
        self.assertEqual(record['import_adjustments'][0]['from'],59)
    def test_wrong_dataset_fps_count_and_internal_gaps_are_rejected(self):
        baseline = copy.deepcopy(self.record)
        for field,value in [('dataset_id','other'),('fps',26),('frame_count',59)]:
            self.record = copy.deepcopy(baseline);self.record[field]=value;self.write()
            with self.assertRaises(ValueError): import_result(self.dataset,self.path,repair_tail=True)
        self.record = copy.deepcopy(baseline)
        self.record['result']['segments']=[{'start_frame':0,'end_frame':20,'caption':''},{'start_frame':21,'end_frame':60,'caption':''}]
        self.write()
        with self.assertRaises(ValueError): import_result(self.dataset,self.path,repair_tail=True)
    def test_new_model_source_is_read_and_not_counted_as_human_submission(self):
        self.write();import_result(self.dataset,self.path,repair_tail=True)
        client = TestClient(create_app(self.dataset,self.root/'human'))
        self.assertEqual(client.get('/editor-api/model-preset').json()['source_annotation'],'TempSeg-SFT-v2-epoch07')
        self.assertEqual(client.get('/editor-api/annotations').json(),[])
        self.assertEqual(client.get('/editor-api/episode-status').json()['episodes'][0]['human_count'],0)
    def test_existing_different_result_requires_explicit_replace(self):
        self.write();import_result(self.dataset,self.path,repair_tail=True)
        self.record['result']['segments'][0]['caption']='New model text';self.write()
        with self.assertRaises(FileExistsError): import_result(self.dataset,self.path,repair_tail=True)
        import_result(self.dataset,self.path,repair_tail=True,replace=True)


if __name__ == '__main__': unittest.main()
