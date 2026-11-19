"""Persistent collection registration; source data is always read-only."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
from threading import RLock
import tempfile


def outside(output, source):
    if output == source or source in output.parents or output in source.parents:
        raise ValueError('标注与配置目录必须独立于原始数据目录')


class EpisodeDirectoryDataset:
    """Adapt a date containing independently indexed, single-episode folders."""
    def __init__(self, root, factory):
        self.root, self.rows, self.readers = root, {}, {}
        for folder in sorted(root.iterdir()):
            if not folder.is_dir() or folder.name.startswith('.'):
                continue
            match = re.fullmatch(r'(?:episode[_-]?)?(\d+)', folder.name)
            if not match or not (folder/'meta/info.json').is_file():
                raise ValueError('日期下每个 episode 目录需有数字编号与 meta/info.json')
            if not folder.resolve().is_relative_to(root.resolve()):
                raise ValueError('episode 目录不能指向日期目录之外')
            reader = factory(folder)
            if len(reader.rows) != 1:
                raise ValueError('独立 episode 子目录须恰好包含一条轨迹')
            index, inner = int(match[1]), next(iter(reader.rows))
            if index in self.rows:
                raise ValueError('episode 目录编号重复')
            if self.rows and reader.fps != self.fps:
                raise ValueError('同一日期下 episode 帧率不一致')
            self.fps = reader.fps
            self.rows[index] = reader.rows[inner]
            self.readers[index] = (reader, inner)
        if not self.rows:
            raise ValueError('缺少 meta/info.json 或带索引的 episode 子目录')
        self.episodes = [{'episode_index':i,'frame_count':int(row['length'])}
                         for i,row in sorted(self.rows.items())]
    def info(self, index):
        reader, inner = self.readers[index]
        return dict(reader.info(inner), dataset_name=self.root.name, episode_index=index, episodes=self.episodes)
    def video(self, index, camera):
        reader, inner = self.readers[index]
        return reader.video(inner,camera)
    def source(self,index):
        reader, inner = self.readers[index]
        return reader.source(inner)
    def signals(self,index):
        reader, inner = self.readers[index]
        return reader.signals(inner)


class DatasetCatalog:
    def __init__(self, root, output, reader_factory=None):
        self.default_root, self.default_output = Path(root).resolve(), Path(output).resolve()
        outside(self.default_output,self.default_root)
        self.path = self.default_output/'.dataset-collections.json'
        self.default_id = 'default'
        self.lock, self.cache = RLock(), {}
        if reader_factory is None:
            from v3_dataset import ReviewDataset
            reader_factory = ReviewDataset
        self.factory = reader_factory
        config = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.collections = config.get('collections',[])
        self.archived = set(config.get('archived',[]))

    def read(self, root):
        return self.factory(root) if (root/'meta/info.json').is_file() else EpisodeDirectoryDataset(root,self.factory)

    def scan(self, path):
        root = Path(path).expanduser()
        if not root.is_absolute() or not root.is_dir():
            raise ValueError('请填写服务器上存在的合集绝对目录')
        root = root.resolve()
        outside(self.default_output,root)
        rows=[]
        for folder in sorted(root.iterdir()):
            if folder.name.startswith('.') or not folder.is_dir():
                continue
            row={'name':folder.name,'available':False,'episode_count':0,'reason':''}
            try:
                if not folder.resolve().is_relative_to(root):
                    raise ValueError('子目录不能指向合集之外')
                outside(self.default_output,folder.resolve())
                reader=self.read(folder)
                if not reader.rows:
                    raise ValueError('数据集没有 episode 索引')
                row.update(available=True,episode_count=len(reader.rows))
            except (OSError,ValueError,KeyError,TypeError) as error:
                row['reason']=str(error)
            rows.append(row)
        return rows

    def persist(self, collections):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf8',dir=self.path.parent,delete=False) as stream:
            temporary=Path(stream.name)
            json.dump({'collections':collections,'archived':sorted(self.archived)},stream,ensure_ascii=False,indent=2)
            stream.flush();os.fsync(stream.fileno())
        try:
            os.replace(temporary,self.path)
        finally:
            temporary.unlink(missing_ok=True)
        self.collections=collections

    def add(self, name, path, dates):
        if not isinstance(name,str) or not name.strip():
            raise ValueError('请填写合集名称')
        if not isinstance(path,str) or not isinstance(dates,list) or not dates:
            raise ValueError('请先扫描并选择至少一个可用日期数据集')
        scanned={row['name']:row for row in self.scan(path)}
        if any(not isinstance(date,str) or date not in scanned or not scanned[date]['available'] for date in dates):
            raise ValueError('所选日期不存在或无法读取，请重新扫描')
        root=str(Path(path).expanduser().resolve())
        key=hashlib.sha256(root.encode()).hexdigest()[:16]
        with self.lock:
            if any(c['root']==root for c in self.collections):
                raise ValueError('该合集已添加，请使用刷新数据集')
            collection={'id':key,'name':name.strip(),'root':root,'dates':sorted(set(dates))}
            self.persist([*self.collections,collection])
        return self.collection_view(collection)

    def entry(self, dataset_id):
        if dataset_id==self.default_id:
            return self.default_root,self.default_output,None
        for collection in self.collections:
            for date in collection['dates']:
                if dataset_id==collection['id']+':'+date:
                    root=Path(collection['root'])/date
                    if root.resolve().parent != Path(collection['root']):
                        raise ValueError('数据集目录已改变，请检查合集路径')
                    output=self.default_output/'collections'/collection['id']/date
                    outside(self.default_output,root.resolve())
                    return root,output,collection
        raise ValueError('数据集未登记')

    def open(self, dataset_id):
        with self.lock:
            root,output,_=self.entry(dataset_id)
            if not root.is_dir():
                raise ValueError('数据集目录暂不可用，已有标注仍保留')
            if dataset_id not in self.cache:
                reader=self.read(root)
                if not reader.rows:raise ValueError('数据集没有 episode 索引')
                self.cache[dataset_id]=reader
            return self.cache[dataset_id],output

    def dataset_view(self, dataset_id, name):
        row={'id':dataset_id,'name':name,'available':False,'episode_count':0,'reason':''}
        try:
            reader,_=self.open(dataset_id)
            row.update(available=True,episode_count=len(reader.rows),first_episode=min(reader.rows),episode_indexes=sorted(reader.rows))
        except (OSError,ValueError,KeyError,TypeError) as error:
            row['reason']=str(error)
        return row

    def collection_view(self, collection):
        return {'id':collection['id'],'name':collection['name'],'root':collection['root'],
                'datasets':[self.dataset_view(collection['id']+':'+date,date) for date in collection['dates']]}

    def view(self):
        with self.lock:
            legacy={'id':'legacy','name':'原有数据集','root':str(self.default_root),
                    'datasets':[self.dataset_view(self.default_id,self.default_root.name)]}
            return {'default_dataset_id':self.default_id,'collections':[legacy,*[self.collection_view(c) for c in self.collections]]}

    def archive(self, dataset_id, archived):
        if type(archived) is not bool: raise ValueError('归档状态无效')
        with self.lock:
            self.entry(dataset_id)
            previous=self.archived.copy()
            if archived: self.archived.add(dataset_id)
            else: self.archived.discard(dataset_id)
            try: self.persist(self.collections)
            except OSError:
                self.archived=previous
                raise

    def refresh(self, collection_id):
        with self.lock:
            collection=next((c for c in self.collections if c['id']==collection_id),None)
            if collection is None:raise ValueError('合集未登记')
            updated=copy.deepcopy(collection)
            try:
                updated['dates']=sorted(set(updated['dates'])|{r['name'] for r in self.scan(updated['root']) if r['available']})
            except (OSError,ValueError):
                pass  # Offline roots retain all registered dates and outputs.
            self.persist([updated if c['id']==collection_id else c for c in self.collections])
            self.cache={key:value for key,value in self.cache.items() if not key.startswith(collection_id+':')}
            return self.collection_view(updated)
