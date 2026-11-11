# Version history / 版本记录

## v0.2.0 · 2026-11-11

Browser annotation with optional AI caption assistance. This release includes all changes since the fixed `v0.1.0` snapshot.

本版加入可选的 AI 文字辅助，并汇总固定版 `v0.1.0` 之后的编辑、导航和复审改动。完整使用方法与模型配置见 [English README](README.md) / [中文说明](README.zh-CN.md)。

### Caption assistance / 文字辅助

- **Simplify / 精简整理:** deduplicate merged captions and summarize phases of one goal as an imperative subtask. Prompt: `subtask-simplify-2-imperative`.
- **Rewrite / 多样化改写:** vary sentence structure and equivalent nouns while preserving task facts. Prompt: `subtask-diversify-1`.
- Both use preview → optional manual edit → explicit Apply. Regenerate, cancel and Undo are available. Applying changes only the current caption and browser draft; boundaries and submitted records are unchanged. Submit separately after reviewing.
- 两个按钮仅用于 Subtask。精简整理用于合并后的阶段归纳，多样化改写用于指令句式和等义词变化。采用前检查对象、颜色、左右手、来源／目标、位置和成败；模型无法核对视频。
- Only the current caption and built-in examples are sent to the configured model. No video, original instruction, state or annotator name is sent. Manual annotation remains available without a model key. Requests are limited to two concurrent calls per process; failed or incomplete responses do not replace captions.

### Editing and collaboration / 编辑与协作

- Next episode prioritizes episodes without submitted human annotations of the current type and rechecks the server on each click. Model predictions and browser drafts count as zero human submissions.
- Human annotation counts and available sources refresh every 3 seconds while visible and on return, type changes and submission. Current edits and source selection are preserved. Episodes are not reserved, so independent submissions can still occur.
- **上一条** returns to the named annotator's most recent submitted episode and annotation type. Clicking a caption card seeks to its start.
- Red **人工复审** accepts a required anomaly note. Reports are episode-wide, saved separately and do not count as annotations or change the source instruction. Report resolution is not implemented.
- 优先未标注导航、实时人工计数、返回最近提交、点击卡片定位和异常复审均已纳入本版。顶部「使用说明」补充了署名、提交覆盖、草稿、多用户同步与 AI 文字辅助规则。

### Compatibility and upgrade / 兼容与升级

- Annotation JSON keeps the existing flat, independent `subtask` / `fine_action` records and continuous integer-frame intervals. No annotation migration is required.
- Keep using the same dataset and independent output directory. After updating the checkout, restart the server using the existing arguments. Keep the same browser origin to access existing local drafts.
- The standalone entry point remains `python full_server.py DATASET OUTPUT [--host HOST] [--port PORT]`, with localhost binding by default. Model configuration is optional and uses server-side environment variables; `.env.example` is supplied and real `.env` files are ignored by Git.
- 升级时沿用原数据与人工输出目录，重启服务。AI 建议只有人工采用后才进入草稿，只有提交后才成为服务器人工记录。

### Validation / 验证

- 19 Python tests and four JavaScript suites cover storage, navigation, review reports, caption modes, request failures, concurrency limits, preview, stale responses, adoption and Undo.
- Text-model sanity checks cover clothing transfer, equivalent toy names, failed handover and simplify-mode regression. Browser checks verify preview, caption-only adoption, fixed boundaries and Undo on an isolated test origin.
- 上述检查验证功能链路；AI 改写的事实正确性仍需人工复核。

## v0.1.0

Initial fixed release: synchronized multi-view playback, frame stepping with press-and-hold, playback marking, shared boundary dragging, caption editing, source loading, browser drafts and per-annotator submissions.

首个固定版包含多视角播放、可调帧步长与长按、播放打点、边界拖动、caption 编辑、来源加载、本地草稿和按标注人提交。历史快照保留在 `v0.1.0` 标签。
