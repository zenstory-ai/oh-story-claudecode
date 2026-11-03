# 追踪初始化事务

> 谁读：还没有追踪状态、要初始化时读（新书写第 1 章前）。

## 初始化事务

仅尚无追踪状态时初始化。新书从第 0 章开始：把下面的 JSON 写到 `{书目录}/.story/work/init.json`，跑 `{PYTHON} {skill 根}/scripts/tracking_commit.py init --project {书目录} --input {书目录}/.story/work/init.json`，成功后删掉临时文件。`story-import` 导入已有小说时把最后完整章写入 `last_chapter=N`；第 1..N 章不伪造日更记录，常规续写从 N+1 章开始。

```json
{
  "schema_version": 1,
  "book_title": "让你管账号，你高燃混剪炸全网",
  "last_chapter": 0,
  "context": {
    "position": {
      "volume": "第一卷·军宣整顿",
      "volume_start_chapter": 1,
      "story_time": "江晨到火箭军文工团报到前",
      "scene": "火箭军文工团"
    },
    "long_term_constraints": ["军宣爽点要用作品效果和围观反应链兑现，不能只靠系统播报"],
    "active_character_names": [],
    "continuity_risks": [],
    "recent_chapters": [],
    "next_chapter_commitments": ["让江晨报到，并落下五天百万粉的新手任务"]
  },
  "character_snapshots": {},
  "foreshadow": [],
  "timeline_events": []
}
```

导入示例须按已读正文改写当前状态，不能照用第 0 章内容；全部导入批次完成后初始化一次，不重置已有 state。传入当前核心角色快照、伏笔当前行、时间线事件与 JSON 中六项 context 输入，由脚本生成七栏 `追踪/上下文.md`。阶段/卷级回看按需查询正文，不作为每章强一致追踪产物。
