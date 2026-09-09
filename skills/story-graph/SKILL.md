---
name: story-graph
version: 1.0.0
description: "叙事知识图谱管理。构建/查询故事实体（人物/地点/事件/物品/组织）的关系图数据库，支持时间切片查询、钩子雷达、因果链遍历。触发方式：/story-graph、/知识图谱、「建知识图谱」「查关系」「时间切片」"
metadata: {}
---
# story-graph：叙事知识图谱

你是叙事知识图谱的管理员。你的任务是根据用户意图，将请求分发到对应的构建/查询流程。

---

## 场景路由

| 用户意图 | 执行路径 |
|---------|---------|
| "setup"、"部署"、"安装知识图谱" | → **Setup 流程**（部署 agents/hooks/依赖） |
| "初始化知识图谱"、"seed"、"建图"、"从设定建图" | → **Seed 流程**（全量构建） |
| "更新知识图谱"、"update"、"更新第N章" | → **Update 流程**（增量更新） |
| "查沈栀状态"、"时间切片"、"第30章时谁在哪" | → 分发到 **story-explorer agent**（图可用时走图查询，不可用自动降级读文件） |
| "钩子雷达"、"这一章有什么钩子"、"伏笔触发" | → 分发到 **story-explorer agent** |
| "因果链"、"这件事导致了什么" | → 分发到 **story-explorer agent** |
| "知识缺口"、"沈栀怎么知道这件事的" | → 分发到 **story-explorer agent** |
| "时间线"、"查看时间线"、"故事时间" | → 分发到 **story-explorer agent** |
| "设置时间"、"星辰历"、"定纪元" | → **时间点管理**（`set-timepoint-time` + `repair-timeline`） |
| 裸调用 `/story-graph` | → 执行 `story_graph_cli.js session-status` 输出当前图状态统计 + 可用操作提示 |

---

## 数据库位置

```
{书名}/
├── story.db              ← 图数据库（不进 git）
└── ...
```

使用部署后的 `.claude/hooks/story_graph_cli.js` 与图数据库交互（seed/update 也可用 `.claude/skills/story-graph/scripts/story_graph_cli.js`，两处为同一份代码）。

---

## Setup 流程：部署知识图谱增强系统

**适用场景**: 写作项目已通过 `/story-setup` 初始化，需要叠加知识图谱能力。

### 前置条件

确认项目已部署 story-setup：
- `.claude/agents/` 目录存在（至少包含 story-explorer.md）
- `.claude/hooks/` 目录存在
- 如不满足，提示用户先运行 `/story-setup`

### 执行方式

```bash
bash .claude/skills/story-graph/scripts/deploy-graph.sh <项目根目录>
```

部署脚本将自动完成：
1. 复制 skill 定义：**自动识别项目技能形态**——链接形态（`.claude/skills/{name}` 是符号链接，真实文件在 `.agents/skills/`，skills CLI 安装形态）时真实文件入 `.agents/skills/story-graph/`、`.claude/skills/story-graph` 建同款符号链接；真实目录形态直接复制到 `.claude/skills/story-graph/`
2. 复制 `graph-builder.md` + `story-explorer.md`（图谱增强版）→ `.claude/agents/`。story-explorer 覆盖 story-setup 部署的同名 agent：图可用时走图查询、不可用时降级读文件；**重跑 `/story-setup` 会恢复无图版本，需重跑本部署**
3. 复制 `session-start-graph.sh` + `graph-update-check.sh` + `story_graph_cli.js` + `story_graph_core.js` + `viz_html.js` → `.claude/hooks/`
4. 合并 hook 注册到 `.claude/settings.local.json`（按 command 去重，不覆盖用户已有配置）
5. 添加 `story.db` / `story.db-wal` / `story.db-shm` 到 `.gitignore`
6. 注入 CLAUDE.md「知识图谱」段（写作循环自动走图的说明）
7. 安装 `better-sqlite3` 到 **skill 真实目录**的 `node_modules`（`.claude/skills/story-graph/` 或 `.agents/skills/story-graph/`，项目根保持干净；`story_graph_core.js` 按部署拓扑自动解析）
8. **收口写作流程**（`patch-long-write.js`，幂等）：给已部署的 story-long-write 注入图谱更新步骤 —— SKILL.md 单章流程注入 12b（写完即 `update`），workflow-daily.md 注入批末收尾（一次更新本批全部章节）；hook 的「📊 知识图谱需更新」提示降级为兜底提醒

