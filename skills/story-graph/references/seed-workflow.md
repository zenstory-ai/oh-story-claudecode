# Graph Builder - Seed 工作流

## Seed 模式：从设定文件全量构建知识图谱

### 概述

Seed 模式从已有项目文件（设定/角色/、设定/势力/、设定/世界观/、设定/关系.md、大纲/）一次性提取所有实体和关系，构建完整的初始知识图谱。

### 适用场景

1. 开书后、正文前——设定和大纲已完成，准备开始正文写作
2. 已有项目首次启用知识图谱——已有大量章节，需要一次性从文件重建图

### 执行方式

Seed 通过 graph-builder agent（Sonnet）执行。主会话 spawn graph-builder agent，传入全量文件内容。

### 输入数据源

按优先级和并行度分三组：

**Group A — 并行读取（独立文件，互不依赖）**:
- `设定/角色/*.md` → PERSON 节点
- `设定/势力/*.md` → ORG 节点
- `设定/世界观/*.md` → LOCATION 节点
- `大纲/卷纲_*.md` → CHAPTER 节点、卷级 EVENT 节点

**Group B — 关系文件（依赖 Group A 的实体 ID）**:
- `设定/关系.md` → KIN_TO / ALLIED_WITH / HOSTILE_TO / ROMANTIC_WITH / MENTOR_OF 边

**Group C — 大纲文件（依赖 Group B 的角色关系）**:
- `大纲/细纲_*.md` → 章节级 EVENT 节点、PARTICIPATES_IN 边、NARRATES 边

### 提取流程

```
Phase 1: 并行读取 Group A 文件
  ├── 角色文件 → 提取：名字、别名、性别、年龄、角色定位、能力、动机、背景知识
  ├── 势力文件 → 提取：名称、类型、首领、总部、成员列表
  ├── 世界观文件 → 提取：地点名称、类型、层级关系
  └── 卷纲文件 → 提取：卷号、章节范围、剧情单元、情绪弧线

Phase 2: 读取关系文件
  └── 关系.md → 按关系类型提取边（人物A --[关系类型]--> 人物B）

Phase 3: 读取细纲文件（可分批处理）
  └── 每章细纲 → 提取：事件摘要、事件类型、参与者、本章角色出场列表

Phase 4: 生成 SQL 并写入
  ├── 生成所有节点 INSERT 语句
  ├── 生成所有边 INSERT 语句
  ├── 分批执行（50条/批）
  └── 提交事务

Phase 5: 验证
  └── node story_graph_cli.js stats <dbPath>
```

### 实体 ID 生成规则

| 节点类型 | ID 格式 | 示例 |
|---------|--------|------|
| PERSON | `P_{角色名}` | `P_沈栀` |
| LOCATION | `L_{地名}` | `L_青云城` |
| EVENT | `E_{章节}_{简短描述}` | `E_003_沈栀发现玉佩` |
| ITEM | `I_{物品名}` | `I_盘龙戒指` |
| ORG | `G_{组织名}` | `G_天机阁` |
| TIME_POINT | `T_{描述}` | `T_星辰历1024年春` |
| CHAPTER | `C_{三位章节号}` | `C_015` |

### 角色关系提取规则

从 `设定/关系.md` 中提取人物关系时，按以下关键词映射边类型：

| 关系描述关键词 | edge_type |
|-------------|-----------|
| 兄弟/姐妹/父子/母女/亲属/血缘 | KIN_TO |
| 盟友/朋友/同盟/合作/伙伴 | ALLIED_WITH |
| 敌对/仇人/宿敌/对手/对立 | HOSTILE_TO |
| 爱慕/暗恋/恋人/夫妻/情侣 | ROMANTIC_WITH |
| 师父/徒弟/老师/学生/导师 | MENTOR_OF |

### 事件提取规则

从大纲/细纲中提取事件时：

**事件类型映射**:
- "冲突/战斗/对抗/对决" → event_type: conflict
- "揭示/发现/得知/真相/秘密" → event_type: revelation
- "转折/变局/逆转/突变" → event_type: transition
- "行动/出发/前往/执行" → event_type: action
- "对话/交谈/谈判/摊牌" → event_type: dialogue
- "升级/突破/觉醒/获得能力" → event_type: state_change

**参与者提取**:
- 细纲的"出场角色"列表 → PARTICIPATES_IN 边
- 每章自动建立 NARRATES 边（CHAPTER → 本章所有 EVENT）

### 验证检查清单

Seed 完成后，graph-builder 必须验证：

1. [ ] 所有 `设定/角色/` 中的角色都已创建 PERSON 节点
2. [ ] 所有 `设定/势力/` 中的组织都已创建 ORG 节点
3. [ ] `设定/关系.md` 中每条关系都有对应的边
4. [ ] 所有 `大纲/细纲_*.md` 中描述的章都有 CHAPTER 节点
5. [ ] 所有章节的出场角色都建立了 PARTICIPATES_IN 边
6. [ ] 节点 ID 无冲突、无重复
7. [ ] properties JSON 格式有效

### 输出格式

Seed 完成后，graph-builder 向主会话返回：

```json
{
  "mode": "seed",
  "status": "completed",
  "db_path": "故事名/story.db",
  "stats": {
    "nodes": { "PERSON": 12, "LOCATION": 8, "EVENT": 45, "ITEM": 5, "ORG": 3, "CHAPTER": 30, "TIME_POINT": 4 },
    "edges": { "total": 156 },
    "relationships": { "KIN_TO": 5, "ALLIED_WITH": 8, "HOSTILE_TO": 3, "ROMANTIC_WITH": 2, "MENTOR_OF": 6 },
    "warnings": []
  },
  "issues": []
}
```
