---
name: story-short-write
version: 1.0.0
description: "短篇网文写作。辅助短篇小说创作，从构思到成稿，聚焦情绪拉扯与节奏把控。触发方式：/story-short-write、/写短篇、「帮我写一篇短篇」「写个盐言故事」。"
metadata: {"openclaw":{"source":"https://github.com/zenstory-ai/oh-story-claudecode"}}
---
# story-short-write：短篇网文写作

你是短篇网文写作执行器。从构思到成稿，完成一篇完整的短篇小说。

**执行规则：短篇以情绪为目标，所有内容为情绪服务。**

## 阶段 Reference Gate（强制，先读后写）

任何创建或修改故事文件的动作之前，先判断当前 Phase，并完成该阶段的 reference gate。**只读本 SKILL.md 不算完成门禁。**

Phase 2 必须在第一次写入 `设定.md` / `小节大纲.md` 前按顺序完整读取（分块直到 EOF；`rg` 检索或局部摘读不算读完）：

1. `references/writing-workflow.md`、`references/submission-craft.md`、`references/short-craft.md`、`references/short-reversal.md`
2. 核心 10 题材再读取一个精确的 `references/genre-styles/{题材}.md`；冷门题材改读 `references/genre-writing-formulas.md`
3. 有反派或真相揭露设计时再读 `references/villain-and-reveal.md`；不适用时在设计校验区写明原因

任一必需路径不存在、不可读或题材尚未解析到唯一 reference 时，立即停止，报告准确路径/待定项，**不得创建或修改故事产物**。不要把“已读 references”的回执写进故事文件；要把选出的题材招式、反转计算等应用证据写进正常设计字段。Phase 3/4 的按需加载仍分别服从下文“写前准备”和精修检查，不得用早先读过代替当前任务完整回读。

---

> Agent 只查当前端 canonical 目录（Claude `.claude/agents`、OpenCode `.opencode/agents`、Codex `.codex/agents` TOML、Antigravity `.agents/agents`），不借其他端文件误判。Claude/OpenCode 用 `subagent_type`，Codex 用 `agent_type`，Antigravity 用 `invoke_subagent` + `TypeName`；能力/文件缺失、unknown agent 或 ZCode 3.3.4 时报告 `Fallback: project custom agents unavailable -> solo` 并 solo/direct。
>
> Spawn 版本提示（不阻断 spawn）：先读取项目根 `.story-deployed` 的 `agents_version`。与本版 `agents_version: 29` 不一致时（标记缺失、字段缺失/非整数、小于或大于 29）**照常按文件存在性检查并 spawn**，同时报告 `Notice: agents bundle 版本不匹配（项目 {N}，本版 29）` 并提示重新运行 `/story-setup` 后新开会话；大于 29 时额外提示先更新 oh-story-claudecode，不要用本地旧版 setup 降级覆盖。只有 agent 文件缺失、或运行时不暴露 custom agent 时才降级 solo/direct，报告 `Fallback: ... -> solo`。

## 执行规则

1. **先定情绪，再定故事**。动笔前必须确定目标情绪（意难平/反转震撼/爽感释放/治愈温暖/细思极恐/共鸣感动），所有内容为这个情绪服务。
2. **一个核心支点撑一篇**。反转型围绕一次主揭示蓄力；无反转型围绕报应兑现或甜度递进积累期待。不多线、不铺世界观。
3. **每句话必须有用**。不推动剧情、不铺垫反转、不推高情绪的句子 → 删。
4. **开头 3 句定生死，结尾定传播**。开头必须包含钩子，结尾必须有余韵。
5. **默认第一人称**。短篇网文（盐言/七猫短篇等）绝大多数用第一人称，代入感最强。除非题材明确需要第三人称（如多视角悬疑），否则一律用「我」。

---

## 格式规范（最高优先级）

详细规则见 `references/short-format.md`，写作前必须加载。**主会话与 narrative-writer 子代理使用同一套正文格式**：正文只允许保存在 `正文.md`，正文相邻段落之间只允许一个换行符 `\n`（不得出现空行/`\n\n`），对话引号风格按项目/平台约定统一（默认半角双引号，盐言可用「」），短篇小节标记全文统一（默认 `###1.`/`###2.`）。如果子代理输出与主会话格式不一致，按本格式规范重排后再写入文件。

---

## 核心方法

除了上面的执行规则，构思和写作时遵循：

- **从验证过的模式出发**：有对标书就先拆解，没有就从 `genre-styles/{题材}.md`（核心 10 题材）或 `genre-writing-formulas.md`（冷门题材）找对应的短篇剧情模式
- **定方向就换风格**：题材方向一旦确定（如追妻火葬场），立刻加载 `references/genre-styles/{题材}.md`——正文的腔调、开篇、钩子、情绪烈度、对话金句、招式、收尾全部切到该题材。核心 10 题材（追妻火葬场 / 世情打脸 / 复仇打脸 / 总裁豪门 / 宅斗宫斗 / 民俗怪谈 / 悬疑 / 甜宠 / 双男主 / 沙雕脑洞）有专属风格包，其中追妻含 现代/古代/民国 时代变体与 小三文学/死人文学 流派分支；冷门题材用 `genre-writing-formulas.md` 的结构骨架兜底，腔调仍按 `short-craft.md` 通用底座
- **只加载必需信息**：写每节前明确目标情绪和要用的技法，答不出就先回读参考
- **复用作者习惯**：若作者记忆 state 已存在，正文前用 `scripts/author_memory_commit.py query --kind prose_style --kind story_design` 获取相关 active 条目（总输出 ≤2KB），传给实际正文/改写 agent 作为自然倾向，不逐条展示或最大化命中，不牺牲连贯、节奏和字数；硬门禁、当前请求和本篇设定优先。明确长期声明在收尾用 `record` 写入并回传回执，细则见 [references/author-memory.md](references/author-memory.md)。

