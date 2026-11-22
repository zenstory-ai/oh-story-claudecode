# Agent Note: 对照真人网文语料全栈重构短篇、长篇与周边技能（流程化 + 流派包 + 竖屏网感校准）

Status: implemented
Date: 2026-11-22
Related: [对照网文真实语料与平台现况校准非长篇写作 13 个 Skill](2026-11-12-non-long-write-skills-calibration.md)、[对照网文真实语料校准长篇写作规则自洽性、标点清洗与去味阻断阈值](2026-11-12-long-write-corpus-calibration.md)、[确定性硬底线与有摩擦软门禁分层](2026-11-21-deterministic-hard-floor-and-soft-gates.md)

## Problem

在 MongoDB `novel` 真人语料库（**87,817 篇网络短篇**，覆盖七猫 43,885 / 知乎盐言 29,756 / 黑岩 9,868 / 点众 4,308，洁净分层样本 `N=380`；以及 **23,540 本连载长篇**，覆盖番茄 17,424 / 七猫 6,116，黄金三章样本 `N=270`）与 `story-short-write` / `story-long-write` 全链路回测后，发现生成正文滑向「传统纸媒短篇 / 严肃文学 / 故事会腔」的四个系统性根因：

1. **短篇与长篇指令过度碎片化且自相矛盾**：
   - `story-short-write` 把规则拆进 `SKILL.md` + 18 份非流派参考（单轮加载逼近 33.3K 迫使 Phase 2→3 换会话，导致构思时的导语/付费卡点/反派法则在写正文时被驱逐出上下文），且内部暗藏 `emotional-methods.md`（前 1/3 羁绊 + 余韵留白）、`short-reversal.md`（全局禁偷听/反派自白/叙述者剧透）、`dialogue-mastery.md`（反直球交锋）与 `short-craft.md`（情绪宁烈不温）9 处直接冲突；
   - `story-long-write` 拆成 71 份文档（含 33 张碎片化题材卡），写正文时在「召回降档」下会跳过原文语感切片，且 `writing-craft.md` / `long-format.md` 仍偏向传统段长与克制反应。
2. **检测器、写后钩子、审稿与去味反向惩罚真网文特征**：
   - 对 120 篇真人网络短篇实跑旧版 `check-ai-patterns.js --fail-on=review_required` 误拦高达 **35.0%（42/120，主要为旁白 `——`）**，`advisory` 触发达 **91.7%**（`overcompressed-prose-tic` 18.3%、`low-connective-density-tic` 14.2%、未按篇幅缩放的 `quote-emphasis-tic` 42.5% 与 `negation-pair-tic` 15.0%）；对 100 章真人长篇误拦达 **22.0%**；
   - `story-review` 把所有短篇平台塞进单一 `zhihu.md`（偏余韵）并叠加 `quality-rubric.md`（把套路化开局判 S2/S3）；`story-deslop` 的 `short-deslop.md` 未接入 `story-review` 与 `narrative-writer`，且三层去味（`expression`/`narrative-focus`/`story-logic`）与旧 `banned-words.md` 把网文常见短段、直给反应和围观震惊当 AI 味清掉。
3. **拆文与对标链路剥离了真实网文语感**：
   - `story-short-analyze` 混入《故事会》与纸媒赏析口径（`结尾余韵`/`主题意象群`/`潜台词率`/`价值观传达`）；`story-short-write/references/benchmark-recall.md` 明确禁止参考对标腔调且不向写正文注入原文切片；
   - `story-long-analyze` 维护 6 套重叠编号（`EV/RV/AX/RH/TR/EM`），Stage 1 与 Stage 6 缺少竖屏段长、对话占比与原文切片的硬抽取。
4. **流派覆盖与语料真实分布错位**：
   - 短篇缺口最大的是 `男频都市反杀`（7.8k+，黑岩 26.4%、七猫都市 17.6%，98% 第一人称、84% 明账清算）、`年代重生打脸`（10.5k，全四平台 10–15%）与正剧/轻喜双轨 `脑洞设定流`（10.4k，知乎 24%，原 `沙雕脑洞` 窄化到仅占 1.3% 的纯沙雕），而 `民俗怪谈` 仅占 1.9%；长篇 33 张碎片卡中多张低 ROI 且无连续原文示范切片。

## Decision

统一以**「精简自包含流程核 + 真网感流派包（内置 2–3 段 150–250 字竖屏示范切片）+ 语料校准门禁」**重构写作、拆文、去味、审稿、导入与部署适配层：

