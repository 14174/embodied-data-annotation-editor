"""Independent annotation files; source labels are never overwritten."""
import hashlib
import json
import os
import tempfile
import time
import uuid
from pathlib import Path
from threading import Lock

TYPES = {'subtask', 'fine_action'}
WRITE_LOCK = Lock()


def next_episode(root, indexes, current, kind):
    """Prefer another episode without a submitted annotation of this type."""
    if kind not in TYPES:
        raise ValueError('标注类型无效')
    indexes = sorted(indexes)
    ordered = [i for i in indexes if i > current] + [i for i in indexes if i < current]
    for index in ordered:
        directory = root / f'episode_{index:06d}' / kind
        if not any(path.is_file() for path in directory.glob('*.json')):
            return {'episode_index': index, 'unannotated': True}
    return {'episode_index': ordered[0] if ordered else None, 'unannotated': False}


class AnnotationConflict(Exception):
    def __init__(self, created_at):
        self.created_at = created_at

class AnnotationStore:
    def __init__(self, root: Path, frame_count: int):
        self.root, self.frame_count = root, frame_count

    def _path(self, author, kind):
        if not isinstance(author, str) or not author.strip() or len(author.strip()) > 80:
            raise ValueError('请填写标注人姓名（最多 80 字）')
        if kind not in TYPES:
            raise ValueError('标注类型无效')
        key = hashlib.sha256(author.strip().encode()).hexdigest()
        return self.root / kind / (key + '.json')

    def validate(self, segments):
        if not isinstance(segments, list) or not segments:
            raise ValueError('至少需要一个分段')
        end = 0
        for s in segments:
            if not isinstance(s, dict):
                raise ValueError('分段格式错误')
            a, b = s.get('start_frame'), s.get('end_frame')
            if type(a) is not int or type(b) is not int or a != end or not a < b <= self.frame_count:
                raise ValueError('分段须为连续整数帧区间，不能有空隙、重叠或零长度段')
            if not isinstance(s.get('caption'), str) or not s['caption'].strip():
                raise ValueError('请补齐每段 caption 后提交')
            if not isinstance(s.get('category', ''), str):
                raise ValueError('动作类别应为文本')
            end = b
        if end != self.frame_count:
            raise ValueError('最后一段须覆盖到视频末尾')

    def save(self, author, kind, segments, source=None, metadata=None, *,
             protect_existing=False, expected_created_at=None):
        path = self._path(author, kind)
        self.validate(segments)
        with WRITE_LOCK:
            if protect_existing and path.exists():
                existing = json.loads(path.read_text())
                if existing['created_at'] != expected_created_at:
                    raise AnnotationConflict(existing['created_at'])
            data = dict(metadata or {})
            data.update(annotation_type=kind, annotator=author.strip(), created_at=time.time(),
                        frame_count=self.frame_count, source_annotation=source,
                        result={'segments': [{k:s.get(k,'') for k in ('start_frame','end_frame','caption','category')} for s in segments]})
            self._write(path, data)
        return data

    def _write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf8',dir=path.parent,delete=False) as f:
                tmp=f.name
                json.dump(data,f,ensure_ascii=False,indent=2)
                f.flush(); os.fsync(f.fileno())
            os.replace(tmp,path)
        finally:
            if tmp and os.path.exists(tmp): os.unlink(tmp)

    def get(self, author, kind):
        path = self._path(author,kind)
        return json.loads(path.read_text()) if path.exists() else None

    def list(self):
        return [json.loads(p.read_text()) for kind in sorted(TYPES)
                for p in sorted((self.root / kind).glob('*.json'))]

    def flag(self, author, kind, note, metadata=None):
        self._path(author, kind)  # Apply the same signature and type validation.
        if not isinstance(note, str) or not note.strip() or len(note.strip()) > 2000:
            raise ValueError('请填写异常备注（最多 2000 字）')
        data = dict(metadata or {})
        data.update(report_id=uuid.uuid4().hex, status='needs_review', annotator=author.strip(),
                    annotation_type=kind, note=note.strip(), frame_count=self.frame_count,
                    created_at=time.time())
        self._write(self.root / 'review_flags' / (data['report_id'] + '.json'), data)
        return data

    def flags(self):
        records = [json.loads(p.read_text()) for p in (self.root / 'review_flags').glob('*.json')]
        return sorted(records, key=lambda record: record['created_at'], reverse=True)
