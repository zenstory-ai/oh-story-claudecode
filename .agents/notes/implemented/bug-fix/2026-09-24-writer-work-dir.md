# Agent Note: 单章临时文件统一落到书内 .story/work/，提交成功后自动清理

Status: implemented
Date: 2026-09-24

## Problem

workflow-chapter 要求 writer「先写前组临时 segment」、`build_writer_prompt.py … --out {留档文件}`、
每章构造逐章事务 JSON，但从没规定这些文件放哪。真机会话里：

- 模型写到全局 `/tmp/ch22_seg1.md`、`/tmp/ch1_front.md`、`/tmp/ch1_writer_prompt.md`：多本书或多个
  会话写同一章号会互相覆盖，Windows 上没有 `/tmp`；
- 另一次把 `_seg_001_a.md` 放进 `正文/`：污染正文目录。若文件名形如 `第001章_前组.md`，
  `wordcount_core.find_chapter_file` 会因「同章正文不止一个」让 `chapter check/commit` 失败，
  `detect-story-gaps.sh` 也会把它算作一章；
- 还有一次提交后留下 `大纲/_tx_ch1.json`、`大纲/_writer_prompt_ch1.md`。清理规定写在步骤 13
  「每 3 章中途快照」里，单章或 1-2 章的批次根本走不到。

## Decision

1. 唯一落点：书目录下 `.story/work/第NNN章/`（章号补零到 3 位，与逐章记录同宽），文件名固定为
   `前组.md`、`后组.md`、`writer_prompt.md`、`tracking.json`。workflow-chapter 顶部「工作目录」
   一段、workflow-daily 事务步骤、tracking-transaction（同步到 story-import / story-review 副本）、
   project-files 目录树、narrative-writer 模板（已重新生成 OpenCode / Codex 适配）同口径。
2. `build_writer_prompt.py`：`--out` 不带值时留档到 `.story/work/第NNN章/writer_prompt.md`，并自动
   建父目录；执行安排槽直接写出前组/后组的绝对路径，写手不用自己编路径。
3. `storyctl.py chapter commit` / `accept-current-length` 在事务成功提交后删除
   `.story/work/第NNN章/`，再在为空时顺带删掉 `.story/work`、`.story`（`.story/作者记忆/` 存在时
   不动），返回 `work_dir_removed`。提交被拒（带外、blocking、事务无效）时目录原样保留供重跑。
   清理失败只在返回里附 `work_dir_cleanup_error`，不把已落盘的提交报成失败。
3a. 事务命令示例不留抽象占位：tracking-transaction（三份副本）与 story-import 的 `--input` 直接写成
   `{书项目根}/.story/work/init.json`、`{书项目根}/.story/work/第{NNN}章/tracking.json`。发版前实测开书
   首次初始化时，模型照 `{初始化事务.json}` 占位把事务写到了 `/tmp/claude-story-init/init.json`。
4. 文档把「提交成功后清理」从步骤 13 挪到步骤 12；作者选「这章不要了」时删正文与工作目录。
5. 回归：`test-chapter-completion-lifecycle.py` 覆盖「被拒保留 → 成功删除 → 作者记忆不受影响 →
   正文目录只剩一章」；`test-writer-pipeline.py` 覆盖 `--out` 无值留档与执行安排里的路径。

## Alternatives considered

- **`追踪/.work/`**：离事务 JSON 最近，且 dashboard 默认隐藏点目录。但 `追踪/` 全部是由
  `_tracking-state.json` 派生、禁止手改的文件，混进可手写的草稿会模糊这条纪律；`init` 迁移旧
  结构时也要在这个目录里搬文件，边界越清楚越好。
- **系统临时目录（`tempfile`）**：跨平台、不污染书目录。但路径每次不同，事务失败后「原样重
  跑同一份 JSON」要求文件能被找回；多会话之间也无法约定路径，模型仍会自己编。
- **每个书一个平铺的 `.story/work/` 目录，文件名带章号**：少一层目录。但清理要按文件名模式
  匹配，形如 `第001章_前组.md` 的名字又和正文命名撞型；按章分目录可以整目录删除，不猜文件。
- **只改文档不改脚本**：改动最小。但原问题就是清理步骤没被执行；由提交脚本在成功时确定性
  删除，不再依赖模型记得。

## Consequences

- 收益：并发书/会话不再撞文件，Windows 可用；正文目录只有章节，章节解析和 hooks 不会误判；
  提交成功即无残留，失败时现场完整可重跑。
- 收益：hooks 无需改动——写前守卫与写后兜底只认父目录名为 `正文` 的 `第N章*.md`，工作目录
  不触发细纲门；`story_hook_core` 找书只认名为 `正文`/`追踪` 的目录。
- 代价：`.story/` 在书目录下原本只放书级作者记忆，现在还会短暂出现 `work/`；story 看板对
  `.story` 不做隐藏，写作过程中能看到这些临时文件。
- 代价：`mode=revision` 事务仍走 `tracking_commit.py commit`，不经 storyctl，不会自动清理，靠
  文档要求删除；大修的原稿备份仍写在 `正文/`（`第X章_章名_原稿_日期.md`），本次未动。
