# Agent Note: 对照网文真实语料与平台现况校准非长篇写作 13 个 Skill 的教条规则、陈旧契约与检测阈值

Status: implemented
Date: 2026-11-12
Related: [对照网文真实语料校准长篇写作规则自洽性、标点清洗与去味阻断阈值](2026-11-12-long-write-corpus-calibration.md)、[放开正文情绪直写与人物算账](../bug-fix/2026-11-12-prose-action-thought-balance.md)、[短篇写作 0.10.0 清理](2026-11-03-short-write-0-10-cleanup.md)

## Problem

完成 `story-long-write` 的情绪通道放开（#543）与真人语料标点/去味校准（#544）后，对其余 13 个 Skill（`story-short-write`、`story-deslop`、`story-review`、`story-setup`、`story-long-analyze`、`story-short-analyze`、`story-import`、`story-long-scan`、`story-short-scan`、`story-publish`、`story-cover`、`story`、`browser-cdp`）做逐文件核查，并在 `node38` 真实语料（24,012 篇短篇元信息、2,744 篇完结短篇正文、500 篇短篇检测器回测、133 本完结长篇共 151,785 章）与平台证据（`docs/evidence/fanqie/`、OpenAI Images API 规格）上验证，发现五类失准问题：

1. **短篇单文件篇幅下的检测器阈值与退化误报**：
   - #544 将 `not-is-comparison + reverse-not-is`（≥3）、`voice-contrast`（≥2）、`negation-parade`（≥2）改为按「单章文件」固定次数阻断，在 2,200 字长篇单章上误拦降至 `1.12%`；但短篇整篇约 10,000 字写在单个 `正文.md` 内（相当于 3–4 章容量），500 篇真人完结短篇回测（中位 8,778 字）显示非破折号阻断误报达 **9.40%（47/500 篇）**（其中 `not-is + reverse-not-is` 占 `6.00%`、`voice-contrast` 占 `2.80%`、`negation-parade` 占 `1.20%`）；写后钩子 `story_hook_core.js` / `story_codex_hook.py` 存在同一固定次数失配；
   - `check-degeneration.js` 与写后钩子的 Tier-1 工程词正则裸写 `情节点`，把穿书/快穿常见剧情词 `剧情节点`（2,744 篇短篇命中 3 处，裸 `情节点` 为 0 处）判为 `blocking` 工程词泄漏；`findMetaLeak` 只豁免文件首行章节标题，把短篇正文中间的 `第二章 心痛` 等分节标题报成 `advisory:meta-leak`（`119/500 = 23.80%`）；`findTruncation` 与钩子收尾检查未跳过 `-完-`、`（全文完）`、`＜完结＞` 等完结落款行（2,742 篇短篇占 `329` 篇 / `12.00%`），造成 `blocking:truncated` 误报（`12/500 = 2.40%`）。
2. **短篇排版、平台规则与范文同 #543/#544 及事实证据冲突**：
   - `story-short-write` 的 `short-format.md`、`submission-craft.md`、`workflow-draft.md` 仍规定默认使用英文直引号 `""`；但在 2,744 篇真人短篇正文中，中文弯引号 `“…”` 占 **91.62%（2,514 篇）**、直角引号 `「」` 占 **6.85%（188 篇）**，纯 ASCII 直引号仅占 **0.66%（18 篇）**；
   - `submission-craft.md` 声称番茄短故事「免费阅读，没有付费墙」，与 `docs/evidence/fanqie/fanqie-short-settings-2026-10-28.png` 及 `story-publish/references/fanqie-short.md` 的「试读比例」后台截图直接矛盾；
   - `short-format.md` 写「九成段落在 36 字以内」（2,744 篇实测 P50 为 `22` 字，`≤36` 字占 **85.1%**、P90 为 `41` 字），`scene-craft.md` 把移动端正常的一句一段与三五字切碎残句混同；10 份 `genre-styles/*.md` 全部把标点要求指向已迁出标点章节的 `short-craft.md`；`short-craft.md`、`宅斗宫斗.md`、`总裁豪门.md`、`悬疑.md` 的正面范文亲自示范了违禁句式、旁白破折号与「指甲掐掌心」套话；多处短篇参考把字节系短剧平台「红果」误列为独立短篇小说投稿平台；`check-phase2-contract.js` 不认 `番茄短故事`，且把冷门题材必填的 `- 参照的结构：…` 算进「2–3 个套路」计数导致误判超标。