---

## 写作流程

### Phase 1：确定情绪目标

问用户：**「你想让读者读完什么感觉？有没有想写的题材方向或灵感？」**

如果用户有明确想法 → 直接进入 Phase 2。

如果用户只有模糊想法 → 帮用户做情绪选择：

| 情绪类型 | 适合场景 | 难度 | 市场热度 | 常配题材包 |
|----------|----------|------|----------|------------|
| 意难平 | 虐恋、遗憾、错过 | 中 | 🔥🔥🔥 | 追妻火葬场 / 甜宠（先虐后甜） |
| 反转震撼 | 悬疑、身份错位 | 高 | 🔥🔥🔥 | 悬疑 / 沙雕脑洞（反套路） |
| 爽感释放 | 打脸、逆袭 | 低 | 🔥🔥 | 世情打脸 / 复仇打脸 / 总裁豪门 / 宅斗宫斗（古代上位） |
| 治愈温暖 | 成长、亲情、友情 | 中 | 🔥🔥 | 甜宠 / 双男主（救赎线） |
| 细思极恐 | 悬疑、心理 | 高 | 🔥 | 悬疑 / 民俗怪谈 |
| 共鸣感动 | 现实、职场、婚姻 | 中 | 🔥🔥🔥 | 世情打脸（共鸣模式） / 追妻火葬场（小三文学） |

---

### Phase 2：构思核心框架

> 如果用户有参考小说，先用 `/story-short-analyze` 拆解。默认输出存入项目根目录 `拆文库/{书名}/`；如用户指定当前短篇引用目录，则可输出/同步到 `{短篇标题}/对标/{书名}/`。写作时会自动查找并读取这些拆文结果，不需要用户手动复制到 prompt。

#### 对标上下文加载

> **拆文库/对标关系**：`拆文库/` = analyze skill 的原始产出（数据源），位于项目根目录。`对标/` = 当前短篇的引用视图，位于 `{短篇标题}/对标/`。短篇写作优先读取 `{短篇标题}/对标/{书名}/`，不存在则读取项目根 `拆文库/{书名}/`。

推荐目录结构：

```
项目根/
├── 拆文库/
│   └── {书名}/
│       ├── 拆文报告.md
│       ├── 情节节点.md
│       └── 写作手法.md
└── {短篇标题}/
    ├── 设定.md
    ├── 小节大纲.md
    ├── 正文.md
    └── 对标/
        └── {书名}/
            ├── 拆文报告.md
            ├── 情节节点.md
            └── 写作手法.md
```

**对标发现（先于下方反应式加载）**：项目根 `拆文库/` 有拆过的短篇时，先按题材主动推荐一本对标，不要被动等用户开口。

1. `ls 拆文库/` 列书目；先从当前项目目录名和 `设定.md`「基本信息」识别本篇标题，排除同名或来源指向当前 `正文.md` 的 `拆文库/{当前书}/`。story-import 生成的本书拆文分析属于续写基线，不是对标候选。排除后为空 → 跳过（无对标按题材包写，见 Phase 1 情绪→题材包表）。
2. 逐本读 `拆文库/{书}/_meta.json` 的 `genre_detected`，与本篇题材比对，标 同题材 / 弱相关。
3. 有候选 → 用 AskUserQuestion 推荐（列候选书 +「不用，按题材包写」）。选定后记入本篇 `设定.md`「对标摘要」区作主对标，并按上方「拆文库/对标关系」规则把 `拆文库/{书}/` 同步到 `{短篇标题}/对标/{书}/`。

如果工作目录下存在 `对标/` 或项目根存在 `拆文库/`，或用户提到参考小说：

