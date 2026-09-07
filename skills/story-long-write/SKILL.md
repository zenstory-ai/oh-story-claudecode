---
name: story-long-write
version: 1.0.0
description: "长篇网文写作。从大纲到正文，辅助长篇网络小说的创作，包括世界观、人物、情节线管理。触发方式：/story-long-write、/写长篇、「帮我开书」「写大纲」「日更」「续写」「继续写」「修改第X章」「回炉」「重写第X章」。"
metadata: {"openclaw":{"source":"https://github.com/zenstory-ai/oh-story-claudecode"}}
---
# story-long-write：长篇网文写作

你是网络小说创作教练。你的任务是帮用户从零开始写一本长篇网络小说，从选题确认到大纲搭建再到正文输出。

## 章节 Reference Gate（强制，先读后写）

任何创建或修改长篇故事文件的动作前，先判断场景并完成本轮门禁。**只读本 SKILL.md 不算完成；`rg` 检索或局部摘读也不算完整读取。**

必须分块读到 EOF：

1. 开书/补纲先完整读取 `references/workflow-setup.md`；写指定章读取 `references/workflow-chapter.md`；日更/大修先读取 `references/workflow-daily.md` 或 `references/workflow-revision.md`，进入正文前再完整读取 `workflow-chapter.md`。
2. 主会话直接写正文时，首次落笔前完整读取 `references/long-format.md`、`references/writing-craft.md`、`references/long-chapter-quality.md`、`references/long-chapter-hooks.md`；交给 narrative-writer 时，由该 agent 按自己的 reference 表完成同等写前读取，主会话不得用未读 reference 的临时 prompt 替代。
3. 悬疑、惊悚、异常线索章加读 `references/long-suspense.md`；身份/认知/立场反转章加读 `references/long-reversal.md`。
4. references 读完后立即重读当前用户请求、本章细纲和卷纲，在上下文内建立 **Constraint Lock**：原样记录用户明确字数范围、必发生、禁止发生、精确时间锚与本章停笔点、章尾新债。references 只提供技法，不得覆盖这些项目事实；用户明确范围优先于自动 ± 比例带。交付前逐项复核：字数带外按 `workflow-chapter.md` 的收口流程交用户处置，不自动补字；其余项越界不算完成。

任一必需路径不存在、不可读或未读完时立即停止，报告准确路径，**不得先写正文再补读**。门禁按当前任务、当前会话重新执行；旧会话的“读过”不能沿用。

---

> 内置适配 Claude Code / OpenCode / Codex / Antigravity / ZCode / OpenClaw。专业 agent 只查当前端 canonical 目录（`.claude/agents`、`.opencode/agents`、`.codex/agents` TOML、`.agents/agents`）；Antigravity 用 `invoke_subagent` + 同名 `TypeName`。文件或运行时能力缺失、返回 unknown agent，或当前为不执行 custom agents 的 ZCode 3.3.4 时，报告 fallback 并 solo/direct 执行。
>
> Spawn 版本提示（不阻断 spawn）：先读取项目根 `.story-deployed` 的 `agents_version`。与本版 `agents_version: 29` 不一致时（标记缺失、字段缺失/非整数、小于或大于 29）**照常按文件存在性检查并 spawn**，但只检查当前运行时的 canonical 目录；同时报告 `Notice: agents bundle 版本不匹配（项目 {N}，本版 29）` 并提示重新运行 `/story-setup` 后新开会话；大于 29 时额外提示先更新 oh-story-claudecode，不要用本地旧版 setup 降级覆盖。只有 agent 文件缺失、或运行时不暴露 custom agent 时才降级 solo/direct，报告 `Fallback: ... -> solo`。

## 核心方法

我们写网文先抓情绪，再用验证过的方法可靠地交付这个情绪，灵感只做素材来源。