3. **审稿、部署与共享规则残留旧长句教条、微动作补偿和 0.10 前字段**：
   - `story-review/SKILL.md` 与 `quality-rubric.md` 仍要求「叙述默认是逗号长句，短句只作偶尔的孤立重拍」，并把单章无硬阻碍或无高潮一律判 S2，同长篇 `38%` 短段占比、短篇 `22` 字中位段长及日常/种田/过渡章规律冲突；
   - `story-setup` 的 `story-outline.md` 仍把已降为可选的 `逻辑线`、`事件线/任务线`、`行动成本` 列为必填且漏掉 `分场`；`story-format.md` 与 `format-and-structure.md` 残留直引号默认、端茶杯动作凑标签及省略号/破折号冲突条款；`long-emotional-methods.md`（与 `story-long-write/references/emotional-methods.md` 派生同步）仍写「删掉形容词，写她的手在抖、水洒了一地」；`generic/openclaw/reasonix` 模板仍写「对照禁用词表自检、改净」逼模型逐词替换。
4. **拆文与导入对篇幅、章节结构及半成品边界过于死板**：
   - `story-import/references/length-routing.md` 把「含 ≥5 个章节标记且 <3 万字」初判为长篇，而完结短篇中仅算 `第\d+章` 就有 **30.09%（825/2,742 篇）** 满足该条件（算上中文数字分节近九成短篇在 8–12 节、9,000–12,200 字），容易把分节短篇误导进长篇管道；
   - `story-long-analyze` 的 `build_chapter_index.py` 对正文长句里以 `第X章` 开头的行无长度过滤（133 本长篇命中 `91` 处 `>50` 字正文行），且遇作者原书章号跳号/重号即硬报错无放行开关（133 本完结长篇官方章节索引中有 **40 本 / 30.08%** 含原书章号笔误跳号）；`manage_analysis_run.py` 对 `>5,000` 字大章（`25/133` 本共 `145` 章）封死 30 个情节点上限，对原文 `quote` 含字面 `{` / `}`（`7/133` 本）误判为未填模板占位符；`author-facing.md` 与 `style-profile-generator.md` 仍把「身体反应代替心理描写」当作通用高分文风标准；
   - `story-short-analyze` 强制 `structure_counts.beats >= 4` 否则 `[BLOCK]`，卡死 `story-import` 导入 1–3 节短篇半成品的合法路径；情绪极性 `-9~+9` 与无反转分类只覆盖「憋屈→虐渣报应」，排斥甜宠、沙雕、悬疑、治愈。
5. **扫榜、发布、封面、工作台与浏览器脚本的局部偏差**：
   - `story-long-scan` 首次扫榜信心上限封死在「中」且新书题材信号混用主类样本门槛；`fanqie-rank-scraper.js` 榜单分支未优先取详情页已解码章节名（落回 PUA 乱码字段），`qimao-rank-scraper.js` 与 `dz-browse-scraper.js` 漏解析 `<1万` 读数或混入 `>5万字` 长篇；
   - `story-publish/scripts/check-publish-format.py` 用子串匹配 `建议|未定|待定|草案|暂无`，把含「律师建议」「婚期未定」「手头暂无现钱」「并购草案」的正常书名与简介误判为未填占位符，且把封面单行提示词或 Windows 路径里的冒号误判为多字段同行；
   - `story-cover` 把番茄之外平台一律算作 `2:3`、在番茄平台风格串里硬锁 `character portrait dominating frame`（与纯场景封面 `no human figure` 冲突）、强制笔名带装饰，且 `api-fallback.md` 建议在官方接口传非标 `768x1024`（易触发 400）；
   - `story` 的 `dashboard-server.mjs` 只认已有 `正文.md` 的短篇目录，Phase 2 已立项（有 `设定.md` + `小节大纲.md`）但未开写的短篇在工作台不可见；`browser-cdp/scripts/setup-cdp-chrome.js` 漏同步上层 `Local State` 解密密钥与 SQLite `-wal`/`-shm` 旁路文件。

## Decision