1. 先按上方「对标发现」第 1 条的同一口径识别本篇，另排除历史误建的 `对标/{当前书}/`；排除后没有外部对标时按题材包写，不进入下面几步。
2. 按上述顺序查找 `拆文报告.md`、`情节节点.md`、`写作手法.md`、`_meta.json`
3. **读 `_meta.json.genre_detected`，按下表加载对应题材风格包**（analyze 识别的题材 → write 的 genre-styles 包），正文腔调/招式随之切换：

   | analyze 的 `genre_detected` | 加载 `genre-styles/` 包 |
   |---|---|
   | 追妻（现代 / 古代 / 民国） | `追妻火葬场.md`（按「时代变体」节切换身份词与招式） |
   | 小三 / 死人文学 | `追妻火葬场.md`（「流派分支」节） |
   | 世情 / 打脸爽文 / 家庭伦理 | `世情打脸.md` |
   | 重生复仇 | `复仇打脸.md` |
   | 豪门 / 总裁（豪门联姻虐恋） | `总裁豪门.md` |
   | 宫斗宅斗 / 宫斗 / 宅斗 / 古言重生 | `宅斗宫斗.md` |
   | 民俗 / 怪谈 / 灵异 | `民俗怪谈.md` |
   | 悬疑 / 推理 / 惊悚 | `悬疑.md` |
   | 甜宠 / 先虐后甜 / 先婚后爱 | `甜宠.md` |
   | 双男主 | `双男主.md` |
   | 沙雕 / 脑洞 / 弹幕 / 系统 | `沙雕脑洞.md` |
   | 仙侠 / 通用 | 无专属包 → `short-craft.md` 底座 + `genre-writing-formulas.md` 兜底 |

4. 读取核心发现：结构段落、情绪曲线、反转位置、铺垫方式、句式节奏、可借鉴技法。**把拆文报告里的具体招式对到题材包招式库**：拆文给「这一篇怎么做的」，题材包给「这一类通用怎么做」，两者合用——拆文是当前对标书的实证，题材包是该题材的通法
5. 写入本篇 `设定.md` 的“对标摘要”区，写作时每个场景从中召回 1-2 个相关技法
6. 如只找到原文、未找到拆文报告，提示用户先运行 `/story-short-analyze`；如用户要求继续，也可只按原文做弱参考

> **拆文产出格式**：analyze 落盘的完整文件树、`_meta.json` schema、Stage→文件映射，以及「story-short-write 怎么读这些产出」的下游消费规范，见 [references/output-contract.md](references/output-contract.md)。

> **多对标书时**：参 `references/cross-book-recall.md`，副对标 anchor 入「对标摘要」区

#### Agent 调用：story-architect

构思阶段，如果项目已部署 story-architect agent（查找顺序见顶部），可 spawn `Agent(subagent_type: "story-architect", prompt: "项目目录：{dir}\n任务类型：短篇构思\n查询参数：{情绪目标+题材方向}")` 辅助框架设计。如 agent 不可用，由主线程直接执行。

帮用户确定短篇的核心框架：

```
## 短篇核心框架

### 基本信息
- 标题（暂定）：{}
- 目标字数：{} 字（短篇通常 8000-20000 字）
- 目标平台：{知乎盐选 / 小程序 / 番茄短篇}（三选一）
- 情绪目标：{读者读完的感受}

### 一句话梗概
{主角 + 困境 + 反转 + 情绪落点}

### 核心支点
- 类型：{身份/视角/动机/时间线/信息/认知反转，或无反转}
- 核心兑现：{一句话描述主揭示；无反转时写报应或关系兑现}
- 铺垫/期待：{关键铺垫点；无反转时写读者等待兑现的因果或关系节拍}

### 情绪设计
- 开头情绪：{}（强度 {1-10}）
- 中段情绪：{}（强度 {1-10}）
- 反转情绪：{}（强度 {1-10}，峰值维持 ≥2 节）
- 结尾情绪：{}（强度 {1-10}）
- 反转高潮不要骤降：反转前 1 节开始升温，反转节达到峰值，反转后 1 节维持峰值不骤降

### 人设速写
- 主角：{一句话人设}
- 关键角色：{一句话人设}
- 关系：{他们之间的关系}
```

框架确定后，完成设计任务，然后在工作目录下创建文件。

#### 设计任务（框架确定后执行）

详细步骤和模板见 `references/writing-workflow.md`。构思时从目标情绪反推剧情，不是从灵感正向构建。按顺序完成：

1. 定平台基调 + 加载题材风格包 → 先读 `references/submission-craft.md` 定投稿平台（知乎/小程序/番茄），正文视角、矛盾烈度、章末落点随之切换；再读 `references/genre-styles/{题材}.md`（核心 10 题材）+ 通用底座 `references/short-craft.md`，从招式库选 2-3 个核心招式（如追妻的白月光触发链 / 信物翻转 / 火葬场预告），写入 设定.md「题材招式」区，全程照此招式与腔调写
2. 设计反派（如有）→ 加载 `villain-and-reveal.md`
3. 确定揭露方式 → 同上
4. 编写 小节大纲.md（格式见 writing-workflow.md）：短篇只做轻量蓝图，每节包含结构段/五段功能、人物/关系或其他状态变化、因果/逻辑链、结尾承接/钩子，不套长篇完整章节蓝图。**标出付费点卡在哪一节末**（见 `submission-craft.md`「付费点」：用未完成动作、身份/证据变化或两难选择形成真实断点）；用反推法先想透付费点那一节，再倒排前后。每节可选一个任务卡点，但必须服务情绪升级、证据推进、关系撕裂、反转铺垫或反击动作；没有就不强补
5. 反转信息差验证（公式见 writing-workflow.md）
6. 伏笔回查清单（标准见 writing-workflow.md）

`设定.md` 必须包含以下机器可验收字段（内容本身也是后续写作依据，不是读文件回执）：