1. **短篇写作重构（`skills/story-short-write/`：29 → 16 文件，热路径 33.3K → ~10K，-70%）**：
   - 将原 15 份非流派参考（`workflow-*`、`short-craft`、`scene-craft`、`short-format`、`submission-craft`、`emotional-methods`、`short-reversal`、`villain-and-reveal`、`hooks-chapter`、`genre-writing-formulas`、`short-deslop`、`dialogue-mastery`、`banned-words`）折叠、下沉至对应流派或解绑删除；
   - 重写自包含 `SKILL.md`（~6.5K，覆盖核心笔法、竖屏单句段排版、5 平台速查表、导语冷开场与 30–40% 付费卡点、40% 连环打脸、明账清算与反样板收尾、Phase 1–4 白话模板与便携 Node 计字命令），同会话走完 Phase 1–4 消除上下文驱逐；仅留 3 份按需冷路径文件（`benchmark-recall.md` 升级为注入 2–3 段原文语感切片并解除同题材腔调禁令、`author-memory.md`、`agent-calls.md`）；
   - 流派包重构为 **12 份**（升级 8 份 + `沙雕脑洞`→`脑洞设定流` + 合并 `民俗怪谈` 进唯一保留公平推理/留白的 `悬疑.md` + 新增 `年代重生打脸`、`男频都市反杀`、`通用短篇` 兜底），每包均附 2–3 段 150–250 字竖屏语感切片。
2. **长篇写作流程化重构（`skills/story-long-write/`：71 → 25 文件，热路径降至 ~12–20K）**：
   - 将分散的写作、开书、大纲、钩子、反转、爽点、对话与追踪参考收口为 4 份按时刻加载的流程手册（`flow-opening-plan.md`、`flow-outline.md`、`flow-drafting.md`、`flow-revision.md`）+ `benchmark-recall.md`、`agent-calls.md`、`tracking-protocol.md`、`author-memory.md`；
   - 将 33 张 `genre-prose-cards/` 重构为 **16 份** `references/genre-styles/*.md`（8 男频 + 7 女频/泛题材 + `通用长篇.md` 兜底，含 2–3 段真网感切片）；
   - 更新 `build_writer_prompt.js` 与 `build_architect_brief.js`：切换至 `genre-styles/` 与 `flow-*.md`，并确保**即使「召回降档」成立也强制注入 1–2 段原文语感切片**（对标 `文风.md` 优先，无对标取流派包切片）。
3. **检测器、标点清洗、写后钩子与契约脚本按语料校准（`--mode=auto|long|short`）**：
   - `check-ai-patterns.js`、`normalize-punctuation.js`（及 4 份共享副本）与 `story_hook_core.js`（及 5 端共享副本）支持 `--mode=auto|long|short`（`正文.md` 自动识别为 `short`，`正文/第*章*.md` 为 `long`）：
     - **短篇模式**：旁白 `——` 降为密度 `advisory`（`≥6` 且 `≥1.5/k`）并在 `normalize-punctuation.js` 中保留标准 `——`；拆分 `trailer-ending` 豁免具体信息差剧透（`他不知道的是/殊不知/没人知道/谁也没想到` 降 `advisory`），写后钩子在 `<6,000` 字分批草稿上跳过 `trailer-ending` 并改软提示措辞；`not-is` 升至 `5*scale`（min 6）；跳过 `overcompressed-prose-tic` 与 `low-connective-density-tic`；`period-stutter` 升至 9；`quote-emphasis-tic`/`negation-pair-tic` 按 `scale` 缩放；`stock-reaction-tic` 升至 `8 & 3.0/k`；`long-paragraph` 收紧至 `100` 字（抓散文砖块）；
     - **长篇模式**：同步按 270 本热书实测校准（旁白 `——` 与短效反应不再误拦，真长篇 100 章误拦由 22.0% 降至 **2.0%**；短篇 120 篇误拦由 35.0% 降至 **0.83%**）；
   - `check-phase2-contract.js` 新增 `advisory` 级导语与 20–55% 付费点位置检查并更新模板路径至 `SKILL.md`；`check-delivery-contract.js` 新增 3 项纯结构 `advisory`（段长、对话占比、导语存在）不设情绪词/标点硬门禁。
4. **周边技能与七端部署同步收口**：
   - **`story-deslop`（10 → 5 文件）**：合并 `expression/narrative-focus/story-logic/deslop-gates` → `deslop-guide.md`，分层重写 `banned-words.md`（Tier 1 真 AI 腔 vs Tier 2 语境词），将 `agent-calls.md` 折入 `SKILL.md`，强化 `short-deslop.md` 为显式覆盖矩阵并同步至 `story-review` 与 `story-setup/agent-references/`；
   - **`story-review`（19 → 14 文件）**：拆分短篇平台表为 `rubrics/zhihu.md`（盐言）与新建 `rubrics/short-shuang.md`（番茄/七猫/黑岩/点众/小程序/未定），长篇 `fanqie.md` 同步覆盖七猫，校准 `quality-rubric.md` 豁免商业套路开局，将修订追踪折入 `review-tracking.md`；
   - **`story-short-analyze` / `story-long-analyze` / `story-import`**：短篇拆文清除《故事会》与文学赏析维度，改为网感五维评分 + `[BLOCK]` 抽取「量化网感体检表 + 3 段 150–250 字原文语感切片」；长篇拆文（12 → 10 文件，-30.1%）在 Stage 1/6 加入黄金三章与竖屏网感体检及原文切片、Stage 3 收拢为 `RH/TR` + `EM` 双索引；导入（13 → 8 文件，-35.8%）折叠零散参考并同步新版长/短篇模板；
   - **`story-setup` 与中央注册表**：清理 `agent-references/` 中 17 份过时文件与 33 张旧卡，接入 `deslop-guide.md`、`short-deslop.md`、`flow-opening-plan.md`、`flow-outline.md`、`flow-drafting.md`、`benchmark-recall.md` 与 16 份长篇 `genre-styles/`；更新 `templates/agents/{narrative-writer,character-designer,story-architect}.md`、`agent-reference-profiles.md`、`scripts/shared-references.json`、`scripts/doc-budget.json` 及 OpenCode / Codex / ZCode 适配产物。

