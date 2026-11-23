# Agent Note: 长短篇写作与周边技能流程化重构（流程核 + 流派包 + 检测审稿校准）

Status: implemented
Date: 2026-11-22
Related: [非长篇写作 13 个 Skill 平台与节奏校准](2026-11-12-non-long-write-skills-calibration.md)、[长篇写作规则自洽性、标点清洗与去味阈值校准](2026-11-12-long-write-corpus-calibration.md)、[确定性硬底线与有摩擦软门禁分层](2026-11-21-deterministic-hard-floor-and-soft-gates.md)

## Problem

在持续的长短篇写作与评审实践中，现有技能体系暴露出四个系统性瓶颈，导致生成正文容易偏离当代网文竖屏阅读节奏、滑向传统书面散文腔：

1. **短篇与长篇指令过度碎片化且存在跨文件规则冲突**：
   - `story-short-write` 将核心规则拆散至 `SKILL.md` 与 18 份非流派参考，热路径上下文体积偏高、迫使 Phase 2→3 切换会话（构思阶段的导语、付费卡点与反派约束在写正文时被挤出上下文），且多份参考在情绪节奏、反转手段与对话直白度上存在直接矛盾；
   - `story-long-write` 分散为 71 份文档（含 33 张细分题材卡），写正文时在「召回降档」路径下会跳过原文语感切片，部分旧写作参考仍偏向传统段长与克制反应。
2. **检测器、写后钩子、审稿与去味口径未区分长短篇特征**：
   - 旧版 `check-ai-patterns.js`、`normalize-punctuation.js` 与写后钩子按单一长篇默认口径检查短篇，对竖屏短段、功能性旁白破折号 `——`、直给情绪与常见反应短语存在较多误报，且未按短篇整篇篇幅缩放密度阈值；
   - `story-review` 将全部短篇平台归入偏余韵的单一 `zhihu.md`，`quality-rubric.md` 对商业经典开局范式偏严；`story-deslop` 的 `short-deslop.md` 未同步接入 `story-review` 与 `narrative-writer`，三层去味参考分散且易将正常网文短段与直白交锋误判为 AI 味。
3. **拆文与对标链路未能有效传递语感**：
   - `story-short-analyze` 残留传统纸媒赏析口径，缺少结构化的网感体检指标与连续原文切片；`story-short-write/references/benchmark-recall.md` 禁止参考同题材对标腔调且不向正文阶段注入原文切片；
   - `story-long-analyze` 维护多套重叠编号（`EV/RV/AX/RH/TR/EM`），Stage 1 与 Stage 6 缺少竖屏段长、对话占比与原文切片的硬抽取。
4. **流派覆盖与实际网文题材结构错位**：
   - 短篇缺少高频商业赛道（男频都市反杀、年代重生打脸）与覆盖正剧/轻喜双轨的脑洞设定流，`民俗怪谈` 体量过窄；长篇 33 张旧题材卡粒度过细且缺少可供写前校准的连续示范片段。

## Decision

统一以**「精简自包含流程核 + 带示范切片的流派包 + 区分长短篇的检测与审稿标准」**重构写作、拆文、去味、审稿、导入与七端部署适配层：

1. **短篇写作重构（`skills/story-short-write/`：29 → 16 文件）**：
   - 将原 15 份非流派参考（`workflow-*`、`short-craft`、`scene-craft`、`short-format`、`submission-craft`、`emotional-methods`、`short-reversal`、`villain-and-reveal`、`hooks-chapter`、`genre-writing-formulas`、`short-deslop`、`dialogue-mastery`、`banned-words`）折叠、下沉至流派包或解绑清理；
   - 重写自包含 `SKILL.md`（覆盖核心笔法、竖屏单句段排版、5 平台速查表、导语冷开场与 30%–40% 付费卡点、中后段连环反击、明账清算与反样板收尾、Phase 1–4 白话模板与便携 Node 计字命令），支持单会话连贯跑完 Phase 1–4；仅留 3 份按需冷路径文件（升级 `benchmark-recall.md` 注入 2–3 段原文语感切片、`author-memory.md`、`agent-calls.md`）；
   - 流派包重构为 **12 份**（升级 8 份 + `沙雕脑洞`→`脑洞设定流` + 合并 `民俗怪谈` 进唯一保留公平推理/留白的 `悬疑.md` + 新增 `年代重生打脸`、`男频都市反杀`、`通用短篇` 兜底），每包均附 2–3 段 150–250 字竖屏示范切片。