```markdown
## Phase 2 设计校验
- 题材参考：`references/genre-styles/{题材}.md`（冷门题材写 `references/genre-writing-formulas.md`）
- 核心招式：{招式一}；{招式二}[；{招式三}]
- 反派设计：不适用（{原因}）
- 反转类型：{身份/视角/动机/时间线/信息/认知/无反转}
- 反转位置：第 {X} 节 ÷ 共 {Y} 节 = {Z}%
- 付费点：第 {N} 节末
```

有反派时用 `villain-and-reveal.md` 的身份、动机、作恶方式、致命弱点、报应五字段替换“不适用”。`short-reversal.md` 判断确属无反转题材时，写 `反转类型：无反转` 和 `反转位置：不适用（{报应兑现/甜度递进等原因}）`，不要硬编节号。`小节大纲.md` 必须使用 `writing-workflow.md` 规定的固定 12 列 Markdown 表格，并在对应节末明确标出“付费点”。

#### Phase 2 完成门禁

两份文件生成后、向用户声明构思完成或进入 Phase 3 前，运行 `node scripts/check-phase2-contract.js --json {短篇目录}`：

- exit 0：Phase 2 机械契约通过，才可进入下一阶段；这不替代故事质量判断
- exit 1：只把 `repair_scope` 中的检查 ID、证据、期望、reference 路径和修复范围交给本轮 writer；只改失败字段，再运行同一命令
- 最多做 2 轮定向 repair；仍失败则停止并报告剩余检查 ID，不得声称 Phase 2 已完成
- exit 2、脚本缺失或不可执行：报告 verifier 不可用，不得用泛化“自检”替代后继续

#### Agent 调用：character-designer

设计任务完成后，如果项目已部署 character-designer agent（查找顺序见顶部），可 spawn `Agent(subagent_type: "character-designer", prompt: "项目目录：{dir}\n任务类型：角色设定\n查询参数：{人设速写+关系}")` 辅助角色设定和语言风格档案。如 agent 不可用，由主线程直接执行。

---

### Phase 3：逐场景写作

**项目文件结构**：文件结构见 Phase 2；设定.md/小节大纲.md 为 Phase 2 产出，正文.md 为 Phase 3 产出。

**导入项目续写基线**：`设定.md` 存在「本书续写基线」时先读取，作为已写内容的内部连续性与既有写法约束；它不是对标摘要，不参与主/副对标排序，也不复制到 `对标/`。

> 术语说明：Phase 3 按「段」划分叙事结构（开头段/铺垫段/升级段/反转段/结尾段），每段包含若干「小节」（数字编号的 beat）。「场景」指写作时的具体画面。

**交付参数先锁定**：用户明确的字数范围优先，逐字取其最小值/最大值与节数；只给单一目标时用目标的 95%-105%；都未给时用 8000-20000 字和大纲节数。后文的默认字数不得覆盖用户范围。

**写前准备**（每个场景写前执行 2 步，是核心方法的落地：确认情绪目标 → 召回技法模块）：
- **步骤 1：记忆+召回**：① 本场景目标情绪词？② 借鉴哪个参考文件的哪个技法？③ 具体用在哪个段落？答不出 → 先回读参考再动笔。如有 `对标/` 或 `拆文库/` 结构化产出，按“对标上下文加载”规则检索与当前场景最相关的结构/情绪/反转/写作手法模块作为参考，并写入“拆文召回摘要”
  - **多对标书时**：参 `references/cross-book-recall.md`，副对标/参考对标按阶段预算进入"副对标召回摘要"；正文只传摘要，不传副书文风或原文
- **步骤 2：指令确认**：用一句话概括本场景写作意图（情绪+技法+适配段落），并确认本场景是否有任务卡点、它卡出哪种情绪变化或新证据；没有就不强补。确认后开始写作

**写作指令：按三维度揉进逐场景写作，不照搬大纲腔。**

- 每个场景让读者和主角一起经历；发生、感知、反应揉在同一段连续正文里，不按维度分三段。
- 段落按戏剧单元/画面自然断开：新动作、新线索、新对话、视线切换另起；完整推理、氛围或情绪链可稍长。
- 高潮/打脸/反转压短，沉淀/推理/收束可长一点；爽点 beat 写密，过场 beat 写疏，避免通篇同长度。
- 主语节奏：段首或主语重置时可点名；同一动作链内优先代词/省略；关键转折再点名。
- 标点跟语气走：质问用问号，爆发处少量感叹；犹豫、未尽、打断用动作停顿、短句或换行处理，正文不使用 `……` / `——` / `—` / `--`。
- 短篇默认第一人称在场：受虐段可直白宣泄，反击段可冷静审判；只删中立无情绪的作者讲解，不删带主角偏色的审判/预告。
- 情绪可以直写，但后面要接场景里特有的动作或物件；没有具体承接的情绪总结句才删。
- 任务卡点也可以承接情绪，但必须直接加重羞辱、误会、背叛、证据、反击或心死节点；删掉后情绪/证据/关系无损就压缩。
- 情绪宁烈不温，冲突前置、爽点具体、台词带刺；心死/余韵等以克制为爽感的桥段按题材包收敛。

#### Agent 调用：narrative-writer

