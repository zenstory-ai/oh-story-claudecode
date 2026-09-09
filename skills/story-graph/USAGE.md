# 叙事知识图谱 — 完整使用指南

## 一、系统概述

知识图谱增强系统用 SQLite 图数据库管理故事的人、地、事、物、组织及其关系，提供传统文件读取做不到的多跳查询、时间切片、钩子雷达和因果链遍历。

**查询入口统一**：图谱查询能力并入 **story-explorer**（图谱增强版）——story.db 存在时内部走图查询，不可用时自动降级读文件，两种来源输出同一套 schema。写作流程、路由不需要感知图谱是否存在。

**和现有追踪/文件的关系**：增强，不是替代。`追踪/伏笔.md`、`追踪/时间线.md`、`追踪/角色状态.md` 照常更新（文件是权威源），图是额外的查询加速层；钩子数据由 `sync-hooks` 从 `追踪/伏笔.md` 同步进图。

---

## 二、安装（只需一次）

### 前提

写作项目已运行过 `/story-setup`（`.claude/agents/` 和 `.claude/hooks/` 已存在）。

### 步骤

```bash
# 1. 从 oh-story-claudecode 仓库复制 story-graph skill 到写作项目
#    （项目技能统一位于 .claude/skills/，与 story-setup 部署布局一致）
cp -r <oh-story-claudecode路径>/skills/story-graph/ <写作项目>/.claude/skills/story-graph/

# 2. 进入写作项目，运行部署
cd <写作项目>
bash .claude/skills/story-graph/scripts/deploy-graph.sh
```

部署脚本自动完成：

| 操作 | 细节 |
|------|------|
| Skill 注册 | 自动识别项目技能形态：链接形态（`.claude/skills/{name}` 是符号链接、真实文件在 `.agents/skills/`）时，真实文件复制到 `.agents/skills/story-graph/`，`.claude/skills/story-graph` 建同款符号链接；真实目录形态直接复制 → `/story-graph` 命令可用（需新开会话） |
| Agent 部署 | `graph-builder.md` + `story-explorer.md`（图谱增强版）→ `.claude/agents/`（覆盖 story-setup 同名 agent；**重跑 story-setup 后 story-explorer 会恢复为无图版本，需重跑本部署**） |
| Hook 部署 | `session-start-graph.sh` + `graph-update-check.sh` + `story_graph_cli.js` + `story_graph_core.js` + `viz_html.js` → `.claude/hooks/` |
| Hook 注册 | 合并到 `.claude/settings.local.json`（按 command 去重，不覆盖用户已有配置） |
| .gitignore | 添加 `story.db` / `story.db-wal` / `story.db-shm` |
| CLAUDE.md | 注入「知识图谱」段（写作循环自动走图的说明） |
| 依赖 | `npm install better-sqlite3 --no-save` 装进 **skill 真实目录**的 `node_modules`（项目根保持干净；`story_graph_core.js` 按部署拓扑自动解析） |
| 写作流程收口 | `patch-long-write.js`（幂等）给已部署 story-long-write 注入图谱更新步骤：SKILL.md 单章流程 12b（写完即 update）+ workflow-daily.md 批末收尾（一次更新本批全部章节）；hook 提示降级为兜底 |

### 3. 新开会话

部署后必须新开 Claude Code 会话，让 agents 和 hooks 注册生效。

---

## 三、开书时：构建初始知识图谱

### 时机

完成 `/story-setup` 和 `/story-graph setup` 后，设定和大纲已写好，正文还没开始写。

### 执行

```
/story-graph seed
```

**内部流程**：
1. graph-builder agent（Sonnet）被 spawn
2. 并行读取 `设定/角色/*.md`、`设定/势力/*.md`、`设定/世界观/*.md`
3. 读取 `设定/关系.md` 提取人物关系
4. 读取 `大纲/卷纲_*.md`、`大纲/细纲_*.md` 提取事件和章节点
5. 读取 `追踪/伏笔.md` → `sync-hooks` 同步 HOOK 节点与 PLANTS_IN 边
6. 写入 `story.db`，`stats` 验证

**输出示例**：
```
知识图谱已初始化:
  节点: 67个（PERSON: 8, LOCATION: 5, EVENT: 30, ITEM: 3, ORG: 2, CHAPTER: 15, TIME_POINT: 4）
  边:   120条（NARRATES: 30, PARTICIPATES_IN: 45, KIN_TO: 5, ALLIED_WITH: 3, ...）
  数据库: 故事名/story.db
```

### 如果已有正文

如果项目已经写了很多章再启用图谱，seed 会从设定文件构建初始骨架，然后需要逐章跑 `/story-graph update` 把正文章节的事件数据追加进去。

---

## 四、日更写作时：增量更新

### 自动触发（推荐）

正文落盘后触发图更新（**写作流程已收口**，hook 只是兜底）：

