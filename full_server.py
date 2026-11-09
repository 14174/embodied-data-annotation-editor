"""Serve the full v3 dataset with a separate writable annotation root."""
import argparse
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from storage import AnnotationConflict, AnnotationStore, next_episode
from v3_dataset import ReviewDataset


def create_app(root, output):
    dataset = ReviewDataset(root)
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
        return dataset.info(episode)

    @app.get('/editor-api/next-episode')
    def next_unannotated(response: Response, episode: int = 0, kind: str = 'subtask'):
        response.headers['Cache-Control'] = 'no-store'
        get_episode(episode)
        try:
            return next_episode(output, dataset.rows, episode, kind)
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

    @app.get('/editor-api/review-flags')
    def review_flags(response: Response, episode: int = 0):
        response.headers['Cache-Control'] = 'no-store'
        flags = store(episode).flags()
        return {'status': 'needs_review' if flags else 'unflagged', 'flags': flags}

    @app.post('/editor-api/review-flags')
    def flag_episode(payload: dict, episode: int = 0):
        destination = store(episode)
        if payload.get('episode_index') != episode:
            raise HTTPException(422, '异常备注的 episode 与当前页面不一致')
        try:
            return destination.flag(
                payload.get('annotator'), payload.get('annotation_type'), payload.get('note'),
                {'dataset_name': dataset.root.name, 'episode_index': episode, 'fps': dataset.fps,
                 'original_instruction': dataset.info(episode)['instruction']},
            )
        except (ValueError, TypeError) as error:
            raise HTTPException(422, str(error))

    @app.post('/editor-api/annotation')
    def submit(payload: dict, episode: int = 0):
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
                {'dataset_name': dataset.root.name, 'episode_index': episode, 'fps': dataset.fps, 'model': 'human'},
                protect_existing=True, expected_created_at=expected,
            )
        except AnnotationConflict as error:
            raise HTTPException(409, {'message': '该标注已存在', 'created_at': error.created_at})
        except (ValueError, TypeError) as error:
            raise HTTPException(422, str(error))

    app.mount('/editor-static', StaticFiles(directory=static), name='editor-static')
    return app


if __name__ == '__main__':
    import uvicorn
    parser = argparse.ArgumentParser(description='Run the robot video annotation editor.')
    parser.add_argument('dataset', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(create_app(args.dataset, args.output), host=args.host, port=args.port)
