# Agent Note: 网文笔法精修、28 份题材包去毒与确定性守卫加固

Status: implemented
Date: 2026-11-24
Related: [2026-11-21-deterministic-hard-floor-and-soft-gates.md](2026-11-21-deterministic-hard-floor-and-soft-gates.md), [2026-11-22-web-novel-full-refactor.md](2026-11-22-web-novel-full-refactor.md)

## Problem

v0.12.1 实测与全量流派抽检暴露了三类叠加失真：

1. **示范切片自我污染**：长篇 16 份、短篇 12 份流派包的示范切片中仍残留旁白破折号（短篇 14.6/万字、长篇 25.4/万字）、过密感叹号（短篇 9.9/千字、长篇 15.8/千字）、54 处戏剧套词/塑料豪门道具与高频默认人名（`死寂/轰然/破麻袋/迈巴赫/黑卡/红酒/香槟/百亿/脸色惨白/倒吸/眼底猩红` 及 `林晚/林砚` 等），且 ≤15 字短对白占比偏低（短篇 33.6%、长篇 31.6%）并存在 9 段 ≥45 字说教对白；短篇 6 份非盐言流派切片仍混用 `「」`。写手开写与每批续写前会重读切片锁定语感，样本瑕疵会直接放大成正文坏习惯。
2. **确定性脚本与状态追踪的边界缺口**：
   - `wordcount_core.js` 与 `tracking_commit.js` 仅认单章细纲，不识别批量区间细纲（`细纲_第A-B章*.md`）。
   - 反文学腔后模型常出现感叹号咆哮标点、同章重复 `死寂` 与 `死寂/轰然/骤然/猛地/瞬间` 聚集，以及长篇中等频次旁白破折号；`check-ai-patterns.js` 缺少对应软提示，同时 `quote-emphasis-tic` 易误伤历史商号/宗族/匾额专名。
   - `check-degeneration.js` 未对正文元词 `主角/男主/女主/反派` 提供分级软提示；`check-delivery-contract.js` 短篇段长软检偏松且未计入 `【】` 心声/弹幕。
   - `build_writer_prompt.js` 未把近期时间锚点摘要注入写手上下文；`tracking_commit.js` 在 `revision` 模式下禁止退役已兑现长期约束、`delta` 软帽偏紧（1536B / 3072B），且 `check` 未提醒长期出场核心角色的快照陈旧。
3. **写作流程、审稿口径与副产物位置**：修订原稿备份直接落在 `正文/` 目录，容易与正文章节混淆；长短篇写稿/起名规则缺少防咆哮标点、乒乓短对白、日常落地道具、防默认撞名与换地图防空转要求；`story-review` 缺少对感叹号过密、跨章套词重复、长演讲、悬疑物理/线索时序、现代法务常识及悬疑短篇不强求连环打脸的显式审稿项，报告模板也未并列覆盖短篇 `第 N 节`。

## Decision

分三条正交改动同步收口，全部热路径文本维持在既有 `scripts/doc-budget.json` 预算与 35K 单次加载上限内，并重新生成共享副本与 7 端宿主适配产物：

### 1. 确定性脚本、提示词组装与状态追踪（同步全部共享副本）

- **`wordcount_core.js`（同步 `story-long-write` / `story-import` / `story-review`）**：以线性正则支持区间细纲 `细纲_第A-B章*.md` 与 `extractChapterSlice()`（按 `## / ### 第N章` 切章，单章细纲优先，区间细纲缺目标章抛 `WordcountError`），贯通 `findChapterFile()`、`readChapterOutline()` 与 `wordcountRecordDrift()`。
- **`check-degeneration.js`（同步 4 份）**：将 `主角|男主|女主|反派` 加入 `META_TIER2_RE`（仅 advisory，不进 tier1 阻断，保持穿书/快穿 0 阻断误杀）。
- **`check-ai-patterns.js`（同步 4 份）**：
  - 长篇旁白 `——` `advisory` 门槛下调至 `>=4` 且 `>=1.5/千字`（短篇维持 `>=6` 且 `>=1.5/千字`，长篇 `review_required` 维持 `>=10` 且 `>=2.5/千字`）。
  - 新增纯 `advisory` 语义提示 `exclamation-density-tic`（引号与面板外叙述 `！` `>=12` 且 `>=10/千字`，或全文 `>=25` 且 `>=18/千字`，短篇 `>=28` 且 `>=21/千字`）与 `dramatic-cliche-tic`（叙述 `死寂` 长篇 `>=2` / 短篇 `>=3`，或 `死寂|轰然|骤然|猛地|瞬间` 长篇 `>=6` 且 `>=3.5/千字` / 短篇 `>=10` 且 `>=4.2/千字`）。
  - `quote-emphasis-tic` 豁免 `[氏府堂号铺庄坊印匾]$` 专名及 `刻着|写着|印着|挂着|贴着` 前缀。
  - 在真实书库（N=450：黑岩短篇 150、七猫长篇 150、番茄 9.0+ 长篇 150）回测中，`review_required` 总体误报率为 0.89%（4/450），番茄 9.0+ 样本上新增 advisory 命中率均在 0.67%–3.33%。
- **`check-delivery-contract.js`**：收紧 `delivery.short-para-rhythm` 软检至 `median <= 30 && over80Ratio <= 0.03`；将引号外 `【】` 心声/弹幕并入 `delivery.short-dialogue-share` 并透明输出证据，避免引号内嵌套重复计字。
- **`build_writer_prompt.js`**：新增 `recentTimelineAnchors()`，从 `追踪/_tracking-state.json` 提取最近 ≤5 条非 `未揭示` 事件注入 `——— 近期时间锚点`（总长 ≤150 字）。
- **`tracking_commit.js`（同步 3 份）**：`delta` 软阈值调整为 2048B 目标 / 3584B 软上限；允许 `mode=revision` 通过 `delta.retired_context_items` 退役已兑现长期约束并合并写入 `## 本章退役登记`（`retired_characters` 仍限 append，未声明删除继续拒绝）；`check` 在活跃核心角色跨 ≥2 章出场且快照未更新时输出软警告；`draft` 兼容区间细纲标题提取。

