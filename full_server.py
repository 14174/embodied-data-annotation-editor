"""Serve the full v3 dataset with a separate writable annotation root."""
import argparse
import json
import os
from threading import RLock
from urllib.parse import parse_qs, urlencode
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from storage import TYPES, AnnotationConflict, AnnotationStore, next_episode, episode_statuses
from v3_dataset import ReviewDataset
from caption_assist import simplify, AssistUnavailable
from dataset_catalog import DatasetCatalog


def create_dataset_app(root, output, dataset=None, dataset_id="default"):
    dataset = dataset or ReviewDataset(root)
    output = output.resolve()
    if output == root.resolve() or root.resolve() in output.parents:
        raise ValueError('标注输出目录必须独立于原始数据')
    app = FastAPI(title='Robot annotation editor')
    static = Path(__file__).parent / 'static'

    def get_episode(index):
        if index not in dataset.rows:
            raise HTTPException(404, 'episode 不存在')
        return dataset.rows[index]

    def store(index):
        return AnnotationStore(output / f'episode_{index:06d}', int(get_episode(index)['length']))

    @app.get('/')
    def home():
        return RedirectResponse('/editor')

    @app.get('/editor')
    def editor():
        return FileResponse(static / 'index.html', headers={'Cache-Control': 'no-store'})

    @app.get('/api/health')
    def health():
        return {'ok': True, 'episodes': len(dataset.episodes)}

    @app.get('/editor-api/info')
    def info(episode: int = 0):
        get_episode(episode)
        data = dataset.info(episode)
        data.update(dataset_id=dataset_id, legacy_dataset_name=root.name if dataset_id == 'default' else None)
        return data

    @app.post('/editor-api/caption-assist')
    def caption_assist(payload: dict, response: Response, episode: int = 0):
        response.headers['Cache-Control'] = 'no-store'
        get_episode(episode)
        if payload.get('annotation_type') != 'subtask':
            raise HTTPException(422, '当前文字辅助仅用于 Subtask 标注。')
        try:
            return simplify(payload.get('caption'), mode=payload.get('mode', 'simplify'))
        except ValueError as error:
            raise HTTPException(422, str(error))
        except AssistUnavailable as error:
            raise HTTPException(503, str(error))

    @app.get('/editor-api/next-episode')
    def next_unannotated(response: Response, episode: int = 0, kind: str = 'subtask', direction: int = 1):
        response.headers['Cache-Control'] = 'no-store'
        get_episode(episode)
        try:
            return next_episode(output, dataset.rows, episode, kind, direction)
        except ValueError as error:
            raise HTTPException(422, str(error))

    @app.get('/editor-api/episode-status')
    def episode_status(response: Response, kind: str = 'subtask'):
        response.headers['Cache-Control'] = 'no-store'
        try:
            return {'annotation_type': kind, 'episodes': episode_statuses(output, dataset.rows, kind)}
        except ValueError as error:
            raise HTTPException(422, str(error))

    @app.get('/editor-api/video')
    def video(camera: str, episode: int = 0):
        get_episode(episode)
        try:
            path = dataset.video(episode, camera)
        except KeyError:
            raise HTTPException(404, '相机不存在')
        except ValueError as error:
            raise HTTPException(422, str(error))
        if not path.is_file():
            raise HTTPException(404, '视频文件不存在')
        return FileResponse(path, media_type='video/mp4')

    @app.get('/editor-api/signals')
    def signals(episode: int = 0):
        get_episode(episode)
        try:
            return dataset.signals(episode)
        except ValueError as error:
            raise HTTPException(422, str(error))

    @app.get('/editor-api/source')
    def source(episode: int = 0):
        get_episode(episode)
        data = dataset.source(episode)
        if data['result']['segments']:
            try:
                store(episode).validate(data['result']['segments'])
            except ValueError as error:
                return {'result': {'segments': []}, 'source_annotation': None, 'warning': str(error)}
        return data

    @app.get('/editor-api/annotations')
    def annotations(response: Response, episode: int = 0):
        response.headers['Cache-Control'] = 'no-store'
        return [
            {'annotator': record['annotator'], 'annotation_type': record['annotation_type'],
             'created_at': record['created_at'], 'segments': len(record['result']['segments'])}
            for record in store(episode).list()
        ]

    @app.get('/editor-api/annotation')
    def annotation(author: str, kind: str, episode: int = 0):
        try:
            return store(episode).get(author, kind)
        except ValueError as error:
            raise HTTPException(422, str(error))

    @app.get('/editor-api/last-submission')
    def last_submission(author: str, response: Response):
        response.headers['Cache-Control'] = 'no-store'
        latest = None
        try:
            for index in dataset.rows:
                episode_store = store(index)
                for kind in sorted(TYPES):
                    record = episode_store.get(author, kind)
                    if record and (latest is None or record['created_at'] > latest['created_at']):
                        latest = {'episode_index': index, 'annotation_type': kind,
                                  'created_at': record['created_at']}
        except ValueError as error:
            raise HTTPException(422, str(error))
        return latest

    @app.get('/editor-api/review-flags')
    def review_flags(response: Response, episode: int = 0):
        response.headers['Cache-Control'] = 'no-store'
        flags = store(episode).flags()
        return {'status': 'needs_review' if flags else 'unflagged', 'flags': flags}

    @app.post('/editor-api/review-flags')
    def flag_episode(payload: dict, episode: int = 0):
        if payload.get('dataset_id', dataset_id) != dataset_id:
            raise HTTPException(422, '提交的数据集与当前页面不一致')
        destination = store(episode)
        if payload.get('episode_index') != episode:
            raise HTTPException(422, '异常备注的 episode 与当前页面不一致')
        try:
            return destination.flag(
                payload.get('annotator'), payload.get('annotation_type'), payload.get('note'),
                {'dataset_name': dataset.root.name, 'dataset_id': dataset_id, 'episode_index': episode, 'fps': dataset.fps,
                 'original_instruction': dataset.info(episode)['instruction']},
            )
        except (ValueError, TypeError) as error:
            raise HTTPException(422, str(error))

    @app.post('/editor-api/annotation')
    def submit(payload: dict, episode: int = 0):
        if payload.get('dataset_id', dataset_id) != dataset_id:
            raise HTTPException(422, '提交的数据集与当前页面不一致')
        destination = store(episode)
        result = payload.get('result')
        if payload.get('episode_index') != episode or not isinstance(result, dict):
            raise HTTPException(422, '提交的 episode 与当前页面不一致，或缺少分段数据')
        try:
            expected = payload.get('expected_created_at')
            if expected is not None and type(expected) not in (int, float):
                raise ValueError('覆盖确认信息无效')
            return destination.save(
                payload.get('annotator'), payload.get('annotation_type'), result.get('segments'),
                payload.get('source_annotation'),
                {'dataset_name': dataset.root.name, 'dataset_id': dataset_id, 'episode_index': episode, 'fps': dataset.fps, 'model': 'human'},
                protect_existing=True, expected_created_at=expected,
            )
        except AnnotationConflict as error:
            raise HTTPException(409, {'message': '该标注已存在', 'created_at': error.created_at})
        except (ValueError, TypeError) as error:
            raise HTTPException(422, str(error))

    app.mount('/editor-static', StaticFiles(directory=static), name='editor-static')
    return app