1. **按篇幅折算句式阻断阈值，修复退化与钩子误报（`story-deslop` + 共享副本 + 写后钩子）**：
   - `check-ai-patterns.js`、`story_hook_core.js` 与 `story_codex_hook.py` 按去空白有效正文长度折算章节当量 `scale = max(1, floor((chars + 2250) / 4500))`（单章 `≤6,749` 字时 `scale = 1`，阈值保持不变；万字单文件短篇按章当量等比放宽 `not-is`、`voice-contrast`、`negation-parade` 阻断线，低频仍保留 `advisory` 提示）；500 篇真人短篇回测非破折号阻断误报从 `47/500 (9.40%)` 降至 **`7/500 (1.40%)`**；
   - `check-degeneration.js`、`story_hook_core.js`、`story_codex_hook.py` 将 Tier-1 `情节点` 收窄为 `(?<!剧)情节点`（`blocking:meta-leak` 从 `1/500` 降至 `0/500`）；`check-degeneration.js` 豁免全文独立成行的短分节标题（`advisory:meta-leak` 从 `119/500 (23.80%)` 降至 **`8/500 (1.60%)`**），并在截断检查与钩子 `skippableLine` 中跳过完结落款行且兼容省略号收尾（`blocking:truncated` 从 `12/500 (2.40%)` 降至 **`3/500 (0.60%)`**）；
   - 同步 `story-deslop` 的 `SKILL.md`、`expression.md`、`style-resolution.md` 与 #543/#544 口径。
2. **校准 `story-short-write` 引号、平台付费点、范文与 Phase 2 校验脚本**：
   - 默认引号对齐弯引号 `“…”`（内嵌 `‘…’`，盐言或显式指定用 `「」`），修正番茄短故事「试读比例」付费断点描述与实测段长分布（P50 `22` 字、`85% ≤ 36` 字、P90 `41` 字），区分正常一句一段与三五字切碎残句；
   - 修复全部 10 份 `genre-styles/*.md` 的标点引用路径，改写 `short-craft.md`、`宅斗宫斗.md`、`总裁豪门.md`、`悬疑.md` 正面范文中的违禁句式与掐掌心套话，放宽甜宠/沙雕/悬疑/治愈在筹码、口头禅、阶梯背叛与崩溃次数上的窄化规定；
   - `check-phase2-contract.js` 兼容 `番茄短故事`，统计套路条数时排除 `- 参照的结构` 说明行；从短篇写作、拆文、导入、审稿、封面与格式覆盖表的新项目引导中移除短剧平台「红果」（仅在 `check-phase2-contract.js` 正则中保留旧项目兼容）。
3. **对齐 `story-review` 与 `story-setup`（含多端生成产物）**：
   - `story-review` 移除「默认逗号长句」要求，对齐四通道情绪落地与 #544 标点口径，按章节松紧定位审读冲突与高潮，扩充起点、番茄、知乎平台审稿细则对群像、种田日常及非报应结局的包容度；
   - `story-setup` 同步 0.10 细纲模板字段、弯引号默认、反凑微动作规则、按题材限定硬规则/取证链要求，修正 `emotional-methods.md` 派生组，补齐 Antigravity 短篇恢复规则、`UPGRADING.md` 14 个 Skill 计数及 `generic/openclaw/reasonix` 去味表述，并重跑 OpenCode、Codex、ZCode 适配生成脚本。
4. **放宽 `story-long-analyze`、`story-short-analyze`、`story-import` 的硬编码卡点**：
   - `length-routing.md` 增设「总字数 <2 万且单节均长 <1,800 字的分节文默认归短篇」判据；`build_outline_brief.py` 对已有细纲落盘的章节返修自动放行小批次（不足 10 章半成品整本已随末批规则自然通过），`check-outline-contract.js` 检测到同章 `正文/` 已落盘时自动放宽历史章节字数目标区间（1–500,000 字），不额外引入 CLI 开关；同步长短篇逆向映射说明与 0.10 字段别名（保留跨 Skill 交接契约锚点）；
   - `build_chapter_index.py` 支持可选 `#` 标题前缀、`第X回/节`（带分隔符校验防 `回合`/`节课` 误切）、逗号或无空格紧接标点的 `第X章` 标题（如 `第1章，稻花`、`第75章难道…？`）、`第X卷《卷名》第Y章` 组合标题、卷部行排除 `部分` 与句末叙述句、紧邻重复章标题去重及 `MAX_HEADING_CHARS = 50` 标题长度上限，并对原书跳号/重号直接按出现顺序建表、在 JSON 输出 `numbering_anomalies` 记录异常行号（132 本拼接长篇零参数直接通过数从 `121/132` 升至 **`132/132` 全通**）；`manage_analysis_run.py` 按章长动态放宽超长章情节点上限并豁免 `quote` 与引号内原文字面花括号（保留含空格模板占位符拦截）；校准 `author-facing.md`、各 Stage 参考与 `style-profile-generator.md` 的男频爽文偏向；
   - `story-short-analyze` 允许半成品/小品 `beats >= 1`，扩充甜宠/喜剧/悬疑情绪标签与非报应型无反转说明。