### 部署后提示

```
知识图谱增强系统部署完成。
下一步: 新开 Claude Code 会话 → 运行 /story-graph seed 构建初始图谱。
```

---

## Seed 流程：全量构建知识图谱

**适用场景**: 开书后、正文前，或已有项目首次启用知识图谱。

### Step 1: 发现项目结构

确认活跃书路径。按以下优先级查找（与 `story_hook_core.js::discoverActiveBook` 同口径）：
1. `.active-book` 文件首行（**空或指向失效目录时自动回退，不把项目根当书目录**）
2. 深度≤4 找包含 `追踪/` 目录的目录（长篇）
3. 找包含 `正文/` 目录的目录
4. 找含 `正文.md` 的目录（短篇）
5. 询问用户

### Step 2: 初始化数据库

```bash
node .claude/hooks/story_graph_cli.js init {书路径}/story.db
```

### Step 3: 并行读取源文件

一次性读取以下所有文件：

| 类别 | 文件 | 提取内容 |
|------|------|---------|
| 角色设定 | `设定/角色/*.md` | PERSON 节点 |
| 势力设定 | `设定/势力/*.md` | ORG 节点 |
| 世界观 | `设定/世界观/*.md` | LOCATION 节点 |
| 关系 | `设定/关系.md` | KIN_TO/ALLIED_WITH/HOSTILE_TO/ROMANTIC_WITH/MENTOR_OF 边 |
| 卷纲 | `大纲/卷纲_*.md` | CHAPTER 节点、EVENT (draft) 节点 |
| 细纲 | `大纲/细纲_*.md` | EVENT (draft) 节点、PARTICIPATES_IN 边 |
| 钩子 | `追踪/伏笔.md` | HOOK 节点 + PLANTS_IN 边（`sync-hooks` 幂等同步） |

### Step 4: 生成并执行 SQL

对于提取到的每一组实体和边，使用 `story_graph_cli.js exec` 写入：

```bash
node .claude/hooks/story_graph_cli.js exec {dbPath} "INSERT OR REPLACE INTO nodes (id, node_type, label, properties) VALUES ('P_沈栀', 'PERSON', '沈栀', '{\"aliases\":[\"阿栀\"],\"role\":\"protagonist\"}');"
```

**批量写入策略**: 每 50 条 INSERT 合并为一个事务。

### Step 5: 验证

```bash
node .claude/hooks/story_graph_cli.js stats {dbPath}
```

输出摘要：
```
知识图谱已初始化:
  节点: {N}个（PERSON: {x}, LOCATION: {y}, EVENT: {z}, ITEM: {w}, ORG: {v}, CHAPTER: {c}）
  边:   {M}条（关系: {x}, 因果: {y}, 空间: {z}, 知识: {w}, ...）
  数据库: {书路径}/story.db
```

---

## Update 流程：增量更新知识图谱

**适用场景**: 每次日更写完后自动/手动触发。

### Step 1: 检测更新范围

```bash
node .claude/hooks/story_graph_cli.js stats {dbPath}
```

获取当前最新章节号，与 `正文/` 目录对比，找出需要处理的章节。

### Step 2: 启动 graph-builder agent

Spawn graph-builder agent，模式: `update`，传入：
- 待处理的章节号列表
- 数据库路径

graph-builder 将：
- 从新章正文提取实体和事件
- 查重（避免重复创建）
- 写入 staging → commit
- 同步钩子（`sync-hooks` 从 `追踪/伏笔.md` 增量同步 HOOK 节点与 PLANTS_IN 边）+ 钩子生命周期扫描
- 清理 `.claude/.graph-update-pending` 标记（session-status 下次会话也会按章节号自愈清理，双保险）
- 返回新增/变更摘要

### Step 3: 输出更新摘要

```
知识图谱已更新:
  处理章节: 第24-25章
  新增节点: {N}个（EVENT: {x}, PERSON: {y}）
  新增边:   {M}条（NARRATES: {x}, PARTICIPATES_IN: {y}, CAUSES: {z}）
  状态变更: {角色} 位置: L_A → L_B
```

> 处理范围：与 `正文/` 目录对比找出所有待处理章节；章节积压较多时优先处理最新章节并报告剩余，可重复执行直至无 pending。

