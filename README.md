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

下面用一条 **2 秒、30 fps、60 帧、两个相机视角**的 episode 举例。编辑器读取带相机索引的 LeRobot v3 风格目录，每个 MP4 对应一个视角的一条完整 episode。编号从 `0` 开始。

### 目录结构

```text
example_dataset/
├── meta/
│   ├── info.json
│   └── episodes/
│       └── chunk-000/file-000.parquet
├── videos/
│   ├── observation.images.scene/
│   │   └── chunk-000/file-000.mp4
│   └── observation.images.left_wrist/
│       └── chunk-000/file-000.mp4
├── data/                              # 可选，状态曲线数据
│   └── chunk-000/file-000.parquet
└── output/                            # 可选，已有预标注
    └── flora/episode_000000/caption.json
```

### 1. 数据集配置 · `meta/info.json`

```json
{
  "fps": 30,
  "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4",
  "data_path": "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet"
}
```

路径模板中的 `video_key` 来自相机列表，`chunk_index` 和 `file_index` 来自下面的 episode 索引。状态文件和视频使用各自的索引。

### 2. Episode 索引 · `meta/episodes/chunk-000/file-000.parquet`

下方 JSON 展示 **Parquet 的一行**，每个键都是独立列。两个 `viewer/*_json` 字段存的是 JSON **字符串**，写入 Parquet 前先用 `json.dumps()` 序列化。

```json
{
  "episode_index": 0,
  "length": 60,
  "tasks": ["把方块放进托盘"],
  "viewer/cameras_json": "[\"observation.images.scene\", \"observation.images.left_wrist\"]",
  "videos/observation.images.scene/chunk_index": 0,
  "videos/observation.images.scene/file_index": 0,
  "videos/observation.images.scene/from_timestamp": 0.0,
  "videos/observation.images.scene/to_timestamp": 2.0,
  "videos/observation.images.left_wrist/chunk_index": 0,
  "videos/observation.images.left_wrist/file_index": 0,
  "videos/observation.images.left_wrist/from_timestamp": 0.0,
  "videos/observation.images.left_wrist/to_timestamp": 2.0,
  "viewer/signals_json": "{\"observation.state\": {\"shape\": [2], \"names\": [\"gripper_x\", \"gripper_width\"]}}",
  "data/chunk_index": 0,
  "data/file_index": 0
}
```

`length` 是帧数，视频时间戳以秒为单位，范围是 `0` 到 `length / fps`。每个相机分别填写四个 `videos/<camera>/...` 字段。`tasks` 可选，页面显示列表中的第一项。没有状态数据时，可省略 `viewer/signals_json` 和两个 `data/*` 索引列。

### 3. 状态曲线（可选） · `data/chunk-000/file-000.parquet`

每帧一行。这个例子有 60 行，`frame_index` 为 `0–59`；每行 `observation.state` 有两个值，分别对应上面的 `gripper_x` 和 `gripper_width`。

| episode_index | frame_index | observation.state |
| ---: | ---: | --- |
| 0 | 0 | `[0.12, 0.08]` |
| 0 | 1 | `[0.13, 0.08]` |
| 0 | … | … |
| 0 | 59 | `[0.31, 0.04]` |

### 4. 预标注（可选） · `output/flora/episode_000000/caption.json`

```json
{
  "fps": 30,
  "result": {
    "segments": [
      {"start_frame": 0, "end_frame": 30, "caption": "夹起方块"},
      {"start_frame": 30, "end_frame": 60, "caption": "把方块放进托盘"}
    ]
  }
}
```

区间采用 `[start_frame, end_frame)`。第一段覆盖第 0–29 帧，第二段覆盖第 30–59 帧，末尾边界写 `60`。各段连续覆盖整条 episode；预标注帧率不同时，编辑器按时间换算到视频帧率。

人工提交写到启动命令指定的独立目录，例如 `annotations/episode_000000/subtask/<标注人姓名的哈希>.json`。`fine_action` 类型保存到同级的 `fine_action/` 目录。

## 测试

```sh
python -m unittest discover -s tests
node tests/segments.test.mjs
```
