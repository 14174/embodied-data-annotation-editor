"""Discover a configured source collection while retaining existing annotation IDs."""
import copy
import hashlib
import json
from pathlib import Path
import re
import time

from dataset_catalog import DatasetCatalog, outside


class FixedDatasetCatalog(DatasetCatalog):
    def __init__(self, root, output, fixed_root, review_root=None, reader_factory=None, scan_interval=30):
        super().__init__(root, output, reader_factory)
        self.fixed_root = Path(fixed_root).expanduser().resolve()
        self.review_root = Path(review_root).expanduser().resolve() if review_root else None
        outside(self.default_output, self.fixed_root)
        if self.review_root:
            outside(self.default_output, self.review_root)
        self.fixed_id = hashlib.sha256(str(self.fixed_root).encode()).hexdigest()[:16]
        self.native_reader = reader_factory is None
        self.scan_interval = scan_interval
        self.last_scan = None
        self.scan_error = ''
        self.fingerprints = {}
        self.synchronize(force=True)

    def source(self, date):
        path = self.fixed_root/date
        if path.resolve().parent != self.fixed_root:
            raise ValueError('数据集目录必须位于固定合集内')
        return path

    def prepared(self, date):
        source = self.source(date)
        candidates = [self.default_root]
        if self.review_root:
            candidates.append(self.review_root/date)
        for path in candidates:
            if path == source:
                return path
            marker = path/'preparation.json'
            try:
                if path.name == date and Path(json.loads(marker.read_text())['source']).resolve() == source:
                    return path
            except (OSError, ValueError, KeyError, TypeError):
                pass
        return source

    def preferred_id(self, date):
        playback = self.prepared(date)
        if playback == self.default_root:
            return self.default_id
        for collection in self.collections:
            if collection['id'] != self.fixed_id and (Path(collection['root'])/date).resolve() == playback:
                if date in collection['dates']:
                    return collection['id']+':'+date
        return self.fixed_id+':'+date

    def fingerprint(self, date):
        signatures = []
        for root in {self.source(date), self.prepared(date)}:
            paths = [root/'meta/info.json', root/'preparation.json']
            paths.extend(sorted((root/'meta/episodes').rglob('*.parquet')))
            for path in paths:
                try:
                    stat = path.stat()
                    signatures.append((str(path),stat.st_mtime_ns,stat.st_size))
                except OSError:
                    signatures.append((str(path),None,None))
        return sorted(signatures)

    def synchronize(self, force=False):
        with self.lock:
            if not force and self.last_scan is not None and time.monotonic()-self.last_scan < self.scan_interval:
                return
            current = next((c for c in self.collections if c['id'] == self.fixed_id), None)
            updated = copy.deepcopy(current) if current else {
                'id':self.fixed_id,'name':'服务器采集数据','root':str(self.fixed_root),'dates':[]}
            dates = set(updated['dates'])
            self.scan_error = ''
            try:
                # Include indexed datasets and unfinished date folders, but not vis/cache containers.
                for folder in self.fixed_root.iterdir():
                    if folder.name.startswith('.') or not folder.is_dir():
                        continue
                    if (folder/'meta/info.json').is_file() or re.match(r'^\d{4}-?\d{2}-?\d{2}(?:[_-]|$)',folder.name):
                        dates.add(folder.name)
            except OSError as error:
                self.scan_error = f'数据目录暂不可用：{error}'
            updated['dates'] = sorted(dates, reverse=True)
            if updated != current:
                self.persist([c for c in self.collections if c['id'] != self.fixed_id]+[updated])
            signatures = {}
            for date in updated['dates']:
                try:
                    signatures[date] = self.fingerprint(date)
                except (OSError, ValueError):
                    signatures[date] = None
            if signatures != self.fingerprints:
                self.cache.clear()
                self.fingerprints = signatures
            self.last_scan = time.monotonic()

    def entry(self, dataset_id):
        if isinstance(dataset_id,str) and dataset_id.startswith(self.fixed_id+':'):
            date = dataset_id[len(self.fixed_id)+1:]
            collection = next(c for c in self.collections if c['id'] == self.fixed_id)
            if date not in collection['dates']:
                raise ValueError('数据集未登记')
            return self.prepared(date), self.default_output/'collections'/self.fixed_id/date, collection
        return super().entry(dataset_id)

    def open(self, dataset_id):
        root, _, _ = self.entry(dataset_id)
        if self.native_reader:
            try:
                meta = json.loads((root/'meta/info.json').read_text())
                features = meta.get('features',{})
                if features and not any(v.get('dtype') == 'video' for v in features.values()):
                    raise ValueError('Parquet 图像需先导出同步视频')
                if not any((root/'meta/episodes').rglob('*.parquet')):
                    raise ValueError('缺少完整的 episode 索引')
            except (OSError, ValueError) as error:
                raise ValueError(str(error)) from error
        reader, output = super().open(dataset_id)
        if self.native_reader:
            try:
                cameras = reader.info(min(reader.rows))['cameras']
                if not cameras:
                    raise ValueError('缺少相机视角')
                for index in reader.rows:
                    for camera in cameras:
                        if not reader.video(index,camera).is_file():
                            raise ValueError('视频尚未准备完成')
            except (OSError, ValueError, KeyError) as error:
                self.cache.pop(dataset_id,None)
                raise ValueError('需要完整的独立 episode 视频和相机索引') from error
        return reader, output

    def fixed_view(self):
        collection = next(c for c in self.collections if c['id'] == self.fixed_id)
        datasets = []
        for date in collection['dates']:
            try:
                source = self.source(date)
                row = self.dataset_view(self.preferred_id(date),date)
                if not row['available']:
                    try:
                        meta = json.loads((source/'meta/info.json').read_text())
                        row['episode_count'] = int(meta.get('total_episodes',0))
                    except (OSError, ValueError, TypeError):
                        pass
                row.update(status='ready' if row['available'] else 'needs_preparation',source_root=str(source))
            except (OSError, ValueError) as error:
                row = {'id':self.fixed_id+':'+date,'name':date,'available':False,
                       'episode_count':0,'status':'unavailable','reason':str(error)}
            datasets.append(row)
        return {'id':self.fixed_id,'name':collection['name'],'root':str(self.fixed_root),
                'fixed':True,'scan_error':self.scan_error,'datasets':datasets}

    def view(self):
        self.synchronize()
        with self.lock:
            return {'default_dataset_id':self.default_id,'fixed_root':str(self.fixed_root),
                    'review_root':str(self.review_root) if self.review_root else None,
                    'scan_interval_seconds':self.scan_interval,'collections':[self.fixed_view()]}

    def scan(self, path):
        if Path(path).expanduser().resolve() != self.fixed_root:
            raise ValueError(f'数据合集已固定为 {self.fixed_root}')
        self.synchronize(force=True)
        return self.fixed_view()['datasets']

    def add(self, name, path, dates):
        if Path(path).expanduser().resolve() != self.fixed_root:
            raise ValueError(f'数据合集已固定为 {self.fixed_root}')
        return self.refresh(self.fixed_id)

    def refresh(self, collection_id):
        if collection_id != self.fixed_id:
            raise ValueError('请刷新固定的数据合集')
        self.synchronize(force=True)
        return self.fixed_view()
