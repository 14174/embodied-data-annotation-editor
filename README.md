# Embodied Data Annotation Editor

一个浏览器标注工具，用于编辑机器人多视角视频的动作区间和 caption。

- 同步播放多视角视频，查看状态曲线，按片段跳转或使用自定义帧步长移动。
- 播放时打点切段，拖动共享边界，编辑 caption。支持子任务和细粒度动作两种独立标注。
- 支持加载预标注和已提交结果。草稿保存在浏览器，提交按 episode、标注人、标注类型区分，覆盖前需确认。

## 运行

需要 Python 3.10 或更新版本。

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python full_server.py /path/to/dataset ./annotations
```

打开 [http://127.0.0.1:8000/editor](http://127.0.0.1:8000/editor)。输出目录应位于数据集目录之外。服务默认监听本机；标注人姓名用于署名，服务未提供账号认证。

## 数据格式

当前读取器支持带以下元数据的 LeRobot v3 风格数据集，每路视频文件对应一条完整 episode。准备数据时请使用从 0 开始的 episode 编号。

- `meta/info.json` 提供 `fps`、`video_path` 和 `data_path`。路径模板中的占位符为 `chunk_index`、`file_index`，视频模板另含 `video_key`。
- `meta/episodes/**/*.parquet` 提供 `episode_index`、`length`、`viewer/cameras_json`（相机键 JSON 数组），以及各相机的 `videos/<camera>/{chunk_index,file_index,from_timestamp,to_timestamp}`。视频起点为 0，终点对应 episode 时长。
- 如需状态曲线，在 episode 元数据提供 `viewer/signals_json`（状态列到 `shape`、可选 `names` 的映射）、`data/chunk_index` 和 `data/file_index`。状态文件以 `episode_index`、`frame_index` 对齐视频。
- 可选预标注放在 `output/flora/episode_000000/caption.json` 等位置，包含 `fps` 和 `result.segments`。每段含 `start_frame`、`end_frame`、`caption`，区间左闭右开。

## 测试

```sh
python -m unittest discover -s tests
node tests/segments.test.mjs
```
