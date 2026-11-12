# Agent Note: 对照网文真实语料校准长篇写作规则自洽性、标点清洗与去味阻断阈值

Status: implemented
Date: 2026-11-12
Related: [长篇写作 0.10.0 清理与解耦](2026-11-03-long-write-0-10-cleanup.md)、[放开正文情绪直写与人物算账](../bug-fix/2026-11-12-prose-action-thought-balance.md)、[去味单章机械与语义分级](../bug-fix/2026-09-27-deslop-one-grading.md)

## Problem

在修复 Issue #540（手眼道具小动作泛滥与压制心理算账）后，对 `skills/story-long-write/` 全量文件及耦合的写手/审稿 agent 模板、标点清洗脚本和去味检测器做逐文件自洽性与网文语料（MongoDB `novel` 库 970 本长篇 / 5,458 章跨番茄、七猫、纵横，以及 800 章真人正文误报抽检）核查，发现四类失准与前后打架的问题：

1. **内部字段名与规则互相打架**：
   - 0.10 已将细纲字段改为白话（`这场谁说话多`、`原样出现的原话`、`行动代价与好处归谁`）并将 `逻辑线` 标为可省略，但 `consistency-checker.md` 仍要求必查旧名 `逻辑线` 和 `行动成本（可无）/收益归属`（缺了就报「证据不足」），`narrative-writer.md` 与 `build_writer_prompt.py` 仍只认旧名 `复沓锚句`、`镜头准入`；
   - `long-format.md` 与 `writing-craft.md` 在引号样式、省略号破折号保留范围上表述不一；`long-chapter-hooks.md` 的「反派逼近型」章尾钩子、`long-suspense.md` 的「观众先行」与 `writing-craft.md` 的严格单人限知视角直接冲突；`opening-design.md` 同页既允许金手指第 1–3 章生效又规定「第 1 章必须立刻有用」，既要求日常种田甜宠也塞「身家性命」筹码又一刀切禁世界观与插叙。
2. **标点清洗与排版基准脱离移动端网文常态**：
   - 5,458 章真人样本中，叙述段非引号 `……` 出现在 **32.7%** 的章节（番茄高达 **47.8%**，P90 达 3.0/千字），系统面板 `【……】` 普遍含省略号，对话引号内 `——`（话被打断或拖音）出现在 **13.3%** 的章节，直角引号仅占 **1.0%**（弯引号 `“”` 占 86.2%、ASCII 直引号 `""` 占 12.8%）；而 `normalize-punctuation.js` 一律把引号外的 `……` 和引号内的 `——` 替换成逗号句号，既抹平系统面板与人物思绪停顿，又与网文对白打断习惯相反；
   - `storyctl.py` 的碎度基准（短段占比 `19%`、叙述句长中位数 `39` 字）此前仅取自七猫 3 本书前 30 章，且 `_QUOTED` 未识别 `""`、按整篇切句把无句末标点的独立段跨段粘连；在 970 本书 5,458 章（修正跨段粘连与直引号后）中，真实中位数为短段占比 **38%**（P10–P90 `16%–62%`，番茄中位数 `43%`）、叙述句长中位数 **23 字**（P10–P90 `15–35` 字）；`writing-craft.md`「全章只留一两处单句成段」把移动端正常的单句独立段与「把连贯动作劈成三四行电报体」混为一谈。
3. **去味检测器与写后钩子把真人常用修辞设为 1 处即阻断**：
   - 在 800 章真人正文中，`check-ai-patterns.js` 默认阻断率高达 **27.9%（223/800 章）**（经 `normalize-punctuation.js` 后仍达 **19.1% / 153 章**）：`em-dash`（11.9%，含大量对白引号内的 `——`）、`not-is-comparison`（6.9%）、`voice-contrast`（4.8%）、`trailer-ending`（4.5%）、`reverse-not-is`（4.4%）、`negation-parade`（1.4%）；同时 `story_hook_core.js` 与 `story_codex_hook.py` 对上述句式同样 1 处即记「毒句式」并在 `PreToolUse` 欠账门拦截下一章写作；
   - `check-ai-patterns.js` 与 `check-degeneration.js` 在阻断时调用 `process.exit(1)`，当 `--json` 输出超过 64KB 管道缓冲时会截断 stdout JSON；`quote-emphasis-tic` 漏排了引号内 ASCII `...`、常见说话动词（`笑/叹/应/哼/开口/摇头/点头`）和拟声词（`“唰”的一声`）。
