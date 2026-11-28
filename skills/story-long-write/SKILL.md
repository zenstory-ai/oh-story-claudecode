---
name: story-long-write
version: 2.0.0
description: "长篇网文规划与写作。支持只讨论结构、只写大纲或指定细纲，明确要求正文后再写章节。触发方式：/story-long-write、/写长篇、「帮我开书」「定设定」「出卷纲」「规划剧情」「写大纲」「补细纲」「日更」「续写」「继续写」「修改第X章」「回炉」「重写第X章」。"
metadata: {"openclaw":{"source":"https://github.com/zenstory-ai/oh-story-claudecode"}}
---
# story-long-write：长篇网文写作

帮作者从立项、卷纲、细纲到日更连载完成有追读力的长篇网文。

## 写前必读（强制，先读后写）

动笔前按下表读完当前时刻手册与命中流派包（唯一读取清单）；只读本文件、`rg` 或摘读不算。缺文件或未读完即停报路径，**不得先写再补读**；每次任务重读。

| 时刻 | 必读 | 条件满足才读 |
|---|---|---|
| 立项、定设定、出卷纲 | `references/flow-opening-plan.md` + 命中 1 份流派包 | 有对标：`references/benchmark-recall.md`；子代理：`references/agent-calls.md` |
| 出细纲、补纲 | `references/flow-outline.md` + 命中流派包 | 有对标：`references/benchmark-recall.md`；子代理：`references/agent-calls.md` |
| 写一章、日更 | `references/flow-drafting.md` + 命中流派包 | 降档不成立或取对标切片：`references/benchmark-recall.md`；子代理：`references/agent-calls.md`；首章初始化/追踪报错：`references/tracking-protocol.md` |
| 大修、回炉 | `references/flow-revision.md` + `references/flow-drafting.md`「正文笔法与竖屏网感」+ 流派包 | 子代理：`references/agent-calls.md`；追踪报错：`references/tracking-protocol.md` |
| 管理作者习惯 | `references/author-memory.md`（完成即停，不建书不写正文） | — |

- **22 份流派包（按书只读命中 1 份）**：男频 `references/genre-styles/都市脑洞系统.md`、`references/genre-styles/都市日常神豪.md`、`references/genre-styles/都市高武异能.md`、`references/genre-styles/传统玄幻仙侠.md`、`references/genre-styles/玄幻脑洞反套路.md`、`references/genre-styles/历史架空权谋.md`、`references/genre-styles/末世规则科幻.md`、`references/genre-styles/悬疑灵异.md`、`references/genre-styles/西幻游戏同人.md`、`references/genre-styles/动漫男频衍生.md`、`references/genre-styles/官场商战职场.md`、`references/genre-styles/男频年代乡村.md`；女频与双男主 `references/genre-styles/现言脑洞快穿.md`、`references/genre-styles/豪门虐恋追妻.md`、`references/genre-styles/古言宅斗重生.md`、`references/genre-styles/幻想言情仙侠.md`、`references/genre-styles/女频年代军婚.md`、`references/genre-styles/年代种田经商.md`、`references/genre-styles/女频末世天灾囤货.md`、`references/genre-styles/青春甜宠文娱.md`、`references/genre-styles/双男主.md`；兜底 `references/genre-styles/通用长篇.md`。
- 派 `story-architect` 时主会话读对应流程手册与 `agent-calls.md`；派 `narrative-writer` 时由它按自身读取表读，不得用临时 prompt 替代。写正文/改稿前读本书 `设定/文风.md`。
- **记下本轮约束**：重读请求、细纲与卷纲，原样记下字数范围、必发生、禁发生、时间锚与停笔点；参考文件不覆盖既定事实，作者字数范围写入细纲「字数范围」。

> 专业 agent 只查当前宿主：Claude `.claude/agents`、OpenCode `.opencode/agents`、Codex `.codex/agents` TOML、Antigravity `.agents/agents`（`invoke_subagent` + 同名 `TypeName`）；ZCode 查已启用插件注册角色，用 `Agent` 工具按实际 schema 派发，不要求 `.zcode/agents`。返回 unknown agent 按降级处理，不因他端目录存在而降级。
>
> 版本：项目根 `.story-deployed` 的 `agents_version` 与 `agents_version: 47` 不一致时照常检查并 spawn，只提示一句「写作助手是旧版，运行 /story-setup（ZCode 先更新插件）后新开会话」；大于 47 时补充提示先更新 oh-story-claudecode。仅当前宿主角色缺失或无调用能力时降级 solo/direct，对作者只说「这次我自己写」。

## 平台与男女频速查

| 平台 | 男频重点 | 女频重点 | 常规单章字数 |
|---|---|---|---|
| **番茄** | 强噱头直给；第 1 章开头尽快入冲突、多数首章亮金手指；竖屏短段，章末强卡点 | 下沉强钩、早给安全感；短段快拉扯、强反转或脑洞系统 | 2000–2500（默认 2200） |
| **七猫** | 免费爽感直推，首章立困局与反击筹码，节奏不拖 | 甜虐交替、极限推拉、宅斗/豪门/年代强情绪，卡点密 | 2000–2400（默认 2150） |
| **起点** | 代入与体系扎实，可首章立压迫、第 2–3 章亮底牌，仍须留钩 | 长线人设细、文风稳，容忍适度铺垫，主线清晰 | 2800–3500（默认 3000） |
| **晋江** | 非主力 | 人设与情感张力优先，女主主体性强、安全感高，互动不水 | 2800–3500（默认 3000） |