2. **长篇写作流程化重构（`skills/story-long-write/`：71 → 25 文件）**：
   - 将原分散参考按写作时刻收口为 4 份流程手册（`flow-opening-plan.md`、`flow-outline.md`、`flow-drafting.md`、`flow-revision.md`）+ `benchmark-recall.md`、`agent-calls.md`、`tracking-protocol.md`、`author-memory.md`；
   - 将 33 张 `genre-prose-cards/` 整合为 **16 份** `references/genre-styles/*.md`（9 男频 + 6 女频与双男主 + `通用长篇.md` 兜底，含示范切片）；
   - 更新 `build_writer_prompt.js` 与 `build_architect_brief.js`：切换至 `genre-styles/` 与 `flow-*.md`，并确保即使在「召回降档」路径下也保留 1–2 段原文语感切片注入（对标 `文风.md` 优先，无对标取流派包切片）。
3. **检测器、标点清洗、写后钩子与契约脚本统一长短篇策略**：
   - `check-ai-patterns.js`（共 4 份共享副本）支持 `--mode=auto|long|short`（`正文.md` 附同目录 `设定.md`/`小节大纲.md` 自动识别为 `short`，`正文/第*章*.md` 为 `long`）；`normalize-punctuation.js`（共 4 份共享副本）为 CLI 对称接受 `--mode=auto|long|short`，长短篇统一保留标准 `——`；`story_hook_core.js`（共 5 端共享副本，无 `--mode` CLI 参数）按目标文件名 `正文.md` 内部切换短篇模式（含 Codex Stop Hook 对齐）：
     - **标点清洗统一契约**：`normalize-punctuation.js` 在长短篇模式下均保留标准破折号 `——`（拦截并修复 `—`/`———`/`——……` 等畸形破折号与独立分隔线），旁白 `——` 过密统一由 `check-ai-patterns.js` 做密度语义复核；
     - **短篇模式校准**：旁白 `——` 降为密度 `advisory`（`≥6` 且 `≥1.5/k`）；拆分 `trailer-ending` 豁免具体信息差剧透（`他不知道的是/殊不知/没人知道/谁也没想到` 降 `advisory`），写后钩子在 `<6,000` 字分批草稿上跳过 `trailer-ending` 并改软提示措辞；`not-is`、`quote-emphasis-tic`、`negation-pair-tic` 按篇幅缩放；跳过 `overcompressed-prose-tic` 与 `low-connective-density-tic`；放宽 `period-stutter` 与 `stock-reaction-tic`；收紧 `long-paragraph` 至 `100` 字以捕捉长段文字墙；
     - **长篇模式校准**：同步校准旁白 `——` 与短效反应密度阈值，降低正常快节奏网文的误报。
   - `check-phase2-contract.js` 新增 `advisory` 级导语与 20%–55% 付费点位置检查并更新模板路径至 `SKILL.md`；`check-delivery-contract.js` 新增 3 项纯结构 `advisory`（段长、对话占比、导语存在），不设情绪词或标点硬门禁。
