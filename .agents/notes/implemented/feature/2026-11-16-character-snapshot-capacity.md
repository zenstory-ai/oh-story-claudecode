# Agent Note: 角色快照容量按按需读取边界提升至 64 KiB 并补齐草稿按需快照文件

Status: implemented
Date: 2026-11-16
Related: issue #548, [续写状态卡活跃角色上限 20 人](2026-10-22-active-character-cap-20.md)

## Problem

长篇连载或逆向导入中，核心角色的 `能力与资源`、`关键关系`、`已知信息`、`未结事项` 四个列表随章节推进持续积累有效状态。`tracking_commit.py` 将单角色渲染后的 `追踪/角色状态/{角色名}.md` 硬上限固定为 `SNAPSHOT_MAX_BYTES = 8192`（目标提醒 `4096`），而 UTF-8 中文每字占 3 字节，约 2,650 字（70 余条常规短项）即触发硬拒绝，导致 `init`、`commit` 与 `storyctl.py chapter commit` 退出码 2 失败，作者只能被迫删减有效内容。

沿完整读写与派生链路核查，还存在三处同源缺口：
1. `render_context` 生成每章热上下文 `追踪/上下文.md` 时只读取活跃角色的 `identity`、`state`、`goal` 三个单句字段，根本不读取角色快照的四个列表；旧 4096/8192 字节阈值是早期列表限 8 项时留下的遗留值，放开列表条数后未同步调整，且单条列表项仅限 384 字节（约 128 字），超限报错也不换算中文字数与分节规模。
2. `tracking_commit.py draft` 只在单行 stdout JSON 的 `current_snapshots` 中返回上一章 `context.active_character_names` 内的角色：一方面，不在上一章活跃列表里的久别核心角色本章回归并发生变化时，模型既不能读 `_tracking-state.json` 又在 `current_snapshots` 里拿不到其当前快照；另一方面，单角色容量提升后，多达 20 名活跃角色的完整快照全部拼进单行 stdout 会放大每章主会话输出并在 Codex 等宿主触发工具输出截断。
3. `normalize_initial_document`（`init`）未启用 `normalize_transaction` 已有的多字段超长一次性汇总提示，长篇导入一次提交多角色快照时只能逐字段报错重试。

## Decision

- 单角色快照上限对齐按需读取边界：`SNAPSHOT_TARGET_BYTES = 16384`（16 KiB，约 5,300 字，仅提醒且明示不阻断提交），`SNAPSHOT_MAX_BYTES = 65536`（64 KiB，约 21,500 字，容纳单角色 500+ 条有效记录且保证各宿主单次无分页 `Read` 不超 25K tokens 上限）；角色快照四列表单项上限设为 `SNAPSHOT_ITEM_MAX_BYTES = 600`（约 200 字），`DRAFT_LIMITS` 与超限报错补齐中文字数与四节条目统计。
- 独立保留热上下文与单章增量预算：`CONTEXT_TARGET_BYTES = 8192`、`CONTEXT_MAX_BYTES = 12288`、`ACTIVE_CHARACTER_MAX = 20`、`DELTA_TARGET_BYTES = 1536`、`DELTA_MAX_BYTES = 3072`、快照四个单句字段上限与 `TRACKING_SCHEMA_VERSION = 4` 均保持不变。
- `tracking_commit.py draft` 将 `state["characters"]` 中全部核心角色（含在场与非在场）的当前快照写入本章工作目录 `.story/work/第NNN章/snapshots/{角色名}.json`，在 stdout 返回 `snapshot_files` 映射（由 `storyctl.py chapter commit` 随本章工作目录一并清理）；stdout 的 `current_snapshots` 设 `DRAFT_INLINE_SNAPSHOTS_MAX_BYTES = 16384` 内联预算，超出部分列入 `omitted_active_snapshots` 并在 `fill` 指路文件读取；更新既有核心角色时若把原本非空的 `abilities_resources`、`relationships`、`knowledge` 清空为空列表，输出非阻断 `WARNING` 防误覆盖。
- `normalize_initial_document` 启用 `_LENGTH_ISSUES` 汇总，一次报出 `init` 全部超长字段的字数差额。
- 经 `sync-shared-assets.py` 与 `shared-references.py` 同步 `story-long-write`、`story-import`、`story-review` 脚本和 `tracking-transaction.md`，同步更新 `import-tracking.md`、`character-state-reverse.md`（说明截至当前章的有效状态与 `逐章记录/` 逐章经过的分工，同时保证完整有效状态可正常落盘）。

## Alternatives considered

- **仅将 `SNAPSHOT_MAX_BYTES` 简单翻倍到 16384**：最强理由是只改一个常量、风险极小。不采用：16 KiB 仅约 5,300 中文字，几百章规模的仙侠、悬疑、群像主角在中后期仍会再次超限失败。
- **完全删除 `SNAPSHOT_MAX_BYTES` 硬上限**：最强理由是同属按需视图的 `伏笔.md` 与 `时间线/` 没有文件总字节硬上限。不采用：`story-explorer`、`consistency-checker` 与主会话对 `追踪/角色状态/{角色名}.md` 均采用整文件直接 `Read`；若模型异常复读塞入上百 KB 文本，超过宿主单次 `Read` 的 25K tokens 限制会导致下游查询与一致性审查直接报错中断，64 KiB 已覆盖千章单角色 500+ 条目且守住单次可读边界。
- **引入自动归档/摘要拆分或数据库存储**：最强理由是理论上不受单文件体积限制。不采用：自动改写或截断角色状态会破坏“角色本人已知 vs 作者真相”等精确叙事事实，拆分多文件或引入新存储会破坏既有只读查询协议与零外部依赖约束。
- **顺手放大 `CONTEXT_MAX_BYTES`（12288）**：最强理由是数值上与旧快照上限接近。不采用：`上下文.md` 每章必读且只拼活跃角色的身份、状态、目标三个短句，根本不含快照的四个列表，放大它只会无谓增加每章热上下文开销。

## Consequences

- 收益：核心角色在数百至上千章连载与长篇导入中可完整保存能力资源、关系、已知信息与未结事项；久别核心角色回归变化与大快照场景下 `draft` 不再缺快照或撑爆 CLI 单次输出；存量项目零迁移直接兼容。
- 代价：`draft` 在存在核心角色时会在 `.story/work/第NNN章/snapshots/` 下生成临时单角色 JSON（`storyctl.py` 提交后自动删除；直接调 `tracking_commit.py commit` 的审稿场景留在隐藏工作目录 `.story/work/` 内，不影响书目录与守卫）；单角色超过 64 KiB（约 2.15 万字）的极端异常输入仍会被写盘前拒绝。