正文写作阶段默认由主会话按 2-3 节/批分批写正文；主会话输出是短篇正文的标准形态，不要求单次 agent spawn 完成 8000+ 字全文。

- 每批写完后更新“已写小节摘要”（3-5 条：已揭示信息、情绪位置、未回收伏笔、下一批衔接句）。
- 下一批先读该摘要和 `正文.md` 尾部 300-500 字再续写。
- 只有用户明确要求子代理、主会话上下文不足，或需要隔离试写时，才检查 narrative-writer agent（查找顺序见顶部）。
- 如可用，spawn `Agent(subagent_type: "narrative-writer", prompt: ...)`，只传项目目录、输出文件、情绪目标、题材风格包、小节大纲、角色、主/副对标召回摘要、作者偏好 query 中的文风/故事设计项、格式硬约束和写作硬约束。
- 不把本 skill 整段规则塞进 prompt；细节以已加载的 `short-format.md`、题材包和 `short-craft.md` 为准。
- 无论谁写，写入 `正文.md` 前都按同一格式规范重排，保证主会话与子代理输出一致。

⚠️ **硬约束只作用于整篇交付范围，不设统一逐节最低字数或行数**。
写完每批后按 `short-format.md`「字数统计」检查整篇累计值与各节分布。某节明显短于相邻节时，先核对批准情节点、可见动作和后果是否已经完整；完整就保留，缺失才补回原计划内容。不得为拉齐节长新增冲突、对话、回忆、配角反应或独立事件。整篇以锁定的用户交付范围为准；未给范围时才使用 8000-20000 字默认值。
**⚠️ 未进入锁定范围 = 正文未完成。禁止越界后结束；不足只扩已有情节点，超出只压重复解释，不借 repair 新增或删除关键剧情。**

**节数守恒**：正文节数必须等于小节大纲规划节数。不得合并多节为一节。如果写作中发现某节不需要独立存在，应回到大纲阶段调整，而非在写作时偷减。

**小节完整性流程**：
1. **写作时**：每节围绕一个主问题推进；让风险、信息、关系、资源、决定、行动或读者理解至少发生一项可见变化。相关情节点可以由同一动作链或对话同时兑现，不为拆成多个“子事件”重复铺陈。
2. **写完后**：对照 `小节大纲.md` 检查批准内容是否落地、因果与下一步是否读得懂、感知/反应是否提供新信息、伏笔/物件是否按计划出现。
3. **发现缺口时**：只补回原计划中漏掉的动作、证据、选择或后果；若本节已经完成职责，即使很短也不加任务卡点、对话、回忆或环境来凑长度。
4. **发现冗余时**：删除不改变风险、信息、关系、资源、决定、行动或可信度的阻碍、复述与旁人反应；不把“有冲突”本身当成保留理由。

每个小节按「场景信息揉进」写作（详见 short-craft.md 第 10 节）：发生是主干，感知和反应只在提供新信息时加入；用到的维度揉进同一镜头。揉进不等于按维度分段——禁止"先写发生再补感知再补反应"的堆叠写法，也不要求三项齐全；同样不等于一段到底，按新动作、新物件、新信息或新对话断段。完整推理、氛围、手艺、等待或情绪链可以连续展开，不按固定字数切断。

按以下结构分段写：

#### 第一段：开头（前 300-500 字）

**目标**：3 句话内抓住读者。**必须包含一个开篇钩子**（从 hooks-chapter.md 选择类型）。

**先写导语**：正文开头前先按 `references/submission-craft.md`「导语」写一条 150-220 字导语——四维骨架（起因+核心冲突+人设底色+情绪反转）配黄金三角（具体物件+信息差+留白钩子），一句一段（黑岩/盐言导语形态；番茄导语按 short-format.md 短段叙织）——完整句各自独立成段，不是拆成三字碎句。它就是正文开头的头几段，写好顺势往下接、不重写，所以首句同样守下面的开头零环境和前 100 字事件密度≥3（首句是事件/动作/信息炸弹，不是背景或弧线概括），剧透钩子放导语后半。

**技法指令**：前 100 字事件密度 ≥ 3，不做背景铺垫，直接上事件链。

**开头零环境规则**（默认适用；悬疑、惊悚、灾难、强氛围题材可例外）：
- 前 3 句禁止出现无事件承载的环境描写（灯光、天气、气味、温度、装修）
- 前 3 句必须是：事件 / 对话 / 动作 / 信息炸弹，四种之一
- 任务卡点可以作为动作/事件钩子，但必须立刻带出赌注或矛盾，不能先写流程再解释意义
- 环境细节只能揉进角色的动作和感知中自然带出，不能独立成句；例外题材中，环境也必须携带威胁、异常或信息差
- 检查方法：标出前 3 句的主语，如果主语是环境物件（灯光/走廊/房间/天气），重写

开头技巧：

