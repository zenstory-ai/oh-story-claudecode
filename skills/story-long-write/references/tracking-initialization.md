# 追踪初始化事务

## 初始化事务

新书从第 0 章初始化。`story-import` 导入已有小说时把最后完整章写入 `last_chapter=N`；第 1..N 章不伪造日更记录，常规续写从 N+1 章开始。

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

导入初始化时直接传入当前核心角色快照、伏笔当前行、时间线事件和固定 7 栏状态输入。阶段/卷级回看按需查询正文，不作为每章强一致追踪产物。
