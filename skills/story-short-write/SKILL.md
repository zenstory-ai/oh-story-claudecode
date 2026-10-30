---
name: story-short-write
version: 1.0.0
description: "短篇网文写作。辅助短篇小说创作，从构思到成稿，聚焦情绪拉扯与节奏把控。触发方式：/story-short-write、/写短篇、「帮我写一篇短篇」「写个盐言故事」。"
metadata: {"openclaw":{"source":"https://github.com/zenstory-ai/oh-story-claudecode"}}
---
# story-short-write：短篇网文写作

你负责从构思到成稿，完成一篇完整的短篇小说。

**执行规则：短篇以情绪为目标，所有内容为情绪服务。**

## 写前必读（强制，先读后写）

短篇按作者当前要做的事分阶段加载，阶段之间靠落盘文件交接。创建或修改故事文件前，先判断当前时刻，再完整读取该时刻的必读项；分块读取直到 EOF，`rg` 检索或局部摘读不算读完。**只读本 SKILL.md 不算完成门禁。**

| 时刻 | 作者确认什么 | 读什么 | 落盘 |
|---|---|---|---|
| 定情绪（Phase 1） | 读者读完的感觉、题材方向 | 本文件 | 进构思时写入 `设定.md` |
| 构思（Phase 2） | 故事核、人物、反转、付费点 | ① `references/workflow-design.md`、`references/submission-craft.md`、`references/short-craft.md`、`references/short-reversal.md` ② 核心 10 题材读一个精确的 `references/genre-styles/{题材}.md`，冷门题材读 `references/genre-writing-formulas.md` ③ 有反派或真相揭露设计时读 `references/villain-and-reveal.md`，不适用时在设计校验区写明原因 | `设定.md`、`小节大纲.md` |
| 写正文（Phase 3–4） | 成稿 | Phase 3 写正文前完整读取 `references/workflow-draft.md`，按其「写前加载」读写作手法；Phase 4 精修前完整读取 `references/workflow-revision.md` | `正文.md` |

构思必读项须在首次写入 `设定.md` / `小节大纲.md` 前读完。任一必需路径不存在、不可读，或题材尚未对应到唯一 reference 时，立即停止，报告准确路径或待定项，**不得创建或修改故事产物**。故事文件只记录选出的题材招式、反转计算等设计，不写“已读 references”的回执。进入每个时刻都按当前任务完整回读。

**交接只靠落盘**：作者在对话里定下的字数、平台、人称、偏好、红线和否掉的方案，构思交付前写进 `设定.md`；写正文只读两份设计文件与本时刻的写作手法，不重读构思方法论，也不回翻对话。
**换上下文**：构思阶段加载最多，汇报末尾建议作者新开对话说「写正文」；作者选择在本对话接着写时照常执行。新对话中，两份设计文件通过构思完成门禁即可进入写正文。

---

> Agent 只查当前宿主：Claude `.claude/agents`（`subagent_type`）、OpenCode `.opencode/agents`（`subagent` 的 `agent`）、Codex `.codex/agents` TOML（`agent_type`）、Antigravity `.agents/agents`（`invoke_subagent` + `TypeName`）；ZCode 查插件注册的同名角色，用 `Agent` 按实际 schema 派发，不要求 `.zcode/agents`。主会话自己写正文、去味是常态，不报；作者明确要交给写作助手而角色/工具缺失或 unknown agent 时，由主会话接手并一句白话告诉作者，`Fallback: project custom agents unavailable -> solo` 原文只进汇报最后一行「技术备注：」。
>
> Spawn 版本提示（不阻断 spawn）：先读取项目根 `.story-deployed` 的 `agents_version`。与本版 `agents_version: 38` 不一致时（标记缺失、字段缺失/非整数、小于或大于 38）**照常按当前宿主角色来源检查并 spawn**，同时用一句白话提示作者「写作助手是旧版，运行 /story-setup（ZCode 先更新插件）后新开会话」，`Notice: agents bundle 版本不匹配（项目 {N}，本版 38）` 原文写进技术备注行；大于 38 时额外提示先更新 oh-story-claudecode，不要用本地旧版 setup 降级覆盖。只有当前宿主角色缺失或不暴露调用能力时才降级 solo/direct，`Fallback: ... -> solo` 同样只进技术备注行。

**文风裁决**：正文写作、改写或审稿前先读 [references/style-resolution.md](references/style-resolution.md)，加载本书文风并形成 `style_resolution`；无作者记忆也执行。当前请求、本书文风和 active 偏好按维度覆盖通用 references；同一裁决交给后续执行者。

## 执行规则

1. **先定情绪，再定故事**。动笔前必须确定目标情绪（意难平/反转震撼/爽感释放/治愈温暖/细思极恐/共鸣感动），所有内容为这个情绪服务。
2. **一个核心支点撑一篇**。反转型围绕一次主揭示蓄力；无反转型围绕报应兑现或甜度递进积累期待。不多线、不铺世界观。
3. **每句话必须有用**。不推动剧情、不铺垫反转、不推高情绪的句子 → 删。
4. **开头 3 句定生死，结尾定传播**。开头必须包含钩子，结尾必须有余韵。
5. **默认第一人称**，用亲历视角建立代入感。当前请求、本篇文风或题材需要第三人称时按其执行。

---

## 作者记忆管理

管理习惯读 `references/author-memory.md`（整理、超编、迁移按其中指路）。仅管理习惯时完成即停，不建书、不写正文。

## 核心方法