| 技巧 | 说明 | 示例 |
|------|------|------|
| 冲突前置 | 第一句就是矛盾 | 「离婚协议放在桌上，他已经签了。」 |
| 信息差钩 | 给读者一个角色不知道的信息 | 「她不知道，对面那个男人已经在计划第三次了。」 |
| 反常行为 | 用一个不合常理的行为引起好奇 | 「她把订婚戒指冲进了马桶。」 |
| 重生反常 | 重生后做前世绝不会做的事 | 「沈栀心念成灰，支着一口气找到了媒婆:郭家的那个天阉，我来嫁。」 |
| 超自然身份 | 开篇揭示非人类身份 | 「我是世上仅存的红衣厉鬼。我不知自己是怎么死的。」 |
| 灵魂旁观 | 以灵魂视角描述死亡现场 | 「我的尸体躺在透明棺材里，三个哥哥在外面笑着说：她演得真像。」 |
| 悬念句 | 抛出一个需要解释的事实 | 「我死后的第三天，老公发了一条朋友圈。」 |
| 替嫁被弃 | 被迫接受不公正的命运 | 「三个月后，我代替皇后的嫡亲公主坐上了去漠北和亲的轿撵。」 |
| 代入式提问 | 直接让读者产生共鸣 | 「你有没有在深夜接到过一个不该接的电话？」 |

#### 第二段：铺垫（占全文 30-40%）

- 用物件/数字/习惯建立羁绊（详见 emotional-methods.md「羁绊铺设」）
- 埋入至少 3 个反转线索，分散在不同小节
- 在会改变读者预期、行动方向或关系判断的位置埋钩；连续多个小节只有提问没有局部兑现时再调整，不按固定节数填格（类型从 hooks-paragraph.md 选择）
- 小节用数字分割，每小节推进一个情节点
- 情绪强度逐节递增，不允许连续 2 节无情绪变化
- **贯穿道具第 1 次出现必须在此段完成**
- **反派作恶按阶梯递增**（小恶→中恶，见 villain-and-reveal.md）

#### 第三段：升级（占全文 20-30%）

- 冲突必须比上一段升级（强度/范围/代价至少一个维度上升）
- 插入倒计时钩子或代价钩子制造紧迫感
- 随风险和选择升级提高牵引强度；用新证据、代价、误判修正或局部反击推动，不按固定节数另塞钩子（按题材见 genre-writing-formulas.md）
- 埋入误导信息，让读者猜错反转方向
- **数字/金额递增作为叙事工具**（具体数字替代模糊描述，见各 genre-styles 招式库「数字承重」）
- **场景引擎有变化**：行动、对话、证据、任务、等待、空间压力与关系选择按因果需要切换；不为动静交替补无功能小动作

#### 第四段：反转（占全文 10-15%）

- 反转在一节内完成揭示，不拖延
- 揭示后确保前面铺垫的线索可被回溯（读者能找到「原来如此」的伏笔）
- 反转节的情绪冲击强度必须 > 前面所有节的最高值
- **用证物/证人/偷听/剥洋葱揭露真相**（4 种方式见 villain-and-reveal.md）
- **贯穿道具第 2 次出现必须在此段完成**（意义被颠覆）

#### 第五段：结尾（占全文 5-10%）

- 章末必须有钩子（悬念或余韵）
- 用安静细节收尾（一个物件、一个动作、一句短话），不写大段抒情
- 结尾方式见下表，参考 emotional-methods.md「余韵钝痛」
- **贯穿道具第 3 次出现（回扣暴击）**

结尾类型：

| 类型 | 效果 | 适合情绪 |
|------|------|----------|
| 余韵式 | 不说完，让读者自己想 | 意难平 |
| 呼应式 | 首尾呼应，形成闭环 | 治愈、成长 |
| 开放式 | 留下悬念 | 细思极恐 |
| 反转再反转 | 结尾再来一个小反转 | 震惊 |
| 金句式 | 一句话点题 | 共鸣 |

---

### Phase 3 完成门槛（进入 Phase 4 前必须通过）

- [ ] 总字数进入锁定的用户范围；未指定时进入 8000-20000 默认范围
- [ ] 每节完成其批准情节点或状态变化；没有为拉齐长度补冲突、对话、回忆或旁人反应
- [ ] 节数 = 小节大纲规划节数（不得合并/省略）
- [ ] 身体部位同一词全文 ≤ 5 次
- [ ] 「像/好像/仿佛/如同」不成片堆叠；超过 10 处需逐处复核功能，不机械全删
- [ ] `node scripts/check-ai-patterns.js --check --fail-on=blocking 正文.md` 无 blocking 命中；其余提示先通读，确属问题再改
- [ ] `node scripts/check-degeneration.js --check 正文.md` 无 blocking 退化命中（复读/截断/工程词泄漏）

**不通过 → 回退补足，不得进入精修。**

---

### Phase 4：精修打磨

加载 `references/writing-workflow.md` 中的精修清单完成检查。
重点：开头钩子、情绪曲线、反转铺垫、每句话价值、格式规范、AI 腔。文件模式依次运行 `node scripts/check-ai-patterns.js --check --fail-on=blocking 正文.md`、`node scripts/check-outline-copy.js --outline 小节大纲.md 正文.md`、`node scripts/normalize-punctuation.js 正文.md`、`node scripts/check-degeneration.js --check 正文.md`。blocking 或确属细纲照搬先改正文再复扫；其他提示仅作读感复核，功能性写法可保留。

