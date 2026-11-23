# story-review：审查收尾的追踪文件维护

追踪维护一律通过本 skill 的 `scripts/tracking_commit.js`（Node.js 18+）以结构化 JSON 事务提交。**仅 full / lean 模式可维护 `追踪/`；solo 模式不改任何追踪文件。**禁止直接 Edit/Write/追加 `伏笔.md`、角色快照、时间线、逐章记录或 `上下文.md`。

## 执行步骤

1. **先检查状态**：执行 `node scripts/tracking_commit.js check --project {项目根}`（需严格拦截派生视图漂移加 `--strict`）。返回 `drift_warnings`（exit 0）说明派生 Markdown 被手工改过，先确认吸回修订还是按 `_tracking-state.json` 重建；exit 2 时按下方错误处理。
2. **判定是否修订**：只有正文证据表明现有追踪事实错漏（过期伏笔、漏登开放钩子、角色状态、客观时间线、读者认知）时才维护，归入证据所在章的 `mode=revision` 事务。审查意见与写作建议不进追踪。
3. **起草并补全同章事务**：执行 `node scripts/tracking_commit.js draft --project {项目根} --chapter {N}`，草稿预填至 `.story/work/第NNN章/tracking.json`（同时导出全部角色快照到 `snapshots/`）。保留原记录中仍成立项，仅修正有正文证据的变化；角色/伏笔/时间线/上下文均提交截至最新已写章的完整当前值。
4. **提交并复检**：执行 `node scripts/tracking_commit.js commit --project {项目根} --input {事务文件}`，随后再跑 `check --project {项目根}` 确认无 `drift_warnings` 且全部自动生成视图与 state 一致。
5. **正文已改过时的出口**：若提交报「字数出了作者范围」，不重试、不改字数记录，把待修事实写进报告「需要你决定」，请作者在 `/story-long-write` 说「修改第N章」并同步重提交追踪。

## `mode=revision` 事务字段与约束

- 顶层必填：`schema_version`（1）、`mode`（`"revision"`）、`chapter`、`chapter_title`、`expected_state_revision`（取当前 `state_revision`，`draft` 自动预填）、`delta`、`context`、`character_snapshots`。不写 `wordcount`。
- `delta`：`result`、`character_changes`、`foreshadow_changes`（同 ID `upsert` 当前状态，不增重复行）、`timeline_events`（`action` 为 `upsert/delete`，`未揭示` 的 `reveal_chapter` 必须为 `null`）、`constraints`、`next_chapter_commitments`。**revision 事务不可提交 `retired_characters` 或 `retired_context_items`。**
- `context`：只交 4 项——`position`、`long_term_constraints`（建议 ≤6 条）、`active_character_names`（建议 ≤20 人，须已有快照）、`continuity_risks`（建议 ≤5 条）；不手填 `recent_chapters` 或 `next_chapter_commitments`（工具自动算出，手填报 exit 2）。
- `character_snapshots`：核心复用角色须同时出现在 `character_changes`，并在既有快照上交完整新快照；临时角色只写 `character_changes`。

## 体积上限与错误处理

- 逐章记录目标 ≤1536 字节（约 512 字，软上限 3072 字节 / 约 1024 字）、`上下文.md` 建议 ≤12288 字节（超限只出 `warnings`），单视图安全硬上限 65536 字节。`上下文.md` 由 state 自动生成固定 7 栏：`当前位置`、`长期约束`、`核心角色状态`、`活跃伏笔`、`近三章速记`、`下一章承诺`、`连贯性风险`。
- 遇 `chapter delta N already exists with different content`：通常是手写逐章记录冲突，删掉手写文件后重跑事务。
- 视图与 state 不一致时，用新的同章 `mode=revision` 事务重建，不重跑已清理的旧输入，也不手改自动生成的 Markdown。