---

## 查重与冲突处理原则

- **同名实体**: 先查 `SELECT id FROM nodes WHERE id = ?`，已存在则 update，不重复创建
- **能力/状态升级**: 角色的能力从「医术lv3」升级到「医术lv4」时，更新 PERSON 节点的 properties.abilities
- **位置变更**: 角色的 LOCATED_AT 变更时，旧边的 valid_until 设为当前时间点，新边从当前时间点开始
- **龙套升级**: 之前作为背景的出现，后来成为重要角色时，为其创建 PERSON 节点，并在 properties 中标注 `promoted_from: "background"`

---

## 时间点管理

**核心设计**: 时间是 TIME_POINT 的属性。开书时设定时间原点，后续每个时间点手动设 `epoch`（绝对时间戳），事件通过 OCCURS_AT 自动继承。

```bash
# 设置时间点纪元
node .claude/hooks/story_graph_cli.js set-timepoint-time <db> T_穿越时刻 45113 "星辰历123年7月8日" day

# 查看按 epoch 排序的完整时间线
node .claude/hooks/story_graph_cli.js timeline <db>

# 查看时间空白区间（可插入新内容）
node .claude/hooks/story_graph_cli.js time-gaps <db>

# 修复/补全时间信息（补 BEFORE 边、story_offset、OCCURS_AT）
node .claude/hooks/story_graph_cli.js repair-timeline <db>
```

`epoch` 是数值，单位由你定（day/hour/second）。同一 epoch 内的事件通过 `story_offset` 区分顺序。

---

## 图查询

当用户进行关系/状态/时间线查询时，**优先使用 story-explorer agent**（`.claude/agents/story-explorer.md` 可用时 spawn；不可用时降级主线程直接执行查询）。story-explorer 是图谱增强版：story.db 存在时内部通过 `story_graph_cli.js` 走图查询，图不可用时自动降级读文件（`追踪/` + `设定/`），两种来源输出同一套 schema，标注 `source: graph` 或 `source: fallback: file-read`。

story-explorer 在图上支持以下查询类型（详见其 agent 定义）:
- `time_slice` — 时间切片状态（state-at-time）
- `hook_radar` — 钩子雷达（hook-radar）
- `causal_chain` — 因果链（causal-chain）
- `knowledge_gap` — 知识缺口（knowledge-gap）
- `shortest_path` — 最短关系路径（shortest-path）
- `flashback_opportunities` — 闪回/叙事债务建议（flashback-opps）
- `time_gaps` — 时间空白区间（time-gaps）
- `state_window` — 时空窗口批量查询（state-window）
- `context_load` — 综合上下文加载（进度/钩子/时间线走图，细纲与上一章仍读文件）

既有查询类型（character_status / foreshadow_list / timeline / progress / relationship）在图可用时同样优先走图，schema 不变。

> 设计说明：图谱查询能力已并入 story-explorer（单一 agent、单一 schema、单一路由入口），不再单独部署独立查询 agent；写作流程（story-long-write context_load/benchmark_style_load 快捷路径）与 story 路由无需改动即获得图谱能力。

---

## 快照导出（已实现）

每次 `/story-graph update` 自动导出文本快照到 `设定/知识图谱快照/snapshot-{timestamp}/`；也可手动执行：

```bash
node .claude/hooks/story_graph_cli.js export-snapshot <db> <输出目录>
```

导出文件纯文本、按行结构化，`git diff` 直接可读（按实际存在的类型生成，钩子状态含在 `nodes_hook.txt` 的状态列中）：

```
设定/知识图谱快照/snapshot-{timestamp}/
├── nodes_{person|location|event|item|org|time-point|chapter|hook}.txt  ← "P_沈栀 | 沈栀 | active | role=protagonist"
├── edges_{边类型}.txt     ← "沈栀 --[KIN_TO]--> 沈父 [T_穿越时刻 → 至今]"
├── timeline_merged.txt    ← 物理时间线 + 叙事顺序线合并视图
└── SUMMARY.md             ← 统计 + 人物 + 最近事件摘要
```

---

## 注意事项

- `story.db` 不进 git（需在 `.gitignore` 中添加）
- 知识图谱是增强功能，不是替代追踪/文件——两者共存
- 图不可用时所有降级路径都能正常工作
- 上游仓库更新不影响 story-graph skill（独立目录）