4. **周边技能与七端部署同步收口**：
   - **`story-deslop`（9 → 5 文件）**：合并 `expression/narrative-focus/story-logic/deslop-gates` → `deslop-guide.md`，分层重写 `banned-words.md`（Tier 1 明显 AI 腔 vs Tier 2 语境词），将 `agent-calls.md` 折入 `SKILL.md`，强化 `short-deslop.md` 为显式覆盖矩阵并同步至 `story-review` 与 `story-setup/agent-references/`；
   - **`story-review`（16 → 14 文件）**：拆分短篇平台表为 `rubrics/zhihu.md`（盐言）与新建 `rubrics/short-shuang.md`（番茄/七猫/黑岩/点众/小程序/未定），长篇 `fanqie.md` 同步覆盖七猫长篇，校准 `quality-rubric.md` 豁免有具体冲突与钩子的商业经典开局范式，将修订追踪折入 `review-tracking.md`；
   - **`story-short-analyze` / `story-long-analyze` / `story-import` / `story-short-scan`**：短篇拆文清除纸媒赏析口径，改为网感五维评分并抽取量化网感体检表与 3 段 150–250 字原文语感切片；长篇拆文（12 → 10 文件）在 Stage 1/6 加入黄金三章体检与原文切片、Stage 3 收拢为 `RH/TR` + `EM` 双索引；导入（13 → 8 文件）折叠零散参考并同步新版长短篇模板；短篇扫榜对齐新题材分类；
   - **`story-setup` 与中央注册表**：清理 `agent-references/` 中过时文件与 33 张旧卡，接入 `deslop-guide.md`、`short-deslop.md`、`flow-opening-plan.md`、`flow-outline.md`、`flow-drafting.md`、`benchmark-recall.md` 与 16 份长篇 `genre-styles/`；更新 `templates/agents/{narrative-writer,character-designer,story-architect}.md`、`agent-reference-profiles.md`、`scripts/shared-references.json`、`scripts/doc-budget.json` 及 OpenCode / Codex / ZCode 角色模板与五端 Hook。

## Alternatives considered

- **在原有 18 份短篇参考与 71 份长篇参考上继续局部打补丁，不合并文件**：最强理由是无需大范围更新 `doc-budget.json`、测试路径指针与 `agent-references/` 映射。不采用：多文件分散本身就是规则冲突与上下文驱逐的结构性根因，局部改词无法消除跨文件互相抵消的问题。
- **把 `story-short-write/references/` 彻底清零（将 `benchmark-recall.md`、`author-memory.md`、`agent-calls.md` 全部删掉或内联进 `SKILL.md`）**：最强理由是目录结构最极简。不采用：`author-memory.md` 需与 `story-long-write` 保持共享协议，且这 3 份文件在默认单人直写路径下零加载；保留为冷路径按需文件既让热路径维持轻量化，又不牺牲对标、记忆与子代理扩展能力。
- **把感叹号密度、情绪词频等文风统计指标直接写进 `check-delivery-contract.js` 硬阻断**：最强理由是运行期可强约束输出风格。不采用：违反本仓「确定性硬底线 + 有摩擦软门禁」与反指标博弈原则，容易诱发模型机械堆砌感叹号或口号词；运行期仅保留纯结构 `advisory` 提示。

## Consequences

- **收益**：
  - **上下文显著瘦身**：短篇全流程从需拆两次对话收敛为单会话完成，热路径体积大幅下降；长篇 71 → 25 文件、去味 9 → 5 文件、审稿 16 → 14 文件，所有调用路径均远低于 35K `path_ceiling` 上限。
  - **规则自洽且误报显著下降**：消除短篇跨文件冲突与长短篇混用口径；检测器与审稿标准对正常网文竖屏短段、直给情绪与功能性旁白破折号更加友好，同时维持退化硬底线与明显 AI 腔拦截力。
  - **示范切片直通正文**：拆文与流派包均提供连续原文示范切片，写作任务包在降档路径下也能保留语感锚点。
- **代价与兼容边界**：
  - 仓库文档或外部脚本若直接引用已删除的内部参考文件名（如 `short-format.md`、`workflow-design.md`、`workflow-chapter.md`、`expression.md`、`genre-prose-cards/`），须同步改指新的 `SKILL.md` / `flow-*.md` / `deslop-guide.md` / `genre-styles/`；老项目已生成的 `设定.md`、`小节大纲.md`、`细纲_*.md`、`卷纲_*.md` 及旧字段名在脚本解析层保持向后兼容。
  - 变更了共享参考、共享运行时脚本与写手/架构师/角色师模板，已同步提交 `sync-shared-assets.py`、`shared-references.py` 与各端生成产物，并将 `agents_version` 提升至 `46`，提示已有用户通过 `/story-setup` 刷新助手与 Hook 并清理旧的 `agent-references/` 残留文件。
