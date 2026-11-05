# Agent 参考资料 Profile 契约

> 本文件是 story-architect 的唯一资料清单，agent 模板不重复列出。任务包未覆盖的问题选择 `long` 或 `short` 后，只加载 `Common + 当前 profile`；不自行加读表外文件，表内索引点名的题材卡按索引读取。其他 agent 按自身模板读取，沿用这里的 long / short 选择规则和质量覆盖。

## 选择规则

1. 参数明确写“长篇 / 连载 / 章纲 / 日更”时选择 `long`。
2. 明确写“短篇 / 单篇 / 小节大纲 / 盐言 / 小程序短故事”时选择 `short`。
3. 参数未写明时，用项目产物判定：`大纲/细纲_第XXX章.md`、`追踪/` 属于 long；`小节大纲.md`、单文件 `正文.md` 属于 short。
4. 新建项目尚无产物时按调用方判定：story-long-write 的题材定位、核心设定、大纲任务为 `long`；story-short-write 的构思任务为 `short`。
5. 仍无法判定时返回 `Reference Profile: unresolved`，不得同时加载两套资料兜底。
6. 输出开头标记 `Reference Profile: long|short`；审查任务按被审查作品选择。

## Common

| 文件 | 读取条件 |
|---|---|
| [agent-quality.md](agent-quality.md) | 审查、评分或交付前检查；只提供跨体裁质量核心，必须同时加载当前 profile 的质量覆盖 |
| [genre-readers.md](genre-readers.md) | 判断目标读者、平台与期待 |
| [plot-core-methods.md](plot-core-methods.md) | 排或审细纲、小节大纲：目标情绪与主角选择、爽点六类、高潮构建、过渡章、开篇噱头；short 只取与总篇幅兼容的方法 |

## Long profile

| 文件 | 读取条件 |
|---|---|
| [long-genre-catalog.md](long-genre-catalog.md) | 长篇男频题材定位或框架速查 |
| [female-audience-writing.md](female-audience-writing.md) | 女频长篇的题材框架、读者需求与简介；女频只读本文件，不读题材目录 |
| [long-genre-mechanics.md](long-genre-mechanics.md) | 提炼长篇核心梗、设计金手指或微创新 |
| [genre-prose-cards.md](genre-prose-cards.md) | 确定长篇题材声线与长线约束 |
| [character-relations.md](character-relations.md) | 本书有感情线：只读「感情线阶段」 |
| [outline-methods.md](outline-methods.md) | 讨论或审查卷结构：读「卷纲排法」；没有主对标再读「常见的八步结构」，有自创单元读「情绪模块公式」，换地图读「换地图」 |
| [opening-design.md](opening-design.md) | 新书开篇或前 3 章细纲：只读「开篇规划」 |
| [long-emotional-methods.md](long-emotional-methods.md) | 设计感情桥段或单场情绪：三板斧、两种场景情绪结构、拉扯节奏与失败模式 |
| [long-chapter-hooks.md](long-chapter-hooks.md) | 设计章首/章尾与跨章期待，不采用固定百字配额 |
| [long-suspense.md](long-suspense.md) | 编排短期、中期、远期悬念与回收周期 |
| [long-reversal.md](long-reversal.md) | 设计单元、卷级或全书反转，不采用全文百分比铁律 |
| [long-quality.md](long-quality.md) | 黄金三章、连载节奏、读者契约与终局储备审查 |
| [cross-book-recall.md](cross-book-recall.md) | 任务包按条件点名时读；没有任务包时不读 |

Long profile 禁止读取 `short-*` 文件，不得采用“6 章”“每节 500–800 字”“每两节一钩”“全文 70–85% 必须高潮”等短篇默认口径。

## Short profile

| 文件 | 读取条件 |
|---|---|
| [short-genre-formulas.md](short-genre-formulas.md) | 需要短篇题材结构骨架时 |
| [short-chapter-hooks.md](short-chapter-hooks.md) | 设计节尾、节首、段落钩子、付费断点与全文悬念 |
| [short-emotional-methods.md](short-emotional-methods.md) | 设计单篇内的羁绊、撕裂、拉扯与余韵，选整篇弧线与转折位置 |
| [short-reversal.md](short-reversal.md) | 设计短篇线索、误导与揭示；两层反转按所选方案使用 |
| [short-quality.md](short-quality.md) | 审查全文密度、付费点、反转证据链和结尾兑现 |

Short profile 禁止读取 `long-*`、`outline-*`、`opening-design.md`、`female-audience-writing.md` 或 `genre-prose-cards.md`；不得把卷级、日更或跨十几章指标当硬门槛。