- **按题材选写法**：确定题材后，按文风裁决选用题材包的腔调、开篇、钩子、情绪烈度、金句、招式与收尾；追妻按时代变体及小三/死人文学分支选择。冷门题材用公式安排结构，腔调按 `short-craft.md`
- **复用作者习惯**：有作者记忆时，正文前用 `scripts/author_memory_commit.py query --workspace {工作区} --book-root {项目目录} --kind prose_style --kind story_design [--genre {题材}] [--workflow 短篇]`（改写、去味只带 `--kind prose_style`），把输出的 `lines` 原样交正文/改写 agent 作自然倾向，不逐条追求命中，不牺牲连贯、节奏和字数；硬门禁、当前请求和本篇设定优先；没装下的交稿时用原话告诉作者。长期声明在收尾按上方管理入口处理。

---

## 写作流程

### Phase 1：确定目标情绪

从项目根及上一级往下 3 层找到 `短篇扫榜结论.md`（多份取最新）时先读其「选题匹配」，排第一的方向带着目标情绪当候选问作者；过了复扫日期就提醒可能过期。

问用户：**「你想让读者读完什么感觉？有没有想写的题材方向或灵感？」**

用户已说清读者读完的感觉 → 直接进入 Phase 2；只给了题材或梗、没说情绪 → 从下表带一个推荐情绪问一句，作者点头再进。

如果用户只有模糊想法 → 帮用户做情绪选择：

| 情绪类型 | 适合场景 | 难度 | 常配题材包 |
|----------|----------|------|------------|
| 意难平 | 虐恋、遗憾、错过 | 中 | 追妻火葬场 / 甜宠（先虐后甜） |
| 反转震撼 | 悬疑、身份错位 | 高 | 悬疑 / 沙雕脑洞（反套路） |
| 爽感释放 | 打脸、逆袭 | 低 | 世情打脸 / 复仇打脸 / 总裁豪门 / 宅斗宫斗（古代上位） |
| 治愈温暖 | 成长、亲情、友情 | 中 | 甜宠 / 双男主（救赎线） |
| 细思极恐 | 悬疑、心理 | 高 | 悬疑 / 民俗怪谈 |
| 共鸣感动 | 现实、职场、婚姻 | 中 | 世情打脸（共鸣模式） / 追妻火葬场（小三文学） |

---

### Phase 2：构思核心框架

#### 对标上下文加载

存在本篇 `对标/`、项目根 `拆文库/` 或用户提供参考小说时，先完整读取 [references/benchmark-recall.md](references/benchmark-recall.md)，执行对标发现、排除本书续写基线、题材匹配与召回。无外部对标时仍按原题材包执行。

#### 构思、设计与验收

完整步骤见 [references/workflow-design.md](references/workflow-design.md)。按首屏「写前必读」读完后执行；两份设计文件通过其中的 Phase 2 完成门禁，才可进入 Phase 3。

---

### Phase 3：逐场景写作

进入正文写作前，完整读取 [references/workflow-draft.md](references/workflow-draft.md)，执行交付参数锁定、写前验收与逐场景写作；只做构思或精修时不加载。

**小节完整性流程**：
1. **写作时**：每节围绕一个主问题推进；让风险、信息、关系、资源、决定、行动或读者理解至少发生一项可见变化。相关情节点可以由同一动作链或对话同时兑现，不为拆成多个“子事件”重复铺陈。
2. **写完后**：对照 `小节大纲.md` 检查批准内容是否落地、因果与下一步是否读得懂、感知/反应是否提供新信息、伏笔/物件是否按计划出现。
3. **发现缺口时**：只补回原计划中漏掉的动作、证据、选择或后果；若本节已经完成职责，即使很短也不加任务卡点、对话、回忆或环境来凑长度。
4. **发现冗余时**：删除不改变风险、信息、关系、资源、决定、行动或可信度的阻碍、复述与旁人反应；不把“有冲突”本身当成保留理由。

### Phase 3 完成门槛（进入 Phase 4 前必须通过）

- [ ] 总字数进入锁定的用户范围；作者没给时进入 `设定.md` 的目标字数（构思时按所选平台的投稿区间定，未定平台用 8000-12000，见 submission-craft.md）
- [ ] 每节完成其批准情节点或状态变化；没有为拉齐长度补冲突、对话、回忆或旁人反应
- [ ] 节数 = 小节大纲规划节数（不得合并/省略）
- [ ] 身体细节按叙事功能判断，不设次数上限；不对“手、眼、心”等单字计数改稿
- [ ] 「像/好像/仿佛/如同」不成片堆叠；超过 10 处需逐处复核功能，不机械全删
- [ ] `node scripts/check-ai-patterns.js --check --fail-on=blocking 正文.md` 无 blocking 命中；其余提示先通读，确属问题再改
- [ ] `node scripts/check-degeneration.js --check 正文.md` 无 blocking 退化命中（复读/截断/工程词泄漏）

**不通过 → 回退补足，不得进入精修。**

---

### Phase 4：精修打磨

精修或质量自检前，完整读取 [references/workflow-revision.md](references/workflow-revision.md)，按其职责分工去味、查一致性、做最终扫描与交付验收；只做构思时不加载。

---

## 流程衔接

**流水线：** 短篇
**位置：** 写作（第 3/3 步）

有参考小说想对标 → `/story-short-analyze`（存入 `拆文库/{书名}/`）；写完去 AI 味 → `/story-deslop`；想自检 → Phase 4 流程；要市场方向 → `/story-short-scan`；设定太大适合长篇 → `/story-long-write`。

---

## 参考资料

阶段必读项按首屏「写前必读」执行；其他资料按 [参考索引](references/reference-index.md) 的加载条件选用。
