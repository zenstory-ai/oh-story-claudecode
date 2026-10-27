# Agent Note: 规划时刻分出方法层，任务包只截排纲方法

Status: implemented
Date: 2026-10-17
Related: [开书按作者确认点分段加载](2026-09-26-opening-by-author-moments.md)、[长短篇写作 references 按作者时刻和读者重组](2026-10-17-write-references-by-moment.md)、[35K 加载上限](2026-09-26-per-call-load-ceiling-35k.md)

## Problem

长篇排卷纲、排细纲的方法散在 9 份主流程从不加载的文件里：style-craft、plot-frameworks、commercial-core-methods、outline-structure-theory、plot-emotion-system、plot-special-topics、outline-conflict、outline-rhythm、character-design-methods。同一件事有多处说法，例如剧情单元体量三种口径、感情线阶段五张表，卷结构方法分在四份文件里互相引用。

9 月 26 日按作者确认点拆时刻时定下的几项做法，在这次重组里成了问题：

- 任务包整份带 workflow-volume、workflow-outline，主会话的读取清单、分工说明和作者汇报模板也进了 story-architect 的上下文，两种读者混在一份包里。
- workflow-volume 要求卷纲时刻填「全书体量与阶段总览」：全书章号、阶段占比、各阶段节奏公式。全书只精排当前卷，这些数字在出第一卷时填不出可信的值。
- 卷纲包总是带 outline-methods 的八节点和 emotional-methods 的「长篇单元情绪引擎」，有主对标的书也要多读八节点；情绪引擎和卷结构方法分在两份文件里。
- story-architect 模板在没有任务包时逐项写「执行时按 profile 读取」，照字面会把题材目录、钩子、悬念、反转、弧线全读一遍，约 55K。

## Decision

- **方法文件按时刻定唯一出处**：outline-methods 管卷结构与节奏（「卷纲排法」每次出卷纲都读，八节点、情绪模块公式、换地图三节按条件读）；plot-core-methods 管细纲与章级方法（目标情绪与主角选择、爽点六类、高潮构建、过渡章、开篇噱头）；long-genre-mechanics 管核心梗与金手指；character-relations「感情线阶段」是全书唯一一张感情线阶段表；genre-readers 管读者、平台、书名简介与对标；opening-design 只留「开篇规划」（细纲时刻）和「开篇落笔」（写第 1-3 章）。新建 revision-diagnosis，作者只说「拖、憋屈、变味、追读掉了」时先按症状找原因。9 份旧文件的独有内容迁入上述文件后删除，3 份 agent-references 副本一并删除。
- **流程文件内分两节**：workflow-volume、workflow-outline 都分「主会话」（读取清单、分工、作者汇报）和「排纲方法」两节。build_architect_brief 的卷纲包只截 workflow-volume「排纲方法」、artifact-protocols、outline-methods「卷纲排法」、reader-contract；细纲包只截 workflow-outline「排纲方法」，加 plot-core-methods（首批整份，之后不含开篇噱头一节）、首批的 opening-design「开篇规划」。八节点、情绪模块公式、换地图、感情线阶段都列在包末「按条件可读」。
- **卷纲时刻不填全书章号**：`大纲/大纲.md` 改为全书概况加分卷表，每卷一行（字数区间、所属阶段、功能、核心事件、起止状态、卷契约与终局储备）；目标字数按卷数 × 卷字数估，不预排全书章号，不定阶段占比。刻度只在 workflow-volume「排纲刻度」一处定义，artifact-protocols、部署规则 story-outline 都指向它。story-import 反推的大纲.md 同形。
- **情绪引擎并入卷纲排法**：emotional-methods 删掉「长篇单元情绪引擎」，五问与强度原则进 outline-methods「剧情单元设计」，引擎因果链仍在卷纲剧情单元卡字段里。emotional-arc-design 删掉期待管理、赌注与短篇字数分配，只留「六种弧线速查」；短篇的弧线与转折位置迁回短篇 emotional-methods。
- **story-architect 无任务包时只按 profile 表读**：模板删掉逐项读取句，改为逐行判定 agent-reference-profiles、只读和本次任务类型对得上的行、点名小节只读那一节。profile 表同步：emotional-arc-design 从 Common 移到 Long，新增 female-audience-writing 的 agent-references 副本（题材目录与核心梗都指向它），outline-conflict、outline-rhythm 两行删除。agents_version 35 → 36。
- **预算按实测登记**：卷纲包 24024 → 23228，卷纲包最坏叠加 31944 → 31557；卷纲主会话最坏叠加 32141 → 33701（多了卷纲排法与三个条件节）；细纲包首批 19273 → 15532；定设定主会话最坏叠加 31827 → 32743（金手指与感情线阶段）；单章、日更 direct/solo 加「前三章：开篇落笔」叠加槽，最坏 34519、34512；大修 direct/solo 加「作者只说症状」槽，最坏 34026。story-architect 无任务包登记为题材定位（男频/女频）、卷结构、新书开篇、结构审查五个互斥分支，最重 19187。全部 ≤35000，没有豁免。

