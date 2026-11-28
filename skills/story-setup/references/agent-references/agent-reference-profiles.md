# Agent 参考资料 Profile 契约

> 本文件是 story-architect 的唯一资料清单，agent 模板不重复列出。任务包未覆盖的问题选择 `long` 或 `short` 后，只加载 `Common + 当前 profile`；不自行加读表外文件，流派包按书只读命中的 1 份。其他 agent 按自身模板读取，沿用这里的 long / short 选择规则和质量覆盖。

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

## Long profile

| 文件 | 读取条件 |
|---|---|
| [flow-opening-plan.md](flow-opening-plan.md) | 长篇立项、定设定、人设关系与出卷纲（任务包已切片时优先以任务包为准） |
| [flow-outline.md](flow-outline.md) | 排或审长篇细纲、黄金三章、钩子与悬念反转节奏 |
| [flow-drafting.md](flow-drafting.md) | 核对长篇正文笔法、竖屏网感、对话与爽点反应层 |
| [benchmark-recall.md](benchmark-recall.md) | 有外部对标或任务包点名召回时读；无对标时不读 |
| [long-quality.md](long-quality.md) | 黄金三章、连载节奏、读者期待与后手储备审查 |

Long profile 禁止读取 `short-*` 文件，不得套用短篇固定小节数、全文百分比付费卡点或万字一次清算等短篇写法。

## Short profile

| 文件 | 读取条件 |
|---|---|
| [short-quality.md](short-quality.md) | 设计或审查短篇开门见山导语、付费卡点、连环反击/反转节奏与明账清算收尾 |
| [short-deslop.md](short-deslop.md) | 短篇写作、去味或审查时的卖点保护与长篇默认规则覆盖 |

Short profile 禁止读取 `long-*`、`flow-*`、`benchmark-recall.md` 或 `genre-styles/*`（长篇流派包）；不得把卷级、日更或跨十几章指标当硬门槛。

## 长篇流派包索引（Long profile 按书只读命中 1 份，共 22 份）

- 男频：[都市脑洞系统](genre-styles/都市脑洞系统.md)、[都市日常神豪](genre-styles/都市日常神豪.md)、[都市高武异能](genre-styles/都市高武异能.md)、[传统玄幻仙侠](genre-styles/传统玄幻仙侠.md)、[玄幻脑洞反套路](genre-styles/玄幻脑洞反套路.md)、[历史架空权谋](genre-styles/历史架空权谋.md)、[末世规则科幻](genre-styles/末世规则科幻.md)、[悬疑灵异](genre-styles/悬疑灵异.md)、[西幻游戏同人](genre-styles/西幻游戏同人.md)、[动漫男频衍生](genre-styles/动漫男频衍生.md)、[官场商战职场](genre-styles/官场商战职场.md)、[男频年代乡村](genre-styles/男频年代乡村.md)
- 女频与双男主：[现言脑洞快穿](genre-styles/现言脑洞快穿.md)、[豪门虐恋追妻](genre-styles/豪门虐恋追妻.md)、[古言宅斗重生](genre-styles/古言宅斗重生.md)、[幻想言情仙侠](genre-styles/幻想言情仙侠.md)、[女频年代军婚](genre-styles/女频年代军婚.md)、[年代种田经商](genre-styles/年代种田经商.md)、[女频末世天灾囤货](genre-styles/女频末世天灾囤货.md)、[青春甜宠文娱](genre-styles/青春甜宠文娱.md)、[双男主](genre-styles/双男主.md)
- 冷门兜底：[通用长篇](genre-styles/通用长篇.md)
