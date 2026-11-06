"""Read the indexed LeRobot v3 review dataset without rewriting source files."""
import json
from fractions import Fraction

import numpy as np
import pandas as pd


class ReviewDataset:
    def __init__(self, root):
        self.root = root
        self.meta = json.loads((root / 'meta/info.json').read_text())
        self.fps = float(self.meta['fps'])
        self.rows = {}
        for path in sorted((root / 'meta/episodes').rglob('*.parquet')):
            for row in pd.read_parquet(path).to_dict('records'):
                index = int(row['episode_index'])
                if index in self.rows:
                    raise ValueError(f'Duplicate episode {index}')
                self.rows[index] = row
        self.episodes = [
            {'episode_index': index, 'frame_count': int(row['length'])}
            for index, row in sorted(self.rows.items())
        ]

    def info(self, index):
        row = self.rows[index]
        tasks = row.get('tasks')
        return {
            'dataset_name': self.root.name,
            'episode_index': index,
            'frame_count': int(row['length']),
            'fps': self.fps,
            'cameras': json.loads(row['viewer/cameras_json']),
            'instruction': str(tasks[0]) if tasks is not None and len(tasks) else '',
            'episodes': self.episodes,
        }

    def video(self, index, camera):
        row = self.rows[index]
        if camera not in json.loads(row['viewer/cameras_json']):
            raise KeyError(camera)
        prefix = f'videos/{camera}/'
        duration = int(row['length']) / self.fps
        if abs(row[prefix + 'from_timestamp']) > 1e-6 or abs(row[prefix + 'to_timestamp'] - duration) > 1 / self.fps:
            raise ValueError('此视角的视频文件不是独立 episode，无法直接播放')
        return self.root / self.meta['video_path'].format(
            video_key=camera, chunk_index=int(row[prefix + 'chunk_index']),
            file_index=int(row[prefix + 'file_index']),
        )

    def source(self, index):
        path = self.root / 'output' / 'flora' / f'episode_{index:06d}' / 'caption.json'
        if not path.is_file():
            return {'result': {'segments': []}, 'source_annotation': None}
        original = json.loads(path.read_text())
        source_fps = Fraction(str(original['fps']))
        ratio = Fraction(str(self.fps)) / source_fps
        segments = [{
            'start_frame': round(s['start_frame'] * ratio),
            'end_frame': round(s['end_frame'] * ratio),
            'caption': s.get('caption', ''),
            'category': '',
        } for s in original['result']['segments']]
        return {
            'result': {'segments': segments}, 'annotation_type': 'subtask', 'source_annotation': 'FLORA',
            'source_fps': float(source_fps),
        }

    def signals(self, index):
        row = self.rows[index]
        fields = json.loads(row.get('viewer/signals_json') or '{}')
        fields = {name: spec for name, spec in fields.items() if name != 'action'}
        if not fields:
            return {'names': [], 'values': []}
        path = self.root / self.meta['data_path'].format(
            chunk_index=int(row['data/chunk_index']), file_index=int(row['data/file_index']),
        )
        table = pd.read_parquet(path, columns=['episode_index', 'frame_index', *fields])
        table = table.loc[table.episode_index == index].sort_values('frame_index')
        count = int(row['length'])
        if not np.array_equal(table.frame_index.to_numpy(), np.arange(count)):
            raise ValueError('状态帧索引与 episode 不一致')
        names, arrays = [], []
        for key, spec in fields.items():
            width = int(np.prod(spec['shape']))
            labels = spec.get('names') or []
            if len(labels) != width:
                labels = [f'dim_{i}_unverified' for i in range(width)]
            names.extend(f'{key}.{label}' for label in labels)
            column = [np.asarray(value, dtype=float).reshape(width) if value is not None
                      else np.full(width, np.nan) for value in table[key]]
            arrays.append(np.stack(column))
        values = np.concatenate(arrays, axis=1).astype(object)
        values[~np.isfinite(values.astype(float))] = None
        return {'names': names, 'values': values.tolist()}
