# 长篇拆文运行、提交与恢复

## 唯一状态与三个脚本

生产运行只使用：

1. `build_chapter_index.py`：建立机械章界和逐章原文 hash；
2. `inspect_existing_assets.py`：只读识别旧成果、当前成果、缺章和修复阶段；
3. `manage_analysis_run.py`：只读计划，并负责批次提交、拆分、恢复和阶段标记。

Stage 4 另用 `render_relation_chart.py` 从 `角色/角色关系.md` 生成人物关系图，不参与运行状态。

脚本输出只给你看。失败或需要作者决定时，脚本会带 `author_message`（大白话说明和选项），按 [author-facing.md](author-facing.md) 转述给作者；不要把 JSON、错误码或下文的分类、路径名原样贴给作者。

`chapter_index.csv` 是机械章节边界唯一真源。批次和阶段状态只写在 `_progress.md` 的
`story-long-analyze:runtime-state` 受管区。`_analysis_cache/` 保存完整结果和恢复证据，不承担状态库功能。

既有项目中的 `schema_version: 2` 沿用且不修改；该值只供报告，不用于否定旧成果。`_progress.md` 不再保存机械章节边界镜像。

禁止创建 `run-plan.json`、`batch-checkpoints.json`、逐批 JSON receipt 或 Stage receipt。计划始终打印到标准输出，由当前运行直接消费。

所有命令使用实际 Python 与 skill 根路径：

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/{脚本名}.py" ...
```

## 1. 先检查目录

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/inspect_existing_assets.py" --root "{拆文目录}" --compact
```

- 路径不存在、不是目录或不可读：非零退出，先修正路径。
- 已存在的空目录：`empty / new_analysis`。
- 完整旧项目：`direct_use`，不建索引、不读原文。
- 部分项目：精确报告 `missing_semantic_chapters` 与 `missing_summary_chapters`。
- 新旧投影混存：`mixed_sources: true` 并列明逐章来源，仍可直接使用完整项目。
- `schema_version` 只报告，不参与否定旧项目，也不在检查或复用时改写。
- `stage_repairs` 中的情绪、节奏和文风修复与 Stage 2 缺章分开处理。

## 2. 需要原文时建立或校验索引

完整旧成果默认直接使用和纯旧成果增强无需索引。全新或部分完成才运行：

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/build_chapter_index.py" \
  --source "{拆文目录}/原文/原文.txt" \
  --output "{拆文目录}/chapter_index.csv" \
  --locator-path "原文/原文.txt"
```

脚本只按 LF 计算物理行号，支持楔子、序章、第0章、任意正文起始章、番外、后记、多卷和中文大数。CSV 保存内部连续号、来源章号、卷、标题、行界、字符数、`chapter_sha256`、全源 hash 和解析器版本。

同源索引直接复用且不重写。原文变化时先非零退出；人工确认后加 `--rebuild`。重建沿用已有索引的章号口径：已有索引第 1 章是正式章节、而原文开头有楔子/序章/第0章（即上次用了 `--fold-prologue`），自动照样并入，无需再加参数；重建出的前面各章与已有索引对不上（`chapter_mapping_ambiguous:position=N` 或 `index_would_shrink`）时不写索引，返回 `author_message`。追加新章时旧章 hash 保持稳定，输出仅列出新增或内容变化的 `pending_chapters`。改动已拆章节的原文只会让覆盖它的批次缓存失效、下次计划重读该批；已有摘要不刷新——要刷新哪章就删掉哪章的 `章节/第N章_摘要.md` 和覆盖它的 `_analysis_cache/批次-*.md` 再续跑（只删摘要会从缓存原样补回）。旧成果按旧章号命名，写新索引前逐一核对：旧摘要一律参与；黄金三章在 `_progress.md` 来自旧版（有「章节边界」表，或没有运行状态受管区）时参与，本次 Stage 1 按索引写的不参与。有旧版「章节边界」表时逐章定位：起始行正好是某章标题行就直接认定；否则按标题找（统一全半角，去掉章号前缀和「（求收藏）」「【二合一】」这类尾注，允许包含关系；标题只有章号时比章号），多个候选取离旧起始行最近的；全部对上才放行；没有表时，原文首章不是第 1 章就无法确认。对不上时不写索引，返回 `chapter_mapping_ambiguous` 和 `author_message`；`plan` 遇到已建好的错位索引同样拒绝。作者的三个选择：

1. **按旧章号继续（推荐）**：`build_chapter_index.py ... --fold-prologue`，开头的楔子/序章/引子/前言/第0章并进第一个正式章节，编号回到旧版口径，旧成果原样复用；输出里的 `folded_into_first_chapter` 列出被并入的章节标签（如「楔子」「第0章」）。楔子内容不会单独拆，要在报告「还不确定的地方」说明。
2. **楔子单独成章**：把除 `原文/` 外所有按旧章号写的产物——`章节/`、`剧情/`、`角色/`、`设定/`、`人物关系图/`、`快速预览.md`、`概要.md`、`拆文报告.md`、`文风.md`、`_analysis_cache/批次-*.md` 和 `_progress.md`——挪进 `_analysis_cache/legacy/旧章号/`（挪走，不删除），再从 Stage 0 按新章号重拆。旧库只拆到黄金三章时代价最小。
3. **换一个新目录整本重拆**。

`chapter_index.csv` 已按错误口径建好时，先删掉它（纯机械章节表，可随时重建），再按选择重建；`--rebuild` 只沿用已有索引的口径，不能用来改口径。

## 3. 生成只读计划

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/manage_analysis_run.py" plan \
  --root "{拆文目录}" \
  --intent continue
```