1. **主触发（写作流程内）**：部署时 `patch-long-write.js` 已把图更新注入写作流程 —— 单章场景在 SKILL.md Step 12b 写完即执行 `/story-graph update`；日更批量在 workflow-daily.md 批末收尾一次更新本批全部章节。
2. **兜底提醒（hook）**：正文落盘后 `graph-update-check.sh` 自动检测并提示：

```
📊 知识图谱需更新 — 第25章已写入。
  当前图谱: 89节点/178边
  请运行 /story-graph update 将新章实体和事件增量写入图谱。
```

看到此提示说明写作流程的图更新步骤被跳过或尚未执行，执行 `/story-graph update` 即可（幂等）。

### 手动触发

```
/story-graph update
```

**内部流程**：
1. graph-builder agent 被 spawn，模式: update
2. 读取最新章正文 + 细纲 + `追踪/伏笔.md`
3. 增量提取新事件、新实体、角色状态变更、新埋设钩子
4. 查重（已有实体不重复创建）
5. 写入 staging → 验证 → commit
6. `sync-hooks` 同步 `追踪/伏笔.md`（已埋→dormant、已回收→resolved、废弃→abandoned，幂等）
7. 钩子雷达扫描 → 自动触发/解决符合条件的钩子 + 依赖环检测
8. 清理 `.claude/.graph-update-pending` 标记（session-status 下次会话也会自愈清理）
9. 导出文本快照到 `设定/知识图谱快照/`

**输出示例**：
```
知识图谱已更新:
  处理章节: 第24-25章
  新增: +8节点（EVENT: 6, ITEM: 1, TIME_POINT: 1）
  新增: +15边（NARRATES: 6, PARTICIPATES_IN: 7, CAUSES: 2）
  钩子: H_玉佩秘密 已触发（第25章，评分85）
  快照: 设定/知识图谱快照/snapshot-20260725-103000/
```

---

## 五、写作中查询

### 通过 story-explorer agent（日常使用）

写作时，当你问这些问题，AI 会自动 spawn story-explorer agent（Haiku，只读）。story-explorer 是图谱增强版：story.db 存在时内部通过 `story_graph_cli.js` 走图查询（下述类型全部可用），图不可用时自动降级读文件 —— **写作流程、路由、schema 都不需要感知图谱是否存在**：

| 你的问题 | 查询类型 | 示例 |
|---------|---------|------|
| "沈栀现在在哪？有什么物品？" | time_slice / character_status | 返回时间点完整状态 |
| "第25章可以触发哪些钩子？" | hook_radar | 返回匹配钩子列表+建议 |
| "发现玉佩这件事导致了什么？" | causal_chain | 沿因果边遍历 |
| "沈栀怎么知道陆衍止身份的？" | knowledge_gap | 追溯知识来源链 |
| "沈栀和陆衍止之间什么关系？" | shortest_path | 最短关系路径 |
| "第20-30章按时间线发生了什么？" | timeline / state_window | 时间线事件序列 |
| "本章有没有该解释的因果缺口？" | flashback_opportunities | 闪回/叙事债务建议 |
| "故事时间里有哪些空白？" | time_gaps | 可插入新内容的区间 |
| "帮我准备写第30章的上下文" | context_load | 进度/钩子/时间线走图 + 细纲与上一章读文件 |

### 降级安全

如果 `story.db` 不存在或为空，story-explorer **自动降级为读文件**（`追踪/` + `设定/`），标注 `"source": "fallback: file-read"`。不会报错。两种来源输出同一套 schema，图数据与文件冲突时以文件为准。

### 手动 CLI 查询

```bash
cd <写作项目>

# 时间切片
node .claude/hooks/story_graph_cli.js state-at-time <书名>/story.db P_沈栀 T_星辰历1025年春

# 钩子雷达
node .claude/hooks/story_graph_cli.js hook-radar <书名>/story.db '["P_沈栀","I_玉佩"]' L_断魂崖 T_星辰历1025年秋 25

# 图统计
node .claude/hooks/story_graph_cli.js stats <书名>/story.db
```

---

## 六、钩子管理

### 自动管理（增量更新时）

graph-builder 的增量更新会自动执行：

- **同步**：`sync-hooks` 从 `追踪/伏笔.md` 幂等同步（已埋→dormant、已回收→resolved、废弃→abandoned），`追踪/伏笔.md` 是钩子状态的权威源
- **触发**：评分≥70 的 dormant 钩子 → `triggered`
- **解决**：谜底在本章揭示 → `resolved`
- **告警**：超过 50 章未触发 → 标记建议废弃
- **依赖环检测**：创建 PREREQUISITE_FOR 边前自动检查

### 手动管理

```bash
# 从 追踪/伏笔.md 手动同步（幂等）
node .claude/hooks/story_graph_cli.js sync-hooks <书名>/story.db <书名>/追踪/伏笔.md

# 查看所有钩子状态
node .claude/hooks/story_graph_cli.js hook-summary <书名>/story.db

# 手动触发
node .claude/hooks/story_graph_cli.js trigger-hook <书名>/story.db H_玉佩秘密 25

# 手动解决
node .claude/hooks/story_graph_cli.js resolve-hook <书名>/story.db H_玉佩秘密 30

# 废弃
node .claude/hooks/story_graph_cli.js abandon-hook <书名>/story.db H_废弃伏笔 "主线已改，此伏笔作废"
```