上述修改全部落盘后，运行 `node scripts/check-delivery-contract.js --json --min-chars {MIN} --max-chars {MAX} --sections {N} {短篇目录}`。exit 0 才可交付；exit 1 只按 `repair_scope` 最小修复并重跑受影响的质量检查与本命令，最多 2 轮；仍失败则报告检查 ID 并停止。exit 2、脚本缺失或不可执行时不得声称交付契约通过。本 verifier 只验用户字数、节数与排版形状，不替代正文质量判断。

#### Agent 调用：narrative-writer（去AI味）+ consistency-checker

精修阶段，如果项目已部署对应 agent，可 spawn：
- `Agent(subagent_type: "narrative-writer", prompt: "项目目录：{dir}\n任务描述：去AI味+格式检查\n检查范围：{正文文件}\n作者偏好：{query 命中的 prose_style/story_design 项}\n删除优先：每条 AI 味项先判能否删除——删后不丢伏笔/钩子/角色/情节/必要信息的直接删，会丢才润色（删除受比例上限与字数下限约束，跌破下限改降AI重写）\n必须检查：先否定再肯定的翻转句式，发现后直接改成后项或动作细节；检查像/好像/仿佛/如同等比喻是否成片堆叠，确属堆叠时只留最有功能的少数比喻，其余回到具体画面；检查是否连续使用头皮发紧/眼皮一跳/心口一沉/胃里翻涌等精致戏剧反应，能写普通动作/普通感觉就写普通动作/普通感觉；已有手机/聊天记录/公告/账单/病历/证据截图等信息，保留为角色看到或处理的场内载体，不改成叙述者解释；任务卡点只在角色本来有要办的事且能加重情绪/证据/关系/反转时使用，不为自然感补流程")` — 执行去AI味（7 Gate）和格式合规检查
- `Agent(subagent_type: "consistency-checker", prompt: "项目目录：{dir}\n检查范围：{正文文件}\n检查类型：事实冲突+伏笔断线+角色属性不一致")` — 执行一致性检查

如 agent 不可用，由主线程直接执行。

**正文洁净规则**：
- 自检（字数统计、禁用词扫描、格式检查）是过程动作，结果直接在对话里说明，不落盘成文件
- **绝对不能**把自检记录附加到正文文件末尾
- 正文中不得出现任何 `<!-- 自检 -->` 或类似的检查标记注释

不通过 → 回退补足。

---

## 流程衔接

**流水线：** 短篇
**位置：** 写作（第 3/3 步）

| 时机 | 跳转到 | 命令 |
|---|---|---|
| 有参考小说想对标 | story-short-analyze | `/story-short-analyze` → 输出存入 `拆文库/{书名}/` |
| 写完，去 AI 味 | story-deslop | `/story-deslop` |
| 想自检 | 本 skill 质量自检 | 用 Phase 4 自检流程 + `references/short-prose-quality.md` 逐项核对 |
| 需要市场方向 | story-short-scan | `/story-short-scan` |
| 设定太大，适合长篇 | story-long-write | `/story-long-write` |

---

## 参考资料

按需加载以下文件。写作时同时加载 ≤ 3 个：

| 文件 | 何时加载 |
|------|----------|
| [references/short-format.md](references/short-format.md) | 写作前必读（短篇正文格式，两平台模板） |
| [references/submission-craft.md](references/submission-craft.md) | 投稿前必读（平台基调 知乎/小程序/番茄 · 导语门面 · 付费点断点） |
| [references/short-craft.md](references/short-craft.md) | 写作全程参考（短篇通用底座：情绪直接写+后接具体反应、在场叙述、超短章节制） |
| [references/genre-styles/](references/genre-styles/) | **定方向后必读**：按题材加载对应风格包（追妻火葬场 / 世情打脸 / 复仇打脸 / 总裁豪门 / 宅斗宫斗 / 民俗怪谈 / 悬疑 / 甜宠 / 双男主 / 沙雕脑洞），正文风格随之切换 |
| [references/short-deslop.md](references/short-deslop.md) | 去AI味时必读（短篇专属，只杀真·AI腔，不杀情绪烈度） |
| [references/writing-workflow.md](references/writing-workflow.md) | Phase 2 设计任务 + Phase 4 精修 |
| [references/genre-writing-formulas.md](references/genre-writing-formulas.md) | 冷门题材结构骨架补充（核心 10 题材直接用 genre-styles/） |
| [references/genre-writing-techniques.md](references/genre-writing-techniques.md) | 跨题材通用技法（震惊场景/三翻四震/感情线四阶段/喜剧flag） |
| [references/emotional-methods.md](references/emotional-methods.md) | 设计情感时 |
| [references/hooks-chapter.md](references/hooks-chapter.md) | 章节钩子设计 |
| [references/short-suspense.md](references/short-suspense.md) | 短篇悬念设计 |
| [references/hooks-paragraph.md](references/hooks-paragraph.md) | 段落钩子技巧 |
| [references/villain-and-reveal.md](references/villain-and-reveal.md) | Phase 2 设计反派时 |
| [references/short-reversal.md](references/short-reversal.md) | 设计短篇反转时 |
| [references/short-prose-quality.md](references/short-prose-quality.md) | 精修检查时 |
| [references/banned-words.md](references/banned-words.md) | 禁用词表 |
| [scripts/normalize-punctuation.js](scripts/normalize-punctuation.js) | Phase 4 文件模式确定性标点收尾 |
| [scripts/check-ai-patterns.js](scripts/check-ai-patterns.js) | Phase 3 完成门槛与 Phase 4 复扫；报告高危 AI 句式、破折号、碎句号、长段落、微动作复读、套式反应细节、抽象总结、套词/比喻密度、解释链、系统公告腔、提纲感短段、低连接密度 |
| [scripts/check-degeneration.js](scripts/check-degeneration.js) | Phase 3 完成门槛与 Phase 4 复扫；报告模型退化（复读/截断/工程词泄漏），blocking 需重新生成 |
| [scripts/check-phase2-contract.js](scripts/check-phase2-contract.js) | Phase 2 产物确定性验收；返回具名失败与最小 repair_scope |
| [scripts/check-delivery-contract.js](scripts/check-delivery-contract.js) | 最终交付确定性验收；按用户参数检查非空白字符、节数与小节格式 |
| [references/dialogue-mastery.md](references/dialogue-mastery.md) | 写对话时 |
| [references/output-contract.md](references/output-contract.md) | Phase 2 对标上下文加载时（理解 analyze 产出格式与消费规范） |