5. **修正 `story-long-scan`、`story-short-scan`、`story-publish`、`story-cover`、`story`、`browser-cdp`**：
   - 校准扫榜信心评级与各平台题材画像，修复番茄榜单 PUA 章节名回退、七猫 `<1万` 读数解析、点众 `>5万字` 过滤与黑岩首页空列表自动回退 `zh_CN`；短篇扫榜兼容无独立简介平台并在平台对照表中补齐 `其他/未定 → 未定`；
   - `story-publish` 对齐 0.10 `这篇用的套路` 字段名、补充番茄热榜短故事书名实测分布（中位 15 字、P90 约 20 字），`check-publish-format.py` 收紧占位符边界匹配并豁免 `封面` 的 `提示词/图片/状态` 单行冒号检查；
   - `story-cover` 对齐短篇目录识别、区分 `3:4`（番茄/起点/七猫）与 `5:7`（晋江）及 `2:3` 比例、去掉番茄平台串的强制人像词、将笔名装饰改为可选并补充生僻字无字底图兜底，扩充年代/种田/无限流/克苏鲁等推断词与都市/现言/悬疑/轻小说风格描述，`api-fallback.md` 统一用官方支持的 `1024x1536` 配合 Step 5 裁切；
   - `dashboard-server.mjs` 与 `story/SKILL.md` 识别构思阶段短篇目录（同时含 `设定.md` 与 `小节大纲.md`）；`setup-cdp-chrome.js` 同步上层 `Local State` 并补拷 `-wal`/`-shm` 旁路文件，`browser-cdp/SKILL.md` 补充 Chrome 127+ 应用绑定加密下的调试窗口持久化登录说明。

## Alternatives considered

- **把 `story-short-write` 的「默认第一人称」也一并改成一三人称平起平坐**：表面上看似更宽松，但 `node38` 2,744 篇完结短篇实测显示第一人称占比高达 **96.90%（2,659/2,744）**（连男频都市生活也占 `97.2%`，仅男频侦探推理以第三人称居多），原规则「默认第一人称，群像或用户指定可改第三人称」与真实短篇生态吻合，改平会削弱短篇最核心的代入优势，故保留原规则不动。
- **对万字短篇仍沿用单章固定阈值 `NOT_IS_BLOCKING_MIN_HITS = 3`，让作者靠 `<!-- 去味:跳过 -->` 豁免**：实现零改动，但 10,000 字短篇的篇幅是单章的 3–4 倍，同密度下真人短篇自然偶发 3–4 处对比句的比例达 `6.0%`，拿单章固定次数卡整篇短篇属于量纲失配，不应转嫁给作者手动打豁免标记。
- **为章号跳号、历史导入字数、小批返修分别增加 `--allow-numbering-gaps`、`--allow-historical-wordcount`、`--allow-small-batch` 命令行参数**：能把默认拦截与特殊放行显式拆开，但 `30.08%` 完结长篇原书自带章号跳号、导入旧稿天然先落盘 `正文/`、局部返修天然已有 `大纲/细纲_*`，额外暴露开关会让 Agent 先撞错再读文档重跑并加重 CLI 与参考文档维护负担；直接靠 50 字标题上限 + 分隔符守卫防误切、靠盘面文件状态自动识别导入章与返修章，即可零参数覆盖常规与边界场景。

## Consequences

- **收益**：13 个非长篇写作 Skill 与 #543/#544 的文风、标点、情绪通道及 0.10 白话字段全面拉齐；万字短篇在去味检测器与写后钩子上的量纲误拦、穿书 `剧情节点` 误拦、分节标题与完结落款误报大幅下降；短篇导入分流、半成品拆解、原书章号跳号拆解、发布简介校验、封面提示词自洽性与工作台短篇立项展示恢复顺畅。
- **代价**：句式阈值按篇幅折算、钩子工程词与收尾规则改动涉及 `check-ai-patterns.js`、`check-degeneration.js`、`story_hook_core.js`、`story_codex_hook.py` 及共享副本，已同步更新 `check-hook-regex-sync.sh`、`test-prose-net-parity.sh`、`test-ai-patterns.sh`、`test-degeneration.sh` 与多端适配产物。