意图：

- `continue`：补缺失语义章，以及缓存失效的已记录批次；已有语义但缺摘要时用旧成果投影；
- `enhance`：只读既有拆文成果形成 `REUSE-{起章}-{止章}` 批次，原文读取数必须为 0。

没有“整本重拆”意图：已有摘要永不覆盖。整本重拆就换一个新目录重新拆。

逐批派发时加 `--next 1` 只取下一批，确认进度用 `--next 0` 只看 `remaining_batches` 与压缩成区间的 `summary_gaps`；全量计划每批约五百字符，整本书反复全量输出会白占主会话上下文。不带 `--next` 时输出全部批次。

计划只存在内存和标准输出，`state_written` 必须为 `false`。每块最多 3 章、25,000 字符；批次 ID 直接使用章节范围。`RAW` 只覆盖缺失章和缓存失效批次，`REUSE` 只读取计划列出的旧成果。黄金三章深拆属于已有语义成果，可以生成缺失摘要，无需再次读取前三章原文。

## 4. 执行与提交一个批次

`chapter-extractor` 只处理计划中一个批次。**主会话不中转内容**：原文和批次结果都不经过主会话上下文。派发时只给——

- 批次 ID、输入类型、计划的 `source_files`（原文块是逐章 `source_locator`，子代理自己按行号读原文）和 `chapter_chars`（每章字数，决定情节点密度）；
- 输出文件 `{拆文目录}/_analysis_cache/输入-{批次ID}.md`（不写系统 `/tmp`：Windows 没有，多本书同批号会互相覆盖）；
- 交接缓存路径：按下方派发方式选定的已提交批次缓存（没有就不给），子代理只读其中 `### 跨批状态`。

子代理把完整输出写进输出文件，只回一行 `BATCH_WRITTEN` 回执。主会话**不 Read 这份输入文件**，直接提交；提交被拒时把错误码和输出文件路径交回子代理，让它用 Edit 只改出错处后再提交（结构整体错乱才整份重写）。提交成功后删掉这份输入。不论哪种派发方式，`commit` 都由主会话逐个执行，不并发跑。

**派发方式三档**（Stage 1 后停下询问时一并请作者选，话术见 author-facing「开头三章拆完、停下来问」）：

1. **串行**：上一批提交成功再派下一批，交接缓存给紧邻的前一批。优点：剧情点、未决悬念和已确认别名逐批完整接续，Stage 3 合并最省事。缺点：最慢，墙钟时间随批数线性增长。
2. **有限并行**：每轮同时派 3 批，同轮都给「本轮开始前最近一个已提交批次」的缓存；整轮提交完再派下一轮。优点：约快两到三倍，接续最多滞后一轮。缺点：同轮批次互相看不到对方新建的剧情点与别名，边界处可能重复建 ID，靠 Stage 3 跨块合并收拢。
3. **不限批次顺序**：不等前批，同时在跑的子代理最多 12 个（宿主或账号上限更低时以环境为准）；在跑的少于上限一半时，补派到上限。补派用 `plan --next {在跑数＋补派数}`，跳过已在跑的批次号（计划只认已提交）。遇到限流、超时或子代理报错，把上限减半后再补派。每批给「本批起章之前最近的已提交批次」的缓存，没有就不给。优点：最快。缺点：接续最弱，剧情点与别名最依赖 Stage 3 跨块合并和 Stage 4 归并；并发越高，被限流、整批重跑的风险越大。

作者没选、要求一次拆完 / 全量拆、多本书一起拆，或由 story-import 自动续跑时，都按第 2 档；第 3 档只在作者明确选择时使用。多本书同拆时按书轮流派，第 3 档的总并发也不超过同一上限。第 1、2 档用 `plan --next 1` / `--next 3` 取批。子代理不可用时主线程自己写批次，包裹标记照 output-templates「批次提交格式」：

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/manage_analysis_run.py" commit \
  --root "{拆文目录}" \
  --input "{拆文目录}/_analysis_cache/输入-RAW-4-6.md" \
  --batch-id "RAW-4-6" \
  --range-sha256 "{plan 输出值}" \
  --source-file "{plan 列出的来源}"