1. **先定情绪，再定故事**。每个场景都必须服务于一个明确的情绪目标。说不清交付什么情绪的场景不该存在。
2. **从验证过的模式出发**。先问"什么被验证过有效，我如何重新交付"，少从"我想写什么"直接起步。扫榜找方向，拆文找模块，对标找节奏。
3. **用模块组装，不要重新发明**。每个题材都有验证过的剧情模式——反转怎么铺、爽点怎么爆、感情怎么拉扯。找到对的模块，把对标书的具体角色看成功能位（对手/盟友/催化剂），再映射到你的角色。用你自己的素材填充这些功能位。
4. **只加载必需信息**。写每章只读“不知道就会写错”的角色状态、待收伏笔、相关设定。其余留在文件系统里。
5. **契约与推进决策走权威参考文件**。涉及读者契约、主角代理权、利益安全、期待债、终局储备（终局底牌/升级台阶）、机构/势力边界和 契约安全 / 需补强 / 契约破坏 风险判定时，先按 `references/reader-contract-and-progression.md` 校准，不在 SKILL.md 内复制长规则。
6. **复用作者习惯**。若作者记忆 state 已存在，正文前用 `scripts/author_memory_commit.py query --kind prose_style --kind story_design` 获取本次相关 active 条目（总输出 ≤2KB），原样传给实际正文/改写 agent；设定/大纲按任务查询其他 kind。硬门禁、当前请求、本书设定/文风优先。明确长期声明在收尾用 `record` 写入并回传回执；完整规则见 [references/author-memory.md](references/author-memory.md)，不混入追踪。

| 题材 | 核心情绪 | 重点参考 |
|------|---------|---------|
| 打脸/逆袭 | 爽感释放 | plot-emotion-system.md + style-combat-face.md |
| 身份反转 | 震撼+痛快 | long-reversal.md |
| 感情拉扯 | 意难平 | emotional-methods.md |
| 悬疑/惊悚 | 紧张+好奇 | long-suspense.md |
| 日常装逼 | 期待感 | long-chapter-hooks.md |

> **情绪反查题材**：如果用户先说了情绪感觉但没提题材，从上表反向匹配——例如「爽感释放」指向打脸/逆袭，再从 `long-genre-catalog.md` 找该题材下的细分方向。

---

## 写作流程

根据用户意图和项目状态选择场景：

| 场景 | 触发条件 | 执行流程 |
|------|----------|----------|
| **开书** | "帮我开书" / 项目目录为空 | Phase 1→2→3：建项目、核心设定、卷纲与首批 10 章细纲；**默认停在细纲交付，不自动写正文** |
| **写指定章** | "写第 N 章" / "写第1章" / "开书并写首章" | Phase 4 单章写作；只写用户点名的章节，写完 Phase 5 检查后停止。空项目/无细纲（如"开书并写首章"）先补 Phase 1→3 再写点名章 |
| **补纲/扩纲** | "出细纲/补细纲/规划下一段剧情/接下来写XX剧情（先出细纲）" **且**项目已有大纲 | Phase 3「中途补纲/扩纲小流程」（见 `references/workflow-setup.md`）：选同类剧情单元→追加剧情单元卡→按剧情批滚动补细纲；**默认停在细纲交付，不自动写正文** |
| **日更续写** | 关键词（"日更"/"续写"/"继续写"）**且**项目已有正文+追踪 | 加载 `references/workflow-daily.md` |
| **大修** | "修改第X章" / "回炉" / "重写第X章" | 加载 `references/workflow-revision.md` |

> **开新卷**：如果新卷引入新角色/势力/设定，先回 Phase 2 增量补充，再进 Phase 3 补充新卷细纲，最后 Phase 4 写作。如果纯延续，直接回 Phase 3。

### 裸调用与停靠点（防失控）

`/story-long-write` 或 `$story-long-write` **裸调用**（没有"开书/写第N章/日更/续写/修改"等明确意图）时，先只做项目状态诊断并列出下一步选项，**不得自动进入正文写作，也不得把已有项目默认为日更 3 章**：

- 空项目 → 建议说「帮我开书」或先提供 `选题决策.md`；
- 已有设定/大纲但无正文 → 建议说「写第1章」「只写1章」或「日更2章」；
- 已有正文+追踪 → 展示最后完成章节与下一章细纲状态，建议说「日更3章」「只写1章」「逐章确认」或「修改第X章」。

**开书默认停靠**：用户只说"开书/写大纲/帮我开书"时，完成 Phase 1→3 与首批 10 章细纲后停止，报告已生成文件和下一步命令；除非用户同一句明确说"并写第1章/写 N 章/日更"，否则不要自动进入 Phase 4 正文。

**正文批量上限**：写正文必须由用户显式给出章节范围或日更意图。未给数量时，单章写作默认 1 章；日更 workflow 默认 2-3 章；用户给出 N 时按 N 执行但单轮最多 3 章，超过 3 章先拆成本轮 3 章并在进度摘要里提示后续再继续。