## Alternatives considered

- **在原有 18 份短篇参考与 71 份长篇参考上继续局部打补丁，不合并文件**：最强理由是无需改动 `doc-budget.json`、测试路径指针与 `agent-references/` 映射。不采用：多文件分散导致 9 处跨文件规则打架与 33K 上下文上限驱逐（实测 `2026-11-03` 定位试验输给无 skill 原生模型 0:8），局部改词无法根治结构性漂移。
- **把 `story-short-write/references/` 彻底清零（连 `benchmark-recall.md`、`author-memory.md`、`agent-calls.md` 也全部删掉或塞进 `SKILL.md`）**：最强理由是目录极简。不采用：`author-memory.md` 与 `story-long-write` 共享协议（3.6K，仅独立管理习惯时读），`benchmark-recall.md`（1.4K）与 `agent-calls.md`（0.9K）在默认单人直写时不加载；保留为 3 份冷路径按需文件让默认热路径保持在 ~9.5K–10K，不牺牲扩展能力。
- **把 14 项网感语料指标（感叹号密度、情绪词频、Q3–Q5 打脸比）直接写进 `check-delivery-contract.js` 硬阻断**：最强理由是运行期可强约束输出风格。不采用：违反本仓「确定性硬底线 + 有摩擦软门禁」与反指标博弈原则，易诱发模型机械堆感叹号和口号词；将其留在离线实验评测基准中，运行期仅留 3 项纯结构 `advisory`。

## Consequences

- **收益**：
  - **上下文大幅瘦身**：短篇全流程从 33.3K（且拆两次对话）降至 ~10K–12.5K（单对话连续完成，-65%+）；长篇 71 → 25 文件，立项/细纲/日更/大修全线低于 21K；去味 20.7K → ~10K；审稿 solo 29.4K → ~17K；所有路径远低于 35K `path_ceiling`。
  - **检测器误报骤降**：真人短篇 120 篇 `review_required` 误拦 **35.0% → 0.83%**，真人长篇 100 章误拦 **22.0% → 2.0%**，同时保持退化硬底线与真 AI 腔拦截力。
  - **写作实测验证**：
    - 新版 `story-short-write` 三篇盲写实验（S1 七猫/点众世情断亲、S2 知乎盐言脑洞弹幕、S3 黑岩/七猫男频反杀）在 MongoDB `novel` `ALL_CLEAN N=380` P25–P75 门禁上 **3/3 整体 PASS**（总字数 9.4k–9.7k、段中位 20–24 字、单句段 86–95%、`>80` 字 0%、对话 37–44%、首百字入冲突、0 纯景物开篇、非末节 100% 卡点、人工读感 9.0–9.3/10），且 `check-ai-patterns --mode=short` 零 `review_required`；
    - 新版 `story-long-write` 三组黄金三章盲写实验（L1 番茄男频都市系统 9.3/10、L2 番茄男频都市高武 9.4/10、L3 七猫女频古言宅斗重生 9.3/10）在 MongoDB `novel` 270 本热书 P25–P75 门禁上 **9/9 章全部 PASS**（单章 2,243–2,431 字、段中位 24–25 字、`≤50` 字占 97–99.7%、`>80` 字 0%、单句段 88–97%、对话 23–37%、3/3 强章尾钩、0 纯景物开篇），且 `check-ai-patterns --mode=long` **0 blocking / 0 review_required**（9 章合计仅 2 条 advisory）。
- **代价与兼容边界**：
  - 历史文档或外部脚本若直接引用已删除的内部参考文件名（如 `short-format.md`、`workflow-design.md`、`workflow-chapter.md`、`expression.md`、`genre-prose-cards/`），需改指新的 `SKILL.md` / `flow-*.md` / `deslop-guide.md` / `genre-styles/`；老项目已落盘的 `设定.md`、`小节大纲.md`、`细纲_*.md`、`卷纲_*.md` 与旧字段名均在脚本解析层保持向后兼容。
  - 变更了共享参考、共享运行时脚本与写手/架构师/角色师模板，须同步提交 `sync-shared-assets.py`、`shared-references.py` 与 OpenCode / Codex / ZCode 生成产物，并在用户项目升级时通过 `/story-setup` 清理旧的 `agent-references/` 孤儿文件。
