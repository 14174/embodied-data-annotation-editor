# H100 标注平台与 TempSeg 可复用流程

平台代码位于 H100 的 `/home/zhiwen/workspace/embodied-data-annotation-editor`。下面命令均不需要把 Token 写进命令或仓库；`--config` 只填写管理员分配的凭据文件路径。

## 数据机快捷入口

在本项目目录执行：

```bash
./h100ctl open --browser
./h100ctl platform status
./h100ctl platform logs
./h100ctl model health
```

`open` 先启动 H100 已安装的用户服务，再复用或建立本地 SSH 视频访问转发，检查健康状态后打开 `http://127.0.0.1:18080/editor`。省略 `--browser` 仅打印地址。SSH 别名默认为 `h100`；用 `ANNOTATION_SSH_HOST`、`ANNOTATION_REMOTE_ROOT` 可切换账号或代码位置。其他机器须先配置自己的 SSH 登录。推理命令始终通过 SSH 在 H100 上执行，不需要转发推理服务的 18866 端口。

H100 平台已启用 `annotation-editor.service`，且 `zhiwen` 已开启 linger：支持开机启动、异常重启。数据机已有 `annotation-editor-h100-tunnel.service`，在用户会话启动并自动重连。手动 `open` 建立的临时转发只在 SSH 连接存活期间有效，断线后重新执行即可。

## 首次部署 / 重新安装平台

H100 需 Python 3.10+、ffmpeg/ffprobe，以及本项目 `.venv`。已有环境可直接复用；新机器按项目 README 安装 requirements。

```bash
./annotationctl platform install \
  --dataset "$PWD/data/review/20261118_144854" \
  --output "$PWD/annotations/20261118_144854" --port 18080 \
  --collection-root /data1/huggingface/raw_data --review-root "$PWD/data/review"
./annotationctl platform status
./annotationctl platform start
./annotationctl platform restart
./annotationctl platform logs
```

安装命令检查数据集和 systemd 配置后，备份旧 unit、启用自启并重启平台。要在未登录时随开机启动，由有权限的账号执行 `loginctl enable-linger 用户名`。平台默认只监听回环地址。无 systemd 时可用 `platform run`，参数与 `install` 相同；它前台运行，适合终端或已有进程管理器。

用户服务不自动加载 `.env`；文本 caption 辅助若有额外配置，按 README 配置环境。这与 TempSeg 视频分段服务独立。

## 查数据与准备播放副本

在 H100 项目目录：

```bash
./annotationctl datasets --videos-only
./annotationctl prepare \
  --source /data1/huggingface/raw_data/20261119_172411 \
  --destination "$PWD/data/review/20261119_172411"
```

准备流程支持原生 LeRobot v3 视频索引：按各相机自己的 episode 时间范围生成从零开始的 H.264 视频（CRF 18，浏览器兼容的有损副本），校验帧数/时长，复用原始状态数据。可加 `--episodes 0 2` 仅准备选中轨迹。源目录保持不变，已存在的不同目标拒绝覆盖；同一命令生成且标记一致的副本可重复复用。旧部署准备的副本可直接用来推理和导入，无需重新准备。

Parquet 内嵌图像的数据不能直接交给当前 TempSeg 客户端，需要先导出同步视频。相机名称自动映射支持 `image`/`left_wrist_image`/`right_wrist_image`、`observation.images.scene`/`left_wrist`/`right_wrist` 等常用名称；不明确的角色使用显式 manifest。

当前 H100 合集固定为 `/data1/huggingface/raw_data`。平台启动和页面打开时自动扫描其直属数据集目录；页面可见时每 30 秒刷新一次，也可点击“刷新数据集”立即扫描。无需添加合集、填写路径或勾选日期。

上传未完成、图像仍内嵌于 Parquet、或尚无独立 episode 播放视频的数据会显示“待准备”及原因。准备完成的副本由 `preparation.json` 中的原始来源自动关联，复用 `data/review/<数据集>/`；发现副本或索引更新后自动变为可标注。扫描不自动启动转码、GPU 推理或人工提交。

已有播放副本的原数据集 ID、模型结果与人工输出路径继续复用，合集列表不重复显示“原有数据集”和播放副本合集。历史链接和浏览器草稿仍可使用。自动刷新不会切换当前日期/episode；打开日期下拉框或进行编辑操作时暂缓刷新。目录暂时离线时保留登记和人工结果。`register --root "$PWD/data/review"` 在固定模式下仅用于立即刷新原始目录扫描，通常无需执行。