- **男女频差异**：男频以剧情爽感与实力/地位/资源升级为主轴，感情线辅助；女频以情绪价值与关系/成长双轴咬合，重被珍视、认可与主动权。刺猬猫/二次元向参考起点，单章 2500–3000 字，重人设吐槽与设定反差。

## 写作流程与授权边界

先定操作对象、交付范围和停点，再看项目状态；空项目不等于授权完整开书。

| 场景 | 触发条件 | 执行流程 |
|---|---|---|
| **结构讨论** | "只讨论/推敲故事结构" | 只交方案，不建工程、不写文件 |
| **大纲规划** | "写大纲/规划剧情/规划第X卷/开新卷" | 走 `flow-opening-plan.md` 到卷纲后停，不出细纲、不建追踪 |
| **细纲规划** | "出细纲/补纲/扩纲/写或修改第N章细纲" | 走 `flow-outline.md`；只补/改点名范围，不写正文 |
| **开书** | "帮我开书"（未限层级） | 定方向 → 定设定 → 出卷纲 → 前 10 章细纲，**最远停在细纲交付，不自动写正文** |
| **定设定** | "定设定"，或有题材定位缺角色关系 | 走 `flow-opening-plan.md` 定设定后停 |
| **写指定章** | "写第 N 章" / "写第1章" / "开书并写首章" | 走 `flow-drafting.md` 只写点名章后停；缺前置只补必要设定、卷纲和点名章细纲 |
| **日更续写** | "日更"/"续写"/"继续写" **且**已有正文与追踪 | 走 `flow-drafting.md` 日更批（默认 2–3 章，单轮 ≤3 章） |
| **大修** | "修改第X章" / "回炉" / "重写第X章" | 走 `flow-revision.md`；只改细纲不进此流程 |

- **对象优先与续接**："写/改第N章细纲"属规划不写正文；"继续/按这个来"不扩范围，完成即停；"继续写/接着写"指正文——下章有细纲就写，上轮在规划就问「要接着写第N章正文吗？」（默认是）。规划模式不写追踪、不调写手。
- **裸调用停靠点**：无明确意图调用 `/story-long-write` 只诊断项目给白话选项，**不得自动进入正文写作，也不得把已有项目默认为日更 3 章**：空项目 →「讨论结构 / 写大纲 / 帮我开书」；有纲无正文 →「补细纲 / 写第1章」；有正文+追踪 → 报进度并列「规划下一卷 / 日更2章 / 修改第X章」。
- **匹配优先级**：规划按 结构讨论 → 细纲规划 → 大纲规划 → 开书；正文按 大修 → 写指定章 → 日更续写。

### 面向作者的汇报

给作者的汇报、提问和停下说明只讲故事：写了/改了什么（章名、核心情节）；要作者定的事（白话问题 + 选项 + 推荐）；下一步。**严禁出现**脚本名、字段名、参数名、状态码、版本号和内部清单名；编号必带故事标签（如「伏笔 F012（那封密信）」）。检查结果一句白话带过，不加技术备注、不带代码块围栏。

### 路径与硬约束

- `{skill 根}` 为本 skill 目录。
- **卷纲严禁整读**：一律走 `node {skill 根}/scripts/outline_view.js --chapter {章号} {卷纲路径}`（或 `--unit`/`--contract`/`--toc`）。
- **追踪统一走事务脚本**：读写走 `node {skill 根}/scripts/tracking_commit.js` 与 `storyctl.js`，主数据在 `追踪/_tracking-state.json`，派生视图自动生成不手改（见 `references/tracking-protocol.md`）。
- **新增物三级**（排纲、正文、处置共用；只看下章需不需要知道它存在过）：
  - **直接写**：微连接、路人、器物、地名细部、一次性对话、现场细节；不申报。
  - **补上并记下**：具名配角、势力、复用地点属性、能力形态、规矩、刻度、新伏笔、新关系或承诺、留给主角的物件；排纲先落档再引用，正文照写并逐条进申报表（无写 `0`；末行「本章没写成的」），主会话核对入追踪；新伏笔按本卷伏笔表顺号追加（不算改卷纲）。
  - **先问作者**：新主线事件或反转、金手指规则与力量档位、真相或伏笔结算、物价财富尺度、读者期待、提前写后续章、改细纲结果或人物决定、卷纲加主线、碰本卷主打线或后期揭秘、冲突既有规矩；正文不写，排纲挂起列候选问作者。拿不准：写时按补上记下，处置按先问作者。

## 流程衔接

**流水线：** 长篇 ｜ **位置：** 写作（第 3/3 步）

- 写完去 AI 味：`/story-deslop` ｜ 多视角审查：`/story-review` ｜ 拆参考书：`/story-long-analyze` ｜ 扫榜选题：`/story-long-scan` ｜ 写短篇：`/story-short-write`