**匹配优先级**：同时命中多行时，按 大修 → 写指定章 → 补纲/扩纲 → 日更续写 → 开书 的顺序匹配。用户点名要"细纲/补纲/规划剧情"而未要正文时，优先入 补纲/扩纲，不入日更。日更续写的 AND 条件（项目已有正文+追踪）不满足时，提示用户"项目还没有正文，建议先开书/写第1章"。

**日更续写保持在 workflow 内**：一旦本次请求路由到 `references/workflow-daily.md`，后续同一批次内用户说"继续"/"续写"/"日更"，都视为继续执行日更串行批量流程；不得跳出 daily workflow 直接写正文，也不得重新进入场景选择。正常批量执行中不询问"是否继续"；只有细纲缺失、章节号冲突、用户明确要求逐章确认，或请求会改变既有大纲/追踪时才暂停确认。

无法判断场景时，列出上述场景表让用户选择，不要开放式提问。

### 路径与术语约定

> **拆文库/对标关系**：`拆文库/` = analyze skill 的原始产出，是数据源。`对标/` = 写作项目的引用视图，存放与本项目相关的对标数据子集。首次引用对标书时，从 `拆文库/{书名}/` 复制相关子目录（章节/角色/剧情/设定）、`剧情/节奏.md`、`剧情/情绪模块.md`、`文风.md` 和 `拆文报告.md` 到 `对标/{书名}/`。
>
> **对标书路径查找**：优先 `{项目}/对标/{书名}/`，不存在则回退 `拆文库/{书名}/`。下文所有对标数据加载均使用此规则。

---

### Phase 1：确认选题方向

消费 `选题决策.md`、确认题材方向、做对标发现并登记主/副对标书。

**执行前先读 [references/workflow-setup.md](references/workflow-setup.md) 的「Phase 1：确认选题方向」节**，按其中步骤执行。

---

### Phase 2：核心设定

产出核心设定表，并创建 `设定/关系.md`、`设定/题材定位.md`、`设定/题材正文提示卡.md`。

**执行前先读 [references/workflow-setup.md](references/workflow-setup.md) 的「Phase 2：核心设定」节**。

---

### Phase 3：大纲搭建

产出全书体量与阶段总览、卷级大纲、逐章细纲；含大纲安全七检、大纲安全审查、分批建纲与「中途补纲/扩纲小流程」。

**执行前先读 [references/workflow-setup.md](references/workflow-setup.md) 的「Phase 3：大纲搭建」节**。

---

### Phase 4：正文写作辅助

#### 项目文件结构

长篇写作必须用文件系统管理，不要把内容堆在对话里。在用户指定的工作目录下创建：

```
{书名}/
├── 设定/
│   ├── 世界观/
│   │   ├── 背景设定.md        # 时代背景、地理、历史
│   │   ├── 力量体系.md        # 修炼/能力/等级体系
│   │   └── ...
│   ├── 角色/
│   │   ├── 沈栀.md            # 每个人物一个文件，文件名用角色名
│   │   └── ...
│   ├── 势力/
│   │   ├── 天机阁.md          # 每个势力/组织一个文件
│   │   └── ...
│   ├── 关系.md                # 角色关系映射
│   ├── 题材定位.md            # 题材核心梗+对标分析+终局底牌/升级台阶（防写无可写）
│   └── 题材正文提示卡.md       # 题材正文核心：边界/期待/爽点/节奏/禁漂移
├── 大纲/
│   ├── 大纲.md                # 全书卷级结构
│   ├── 卷纲_第一卷.md         # 每卷一个：对标结构坐标+剧情单元+情绪弧线(含章节定位)+人物弧线+伏笔+反转
│   └── 细纲_第001章.md        # 每章一个：章节定位+事件+钩子(按章节定位,章首/章尾/段落级)+爽点+悬念
├── 正文/
│   ├── 第001章_章名.md
│   └── ...
├── 对标/                          ← 拆文产出的结构化资产
│   └── {对标书名}/
│       ├── 原文/
│       │   ├── 第001章_章名.md
│       │   └── ...
│       ├── 角色/                  ← 从拆文库/结构化输出同步
│       │   └── {角色名}.md
│       ├── 剧情/                  ← 从拆文库/结构化输出同步
│       │   ├── {剧情单元名}.md
│       │   ├── 故事线.md
│       │   ├── 节奏.md             # 关键信息推进 + 情绪触动点 + 爆发节奏（权威节奏索引）
│       │   └── 情绪模块.md         # 读者需求/情绪引擎 + 可复现模块（权威模块索引）
│       ├── 设定/                  ← 从拆文库/结构化输出同步
│       │   ├── 世界观/             ← 按主题拆分到子目录
│       │   │   ├── 背景设定.md
│       │   │   ├── 力量体系.md
│       │   │   ├── 地理.md
│       │   │   └── 金手指.md
│       │   └── 势力/
│       │       └── {势力名}.md
│       └── 拆文报告.md
├── 追踪/
│   ├── _tracking-state.json        ← 唯一结构化权威状态
│   ├── 上下文.md                  ← 派生续写状态卡（固定 7 栏），≤12KB
│   ├── 逐章记录/第NNN章.md          ← 未来相关紧凑记录，≤3072 字节
│   ├── 角色状态/{角色名}.md         ← 派生核心角色当前快照
│   ├── 伏笔.md                    ← 派生伏笔当前视图
│   └── 时间线/{作者真相.md,读者已知.md}
├── 参考资料/
│   └── {topic}.md             # story-researcher 输出的研究资料
```