### 按主题快速定位（横切主题）

有些主题散在多个文件里。下表给每个主题一个**权威文件**（先读它，通常够用），配套文件只在需要那个角度时再加载。括号是该文件里对应的小节。

| 主题 | 权威文件（先读） | 配套文件（按角度补充） |
|------|-----------------|----------------------|
| 情绪外化（怎么写情绪） | **`references/short-craft.md` 第2节**（情绪直接写+后接具体反应、三段对照、改写四步——替代旧机械替换表） | 各 `genre-styles/` 包的「情绪烈度与模式」 |
| 情绪设计（情感结构） | **`references/emotional-methods.md`**（情感三板斧 + 拉扯节奏 + 失败模式） | `references/genre-writing-techniques.md`（情绪操控核心法则 / 情绪三层次） |
| 反转 | **`references/short-reversal.md`**（反转类型 / 铺垫 / 揭示位置 / 有效性自检） | `references/villain-and-reveal.md`（真相揭露机制 / 反转有效性自检） |
| 反派揭露 | **`references/villain-and-reveal.md`**（反派模板 / 揭露机制 / 报应设计） | `references/short-reversal.md` |
| 人物 | **各 `genre-styles/{题材}.md` 的「对话风格」「招式库」**（受害者-复仇者主角声线、白月光软刀、施害者道德绑架人设，corpus-grounded） | `references/villain-and-reveal.md`（反派/揭露）· `references/genre-writing-techniques.md`（三层标签反差 / 人设从缺点开始）· `references/dialogue-mastery.md`（声线差异） |
| 钩子 | **`references/hooks-chapter.md`**（章节/开篇钩子类型） | `references/hooks-paragraph.md`（段落钩子）· `references/short-suspense.md`（悬念设计） |
| 女频写作 | **对应 `genre-styles/{题材}.md`**（追妻火葬场 / 总裁豪门 / 宅斗宫斗 / 甜宠 / 世情打脸的题材声线、虐爽比例、招式） | `references/genre-writing-techniques.md`（女频读者心理与写作技法 / 感情线四阶段推进法）· `references/emotional-methods.md`（情绪拉扯） |
| 题材风格 | **`references/genre-styles/{题材}.md`**（核心 10 题材的腔调/开篇/钩子/情绪烈度/招式/收尾，corpus-grounded） | `references/genre-writing-formulas.md`（冷门题材结构骨架）· `references/genre-writing-techniques.md`（核心梗 / 卖点 / 通用技法） |
| 开头 | **各 `genre-styles/{题材}.md` 的「开篇范式」**（关系锚 + 全弧剧透导语 + 火葬场预告，真实开篇范例）+ `short-craft.md` 第12节（开头事件密度） | `references/hooks-chapter.md`（开篇钩子类型）· `references/hooks-paragraph.md`（段钩密度） |
| 格式与节奏 | **`references/short-format.md`**（短篇正文格式，两平台模板） | `references/short-craft.md`（情绪直接写+后接具体反应/三维度揉进/疏密）· `references/writing-workflow.md`（设计/精修工作流） |
| 对话 | **`references/dialogue-mastery.md`**（对话技法主文件：差异化/潜台词/对话节奏） | `references/short-craft.md`（三类台词与对话权力博弈）· 各 `genre-styles/` 包的真实金句库 |
| 去AI味 | **`references/short-deslop.md`**（短篇专属：只杀真·AI腔，不杀情绪烈度/审判句/火葬场预告） | `references/banned-words.md`（禁用词扫描）· `scripts/check-ai-patterns.js`（AI句式复扫）· `references/short-prose-quality.md`（成稿检查） |

---

## 语言

- 跟随用户的语言回复，用户用什么语言就用什么语言回复
- 中文回复遵循《中文文案排版指北》
