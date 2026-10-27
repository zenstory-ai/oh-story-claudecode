# 长篇拆文运行、提交与恢复

## 唯一状态与三个脚本

拆文运行使用三个脚本：

1. `build_chapter_index.py`：建立机械章界和逐章原文 hash；
2. `inspect_existing_assets.py`：只读识别旧成果、当前成果、缺章和修复阶段；
3. `manage_analysis_run.py`：只读计划，并负责批次提交、拆分、恢复和阶段标记。

Stage 4 另用 `render_relation_chart.py` 从 `角色/角色关系.md` 生成人物关系图，不参与运行状态。

脚本输出只给你看。失败或需要作者决定时，脚本会带 `author_message`（大白话说明和选项），按 [author-facing.md](author-facing.md) 转述给作者；不要把 JSON、错误码或下文的分类、路径名原样贴给作者。

`chapter_index.csv` 是机械章节边界的唯一依据。批次和阶段状态只写在 `_progress.md` 的
`story-long-analyze:runtime-state` 受管区。`_analysis_cache/` 保存完整结果和恢复证据，不承担状态库功能。

保留既有 `schema_version: 2`；只供报告，不据此否定旧成果。

计划只打印到标准输出，由当前运行直接消费；不另建计划、检查点或逐批回执文件。`{PYTHON}` 与路径占位见 SKILL.md「运行约定」。

## 1. 先检查目录

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/inspect_existing_assets.py" --root "{拆文目录}" --compact
```

- 路径不存在、不是目录或不可读：非零退出，先修正路径。
- 已存在的空目录：`empty / new_analysis`。
- 完整旧项目：`direct_use`，不建索引、不读原文。
- 部分项目：`--compact` 用 `semantic_coverage.missing_ranges`；完整输出另列 `missing_semantic_chapters`、`missing_summary_chapters`。
- 新旧投影混存：`mixed_sources: true` 并列明逐章来源，仍可直接使用完整项目。
- `stage_repairs` 按 SKILL.md「Phase 2」第二表补阶段；`invalid_raw_batches` 按 `plan` 续跑，不可直接复用。

## 2. 需要原文时建立或校验索引

完整旧成果默认直接使用；纯增强也无需索引。全新或部分完成且仍需读取原文时运行；只补文风时按 style-profile-generator.md 单独建索引：

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/build_chapter_index.py" \
  --source "{拆文目录}/原文/原文.txt" \
  --output "{拆文目录}/chapter_index.csv" \
  --locator-path "原文/原文.txt"
```

脚本只按 LF 计算物理行号，支持楔子、序章、第0章、任意正文起始章、番外、后记、多卷和中文大数。CSV 保存内部连续号、来源章号、卷、标题、行界、字符数、`chapter_sha256`、全源 hash 和解析器版本。

同源索引直接复用且不重写。原文变化、重建后章号对不上或旧成果章号对不上时，按 [index-rebuild.md](index-rebuild.md) 处理。

## 3. 生成只读计划

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/manage_analysis_run.py" plan \
  --root "{拆文目录}" \
  --intent continue
```

意图：

- `continue`：补缺失语义章，以及缓存失效的已记录批次；已有语义但缺摘要时用旧成果投影；
- `enhance`：把还没有完整批次缓存的已拆章做成 `REUSE-{起章}-{止章}` 批次，从旧成果提取跨章观察。逐章成果已覆盖全书时原文读取数为 0；仍有缺章时计划照样列出这些章的 `RAW` 批次，照计划处理，或先问作者是否只增强已拆的范围（加 `--chapters`）。

没有“整本重拆”意图：已有摘要永不覆盖。整本重拆就换一个新目录重新拆。

逐批派发时加 `--next 1` 只取下一批，确认进度用 `--next 0` 只看 `remaining_batches` 与压缩成区间的 `summary_gaps`；全量计划每批约五百字符，整本书反复全量输出会占用主会话上下文。不带 `--next` 时输出全部批次。

作者只要拆某一段时加 `--chapters 起-止`（可与 `--next` 同用）：只规划这段里的批次，`remaining_batches` 只数这段，`summary_gaps` 仍是全书。这段拆完即停，不标 `stage2`；按 author-facing「全部拆完」只汇报这一段，再问作者是否接着拆其余章节。

计划只存在内存和标准输出，`state_written` 必须为 `false`。每块最多 3 章、25,000 字符，单个超长章允许独占；同一章不能出现在两个原文块；计划原文读取数为 0 时不得派发原文任务；批次 ID 直接使用章节范围。`RAW` 只覆盖缺失章和缓存失效批次，`REUSE` 只读取计划列出的旧成果。黄金三章深拆属于已有语义成果，可以生成缺失摘要，无需再次读取前三章原文。

## 4. 执行与提交一个批次

`chapter-extractor` 只处理计划中一个批次。**主会话不中转内容**：原文和批次结果都不经过主会话上下文。派发时照抄计划里这一批的字段，路径前加 `{拆文目录}/`，不另选、不推算：

- `batch_id`、`input_kind`；
- `source_files`（原文块是逐章 `source_locator`，子代理自己按行号读原文）、`chapter_chars`（每章字数）和 `min_plot_points`（每章情节点下限，按字数算好）；
- `input_file`：子代理的输出路径 `_analysis_cache/输入-{批次ID}.md`，每本书保存在各自拆文目录中；
- `handoff_cache`：交接缓存，计划算好的「本批起章之前最近的已提交批次」，为空就不给；子代理只读其中 `### 跨批状态`。