4. **部分题材与人物教条以偏概全**：
   - 快节奏平台单章字数写 `1500–2000 字` 贴近番茄 2000 字底线，易因小幅欠字跌破平台全勤/分章门槛；`dialogue-mastery.md` 仍残留 `择菜、收拾物件` 凑动作建议和单轮禁纯对话教条；`character-basics.md` 强制主要角色都有口头禅、群像/朝堂场最多三人开口、最终 Boss 第 1 章必埋伏笔；`character-relations.md`、`workflow-outline.md`、`genre-readers.md`、`banned-words.md` 及女频悬疑、都市修真题材卡各有脱离主流子流派惯例的死规定。

## Decision

1. **打通内部契约与视角、开篇、题材边界**：
   - `consistency-checker.md`、`narrative-writer.md`、`build_writer_prompt.py` 兼容 0.10 新旧细纲字段名（`这场谁说话多`/`镜头准入`、`原样出现的原话`/`复沓锚句`、`行动代价与好处归谁`/`行动成本`），`逻辑线` 与代价归属省略时按情节点、章末变化与正文因果核查，不报「证据不足」；
   - `writing-craft.md`、`long-chapter-hooks.md`、`long-suspense.md`、`流派兜底.md` 区分网文主流「第三人称贴身/有限全知视角」（锚定主视角，允许同场众人反应镜头与章尾切一镜反派/远方动向，禁止同场乱跳多人内心）与第一人称/严苛悬疑的「严格单人限知」；
   - 校准 `story-architect.md`、`opening-design.md`、`outline-template.md`、`long-chapter-quality.md`、`dialogue-mastery.md`、`character-basics.md`（含 `agent-references/` 派生副本）、`character-relations.md`、`outline-methods.md`（快节奏常见 `2100–2300 字`，未指定时建议排纲目标 `2200 字`）、`workflow-outline.md`、`genre-readers.md`（含派生副本，补七猫 14–18 字书名说明）、`banned-words.md` 及女频悬疑、都市修真题材卡。
2. **按真实网文排版校准标点清洗、引号与碎度基准**：
   - `long-format.md` 默认使用中文弯引号 `“…”`（内嵌 `‘…’`），`normalize-punctuation.js` 新增 `--quote-mode curly`（默认仍为 `keep`）；
   - `normalize-punctuation.js` 在对话引号内、系统面板 `【…】` 内及叙述旁白中保留标准 `……`，只把非标省略号（`...`、单 `…`、`………+`、`。。。+`、`.……..`）规整为 `……`；保留对话引号内的破折号（统一为 `——`，粘连 `——……` 收束为 `……`），叙述旁白非引号破折号仍替换为中文标点；`writing-craft.md` 放开正常问句/反问/盘算用 `？` 与重拍用 `！`，把移动端正常单句成段与电报体切句区分开；
   - `storyctl.py` 补入 ASCII 直引号与 `『』` 剥离并按段切句（含 `…`），真人参照更新为 970 本书 5,458 章实测值：短段占比 `0.38`（`0.16–0.62`）、叙述句长中位数 `23` 字（`15–35` 字）。