```

`REUSE` 批次不传 `--range-sha256`。完整增强可以只输出 `REUSED_CHAPTERS` 与跨章观察；需要补摘要时输出同一套紧凑章节块。
提交入口会再次检查 3 章与 25,000 字符上限；单个超长章仍允许独占。

提交顺序固定：

1. 在写文件前校验整批范围、标记、所有紧凑字段和情节点（原文块每章 10–20 个、长章最多 30，少于 10 或多于 30 整批拒收；编号连续、每点带主题标签与基调行）；
2. 对 `RAW` 再算当前范围 hash，与计划值不一致就拒绝；
3. 原子写入含完整模型输出和最终结束标记的批次缓存；
4. 只创建缺失的 `章节/第N章_摘要.md`，任何已有摘要都保留，并在结果的 `kept_existing_summary_chapters` 里列出；
5. 最后更新 `_progress.md` 受管批次表为 `completed`；有阶段记录时按 Stage 3–6 状态重写受管区的 `最终状态`（旧项目改写原有行，不写第二行）。

每条成功行记录章节范围、输入类型、原文范围 hash、状态和缓存路径。受管区外的 BOM、换行、作者备注及既有 `schema_version` 必须逐字节保留。

## 5. 失败、拆分和重试

模型输出不完整时不提交。批次过大或连续失败时：

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/manage_analysis_run.py" split \
  --root "{拆文目录}" --batch-id "RAW-4-6"
```

也可用 `--at 4` 指定左右边界。脚本在同一个 `_progress.md` 受管区把父块记为 `superseded`，写入两个相邻子块。重新运行 `plan` 后继续使用子块，不会按位置编号覆盖旧记录，也不会把子块重新合成父块。

## 6. 中断恢复

先重新运行 `plan`。已满足以下三项的成功批次不会出现：

1. 范围内摘要都存在；
2. 批次缓存完整，最后一个非空标记为 cache end；
3. `RAW` 状态行的范围 hash 等于当前索引计算值。

如果缓存已完整，但摘要或进度最后一步尚未落盘：

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/manage_analysis_run.py" repair-progress --root "{拆文目录}"
```

恢复只从完整、范围 hash 有效的缓存补缺失摘要并更新状态；不覆盖用户修改过的文件。缓存缺结束标记或范围 hash 失效时报告错误并重跑相应批次。

## 7. Stage 3–6

Stage 1 黄金三章与快速预览落盘后标 `stage1`；计划不再有批次时标 `stage2`。Stage 3–6 各运行一次。文件成功原子落盘后再标记：

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/manage_analysis_run.py" mark-stage \
  --root "{拆文目录}" --stage stage3 --output "剧情/节奏.md"
```

**Stage 3–5 的读法**：不整份 Read 批次缓存（每批约七成是和逐章摘要重复的章节块），改用只读的 `digest` 按需取料，输出是 Markdown：

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/manage_analysis_run.py" digest --root "{拆文目录}" --part observations [--chapters 1-60]
"{PYTHON}" "{story-long-analyze skill 根}/scripts/manage_analysis_run.py" digest --root "{拆文目录}" --part chapters --chapters 1-60 --fields 三维节奏,涉及,状态变化 --points brief
```

- `observations`：按章序汇总已提交批次的跨章观察（剧情点、关键事件与披露候选、关系变化、三维峰谷、跨批状态），是 Stage 3–4 的主语料；
- `chapters`：从逐章摘要抽字段（概要、关键事件、因果、局面结果、涉及、信息变化、状态变化、三维节奏、章尾钩子、证据），`--points brief` 给每点「标题｜类型｜基调」，`full` 另带白描；
- 全书放不进一次上下文时按 `--chapters` 分窗口取，窗口间只带剧情状态与证据引用；只有关键证据冲突才定点 Read 单章摘要。

阶段完成只看约定产物存在且进度行完成；没有依赖 hash 或 Stage receipt。`mark-stage` 会按阶段检查：Stage 1 的黄金三章与快速预览、Stage 2 的全部摘要、Stage 3 的情绪模块与节奏、Stage 4 的角色与设定、Stage 5 的报告、Stage 6 的文风。Stage 6 的单独重建见 [style-profile-generator.md](style-profile-generator.md)，允许按索引定点读取 4–6 段原文，不重扫全书，也不触发其他阶段。

生成新的 `拆文报告.md` 前先执行：

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/manage_analysis_run.py" mark-stage --root "{拆文目录}" --stage stage5 --prepare
```

若旧报告存在，命令会完整复制到 `_analysis_cache/legacy/拆文报告.md`；已存在的首份备份不覆盖。当前旧报告与首份备份不同时，另存一份带内容 hash 的历史备份。其他旧产物与已有摘要不得覆盖。新报告落盘后再用不带 `--prepare` 的 `mark-stage` 标记完成。

## 8. 最终检查

检查全部通过后，按 [author-facing.md](author-facing.md)「全部拆完」给作者汇报；下面这些检查结果不写进汇报。

- 再运行检查器和计划器；完整项目应 `direct_use`，继续意图应无待处理批次；
- 对比受保护路径 hash：旧 `章节/`、`剧情/`、`角色/`、`设定/`、`文风.md`、`拆文报告.md` 不得被增强或恢复流程改写；
- 允许变化的旧项目文件只有 `_progress.md` 受管状态区和 `_analysis_cache/` 新证据；
- 检查旧 `schema_version` 原值；
- 检查新投影的情节点序列、主题、基调、类型和“涉及”字段能被导入与写作流程读取；
- 报告未执行的真实模型或跨平台检查，不得用静态 fixture 冒充。