### 2026-10-27：卷纲只读模板与判据

2026-10-27：卷纲时刻只读 artifact-protocols 的全书大纲、卷纲两节（保留段位契约与所有字段），不重复读导航、细纲指针与追踪初始化说明。reader-contract 只读契约四问、核心概念、制度/机构、风险三级、续接与换书债五节；好坏例不属于规划必读，原文保留供其他需要完整参考的任务使用。主会话读取清单、生成任务包与预算清单同时改，规则和例外不删。

当前卷纲主会话最坏叠加 33865 → 32071（净减 1794），任务包路径含角色预加载与条件叠加 31354 → 29536（净减 1818）；两条路径各收紧预算 1800。workflow-volume 的精确读取清单增加 39 字，单文件预算 5750 → 5800；35K 总上限不变。公开 CLI 生成的任务包保留两份完整模板与全部规划判据，抽出的卷纲模板通过严格取段检查（15 段，0 问题、0 告警）。没有运行收费模型或据此声称文学质量改善。


## Alternatives considered

- **任务包继续整份带流程文件**：最强理由是 story-architect 看得到主会话怎么验收、怎么汇报，交付时更贴合。不采用：包头已写明交付后只回哪几项，汇报模板留在包里只会让子代理照作者汇报的格式回话；整份带还多付约 1.3K 的读取清单和汇报说明。
- **主会话层与方法层拆成新文件**：读者分得最干净。不采用：workflow-volume、workflow-outline 的文件名被作者汇报守卫、契约清单、参考门禁和 story-import 副本钉住，文件内分节加按小节截取就能达到同样效果。
- **卷纲时刻保留全书体量与阶段总览，只删百分比**：最强理由是作者开书时想看全书大概多长、分几段。不采用：全书章号在第一卷时填不准，写下来又会被后续卷当成约束；分卷表的字数区间和所属阶段已经回答「多长、分几段」。
- **outline-structure-theory 等旧文件改为冷库，不再路由但保留**：保留原文备查。不采用：留着的文件仍会被检索到，其中互相冲突的口径还会被模型读到；原文在 git 历史里可查。

## Consequences

- 收益：卷纲、细纲每个时刻读到的方法和要填的模板字段对得上，同一件事只有一处说法；任务包只装方法，作者汇报模板不再进子代理上下文；有主对标的书不再多读八节点；story-architect 无任务包时的加载从照字面约 55K 降到最重约 19K。
- 代价：卷纲主会话最坏叠加从 32141 涨到 33701，单章、日更 direct/solo 最坏叠加贴近 34.5K，后续给这几条路径加规则要先腾字数。删减时压掉了一批低价值条目（写长三种办法、救赎文八法、高潮分类等），以 git 历史为准。agents_version 递增到 36，已部署项目要重跑 story-setup 才能拿到新的 agent 模板和参考资料包；只装 skills 的宿主在升级前仍运行项目里的旧副本。结构改动没有重跑卷纲与前 10 章细纲的盲评，合入前按 2026-09-26 的协议补跑玄幻、女频各一本。
