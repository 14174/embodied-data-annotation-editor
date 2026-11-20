"""Reusable platform deployment, TempSeg inference, and audited preannotation import."""
import argparse
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

REPO = Path(__file__).resolve().parent
DEFAULT_CLIENT = '/var/tmp/tempseg-v2-client-1008/client.py'
HTTP = build_opener(ProxyHandler({}))


def read_json(path):
    return json.loads(Path(path).read_text())


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def request(base, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    with HTTP.open(Request(base.rstrip('/')+path, data=data,
            headers={'Content-Type':'application/json'} if data else {}), timeout=30) as response:
        return json.load(response)


def import_result(dataset, result_path, *, repair_tail=False, replace=False):
    from prepare_dataset import index_dataset
    dataset, result_path = Path(dataset).resolve(), Path(result_path).resolve()
    meta, rows = index_dataset(dataset)
    original = read_json(result_path)
    record = copy.deepcopy(original)
    index = int(record['episode_id'])
    if index not in rows:
        raise ValueError('结果 episode 不在播放数据集中')
    expected_dataset = dataset.name
    if (dataset/'preparation.json').is_file():
        expected_dataset = Path(read_json(dataset/'preparation.json')['source']).name
    if record.get('dataset_id') != expected_dataset:
        raise ValueError('推理结果属于其他数据集')
    count, fps = int(rows[index]['length']), float(meta['fps'])
    if type(record.get('frame_count')) is not int or record['frame_count'] != count or float(record.get('fps',0)) != fps:
        raise ValueError('推理结果帧数或帧率与视频不符')
    source = record.get('source_annotation')
    if not isinstance(source,str) or not re.fullmatch(r'TempSeg-SFT-v\d+(?:-epoch\d+)?',source) or record.get('annotation_type') != 'subtask':
        raise ValueError('需要 TempSeg subtask 原始推理结果')
    segments = record['result']['segments']
    if not isinstance(segments,list) or not segments:
        raise ValueError('缺少分段')
    cursor = 0
    for segment in segments:
        a, b = segment.get('start_frame'), segment.get('end_frame')
        if type(a) is not int or type(b) is not int or a != cursor or not a < b <= count:
            raise ValueError('模型分段含空隙、重叠或非法帧边界')
        if not isinstance(segment.get('caption'),str) or not isinstance(segment.get('category',''),str):
            raise ValueError('caption/category 必须为文本，预标注允许空字符串')
        cursor = b
    adjustments = []
    if cursor != count:
        if not repair_tail or cursor != count-1:
            raise ValueError('模型分段未覆盖视频末尾；仅末尾缺一帧可显式使用 --repair-single-frame-tail')
        segments[-1]['end_frame'] = count
        segments[-1]['end_s'] = count/fps
        adjustments.append({'field':'result.segments[-1].end_frame','from':cursor,'to':count,
                            'reason':'one uncovered terminal frame; explicit import repair'})
        record['warning'] = '模型原始结果末尾缺 1 帧，导入时已延长最后一段；请对照视频复核。'
    record.update(episode_index=index, import_adjustments=adjustments,
        import_provenance={'original_path':str(result_path),
            'original_sha256':hashlib.sha256(result_path.read_bytes()).hexdigest()})
    destination = dataset/'model-preannotations.json'
    audit = dataset/'.model-preannotations'
    audit.mkdir(parents=True,exist_ok=True)
    with (audit/'import.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        bundle = read_json(destination) if destination.exists() else {'source_annotation':source,'episodes':[]}
        if bundle.get('source_annotation') != source:
            raise ValueError('当前数据集已有另一模型版本；请保留到独立播放数据集')
        existing = {item['episode_index']:item for item in bundle['episodes']}
        if index in existing and existing[index] != record and not replace:
            raise FileExistsError('已有不同的模型结果，使用 --replace-model 显式替换；人工标注不受影响')
        raw = audit/(record['import_provenance']['original_sha256']+'.json')
        if not raw.exists():
            with raw.open('xb') as stream:
                stream.write(result_path.read_bytes())
        existing[index] = record
        bundle['episodes'] = [existing[i] for i in sorted(existing)]
        atomic_json(destination,bundle)
    return {'dataset':str(dataset),'episode':index,'segments':len(segments),'adjustments':adjustments,
            'preset':str(destination),'raw_result':str(raw)}


def connection(args):
    client = runpy.run_path(str(Path(args.client).resolve()))
    config_path = args.config or os.environ.get('TEMPSEG_CONFIG')
    if not config_path:
        raise ValueError('使用 --config 或 TEMPSEG_CONFIG 指定管理员分配的凭据文件')
    config = read_json(Path(config_path).expanduser())
    return client, client['Connection'](config), config['base_url']


def model_command(args):
    if args.model_action == 'health':
        health = request(args.url,'/healthz')
        print(json.dumps(health,ensure_ascii=False))
        if not health.get('ready'):
            raise RuntimeError('模型 worker 尚未就绪，请联系服务管理员启动')
        return
    client, conn, base = connection(args)
    if args.model_action == 'result':
        if args.retry:
            conn.request('POST','/v1/jobs/'+args.job_id+'/retry')
        result = conn.wait(args.job_id, timeout=args.timeout)
        client['save_result'](args.output,result)
        print(json.dumps({'job_id':args.job_id,'output':str(args.output)}))
        return
    health = request(base,'/healthz')
    if not health.get('ready'):
        raise RuntimeError('模型未就绪，未提交任务；请联系服务管理员启动 worker')
    if args.manifest:
        manifests = [read_json(args.manifest)]
    else:
        from prepare_dataset import index_dataset, camera_manifest
        if not args.dataset or not args.episodes:
            raise ValueError('使用 --manifest，或同时指定 --dataset 和 --episodes')
        root = args.dataset.resolve()
        meta, rows = index_dataset(root)
        manifests = []
        if not set(args.episodes) <= rows.keys():
            raise ValueError('所选 episode 不存在')
        original_name = root.name
        if (root/'preparation.json').is_file():
            original_name = Path(read_json(root/'preparation.json')['source']).name
        for i in sorted(set(args.episodes)):
            manifests.append({'dataset_id':original_name,'episode_id':str(i),
                              'videos':camera_manifest(root,meta,rows[i])})
    args.output_dir = args.output_dir.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for manifest in manifests:
        name = str(manifest['dataset_id'])
        index = int(manifest['episode_id'])
        if index < 0 or not re.fullmatch(r'[A-Za-z0-9_.-]+',name) or name in ('.','..'):
            raise ValueError('dataset_id 或 episode_id 不能用于文件路径')
        folder = args.output_dir/name
        folder.mkdir(exist_ok=True)
        stem = f'episode_{index:06d}'
        manifest_path = folder/(stem+'.manifest.json')
        if manifest_path.exists() and read_json(manifest_path) != manifest:
            raise FileExistsError('输出目录已有另一输入，请换独立运行目录')
        atomic_json(manifest_path,manifest)
        # The official service deduplicates identical inputs; failed jobs need explicit result --retry.
        job = conn.submit(manifest,args.transfer)
        job.update(manifest=str(manifest_path), output=str(folder/(stem+'.json')))
        atomic_json(folder/(stem+'.job.json'),job)
        print(json.dumps(job),flush=True)
        if not args.no_wait:
            result = conn.wait(job['job_id'],timeout=args.timeout)
            client['save_result'](job['output'],result)
            job.update(status='succeeded',segments=len(result['result']['segments']))
            atomic_json(folder/(stem+'.job.json'),job)
            print(json.dumps(job),flush=True)


def unit_quote(value):
    # systemd specifiers and ExecStart expansion have different escaping from shells.
    return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%').replace('$','$$')+'"'


def platform_command(args):
    unit = 'annotation-editor.service'
    if args.platform_action == 'install':
        from v3_dataset import ReviewDataset
        from dataset_catalog import outside
        dataset, output = args.dataset.resolve(), args.output.resolve()
        outside(output,dataset)
        reader = ReviewDataset(dataset)
        if not reader.rows:
            raise ValueError('数据集为空')
        reader.info(min(reader.rows))
        python = REPO/'.venv/bin/python'
        if not python.is_file():
            raise FileNotFoundError('先按 README 安装项目 .venv 及依赖')
        command = ' '.join(unit_quote(x) for x in [python,REPO/'full_server.py',dataset,output,
                                                  '--host',args.host,'--port',args.port])
        collection_env = ''
        if args.collection_root:
            collection_root = args.collection_root.resolve()
            outside(output,collection_root)
            collection_env += 'Environment='+unit_quote('ANNOTATION_COLLECTION_ROOT='+str(collection_root))+'\n'
        if args.review_root:
            if not args.collection_root:
                raise ValueError('--review-root 需要同时指定 --collection-root')
            collection_env += 'Environment='+unit_quote('ANNOTATION_REVIEW_ROOT='+str(args.review_root.resolve()))+'\n'
        working_dir = str(REPO).replace('\\','\\\\').replace(' ','\\x20').replace('%','%%')
        content = ('[Unit]\nDescription=Robot annotation editor\nAfter=network.target\n\n[Service]\n'
                   f'Type=simple\nWorkingDirectory={working_dir}\nEnvironment=PYTHONUNBUFFERED=1\n'
                   f'{collection_env}ExecStart={command}\nRestart=on-failure\nRestartSec=3\nTimeoutStopSec=20\n\n'
                   '[Install]\nWantedBy=default.target\n')
        path = Path.home()/'.config/systemd/user'/unit
        path.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='annotation-unit-') as directory:
            candidate = Path(directory)/unit
            candidate.write_text(content)
            subprocess.run(['systemd-analyze','--user','verify',str(candidate)],check=True)
        previous = path.read_text() if path.exists() else None
        if previous is not None and previous != content:
            backup = path.with_name(unit+'.backup-'+time.strftime('%Y%m%d_%H%M%S'))
            backup.write_text(previous)
        path.write_text(content)
        try:
            subprocess.run(['systemctl','--user','daemon-reload'],check=True)
            subprocess.run(['systemctl','--user','enable',unit],check=True)
            subprocess.run(['systemctl','--user','restart',unit],check=True)
        except subprocess.CalledProcessError:
            if previous is not None:
                path.write_text(previous)
            else:
                path.unlink(missing_ok=True)
            subprocess.run(['systemctl','--user','daemon-reload'],check=False)
            raise
        print(f'Installed {path}; loginctl enable-linger {Path.home().name} enables boot without login.')
        return
    if args.platform_action == 'run':
        if args.collection_root:
            os.environ['ANNOTATION_COLLECTION_ROOT']=str(args.collection_root.resolve())
        if args.review_root:
            os.environ['ANNOTATION_REVIEW_ROOT']=str(args.review_root.resolve())
        os.execv(sys.executable,[sys.executable,str(REPO/'full_server.py'),str(args.dataset),str(args.output),
                                '--host',args.host,'--port',str(args.port)])
    if args.platform_action == 'logs':
        subprocess.run(['journalctl','--user','-u',unit,'-n','80','--no-pager'],check=True)
        return
    if args.platform_action == 'status':
        for command in [['systemctl','--user','is-enabled',unit],['systemctl','--user','is-active',unit]]:
            subprocess.run(command,check=True)
        print(json.dumps(request(args.url,'/api/health'),ensure_ascii=False))
        return
    subprocess.run(['systemctl','--user',args.platform_action,unit],check=True)


def register(args):
    root = args.root.resolve()
    catalog = request(args.url,'/editor-api/collections')
    if catalog.get('fixed_root'):
        allowed = [Path(catalog['fixed_root'])]
        if catalog.get('review_root'):
            allowed.append(Path(catalog['review_root']))
        if root not in allowed:
            raise ValueError('平台已固定数据合集，请使用配置的原始目录或播放副本目录')
        result = request(args.url,'/editor-api/collections/refresh',{'collection_id':catalog['collections'][0]['id']})
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return
    existing = next((c for c in catalog['collections'] if c.get('root') == str(root) and c['id'] != 'legacy'),None)
    if existing:
        result = request(args.url,'/editor-api/collections/refresh',{'collection_id':existing['id']})
    else:
        scan = request(args.url,'/editor-api/collections/scan',{'path':str(root)})['datasets']
        dates = args.dates or [item['name'] for item in scan if item['available']]
        result = request(args.url,'/editor-api/collections',{'name':args.name,'path':str(root),'dates':dates})
    print(json.dumps(result,ensure_ascii=False,indent=2))


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='command',required=True)
    listing = commands.add_parser('datasets',help='列出原始数据集及视频可用性')
    listing.add_argument('--root',type=Path,default=Path('/data1/huggingface/raw_data'))
    listing.add_argument('--videos-only',action='store_true')
    prep = commands.add_parser('prepare',help='生成独立 H.264 episode 播放副本')
    prep.add_argument('--source',type=Path,required=True)
    prep.add_argument('--destination',type=Path,required=True)
    prep.add_argument('--episodes',type=int,nargs='+')
    imp = commands.add_parser('import',help='校验、保留原始结果并合并模型预标注')
    imp.add_argument('--dataset',type=Path,required=True)
    imp.add_argument('--result',type=Path,nargs='+',required=True)
    imp.add_argument('--repair-single-frame-tail',action='store_true')
    imp.add_argument('--replace-model',action='store_true')
    reg = commands.add_parser('register',help='登记或刷新平台中的播放数据合集')
    reg.add_argument('--root',type=Path,required=True)
    reg.add_argument('--name',default='服务器采集数据')
    reg.add_argument('--dates',nargs='+')
    reg.add_argument('--url',default='http://127.0.0.1:18080')
    model = commands.add_parser('model',help='使用已部署的 TempSeg 服务')
    models = model.add_subparsers(dest='model_action',required=True)
    health = models.add_parser('health')
    health.add_argument('--url',default='http://127.0.0.1:18866')
    for action in ['infer','result']:
        cmd = models.add_parser(action)
        cmd.add_argument('--config',type=Path,help='凭据文件；也可设置 TEMPSEG_CONFIG')
        cmd.add_argument('--client',default=DEFAULT_CLIENT)
        cmd.add_argument('--timeout',type=float,default=3600)
        if action == 'infer':
            source = cmd.add_mutually_exclusive_group(required=True)
            source.add_argument('--dataset',type=Path)
            source.add_argument('--manifest',type=Path)
            cmd.add_argument('--episodes',type=int,nargs='+')
            cmd.add_argument('--output-dir',type=Path,required=True)
            cmd.add_argument('--transfer',choices=['auto','path','upload'],default='auto')
            cmd.add_argument('--no-wait',action='store_true')
        else:
            cmd.add_argument('--job-id',required=True)
            cmd.add_argument('--output',type=Path,required=True)
            cmd.add_argument('--retry',action='store_true')
    platform = commands.add_parser('platform',help='平台用户服务安装、启动、状态、日志')
    platforms = platform.add_subparsers(dest='platform_action',required=True)
    for action in ['install','run','start','restart','stop','status','logs']:
        cmd = platforms.add_parser(action)
        if action in ('install','run'):
            cmd.add_argument('--dataset',type=Path,required=True)
            cmd.add_argument('--output',type=Path,required=True)
            cmd.add_argument('--host',default='127.0.0.1')
            cmd.add_argument('--port',type=int,default=18080)
            cmd.add_argument('--collection-root',type=Path,help='固定并自动扫描的原始数据目录')
            cmd.add_argument('--review-root',type=Path,help='复用已准备播放副本的目录')
        if action == 'status':
            cmd.add_argument('--url',default='http://127.0.0.1:18080')
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == 'platform':
        platform_command(args)
    elif args.command == 'model':
        model_command(args)
    elif args.command == 'register':
        register(args)
    elif args.command == 'import':
        for path in args.result:
            print(json.dumps(import_result(args.dataset,path,repair_tail=args.repair_single_frame_tail,
                                           replace=args.replace_model),ensure_ascii=False))
    elif args.command == 'prepare':
        from prepare_dataset import prepare
        print(prepare(args.source,args.destination,args.episodes))
    elif args.command == 'datasets':
        for file in sorted(args.root.glob('*/meta/info.json')):
            try:
                meta = read_json(file)
                cameras = {k:v['dtype'] for k,v in meta.get('features',{}).items() if v.get('dtype') in ('video','image')}
                if args.videos_only and 'video' not in cameras.values():
                    continue
                print(json.dumps({'dataset':file.parents[1].name,'episodes':meta.get('total_episodes'),
                    'fps':meta.get('fps'),'cameras':cameras},ensure_ascii=False))
            except (OSError,ValueError,KeyError) as error:
                print(f'{file}: {error}',file=sys.stderr)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('客户端已退出；已提交任务仍在服务端，使用 .job.json 中的 job_id 取回。',file=sys.stderr)
        sys.exit(130)
    except HTTPError as error:
        print(f'HTTP {error.code}: {error.read().decode(errors="replace")}',file=sys.stderr)
        sys.exit(1)
    except (ValueError,KeyError,OSError,RuntimeError,TimeoutError,subprocess.CalledProcessError) as error:
        print(f'Error: {error}',file=sys.stderr)
        sys.exit(1)
