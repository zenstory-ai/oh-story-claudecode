# Agent Note: 概念统一收尾与机制链路闭环（v0.8.1）

Status: implemented
Date: 2026-09-25
Related: [v0.8 瘦身](../../implemented/architecture/2026-09-24-v0-8-lean-writing-loop.md)

## Problem

v0.8.0 发布后做了三路只读审计（长篇与 agent 模板的概念清单、其余 skill 的概念一致性、八个核心机制的端到端链路）。结论：v0.8 的概念收敛只落在各自的「家文件」里，链路多处断开，CI 看不到。

- **会卡住作者或静默出错**：去味豁免标记被检测器当 blocking 破折号，章节无法提交；三个 skill 的作者记忆 query 命令缺必填 `--workspace`；Claude hook 不读 `.deslop-whitelist`；细纲检查与 storyctl 解析「字数目标」规则不同；作者给的字数范围 storyctl 不认；修订 draft 按追加口径提示，照做会清空本章追踪记录；review 把检测器 advisory 降成「可以不改」；五份质量清单写「字数偏离→补足」；import 反推的短篇小节大纲过不了 short-write 契约、长篇细纲缺三个必填字段；deslop 没有短篇分支，会删短篇卖点；拆文文风协议与共享文风裁决相反；路由认不出短篇项目。
- **agent 读不到它要用的定义**：story-architect 要产出卷纲却看不到剧情单元卡模板，必填字段清单漏了单元位置与主角目标；写手被指向只在 deslop 里的「诊断与分级」。「新增物三级」在 solo / skills-only 路径被当 blocking，「先问作者」在写手侧与主会话侧含义不同，「待裁定」无定义。
- **命名仍分叉**：严重度至少五套刻度、一级结构/单元剧/剧情单元、契约风险/风险等级、节拍四义、主线程/主会话/writer、收束状态残留等。
- **机制只存在于文字**：契约四问没有任何检查与作者呈现；「≥3 条语义类 advisory」无法由脚本输出判定；写正文守卫只认细纲文件名；chapter check 的文档状态与实际输出不符；拆文写入守卫只在 Claude；文档里的 CLI 示例从未被执行。

## Decision

v0.8.1 一次收齐，按文件归属五条线并行修，每个行为修复配一条修复前失败的回归。

- **检测器与 hooks**：`check-ai-patterns.js` 扫描前把 HTML 注释替换成等长空白，豁免标记不再被当破折号；每条结果带 `review: semantic|mechanical`，未分类的类型直接报错。Claude 的 `story_hook_cli.js` 与其余各端一样读 `.deslop-whitelist`。写正文守卫在细纲不计 # 号与空白不足 30 字时拦下（JS 核四副本、Codex Python、bash 守卫同改，parity 锚定方向）。毒句式同步守卫解析两端常量表逐条全文比对，含标志位与顺序，并自带变异自测。
- **字数与追踪**：「字数目标」由 `wordcount_core.py` 与 `check-outline-contract.js` 用同一套写法解析，共用 30 个样例锁一致。作者范围写细纲「字数范围」行或传 `--min-chars/--max-chars`，优先级 参数 > 细纲 > 默认 ±15%。`chapter check` 顶层 `status`：ready / needs_decision / blocked / invalid / tool_unavailable，退出码 0/0/1/1/3，错误 schema 退出 2；`quality.semantic_advisories` 计需语义判断的提示条数。`accept-current-length` 低于目标一半或超长未压缩过一次时拒收，作者坚持用 `--force`。修订 `draft` 预填本章完整记录，修订改走 `storyctl.py chapter commit`。标了 `<!-- 去味:跳过 -->` 的章，AI 句式 blocking 降为标注豁免的提示，退化类照常必须修。细纲检查校验「契约风险」取值（旧名「风险等级」照认）并输出。
- **概念统一**：新增物三级只在长篇 SKILL.md 定义；「先问作者」并入主会话「新增物处置」表，区分已写与未写两种问法；架构师拿到卷纲模板与九个必填字段；写手能读到比例上限与字段释义；严重度各处给出同一对照；剧情单元、契约风险、目标情绪、日更批末核对 / 建纲批末复核、主会话、写手等叫法统一。契约风险为需补强、契约破坏时进入作者报告。
- **其余 skill**：审稿、去 AI 味、短篇的作者记忆命令可原样执行；审稿检测器提示归 S3；各质量清单的字数行按本 skill 规则写；导入反推的短篇小节大纲与长篇细纲分别满足各自契约；去 AI 味识别短篇并保留短篇卖点；拆文文风协议与共享文风裁决一致；`/story` 认短篇项目。
- **长篇拆文**：OpenCode 生成的 extractor 只许编辑 `_analysis_cache/输入-*.md`（生成器按模板里的守卫名换算，未登记的守卫生成失败）；`plan` 每批给出 `min_plot_points`、`input_file`、`handoff_cache`，`--chapters A-B` 只规划一段；情节点下限按 `max(1, min(10, round(字数/200)))`。
- `agents_version` 32 → 33，`setup_skill_version` 1.3.1，适配层重新生成。

## Alternatives considered

- **只修 A 层，命名与机制缺口留到下一版**：最强理由是改动面小、回归风险低、能最快止血。不采用：审计显示多数 A 层错误正是命名分叉与链路缺口的症状（同一概念多处重述后漂移），只修症状下一轮还会漂；作者也要求本次收齐。
- **把所有共享概念收进一个跨 skill 的公共文件**：最强理由是一处定义、无从漂移。不采用：仓库规则禁止跨 skill 引用，skill 必须自包含；共享走字节同构副本与守卫，本次在此基础上补齐。

## Consequences

- 收益：作者不再被豁免标记、错误命令、错误严重度卡住；agent 看到的定义与主会话一致；新增的执行型测试让文档命令与脚本同步。
- 代价：改动面大（数十个文件、部署模板与 hook 文案），`agents_version` 抬到 33，所有端需重跑 `/story-setup`；hook 文案改动要同步守卫断言。