---

## 七、快照审阅

每次 `/story-graph update` 自动导出文本快照到 `设定/知识图谱快照/snapshot-{timestamp}/`。

```bash
# 也可手动导出
node .claude/hooks/story_graph_cli.js export-snapshot <书名>/story.db 设定/知识图谱快照/snapshot-manual/
```

导出文件纯文本、按行结构化，`git diff` 直接可读：

```
设定/知识图谱快照/snapshot-20260725-103000/
├── nodes_person.txt        ← "P_沈栀 | 沈栀 | active | role=protagonist"
├── nodes_event.txt         ← 按时间排序
├── nodes_item.txt
├── nodes_location.txt
├── edges_narrates.txt      ← "第25章 --[NARRATES]--> 沈栀发现密信"
├── edges_causes.txt        ← "发现密信 --[CAUSES]--> 进入秘境"
├── edges_hostile-to.txt
├── timeline_merged.txt     ← 物理+叙事双时间线
└── SUMMARY.md              ← 人类可读摘要（统计+人物+近期事件）
```

---

## 八、完整日更工作流（从开书到日更）

```
┌─ 开书前 ──────────────────────────────────────────────────────────┐
│                                                                     │
│  1. /story-setup              ← 部署写作环境（hooks+agents+rules）   │
│  2. bash .claude/skills/story-graph/scripts/deploy-graph.sh         │
│                                ← 部署知识图谱增强（只需一次）        │
│  3. /story-long-write 开书     ← Phase 1-3：选题→设定→大纲           │
│  4. /story-graph seed         ← 从设定+大纲+伏笔构建初始图谱          │
│                                                                     │
├─ 日更循环 ──────────────────────────────────────────────────────────┤
│                                                                     │
│  5. /story-long-write 日更     ← Phase 4：写正文（2-3章）            │
│  6. 批末自动 /story-graph update ← 流程已收口（增量+钩子同步+快照）   │
│     （hook 的 📊 提示仅是兜底提醒）                                  │
│  7. 继续写...                 ← 查询时 story-explorer 自动走图/文件  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 九、命令速查

| 命令 | 功能 | 谁执行 |
|------|------|--------|
| `/story-graph setup` | 部署知识图谱增强系统 | 一次性 |
| `/story-graph seed` | 从设定+大纲+`追踪/伏笔.md`（钩子）全量构建图 | 开书时 |
| `/story-graph update` | 增量更新新章（含钩子同步与生命周期扫描） | 日更后（可自动） |
| `/story-graph`（裸调用） | 显示图统计+可用操作 | 随时 |
| （自然语言查询） | 角色状态/钩子/因果链/时间线 | story-explorer 自动处理（图优先，文件降级） |

---

## 十、常见问题

**Q: story.db 被误删了怎么办？**
A: 重新运行 `/story-graph seed` 重建。设定文件和正文都在，不会丢数据。

**Q: 重跑 /story-setup 会破坏图增强吗？**
A: 部分会。`settings.local.json` 按 command 去重合并、CLAUDE.md 按 section 合并，graph hooks 和 CLAUDE.md 段不受影响；但 `/story-setup` 会把它管理的 **story-explorer.md 覆盖回无图版本**（graph-builder.md 不受影响）。重跑 story-setup 后需**重跑一次部署脚本**恢复图谱增强版 story-explorer。

**Q: better-sqlite3 装不上？**
A: 部署脚本会把它装进 skill 真实目录的 `node_modules`（`.claude/skills/story-graph/` 或 `.agents/skills/story-graph/`），不需要项目根有 package.json。若安装失败，手动执行：
```bash
cd <写作项目>/.claude/skills/story-graph   # 链接形态项目用 .agents/skills/story-graph
npm install better-sqlite3 --no-save
```
如果没有 Node.js，先装 Node.js。

**Q: 知识图谱和追踪/文件的数据不一致怎么办？**
A: 文件的更新（Phase 4 Step 12）和图更新（`/story-graph update`）是独立路径。图是查询加速层，以文件为权威。如有不一致，以文件为准，重新 seed 即可。

**Q: 短篇能用吗？**
A: 短篇也可以。seed 从设定+大纲构建，update 从正文.md 增量更新。但短篇章节少、数据稀疏，图的多跳查询优势不如长篇明显。

**Q: 多书切换时怎么处理？**
A: 图谱数据库是按书存放的（`{书名}/story.db`）。不同书有独立的图（连接按路径隔离，同进程多书不串库）。活跃书发现走回退链：`.active-book` 首行 → 找 `追踪/` 目录（长篇）→ 找 `正文/` → 找 `正文.md`（短篇）；`.active-book` 为空或指向失效目录时自动回退，不会把项目根误当书目录。