## 推理提交与取回

建议使用已准备的独立 episode 视频，避免源视频非零起点带来的时间戳舍入差异。窗口、抽帧、提示词、GPU、重试窗口和合并均由服务维护。

```bash
export TEMPSEG_CONFIG=/var/tmp/tempseg-v2-access-1008/zhiwen.json
./annotationctl model health
./annotationctl model infer \
  --dataset "$PWD/data/review/20261119_172411" --episodes 0 \
  --output-dir "$PWD/data/model-runs/trial-001"
```

凭据必须属于当前获授权账号；换用户时使用管理员分配的文件。也可逐次指定 `--config /path/to/credentials.json`。服务地址从凭据读取，官方客户端默认位于 `/var/tmp/tempseg-v2-client-1008/client.py`，可用 `--client` 指定其他发布路径。当前 TempSeg 服务由 `bingyu` 维护，本工具检查就绪状态并使用服务；未就绪时联系管理员启动 worker。不会用数据账号跨用户重启共享 GPU worker。

每条 episode 都保存 `.manifest.json`、`.job.json` 和原始结果 JSON。`--transfer auto` 默认优先路径读取，必要时自动上传并利用内容缓存。相同输入由服务去重；重复取回相同 JSON 不覆盖不同结果。

`--no-wait` 只提交并保存真实 job_id。中断或超时不会取消服务端任务；随后取回：

```bash
./annotationctl model result --job-id 实际任务ID \
  --output "$PWD/data/model-runs/trial-001/episode-result.json"
```

失败任务可在 `result` 添加 `--retry`，受服务端最多三次尝试限制。调整等待时长使用 `--timeout 7200`。多条 episode 默认逐条提交并等待；批量只提交可加 `--no-wait`，之后分别取回。

如果使用自定义相机或原始长视频，可用 `model infer --manifest /absolute/path/episode.json --output-dir ...`。manifest 结构与 H100 `/var/tmp/tempseg-v2-client-1008/README.md` 一致；每路源起点可不同，选中 episode 的内容、帧率、帧数与相对帧时间戳须一致。时间戳校验失败时先准备独立 episode 副本。

数据机可将以上任意命令中的 `./annotationctl` 换成 `./h100ctl`，后续参数中的文件路径均指 H100。

## 导入与人工复核

```bash
./annotationctl import --dataset "$PWD/data/review/20261119_172411" \
  --result "$PWD/data/model-runs/trial-001/20261119_172411/episode_000000.json"
```

导入严格校验数据集 ID、episode、帧率、帧数与连续边界。结果写入该播放数据集的 `model-preannotations.json`，原始 JSON 按 SHA-256 保存在 `.model-preannotations/`，页面刷新即可出现 `TempSeg-SFT-v2-epoch07 推理结果`。未推理的 episode 不显示该模型，也不会报错。旧 v1 文件继续兼容。

预标注 caption/category 可以为空，且不计入人工提交。复核、填写 caption 后，仍须署名提交人工标注。已有人工结果、人工数量和浏览器草稿不被导入覆盖；来源偏好继续保留，如页面正在显示其他来源，在来源下拉框切换即可。

仅当原始模型输出恰好漏掉末尾一帧时，可显式添加 `--repair-single-frame-tail`：延长最后一段一帧，保存修正记录，并在页面提示人工复核。其他空隙、重叠、越界、帧率不匹配一律拒绝。不同模型结果不会静默覆盖；更新同版本某条 episode 需显式加 `--replace-model`。不同模型版本使用独立播放数据集保留。

## 本次试跑

| 数据集 / episode | 页面入口 | 模型分段 |
| --- | --- | ---: |
| `20261118_144854 / 5` | `http://127.0.0.1:18080/editor?dataset=default&episode=5` | 13；导入副本补齐末尾一帧并提示复核 |
| `20261119_172411 / 0` | `http://127.0.0.1:18080/editor?dataset=02950c89156e9cdc%3A20261119_172411&episode=0` | 3 |

原始推理结果和日志位于 H100 `/home/zhiwen/tempseg_trials/20261120_103342/`。本次部署前代码和 unit 都有备份；代码备份位置见 `data/deploy/workflow-deployment.json`。
