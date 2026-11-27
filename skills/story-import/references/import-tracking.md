# 追踪初始化与核心角色快照反推（仅长篇）

Phase 4 完整读取本文件。截止章、残稿决定与卷划分取自导入记录；证据取自 `拆文库/{导入书名}/`（`角色/*.md`、`角色/角色关系.md`、`章节/第N章_摘要.md`、`剧情/*.md`）与项目 `大纲/`，不重读原文。

**强制规则**：必须通过 `scripts/tracking_commit.js init` 一次性生成 `追踪/`，禁模型手写追踪文件；已有 `_tracking-state.json` 时禁再次 `init`（旧追踪无此 JSON 时，`init` 自动原样归档至 `追踪/_旧追踪存档/`）。

## 一、反推与初始化步骤

1. **截止章 `last_chapter`**：填最后完整章 `N`（写入 `imported_through_chapter=N`），第 1..N 章不伪造日更记录，续写从 N+1 起；末章残稿时快照/伏笔/时间线均截至残稿前完整章，残稿决定入 `continuity_risks`。
2. **核心角色快照 `character_snapshots`**：只为主角、反派、核心配角建独立快照（临时路人不建），截至第 N 章归并为当前值：`identity`、`location`、`goal`、`state`、`abilities_resources`、`relationships`、`knowledge`（本人已知，禁混作者真相）、`open_threads`（有正文证据的未结事项）。
3. **伏笔 `foreshadow`**：仅提取有正文证据的伏笔，每 ID 一行：`id`（`F001`）、`status`（`已埋/已回收/已过期/放弃`）、`importance`（`高/中/低`）、`planted_chapter ≤ N`。
4. **时间线 `timeline_events`**：明确日期直记，推断标 `[推断]`，无参照写「时间未明」；同记 `objective_fact` 与 `reader_knowledge`，`reveal_status` 取 `未揭示`（`reveal_chapter: null`）/`部分揭示`/`已揭示`（禁把未来揭示写既成事实）。
5. **续写状态卡 `context`**：填 `position`、`long_term_constraints`、`active_character_names`、`continuity_risks`、`recent_chapters`（≤3 章升序）、`next_chapter_commitments`，由脚本生成固定 7 栏 `追踪/上下文.md`。
6. **执行**：事务写 `{书目录}/.story/work/init.json`（不写 `/tmp` 或书根），Node 18+ 运行：

```text
node {story-import skill 根}/scripts/tracking_commit.js init --project {书目录} --input {书目录}/.story/work/init.json
node {story-import skill 根}/scripts/tracking_commit.js check --project {书目录} [--strict]
```

## 二、初始化事务格式与容量规则

`init.json` 结构（按已读正文填，禁照搬占位）：

```json
{
  "schema_version": 1, "book_title": "{书名}", "last_chapter": 10,
  "context": {
    "position": {"volume": "第一卷", "volume_start_chapter": 1, "story_time": "{时间}", "scene": "{场景}"},
    "long_term_constraints": ["{长期约束}"], "active_character_names": ["{主角}"], "continuity_risks": [],
    "recent_chapters": [{"chapter": 10, "summary": "{近章摘要}"}], "next_chapter_commitments": ["{下章承诺}"]
  },
  "character_snapshots": {"{主角}": {"identity": "", "location": "", "goal": "", "state": "", "abilities_resources": [], "relationships": [], "knowledge": [], "open_threads": []}},
  "foreshadow": [{"id": "F001", "summary": "", "planted_chapter": 10, "planned_resolution_chapter": null, "status": "已埋", "importance": "中"}],
  "timeline_events": [{"id": "E001", "story_time": "", "objective_fact": "", "reader_knowledge": "", "reveal_status": "已揭示", "reveal_chapter": 10, "characters": ["{主角}"]}]
}
```

**容量**：软提醒（`warnings`，不阻断）——角色列表单项 ≤600B、单角色快照 ≤16384B、`active_character_names`（仅下章活跃且已有快照者）≤20 人、`long_term_constraints` ≤6 条、`上下文.md` ≤12288B（固定 7 栏，活跃伏笔 ≤8 条）；单视图硬上限 **65536B**（超限拒绝写入）。报错改 `init.json` 重跑。

## 三、验收

成功后生成 `追踪/`（`_tracking-state.json`、`上下文.md`、空目录 `逐章记录/`、`角色状态/{名}.md`、`伏笔.md`、`时间线/{作者真相,读者已知}.md`）：

- [ ] `tracking_commit.js check` 通过且无 `drift_warnings`（严格核查加 `--strict`）
- [ ] `imported_through_chapter` = 最后完整章，残稿未提前生效；`逐章记录/` 为空
- [ ] 核心角色快照齐全且 `knowledge` 无作者真相；`伏笔.md` 每 ID 至多一行；`读者已知.md` 无真相泄露；`上下文.md` 固定 7 栏

通过后勾「追踪初始化」，`init.json` 可删；按 [SKILL.md 的换上下文规则](../SKILL.md#时刻表与交接) 建议新开对话。
