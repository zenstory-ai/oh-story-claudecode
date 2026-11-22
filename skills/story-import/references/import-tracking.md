# 追踪初始化与核心角色快照反推（仅长篇）

Phase 4 完整读取本文件。截止章、残稿决定与卷划分取自导入记录；证据取自 `拆文库/{导入书名}/`（`角色/*.md`、`角色/角色关系.md`、`章节/第N章_摘要.md`、`剧情/*.md`）与项目 `大纲/`，不重读原文。

**强制规则**：必须通过 `scripts/tracking_commit.js init` 一次性生成 `追踪/`，禁模型手写追踪文件；已有 `_tracking-state.json` 时禁再次 `init`（旧追踪无此 JSON 时，`init` 自动原样归档至 `追踪/_旧追踪存档/`）。

## 一、反推与初始化步骤

1. **截止章 `last_chapter`**：填最后完整章 `N`（写入 `imported_through_chapter=N`），第 1..N 章不伪造日更记录，续写从 N+1 起。最后一章为残稿时，所有快照与伏笔时间线一律截至残稿前最后完整章，残稿决定写入 `continuity_risks`。
2. **核心角色快照 `character_snapshots`**：只为主角、反派、核心配角建独立快照（临时路人不建）。截至第 N 章归并为当前值（历史弧线留 `设定/角色/`）：`identity`（当前身份）、`location`（最后落点）、`goal`（当前目标）、`state`（影响续写的状态）、`abilities_resources`（当前能力/物品/人脉）、`relationships`（复用角色当前关系）、`knowledge`（本人已知，禁混作者真相）、`open_threads`（有正文证据的未结事项，未来设计留大纲）。
3. **伏笔 `foreshadow`**：从有正文证据的铺垫、部分揭示、关键物品首现、角色秘密与章尾悬念提取；每 ID 仅留当前一行，未埋设计留大纲。`id` 如 `F001`，`status` 取 `已埋/已回收/已过期/放弃`（后续实际回应才判已回收；断点前未回应可注「接近断点」），`importance` 取 `高/中/低`，`planted_chapter ≤ N`。
4. **时间线 `timeline_events`**：明确日期直记，相对时间有参照才推算，无参照写「时间未明」，推断标 `[推断]`。`id` 如 `E001`，同记 `objective_fact` 与 `reader_knowledge`；`reveal_status` 取 `未揭示`（`reveal_chapter` 为 `null`）/ `部分揭示` / `已揭示`（仅填已发生章号），禁将未来揭示写成既成事实。
5. **续写状态卡 `context`**：填六项（`position`、`long_term_constraints`、`active_character_names`、`continuity_risks`、`recent_chapters` 最多 3 章升序、`next_chapter_commitments`），由脚本生成固定 7 栏 `追踪/上下文.md`。
6. **执行**：事务写入 `{书目录}/.story/work/init.json`（不写 `/tmp`、书根、`大纲/`、`正文/`），Node.js 18+ 运行：

```text
node {story-import skill 根}/scripts/tracking_commit.js init --project {书目录} --input {书目录}/.story/work/init.json
node {story-import skill 根}/scripts/tracking_commit.js check --project {书目录} [--strict]
```

## 二、初始化事务示例与容量规则

下例取自 demo 第 10 章（实际导入须按已读正文改写，禁照搬）：

```json
{
  "schema_version": 1,
  "book_title": "让你管账号，你高燃混剪炸全网",
  "last_chapter": 10,
  "context": {
    "position": {"volume": "第一卷·军宣整顿", "volume_start_chapter": 1, "story_time": "实弹训练两天后", "scene": "火箭军文工团看片会"},
    "long_term_constraints": ["军宣爽点须用作品效果与围观反应链兑现"],
    "active_character_names": ["江晨"],
    "continuity_risks": [],
    "recent_chapters": [{"chapter": 10, "summary": "专业重拍版缺灵魂，高层拍板用回手机原版"}],
    "next_chapter_commitments": ["推进五天百万粉任务结算"]
  },
  "character_snapshots": {
    "江晨": {
      "identity": "火箭军文工团宣传兵；军宣爆款创作者",
      "location": "文工团高层看片会",
      "goal": "完成五天百万粉任务",
      "state": "军内认可持续抬升",
      "abilities_resources": ["前世 MCN 运营经验", "《中国军魂》伴奏", "大师级导演能力"],
      "relationships": ["钟嘉嘉供军报资源", "周薄森、张耀祖认可其创作"],
      "knowledge": ["《军报》采访稿过审", "高层决定沿用原版"],
      "open_threads": ["百万粉任务待结算", "钟嘉嘉「只猜对一半」未解"]
    }
  },
  "foreshadow": [{"id": "F027", "summary": "专业团队拍不出原版灵魂", "planted_chapter": 10, "planned_resolution_chapter": null, "status": "已埋", "importance": "中"}],
  "timeline_events": [{"id": "E010", "story_time": "实弹训练两天后", "objective_fact": "高层否决重拍版，沿用手机原版", "reader_knowledge": "读者已见高层当场拍板用回原版", "reveal_status": "已揭示", "reveal_chapter": 10, "characters": ["江晨", "周薄森", "张耀祖"]}]
}
```

**容量**：软提醒（`warnings`，不阻断）——角色列表单项 ≤600B、单角色快照 ≤16384B、`active_character_names`（仅下章活跃且已有快照者）≤20 人、`long_term_constraints` ≤6 条、`上下文.md` ≤12288B（固定 7 栏，活跃伏笔 ≤8 条）；单视图硬上限 **65536B**（超限拒绝写入）。报错改 `init.json` 重跑。

## 三、验收

成功后生成 `追踪/`（`_tracking-state.json`、`上下文.md`、空目录 `逐章记录/`、`角色状态/{名}.md`、`伏笔.md`、`时间线/{作者真相,读者已知}.md`）：

- [ ] `tracking_commit.js check` 通过且无 `drift_warnings`（严格核查加 `--strict`）
- [ ] `imported_through_chapter` = 最后完整章，残稿未提前生效；`逐章记录/` 为空
- [ ] 核心角色快照齐全且 `knowledge` 无作者真相；`伏笔.md` 每 ID 至多一行；`读者已知.md` 无真相泄露；`上下文.md` 固定 7 栏

通过后勾「追踪初始化」，`init.json` 可删；按 [SKILL.md 的换上下文规则](../SKILL.md#时刻表与交接) 建议新开对话。