def create_app(root, output, *, collection_root=None, review_root=None):
    """Resolve each request against its dataset; never switch shared global state."""
    collection_root = collection_root or os.environ.get('ANNOTATION_COLLECTION_ROOT')
    review_root = review_root or os.environ.get('ANNOTATION_REVIEW_ROOT')
    if collection_root:
        from fixed_collection import FixedDatasetCatalog
        catalog = FixedDatasetCatalog(root,output,collection_root,review_root)
    else:
        catalog = DatasetCatalog(root, output)
    app = FastAPI(title='Robot annotation editor')
    app.state.catalog = catalog
    applications, app_lock = {}, RLock()
    static = Path(__file__).parent/'static'

    def describe(data, kind='subtask'):
        if kind not in TYPES:
            raise ValueError('标注类型无效')
        for collection in data['collections']:
            for item in collection['datasets']:
                item['archived'] = item['id'] in catalog.archived
                if item['available']:
                    reader, labels = catalog.open(item['id'])
                    statuses = episode_statuses(labels,reader.rows,kind)
                    item['annotated_count'] = sum(row['human_count'] > 0 for row in statuses)
                    item['flagged_count'] = sum(row['needs_review'] for row in statuses)
        return data

    @app.get('/editor-api/collections')
    def collections(response: Response, kind: str='subtask'):
        response.headers['Cache-Control']='no-store'
        try: return describe(catalog.view(),kind)
        except ValueError as error: raise HTTPException(422,str(error))

    @app.post('/editor-api/collections/scan')
    def scan(payload: dict):
        try: return {'datasets':catalog.scan(payload.get('path',''))}
        except (ValueError,OSError,TypeError) as error: raise HTTPException(422,str(error))

    @app.post('/editor-api/collections')
    def add_collection(payload: dict):
        try: return catalog.add(payload.get('name'),payload.get('path'),payload.get('dates'))
        except (ValueError,OSError,TypeError) as error: raise HTTPException(422,str(error))

    @app.post('/editor-api/collections/refresh')
    def refresh(payload: dict):
        try:
            data=catalog.refresh(payload.get('collection_id'))
            with app_lock:
                for item in data['datasets']: applications.pop(item['id'],None)
            return data
        except (ValueError,OSError,TypeError) as error: raise HTTPException(422,str(error))

    @app.post('/editor-api/datasets/archive')
    def archive(payload: dict):
        try:
            catalog.archive(payload.get('dataset_id'),payload.get('archived'))
            return {'ok':True}
        except (ValueError,OSError,TypeError) as error: raise HTTPException(422,str(error))

    class Dispatch:
        def __init__(self, app): self.router=app
        async def __call__(self, scope, receive, send):
            from starlette.responses import JSONResponse
            path=scope.get('path','')
            management=path.startswith('/editor-api/collections') or path=='/editor-api/datasets/archive'
            if scope['type'] != 'http' or not path.startswith('/editor-api/') or management:
                return await self.router(scope,receive,send)
            params=parse_qs(scope.get('query_string',b'').decode())
            key=params.get('dataset',[catalog.default_id])[0]
            try:
                reader,labels=catalog.open(key)
                if 'episode' not in params:
                    scope=dict(scope,query_string=scope.get('query_string',b'')+b'&'+urlencode({'episode':min(reader.rows)}).encode())
                if scope['method'] not in ('GET','HEAD') and key in catalog.archived:
                    return await JSONResponse({'detail':'该数据集已归档，只能查看和导出'},status_code=403)(scope,receive,send)
                if path in ('/editor-api/vocabulary','/editor-api/model-preset'):
                    name='caption-vocabulary.json' if path.endswith('vocabulary') else 'flora-sft-v1.json'
                    file=reader.root/name
                    if path.endswith('model-preset') and (reader.root/'model-preannotations.json').is_file():
                        file=reader.root/'model-preannotations.json'
                    if not file.is_file() and key==catalog.default_id: file=static/name
                    data=json.loads(file.read_text()) if file.is_file() else None
                    return await JSONResponse(data,headers={'Cache-Control':'no-store'})(scope,receive,send)
                with app_lock:
                    if key not in applications or applications[key].state.dataset_reader is not reader:
                        applications[key]=create_dataset_app(reader.root,labels,reader,key)
                        applications[key].state.dataset_reader=reader
                    target=applications[key]
            except (ValueError,OSError,KeyError,TypeError) as error:
                return await JSONResponse({'detail':str(error)},status_code=404)(scope,receive,send)
            return await target(scope,receive,send)

    # A middleware preserves FastAPI's test/lifespan interfaces and routes normal
    # requests to isolated single-dataset apps without mutating a global reader.
    app.add_middleware(Dispatch)
    @app.get('/')
    def home(): return RedirectResponse('/editor')
    @app.get('/editor')
    def editor(): return FileResponse(static/'index.html',headers={'Cache-Control':'no-store'})
    @app.get('/api/health')
    def health():
        reader,_=catalog.open(catalog.default_id)
        return {'ok':True,'episodes':len(reader.rows),'multi_dataset':True}
    app.mount('/editor-static',StaticFiles(directory=static),name='editor-static')
    return app


if __name__ == '__main__':
    import uvicorn
    parser = argparse.ArgumentParser(description='Run the robot video annotation editor.')
    parser.add_argument('dataset', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('legacy_port', nargs='?', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(create_app(args.dataset, args.output), host='0.0.0.0' if args.legacy_port is not None else args.host, port=args.legacy_port or args.port)