### 2. 28 份流派包去毒与题材定向修复（同步 `agent-references/genre-styles/`）

- 全部 16 份长篇与 12 份短篇流派包的示范切片统一清零 `——`（短篇 14.6→0.0/万字，长篇 25.4→0.0/万字）、压低感叹号（短篇 9.9→6.1/千字，长篇 15.8→7.6/千字）、清零 54 处套词/塑料道具/默认撞名，并提升 ≤15 字短对白占比（短篇 33.6%→61.5%，长篇 31.6%→52.4%）且消除全部 9 段 ≥45 字说教对白。
- 6 份非盐言短篇流派（`男频都市反杀`、`悬疑`、`世情打脸`、`追妻火葬场`、`年代重生打脸`、`通用短篇`）示范切片统一为 `“”`；`甜宠`、`双男主`、`脑洞设定流` 维持 `「」`。
- 补齐 6 项题材定向规则：短篇 `男频都市反杀`（工地/车间/账本落地反打）、`宅斗宫斗`（清算道具去模板化）、`追妻火葬场`（民法典 30 天离婚冷静期与私密微锚点）；长篇 `传统玄幻仙侠`（去除 `破麻袋` 套比喻）、`豪门虐恋追妻`（4–5 章女主视角占比、冷静期与反红眼刷屏）、`历史架空权谋`（换地图防砖块与行军/原料闭环）。

### 3. 写作流程、角色模板与审稿口径对齐（同步 7 端适配）

- `story-long-write`：`flow-revision.md` 将修订原稿备份路径迁出 `正文/` 至 `.story/work/修订原稿/{YYYYMMDD}_{原文件名}`；`flow-drafting.md` 与 `flow-opening-plan.md` 补入反咆哮标点、短来回对话、日常落地道具、第 4 章起换地图锚定、跨章套词防重复与反默认撞名规则。
- `story-short-write/SKILL.md`：同步反咆哮标点、短对白、日常道具、`### 这篇用的套路` 限 2–3 条、9–10k 目标按批控初稿 9,200–9,400 字以及反默认撞名清单，同时保持 ZCode 插件注册与交接契约锚点完整。
- `story-setup/references/templates/agents/character-designer.md`：在 `## 禁止事项` 增加禁默认套用 LLM 高频撞名规则，并通过 `sync-opencode.py`、`generate-codex-agents.py`、`generate-zcode-agents.py` 同步生成各端副本。
- `story-review`（`SKILL.md`、`quality-rubric.md`、`agent-prompts.md`、`solo.md`、`rubrics/short-shuang.md`、`review-tracking.md`）与 `story-deslop/references/deslop-guide.md`：维持 18 维审查契约，并列支持 `第 N 节`，补齐 6 项审稿核查（感叹号 >15/千字、跨章套词重复、塑料豪门道具、≥60 字长演讲、悬疑物理/线索时序、现代法务常识）、悬疑短篇豁免连环打脸、2048B/3584B delta 软阈，以及 2 条新 advisory 规则说明，并由 `shared-references.py sync` 同步全部 20 份共享副本。

## Alternatives considered

- **将 `exclamation-density-tic`、`dramatic-cliche-tic` 与 `主角/男主/女主/反派` 设为 `blocking` 或 `review_required`**：最强理由是对模型约束更强，可强制在提交前逐项处理。未采用原因：450 篇真实书库回测显示热血长篇与穿书/快穿题材存在合法高频使用，升级为阻断会推高误杀并破坏「确定性硬底线 + 软门禁」分层；保留为纯 `advisory` 既能提供精确位置，又将全库 `review_required` 误报压在 0.89%。
- **仅在流程文档加禁令，不重写 28 份流派包示范切片**：最强理由是改动面小、维护成本低。未采用原因：写手在开写与续写前直接重读切片锚定语感，few-shot 样本自带 `——`、密集感叹号和长对白时，模型模仿样本的倾向强于抽象禁令，必须先把样本水位降下来。
- **调高 `scripts/doc-budget.json` 预算以容纳新增规则**：最强理由是编辑省事、无需压缩旧措辞。未采用原因：热路径字数由每次会话持续付费；本次通过等量精简旧冗余表述，全部文件均留在原预算与 35K 单次加载上限内。

## Consequences

- **收益**：示范切片与流程/审稿规则同向对齐，不再出现「规则禁破折号/咆哮标点而示范切片自带」的冲突；区间细纲解析、修订退役约束、时间线锚点注入与修订备份隔离消除了实际长篇写作中的多处运行摩擦；新增检测全部纯 advisory 且经 450 篇真实样本回测验证，不引入新的硬阻断误杀。
- **代价与兼容边界**：
  - 修订原稿备份由 `正文/*_原稿_*` 迁至 `.story/work/修订原稿/`，习惯在 `正文/` 下找旧稿的作者或外部脚本需改查新目录（`wordcount_core.js` 仍继续忽略历史残留 `_原稿_` 文件）。
  - 区间细纲切片当前识别 `## / ### 第N章` 标题，非标准标题仍需拆分单章细纲。
  - `check-ai-patterns.js` JSON 输出新增两类 `advisory` ID（`exclamation-density-tic`、`dramatic-cliche-tic`），下游若对 `issues[].type` 做白名单枚举需同步接纳。