3. **去味检测器与写后钩子统一改为「低频语义提示 + 高频机械阻断」**：
   - `check-ai-patterns.js` 对 `em-dash` 豁免对话引号、未闭合台词段与 `【…】` 面板内命中；将 `not-is-comparison + reverse-not-is`（合计 ≥3 处阻断，1–2 处语义提示）、`voice-contrast`（≥2 处阻断，1 处提示）、`negation-parade`（≥2 处阻断，1 处提示）、`trailer-ending`（章尾 ≥2 处阻断，1 处提示）改为按章密度分级，`trailer-summary` 与旁白 `em-dash` 保持 1 处阻断；
   - 新增叙述段省略号密度提示 `ellipsis-density-tic`（引号与面板外 `……` ≥6 处且 ≥3.5/千字报 `advisory` / `semantic`，同步 `expression.md`）；优化 `quote-emphasis-tic` 排除规则与 `voice-contrast` 修稿文案；`check-ai-patterns.js` 与 `check-degeneration.js` 将 `process.exit(1)` 改为 `process.exitCode = 1` 防止大体积 JSON 截断；
   - 同步 `story_hook_core.js`、`story_codex_hook.py` 与 `check-hook-regex-sync.sh` 的毒句式计数门槛与修稿提示，消除检测器与写后钩子/欠账门的口径分叉，并重新生成 OpenCode、Codex、ZCode 适配层。

## Alternatives considered

- **继续在 `normalize-punctuation.js` 里把旁白 `……` 全部替换成逗号，只豁免 `【……】` 面板**：实现最小，但真人网文近三分之一章节（番茄近半数）在自由间接引语和悬念停顿处正常使用旁白 `……`，一刀切替换会把人物犹豫和留白压平；改为规整非标省略号并由 `ellipsis-density-tic` 在刷屏（≥6 处且 ≥3.5/千字，高于番茄 P90 的 3.0/千字）时提示，既保住正常留白又防模型滥用。
- **直接把 `not-is-comparison`、`voice-contrast`、`trailer-ending` 从阻断降为纯 `advisory`，不设高频阻断线**：能把真人误报降到最低，但模型一旦失控仍会在单章连刷四五处「不是A而是B」或两三段预告腔收尾；按真人语料分布设置单章阈值（真人偶发 1 处占绝大多数，单章连刷极少），兼顾低误报与机械兜底。
- **只改 `check-ai-patterns.js`，不动 `story_hook_core.js` 和 `story_codex_hook.py`**：改动面更小，但写后钩子与 `PreToolUse` 欠账门独立维护了一套 `TOXIC_SENTENCE_PATTERNS`，一旦钩子仍按 1 处记毒句式，单处正常修辞照样会锁死下一章创建，形成双轨脑裂。

## Consequences

- **收益**：消除 0.10 细纲白话化后的子代理字段断层与技法前后矛盾；保留对白打断 `——`、面板 `【……】` 与正常旁白留白；修复 >64KB JSON 管道截断；在 800 章真人正文（番茄 400 + 七猫 400）回测中，`storyctl chapter check` 完整链路（`normalize-punctuation.js` → `check-ai-patterns.js --fail-on=blocking`）的真人误拦率从 **19.1%（153/800 章）** 降至 **1.12%（9/800 章）**，相对下降 **94.1%**（其中标点归一后 `em-dash`、`trailer-ending` 与 `negation-parade` 误拦全部归零，`voice-contrast` 降至 0.12%，`not-is + reverse-not-is` 降至 1.12%，标点清洗触碰章节从 79.4% 降至 43.75% 且仅改动非标省略号与旁白破折号）。
- **代价**：新增 `ellipsis-density-tic` 与钩子侧密度阈值后，需同步维护 `expression.md`、四端检测器副本、JS/Python 双端钩子常量同步守卫（`check-hook-regex-sync.sh`）及相关回归测试。

## Verification

- 800 章真人语料（MongoDB `novel` 库番茄 400 章 + 七猫 400 章）前后回测：标点归一后 `check-ai-patterns.js --fail-on=blocking` 误拦从 `153/800`（`19.1%`）降至 `9/800`（`1.12%`，`em-dash` 误拦 `0/800`）；裸扫非 `em-dash` 误拦从 `153/800`（`19.1%`）降至 `9/800`（`1.12%`）；`quote-emphasis-tic` 提示率从 `21.6%` 降至 `13.0%`；新增 `ellipsis-density-tic` 提示率 `8.12%`。
- 本地全套 CI 守卫与回归测试（静态检查、文档预算、编号守卫、共享文件与正则同步、标点归一、AI 句式检测、写后钩子与四端 parity、白名单优先级、`storyctl` 与完章生命周期、写手管道、七端 CLI 适配器）全部通过。