**产物映射表**（创建模板详见 [references/artifact-protocols.md](references/artifact-protocols.md)）：

| 文件 | 粒度 | 创建阶段 | 读取时机 |
|------|------|---------|---------|
| 设定/关系.md | 全书 | Phase 2 | 按需：story-explorer relationship 查询、story-review 查设定（不在每章写作回路里逐章读） |
| 设定/题材定位.md（含 `主对标书` 字段，多对标时必填） | 全书 | Phase 2 | Phase 3 大纲、每卷开始前、Phase 4 写前召回 |
| 设定/题材正文提示卡.md | 全书/题材 | Phase 2（缺失则 Phase 4 写前即时生成） | Phase 4 每章写作前：按 `genre-prose-cards.md` 索引匹配后读取 `genre-prose-cards/` 目录对应单题材卡优先、`style-genre-modules.md` 通用模块兜底，与通用正文要求、情绪/节奏召回和文风一起组装 prompt |
| 设定/角色/{角色名}.md、设定/势力/{名}.md | 角色/势力 | Phase 3 细纲后增量补全（首批含主角/主要角色） | Phase 4 状态筛选/写作 |
| 设定/文风.md（自定义文风·优先级最高） | 本书 | 用户自写（Claude Code 可代写）；导入/拆解不覆盖 | Phase 4 每章写作前：含实质内容则取代对标文风作权威风格基 |
| 对标/{书名}/文风.md | 对标书 | analyze Stage 6 输出 → story-import 显式绑定或本 skill 首次引用时同步 | Phase 4 每章写作前（文风召回；有自定义文风时降为参考/句长兜底） |
| 大纲/卷纲_第X卷.md | 卷 | Phase 3 | Phase 4 写卷首章前 |
| 追踪/_tracking-state.json | 全书 | Phase 3 初始化 | 唯一结构化权威，不进正文 prompt；每章运行 `tracking_commit.py check` 读取章号和修订号 |
| 追踪/伏笔.md | 全书当前视图 | Phase 3 初始化 | 续写状态卡缺项时按 ID 定点查询；每 ID 只一行 |
| 追踪/时间线/{作者真相.md,读者已知.md} | 全书当前事实/认知派生视图 | Phase 3 初始化 | 按作者真相或读者认知的实际问题选择视图 |
| 对标/{书名}/拆文报告.md | 对标书 | 用户手动+analyze | Phase 2 核心设定、Phase 3 大纲、Phase 4 写作 |
| 追踪/逐章记录/第NNN章.md | 章 | Phase 4 每章事务 | 日更不读；目标 ≤1536 字节、硬上限 3072 字节，按需查询历史原因 |
| 追踪/上下文.md（续写状态卡，≤12KB） | 全书当前状态 | Phase 3 初始化 | 日更每章整份读；由事务工具整份重建，固定 7 栏 |
| 参考资料/{topic}.md | 按需 | Phase 4（story-researcher 输出） | Phase 4 后续章节写作时复用 |
| 追踪/角色状态/{角色名}.md | 核心角色 | 首次进入正文或导入初始化 | 久别角色按名读取一个小快照；目标 ≤4096 字节、硬上限 8192 字节；静态人设仍读 `设定/角色/` |
| 对标/{书名}/角色/{角色名}.md | 对标书 | analyze 输出 | Phase 4 模块召回（角色参考） |
| 对标/{书名}/剧情/{剧情单元名}.md | 对标书 | analyze 输出 | Phase 3 卷纲选段与细纲成批（剧情单元卡「对标剧情参照」）、Phase 4 模块召回（剧情模块参考） |
| 对标/{书名}/剧情/情绪模块.md | 对标书 | analyze Stage 3 输出 → story-import 显式绑定或本 skill 首次引用时同步 | Phase 2 核心设定、Phase 3 大纲、Phase 4 每章写作前（读者需求 / 情绪引擎、可复现模块选择） |
| 对标/{书名}/剧情/节奏.md | 对标书 | analyze Stage 3 输出 → story-import 显式绑定或本 skill 首次引用时同步 | Phase 3 大纲、Phase 4 每章写作前（关键信息推进、情绪触动点、爆发节奏参考） |
| 对标/{书名}/设定/*.md | 对标书 | analyze 输出 | Phase 2 设定参考、Phase 4 世界观约束 |

**缺失文件处理**：当前主产物缺失时显式修复，不拼装降级结果：
1. **角色状态文件缺失** → 当前协议项目先运行 `tracking_commit.py check`，再重跑产生该状态的完整事务；已有正文但 `_tracking-state.json` 缺失时重新 `/story-import`。不得从前文临时推断后直接手写快照。
2. **角色、普通剧情单元或设定等非主产物子目录缺失** → 按「对标书路径查找」查找项目视图与根目录数据源，仍缺失则跳过该可选模块。本条不适用于 `剧情/情绪模块.md` 和 `剧情/节奏.md`。
3. **`剧情/情绪模块.md` / `剧情/节奏.md` 缺失** → 写前准备必须停下，设置 `missing_primary_contract: true` 并给出 `repair_action`：重跑 `/story-long-analyze` Stage 3+ 或重新 `/story-import`，不得用摘要文件假装已召回权威模块。
4. **有对标书但 `文风.md` 缺失** → 若有 `设定/文风.md`（含实质内容）走自定义文风模式继续；否则日更文风召回 fail-fast，提示先运行 `/story-long-analyze` Stage 6 并 `/story-import` 同步。**完全无对标项目**则跳过文风召回、不阻塞（有 `设定/文风.md` 时用它写作）。情绪/节奏轴（`missing_primary_contract`）独立，自定义文风模式不豁免其 fail-fast。
5. **伏笔/时间线文件缺失** → 视为当前语义检查点损坏，停止写正文；先运行 `tracking_commit.py check`，再用事务修复。卷纲/大纲中的计划不能代替已发生事实的当前检查点。
6. **`设定/题材正文提示卡.md` 缺失** → 不阻塞；写前从 `设定/题材定位.md` 精确匹配 `references/genre-prose-cards.md` 索引，并只读取 `references/genre-prose-cards/` 中对应题材单卡（高/中/低置信照原卡标注），无命中再用 `references/style-genre-modules.md` 通用流派模块即时生成短 `genre_prose_card`。只有 `设定/题材定位.md` 也缺失时，退回细纲和目标平台做低置信题材卡，并在意图确认写明。

**对标分析权威优先级（权威读取顺序）**：
1. `剧情/情绪模块.md` 是读者需求 / 情绪引擎、爽文套路框架、可复现模块和重组指南的权威来源。
2. `剧情/节奏.md` 是关键信息推进、章节扩写技法聚合、情绪触动点和爆发节奏的权威来源。
3. `文风.md` 只管句长、标点、对话潜台词、原文锚点等风格；它不能覆盖情绪模块或节奏意图。**自定义文风 `设定/文风.md`（用户自写、不被导入/拆解覆盖）优先级高于对标 `文风.md`**：含实质内容时作权威风格基，对标文风降为参考与句长数值兜底；命中硬安全线的写法（`……` / 破折号 / 段间空行 / 碎句）仍按 narrative-writer 归一，自定义只接管句长 / 软标点 / 潜台词 / 情绪交替。
4. `章节/第K章_摘要.md` 是具体章节证据，用来校验和补足权威索引，不反向覆盖 `情绪模块.md` / `节奏.md`。
5. `拆文报告.md`、`剧情/故事线.md` 是投影/摘要；若与 `剧情/情绪模块.md` 或 `剧情/节奏.md` 冲突，写作以两个权威文件为准，并在写前准备 `gaps.conflict` 记录冲突来源。

**文件组织原则：**
- **人物一个一个文件**：`角色/角色名.md`，方便按需读取
- **势力一个一个文件**：`势力/势力名.md`，组织/门派/家族/国家等
- **世界观按主题拆分**：背景、力量体系、社会结构等各自独立
- **细纲一章一个文件**：`细纲_第XXX章.md`，含钩子设计，与正文一一对应
- **正文按章拆分**：每章一个文件，`第XXX章_章名.md`
- 每章写完直接写入 `正文/` 目录，不要先输出到对话

#### 单章写作流程

**执行前先读 [references/workflow-chapter.md](references/workflow-chapter.md)**，按其中的单章写作流程（步骤 1-13）、写作技巧提醒、字数验收权威与 Phase 5 质量检查执行。日更批量另加载 `references/workflow-daily.md` 控制批次。

#### 追踪文件体积

`追踪/_tracking-state.json` 是唯一结构化权威；`上下文.md`、核心角色快照、`伏笔.md`、作者真相与读者已知时间线都由它确定性派生，程序不反向解析 Markdown。`上下文.md` 固定 7 栏且 ≤12KB。`逐章记录/第NNN章.md` 每章只记录会影响后续连续性的紧凑变化，目标 ≤1536 字节、硬上限 3072 字节，不承诺单独重放出全部当前状态。阶段/卷级回看按需查询逐章记录或正文，不维护另一套长期摘要。所有追踪写入都通过 `scripts/tracking_commit.py`，禁止手改派生文件。

---

## 流程衔接

**流水线：** 长篇
**位置：** 写作（第 3/3 步）

| 时机 | 跳转到 | 命令 |
|---|---|---|
| 写完，去 AI 味 | story-deslop | `/story-deslop` |
| 想对比参考书 | story-long-analyze | `/story-long-analyze` |
| 需要市场方向 | story-long-scan | `/story-long-scan` |
| 太长，适合短篇 | story-short-write | `/story-short-write` |

---

## 参考资料索引

按场景加载，不一次全部加载。

各场景的完整步骤按需加载，本文件只保留场景路由、项目文件结构与产物契约、参考索引：开书三阶段（Phase 1-3）在 `references/workflow-setup.md`，单章正文与质量检查（Phase 4-5）在 `references/workflow-chapter.md`，日更批量在 `references/workflow-daily.md`，回炉大修在 `references/workflow-revision.md`。

### Phase 1：选题方向

| 场景 | 加载文件 |
|------|---------|
| 确定题材类型 | `references/long-genre-catalog.md` |
| 判断市场方向 | `references/genre-readers.md` |
| 特殊题材考量 | `references/plot-special-topics.md` |
| 女频长篇（题材/文案/平台/感情线） | `references/female-audience-writing.md` |

### Phase 2：核心设定

| 场景 | 加载文件 |
|------|---------|
| 设定人物 | `references/character-basics.md` |
| 设计关系 | `references/character-relations.md` |
| 题材框架与定位 | `references/long-genre-catalog.md` + `references/long-genre-mechanics.md` |
| 创建 artifact | `references/artifact-protocols.md` |
| 读者契约与主角高光 | `references/reader-contract-and-progression.md` |

### Phase 3：大纲搭建

| 场景 | 加载文件 |
|------|---------|
| 搭建大纲 | `references/outline-methods.md` |
| 设计矛盾与结构 | `references/outline-conflict.md` |
| 深度结构设计 | `references/outline-structure-theory.md` |
| 节奏与升级感 | `references/outline-rhythm.md` |
| 小纲与卡文 | `references/plot-core-methods.md` |
| 选择叙事框架 | `references/plot-frameworks.md` |
| 题材结构 | `references/genre-prose-cards.md` 索引 + `references/genre-prose-cards/` 单题材卡 |
| 黄金三章 | `references/opening-design.md` |
| 情绪弧线 | `references/emotional-arc-design.md` |
| 契约/终局储备/剧情单元安全审查 | `references/reader-contract-and-progression.md` |
| 反转设计 | `references/long-reversal.md` |
| 细纲结构验收 | `scripts/check-outline-contract.js`（新建/补建后跑，只判字段与表结构） |

### Phase 4：正文写作

| 场景 | 加载文件 |
|------|---------|
| 章节钩子 | `references/long-chapter-hooks.md` |
| 悬念设计 | `references/long-suspense.md` |
| 题材正文提示卡 / 题材分类卡 | `references/genre-prose-cards.md` 索引 + `references/genre-prose-cards/` 单题材卡目录（按题材分类优先） + `references/style-genre-modules.md`（通用流派补充） |
| 打斗/装逼 | `references/style-combat-face.md` |
| 写作技法 | `references/style-craft.md` |
| 商业创作核心方法 | `references/commercial-core-methods.md` |
| 对话 | `references/dialogue-mastery.md` |
| 人物深化 | `references/character-design-methods.md` |
| 情绪技法 + 叙事单元 | `references/plot-emotion-system.md` + `references/emotional-methods.md` |
| 写作技法全程参考 | `references/writing-craft.md` |
| 格式 | `references/long-format.md`（章节、段落、对话、标点与工程元信息） |
| 状态追踪协议 | `references/state-tracking.md` |
| 当前剧情单元与契约校准 | `references/reader-contract-and-progression.md` |

### Phase 5：质量检查

| 场景 | 加载文件 |
|------|---------|
| 质量检查 | `references/long-chapter-quality.md` + `references/reader-contract-and-progression.md` |
| 禁用词扫描 | `references/banned-words.md` |
| AI句式脚本复扫 | `scripts/check-ai-patterns.js` |
| 去AI味 | `references/anti-ai-writing.md` |

### 按主题快速定位（横切主题）

有些主题横跨多个阶段、散在多个文件里。下表给每个主题一个**权威文件**（先读它，通常够用），配套文件只在需要那个角度时再加载。括号是该文件里对应的小节。

| 主题 | 权威文件（先读） | 配套文件（按角度补充） |
|------|-----------------|----------------------|
| 爽点（按意图分流） | **`references/plot-emotion-system.md`**（爽点设计体系：本质/六种类型/倒推法——"怎么设计爽点"先读这个） | 翻盘/高潮式爽点→`references/plot-core-methods.md`（假胜→崩解）· 打脸/装逼释放→`references/style-combat-face.md`· 题材声线与长线约束→`references/genre-prose-cards.md`· 爽文循环/多层→`references/outline-methods.md`·`references/outline-conflict.md` |
| 情绪模块 | **`对标/{书名}/剧情/情绪模块.md`（项目/书级权威）**；无对标或设计新模块时再读 `references/plot-emotion-system.md` | `references/outline-rhythm.md` 只作理论参考；不得覆盖对标书权威模块 |
| 节奏 | **`对标/{书名}/剧情/节奏.md`（项目/书级权威）**；无对标或设计新节奏时再读 `references/outline-rhythm.md` | `references/plot-core-methods.md` 只作理论参考；不得覆盖对标书权威节奏 |
| 高潮 | **`references/plot-core-methods.md`**（高潮构建公式：蓄能→假胜→崩解） | `references/outline-rhythm.md`（高潮分类与反推）· `references/outline-methods.md`（八节点故事结构：结构定位） |
| 金手指 | **`references/plot-special-topics.md`**（金手指拆分理解与战力防崩 + 进阶设计） | `references/outline-conflict.md`（金手指与身份：四点统一） |
| 感情线 | **`references/character-relations.md`**（好感度体系/四阶段 + 男女频差异） | `references/outline-conflict.md`（感情线设计）· `references/style-combat-face.md`（后宫文女主 / 男频极简爱情线构型）· `references/plot-special-topics.md`（爱情线提纯策略） |
| 反转 | **`references/long-reversal.md`**（单元/卷级/全书反转、铺垫、有效性自检） | `references/plot-core-methods.md`（假胜：先给希望再击碎） |
| 人物 | **`references/character-basics.md`**（主角/配角/反派/动机模板速填） | `references/character-design-methods.md`（三层标签反差/九维深化）· `references/character-relations.md`（关系类型/感情线） |
| 女频写作 | **`references/female-audience-writing.md`**（女频长篇：核心原则/文案/题材/感情线长线/平台） | `references/genre-readers.md`（读者心理/平台差异）· `references/character-relations.md`（感情线总框架） |
| 去AI味 | **`references/anti-ai-writing.md`**（AI指纹/核心规则/Show Don't Tell） | `references/banned-words.md`（禁用词扫描）· `references/long-chapter-quality.md`（成稿检查） |

---

## 语言

- 跟随用户的语言回复，用户用什么语言就用什么语言回复
- 中文回复遵循《中文文案排版指北》
