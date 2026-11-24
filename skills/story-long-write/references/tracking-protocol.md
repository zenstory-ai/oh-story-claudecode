# 项目目录、追踪初始化与事务协议（tracking-protocol）

> 谁读：新书写第 1 章初始化追踪、目录缺失排查，或 `tracking_commit.js` / `storyctl.js` 报错时读；常规写章不预读。

## 一、长篇项目目录树

只讨论不建工程；规划阶段只建 `设定/` 与 `大纲/`，**首次写正文前才建 `追踪/`**。

```text
{书名}/
├── 设定/           # 题材定位.md、全书梗概.md、关系.md、文风.md(可选)、角色/、势力/、世界观/
├── 大纲/           # 大纲.md、卷纲_第X卷.md(走 outline_view.js 取段)、细纲_第XXX章.md
├── 正文/           # 第XXX章_章名.md（写完直接落盘）
├── 对标/{书名}/    # 从 拆文库/ 复制的章节、角色、剧情、设定、文风.md、拆文报告.md
├── 追踪/           # _tracking-state.json(主数据)、上下文.md(7栏)、逐章记录/、角色状态/、伏笔.md、时间线/
└── .story/         # 排纲笔记/{剧情段编号}.md、work/第NNN章/(临时文件，提交后自动删除)
```

## 二、首章追踪初始化（仅 `_tracking-state.json` 不存在时）

新书从 `last_chapter: 0` 初始化：将下面 JSON 写入 `{书目录}/.story/work/init.json`，跑 `node {skill 根}/scripts/tracking_commit.js init --project {书目录} --input {书目录}/.story/work/init.json`，成功后删临时文件（导入小说填 `last_chapter: N` 与实际状态）。

```json
{
  "schema_version": 1, "book_title": "示例书名", "last_chapter": 0,
  "context": {
    "position": { "volume": "第一卷", "volume_start_chapter": 1, "story_time": "开篇时间", "scene": "开篇地点" },
    "long_term_constraints": ["全书核心约束"], "active_character_names": [],
    "continuity_risks": [], "recent_chapters": [], "next_chapter_commitments": ["第1章核心动作与钩子"]
  },
  "character_snapshots": {}, "foreshadow": [], "timeline_events": []
}
```

## 三、常用脚本命令与状态码（Node.js 18+）

```text
node {skill 根}/scripts/tracking_commit.js init   --project {书目录} --input {书目录}/.story/work/init.json
node {skill 根}/scripts/tracking_commit.js check  --project {书目录} [--strict]
node {skill 根}/scripts/tracking_commit.js draft  --project {书目录} --chapter {N} [--allow-gap]
node {skill 根}/scripts/storyctl.js chapter check  --project {书目录} --chapter {N} [--fix-punctuation] [--plain] [--min-chars MIN --max-chars MAX]
node {skill 根}/scripts/storyctl.js chapter commit --project {书目录} --chapter {N} --input {书目录}/.story/work/第{NNN}章/tracking.json [--ack <id>:<理由> | --ack-all <理由>] [--allow-gap]
node {skill 根}/scripts/storyctl.js chapter accept-current-length --project {书目录} --chapter {N} --input {书目录}/.story/work/第{NNN}章/tracking.json [--ack <id>:<理由>] [--force]
```

- **`chapter check`**：`ready`（exit 0）/ `review_required`（exit 0，有风格复核项）/ `needs_decision`（exit 0，字数出带，超字附净删区间）/ `blocked`（exit 1，退化或硬伤）/ `invalid`（exit 1）/ `tool_unavailable`（exit 3）。
- **`chapter commit`**：有未确认 `review_required` 报 `REVIEW_ACK_REQUIRED`，改净或附 `--ack <id>:<理由>` / `--ack-all <理由>`；带外字数可 `--ack length:<理由>` 或走 `accept-current-length`（低于目标一半报 `BELOW_ACCEPT_FLOOR`，仅作者坚持加 `--force`）。
- **`check` 漂移**：手改派生视图默认 exit 0 报 `drift_warnings`（问作者 `mode=revision` 吸回还是按 JSON 重建），`--strict` 才 exit 2。遇 `chapter delta N already exists with different content` 时删掉手写逐章记录再重跑。

## 四、逐章事务 JSON 与约束

```json
{
  "schema_version": 1, "mode": "append", "chapter": 1, "chapter_title": "章名", "expected_state_revision": 0,
  "delta": {
    "result": "一句话本章结果",
    "character_changes": [{"name": "主角名", "change": "本章净变化"}],
    "foreshadow_changes": [{"action": "upsert", "id": "F001", "summary": "内容", "planted_chapter": 1, "planned_resolution_chapter": null, "status": "已埋", "importance": "中"}],
    "timeline_events": [{"action": "upsert", "id": "E001", "story_time": "时间", "objective_fact": "事实", "reader_knowledge": "读者所知", "reveal_status": "已揭示", "reveal_chapter": 1, "characters": ["主角名"]}],
    "constraints": ["新约束"], "next_chapter_commitments": ["下章承诺"]
  },
  "context": {
    "position": {"volume": "第一卷", "volume_start_chapter": 1, "story_time": "章末时间", "scene": "章末地点"},
    "long_term_constraints": ["全部长期约束"], "active_character_names": ["活跃核心角色"], "continuity_risks": ["连续性风险"]
  },
  "character_snapshots": {
    "主角名": {
      "identity": "身份", "location": "位置", "goal": "目标", "state": "状态",
      "abilities_resources": ["能力/资产"], "relationships": ["关系"], "knowledge": ["已知"], "open_threads": ["未结"]
    }
  }
}
```

- `draft` 自动预填 `expected_state_revision` 并导出角色快照到 `work/第NNN章/snapshots/`；`append` 填 `delta` 与变化快照，`revision` 在预填记录上修订（禁交 `retired_characters`）。
- `context`：`init` 收 6 项；`commit` 只收前 4 项（`recent_chapters`、`next_chapter_commitments` 由脚本算，手填 exit 2）。
- `character_snapshots` 角色须同时在 `character_changes`；`active_character_names` 仅列已有快照者（建议 ≤20）。移除或改写旧约束/风险写 `delta.retired_context_items`（`append`/`revision` 均支持），退场角色写 `delta.retired_characters`（仅 `append`）。
- `timeline_events` 未揭示时 `reveal_chapter` 必须为 `null`；未来计划留大纲不入追踪。单视图硬上限 65536 字节（`上下文.md` 自动生成 7 栏：`当前位置 / 长期约束 / 核心角色状态 / 活跃伏笔 / 近三章速记 / 下一章承诺 / 连贯性风险`）。