子代理把完整输出写进输出文件，只回一行 `BATCH_WRITTEN` 回执。主会话**不 Read 这份输入文件**，直接提交；提交被拒时重新派发同一批：上面的字段原样再给一遍（子代理补内容要按 `source_locator` 回看原文、按 `min_plot_points` 补情节点），再附错误码，让它用 Edit 只改出错处后再提交（结构整体错乱才整份重写）。提交成功后删掉这份输入。不论哪种派发方式，`commit` 都由主会话逐个执行，不并发跑。

**派发方式**：默认第 2 档有限并行，不请作者在三档里选。作者问起能不能更快或更稳、或明确要求时，才按 author-facing「作者问起怎么拆」用白话解释并切换。三档都用计划给的 `handoff_cache`，它随提交进度自动落到对应的批次上。

1. **串行**：上一批提交成功再派下一批，交接缓存就是紧邻的前一批。优点：剧情点、未决悬念和已确认别名逐批完整接续，Stage 3 合并最省事。缺点：最慢，墙钟时间随批数线性增长。
2. **有限并行**：每轮同时派 3 批，同轮的交接缓存都是本轮开始前最近一个已提交批次；整轮提交完再派下一轮。优点：并发执行可减少等待，接续最多滞后一轮。缺点：同轮批次互相看不到对方新建的剧情点与别名，边界处可能重复建 ID，靠 Stage 3 跨批次合并。
3. **不限批次顺序**：不等前批，同时在跑的子代理最多 12 个（宿主或账号上限更低时以环境为准）；在跑的少于上限一半时，补派到上限。补派用 `plan --next {在跑数＋补派数}`，跳过已在跑的批次号（计划只认已提交）。遇到限流、超时或子代理报错，把上限减半后再补派。优点：可同时处理更多批次。缺点：接续最弱，剧情点与别名最依赖 Stage 3 跨批次合并和 Stage 4 归并；并发越高，被限流、整批重跑的风险越大。

作者没提、要求一次拆完 / 全量拆、多本书一起拆，或由 story-import 自动续跑时，都按第 2 档；第 1、3 档只在作者明确选择时使用。多本书同拆时按书轮流派，第 3 档的总并发也不超过同一上限。第 1、2 档用 `plan --next 1` / `--next 3` 取批。子代理不可用时主会话自己写批次：先读 [stage2-extraction.md](stage2-extraction.md)，提取规则与包裹标记照其中「批次提交格式」：

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

1. 在写文件前校验整批范围、标记、所有紧凑字段和情节点（原文块每章不少于 `min_plot_points`、最多 30，否则整批拒收；编号连续、每点带主题标签与基调行）；
2. 对 `RAW` 再算当前范围 hash，与计划值不一致就拒绝；
3. 原子写入含完整模型输出和最终结束标记的批次缓存；
4. 只创建缺失的 `章节/第N章_摘要.md`，任何已有摘要都保留，并在结果的 `kept_existing_summary_chapters` 里列出；摘要投影把每个情节点的主题、基调和类型映射到固定枚举（主题/基调映射不上写“其他”），保留“关键事件”“情节点”“涉及”“基调”等旧消费者字段；
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

## 7. 阶段标记与后续时刻

Stage 1 黄金三章与快速预览落盘后标 `stage1`；计划不再有批次、全部摘要落盘后标 `stage2`：

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/manage_analysis_run.py" mark-stage --root "{拆文目录}" --stage stage2
```

Stage 3–5 的取料（`digest`）与标记见 [synthesis-inputs.md](synthesis-inputs.md)，Stage 6 见 [style-profile-generator.md](style-profile-generator.md)，全部拆完后的收尾检查见 [final-checks.md](final-checks.md)。
