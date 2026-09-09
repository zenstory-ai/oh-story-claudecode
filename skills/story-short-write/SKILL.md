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

1. `references/workflow-design.md` + `references/writing-workflow.md`、`references/submission-craft.md`、`references/short-craft.md`、`references/short-reversal.md`
2. 核心 10 题材再读取一个精确的 `references/genre-styles/{题材}.md`；冷门题材改读 `references/genre-writing-formulas.md`
3. 有反派或真相揭露设计时再读 `references/villain-and-reveal.md`；不适用时在设计校验区写明原因

任一必需路径不存在、不可读或题材尚未解析到唯一 reference 时，立即停止，报告准确路径/待定项，**不得创建或修改故事产物**。不要把“已读 references”的回执写进故事文件；要把选出的题材招式、反转计算等应用证据写进正常设计字段。Phase 3 写正文前完整读取 `references/workflow-draft.md`，Phase 4 精修前完整读取 `references/workflow-revision.md`，再按各阶段的写前准备和精修检查加载所需资料，不得用早先读过代替当前任务完整回读。

---

> Agent 只查当前端 canonical 目录（Claude `.claude/agents`、OpenCode `.opencode/agents`、Codex `.codex/agents` TOML、Antigravity `.agents/agents`），不借其他端文件误判。Claude/OpenCode 用 `subagent_type`，Codex 用 `agent_type`，Antigravity 用 `invoke_subagent` + `TypeName`；能力/文件缺失、unknown agent 或 ZCode 3.3.4 时报告 `Fallback: project custom agents unavailable -> solo` 并 solo/direct。
>
> Spawn 版本提示（不阻断 spawn）：先读取项目根 `.story-deployed` 的 `agents_version`。与本版 `agents_version: 30` 不一致时（标记缺失、字段缺失/非整数、小于或大于 30）**照常按文件存在性检查并 spawn**，同时报告 `Notice: agents bundle 版本不匹配（项目 {N}，本版 30）` 并提示重新运行 `/story-setup` 后新开会话；大于 30 时额外提示先更新 oh-story-claudecode，不要用本地旧版 setup 降级覆盖。只有 agent 文件缺失、或运行时不暴露 custom agent 时才降级 solo/direct，报告 `Fallback: ... -> solo`。

**文风裁决**：正文写作、改写或审稿前先读 [references/style-resolution.md](references/style-resolution.md)，加载本书文风并形成 `style_resolution`；无作者记忆也执行。当前请求、本书文风和 active 偏好按维度覆盖通用 references；同一裁决交给后续执行者。

## 执行规则

1. **先定情绪，再定故事**。动笔前必须确定目标情绪（意难平/反转震撼/爽感释放/治愈温暖/细思极恐/共鸣感动），所有内容为这个情绪服务。
2. **一个核心支点撑一篇**。反转型围绕一次主揭示蓄力；无反转型围绕报应兑现或甜度递进积累期待。不多线、不铺世界观。
3. **每句话必须有用**。不推动剧情、不铺垫反转、不推高情绪的句子 → 删。
4. **开头 3 句定生死，结尾定传播**。开头必须包含钩子，结尾必须有余韵。
5. **默认第一人称**。短篇网文（盐言/七猫短篇等）绝大多数用第一人称，代入感最强。当前请求、本篇文风或题材需要第三人称时按其执行，不因默认值改回「我」。

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

存在本篇 `对标/`、项目根 `拆文库/` 或用户提供参考小说时，先完整读取 [references/benchmark-recall.md](references/benchmark-recall.md)，执行对标发现、排除本书续写基线、题材匹配与召回。无外部对标时仍按原题材包执行。

#### 构思、设计与验收

完整步骤见 [references/workflow-design.md](references/workflow-design.md)。按首屏 Reference Gate 读完后执行；两份设计文件通过其中的 Phase 2 完成门禁，才可进入 Phase 3。

---

### Phase 3：逐场景写作

进入正文写作前，完整读取 [references/workflow-draft.md](references/workflow-draft.md)，执行交付参数锁定、写前验收、逐场景写作与 Phase 3 完成门槛。只做构思或精修时不加载本阶段细则。

**小节完整性流程**：
1. **写作时**：每节围绕一个主问题推进；让风险、信息、关系、资源、决定、行动或读者理解至少发生一项可见变化。相关情节点可以由同一动作链或对话同时兑现，不为拆成多个“子事件”重复铺陈。
2. **写完后**：对照 `小节大纲.md` 检查批准内容是否落地、因果与下一步是否读得懂、感知/反应是否提供新信息、伏笔/物件是否按计划出现。
3. **发现缺口时**：只补回原计划中漏掉的动作、证据、选择或后果；若本节已经完成职责，即使很短也不加任务卡点、对话、回忆或环境来凑长度。
4. **发现冗余时**：删除不改变风险、信息、关系、资源、决定、行动或可信度的阻碍、复述与旁人反应；不把“有冲突”本身当成保留理由。

### Phase 3 完成门槛（进入 Phase 4 前必须通过）

- [ ] 总字数进入锁定的用户范围；未指定时进入 8000-20000 默认范围
- [ ] 每节完成其批准情节点或状态变化；没有为拉齐长度补冲突、对话、回忆或旁人反应
- [ ] 节数 = 小节大纲规划节数（不得合并/省略）
- [ ] 身体细节按叙事功能判断，不设次数上限；不对“手、眼、心”等单字计数改稿
- [ ] 「像/好像/仿佛/如同」不成片堆叠；超过 10 处需逐处复核功能，不机械全删
- [ ] `node scripts/check-ai-patterns.js --check --fail-on=blocking 正文.md` 无 blocking 命中；其余提示先通读，确属问题再改
- [ ] `node scripts/check-degeneration.js --check 正文.md` 无 blocking 退化命中（复读/截断/工程词泄漏）

**不通过 → 回退补足，不得进入精修。**

---

### Phase 4：精修打磨

精修或质量自检前，完整读取 [references/workflow-revision.md](references/workflow-revision.md)，执行语义去味、一致性检查、最终文件扫描与交付验收；修改后按其中职责分工复核。只做构思时不加载本阶段细则。

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

阶段必读项按首屏 Reference Gate 执行；其他资料按 [参考索引](references/reference-index.md) 的加载条件选用。

## 语言

- 跟随用户的语言回复，用户用什么语言就用什么语言回复
- 中文回复遵循《中文文案排版指北》
