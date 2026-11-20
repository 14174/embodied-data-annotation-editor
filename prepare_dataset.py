"""Create browser-compatible episode videos from native LeRobot v3 video indexes."""
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
import subprocess
import tempfile


def index_dataset(root):
    import pandas as pd
    root = Path(root).resolve()
    meta = json.loads((root / 'meta/info.json').read_text())
    files = sorted((root / 'meta/episodes').rglob('*.parquet'))
    if not files:
        raise ValueError('需要 LeRobot v3 episode 索引和独立视频；Parquet 内嵌图像须先导出视频')
    table = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
    if table.episode_index.duplicated().any():
        raise ValueError('Episode 编号重复')
    fps = float(meta['fps'])
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError('无效帧率')
    return meta, {int(row['episode_index']): row for row in table.to_dict('records')}


def camera_manifest(root, meta, row):
    root = Path(root).resolve()
    cameras = [k for k, v in meta.get('features', {}).items() if v.get('dtype') == 'video']
    roles = {'image': 'scene', 'left_wrist_image': 'left_wrist', 'right_wrist_image': 'right_wrist',
             'observation.images.scene': 'scene', 'observation.images.left_wrist': 'left_wrist',
             'observation.images.right_wrist': 'right_wrist',
             'scene': 'scene', 'left_wrist': 'left_wrist', 'right_wrist': 'right_wrist'}
    if 'viewer/cameras_json' in row:
        cameras = json.loads(row['viewer/cameras_json'])
    videos = {}
    for camera in cameras:
        if camera not in roles or roles[camera] in videos:
            raise ValueError(f'相机角色不明确：{camera}；请使用 --manifest 显式指定')
        prefix = f'videos/{camera}/'
        path = root / meta['video_path'].format(video_key=camera,
            chunk_index=int(row[prefix + 'chunk_index']), file_index=int(row[prefix + 'file_index']))
        if not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError(f'视频不存在或在数据集之外：{path}')
        start, end = float(row[prefix + 'from_timestamp']), float(row[prefix + 'to_timestamp'])
        if not all(math.isfinite(x) for x in (start, end)) or start < 0 or end <= start or abs((end-start)*float(meta['fps'])-int(row['length'])) > .01:
            raise ValueError(f'Episode 时间范围无效：{camera}')
        videos[roles[camera]] = dict(path=str(path), start_s=start, end_s=end)
    if set(videos) not in ({'scene'}, {'left_wrist', 'right_wrist'}, {'scene', 'left_wrist', 'right_wrist'}):
        raise ValueError('仅支持单场景、双腕或三视角视频')
    return videos


def prepare(source, destination, episodes=None):
    import pandas as pd
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError('播放副本目录必须独立于原始数据')
    meta, rows = index_dataset(source)
    selected = sorted(rows if episodes is None else set(episodes))
    if not selected or not set(selected) <= rows.keys():
        raise ValueError('所选 episode 不存在')
    identity = {'source': str(source), 'episode_indexes': selected, 'fps': float(meta['fps']), 'codec': 'h264', 'crf': 18}
    if destination.exists():
        marker = destination / 'preparation.json'
        if marker.is_file() and json.loads(marker.read_text()).get('identity') == identity:
            from v3_dataset import ReviewDataset
            reader = ReviewDataset(destination)
            if sorted(reader.rows) != selected:
                raise ValueError('已有播放副本的 episode 索引不完整')
            for index in selected:
                for camera in reader.info(index)['cameras']:
                    if not reader.video(index, camera).is_file():
                        raise ValueError('已有播放副本缺少视频')
            return destination
        raise FileExistsError(f'目标已存在，拒绝覆盖；已有部署可直接 infer/import：{destination}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.' + destination.name + '-', dir=destination.parent))
    try:
        jobs, updated_rows = [], []
        for index in selected:
            row = rows[index]
            camera_manifest(source, meta, row)
            cameras = [k for k, v in meta['features'].items() if v.get('dtype') == 'video']
            updated = {k: v for k, v in row.items() if not k.startswith('stats/')}
            updated['viewer/cameras_json'] = json.dumps(cameras)
            updated['viewer/signals_json'] = json.dumps({k:v for k,v in meta['features'].items() if k in ('state','observation.state')})
            for camera in cameras:
                prefix = f'videos/{camera}/'
                path = source / meta['video_path'].format(video_key=camera,
                    chunk_index=int(row[prefix+'chunk_index']), file_index=int(row[prefix+'file_index']))
                target = staging / 'videos' / camera / f'chunk-{index//1000:03d}' / f'file-{index:03d}.mp4'
                jobs.append((path, target, float(row[prefix+'from_timestamp']), int(row['length'])))
                updated.update({prefix+'chunk_index':index//1000, prefix+'file_index':index,
                    prefix+'from_timestamp':0., prefix+'to_timestamp':int(row['length'])/float(meta['fps'])})
            updated_rows.append(updated)
        def convert(job):
            path, target, start, count = job
            target.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(['ffmpeg','-nostdin','-v','error','-n','-threads','2','-ss',f'{start:.12f}',
                '-i',str(path),'-map','0:v:0','-an','-frames:v',str(count),'-c:v','libx264',
                '-threads','2','-preset','fast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(target)],check=True)
            probe = json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0',
                '-show_entries','stream=nb_frames,duration','-of','json',str(target)]))['streams'][0]
            if int(probe['nb_frames']) != count or abs(float(probe['duration'])-count/float(meta['fps'])) > 1/float(meta['fps']):
                raise ValueError(f'转换后帧数或时长不符：{target}')
            print(f'Prepared {target.relative_to(staging)}: {count} frames', flush=True)
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(convert, jobs))
        if (source/'data').is_dir():
            os.symlink(source/'data', staging/'data', target_is_directory=True)
        meta['total_episodes'], meta['total_frames'] = len(selected), sum(int(rows[i]['length']) for i in selected)
        meta.pop('splits', None)  # Selected episode IDs need not be contiguous.
        meta['video_path'] = 'videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4'
        for camera in cameras:
            meta['features'][camera].setdefault('info', {})['video.codec'] = 'h264'
        index = staging/'meta/episodes/chunk-000/file-000.parquet'
        index.parent.mkdir(parents=True)
        pd.DataFrame(updated_rows).to_parquet(index, index=False)
        (staging/'meta/info.json').write_text(json.dumps(meta, indent=2)+'\n')
        (staging/'preparation.json').write_text(json.dumps({'identity':identity, 'source':str(source),
            'note':'Separate H.264 episode copies (CRF 18); source files unchanged; state files linked.'}, indent=2)+'\n')
        staging.rename(destination)
    except BaseException:
        shutil.rmtree(staging)
        raise
    return destination
