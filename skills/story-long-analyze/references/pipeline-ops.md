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

既有项目中的 `schema_version: 2` 沿用且不修改；该值只供报告，不用于否定旧成果。

计划只打印到标准输出，由当前运行直接消费；不另建计划、检查点或逐批回执文件。`{PYTHON}` 与路径占位见 SKILL.md「运行约定」。

## 1. 先检查目录

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/inspect_existing_assets.py" --root "{拆文目录}" --compact
```

- 路径不存在、不是目录或不可读：非零退出，先修正路径。
- 已存在的空目录：`empty / new_analysis`。
- 完整旧项目：`direct_use`，不建索引、不读原文。
- 部分项目：带 `--compact` 时缺章看 `semantic_coverage.missing_ranges`；不带时另有逐章的 `missing_semantic_chapters` 与 `missing_summary_chapters`。
- 新旧投影混存：`mixed_sources: true` 并列明逐章来源，仍可直接使用完整项目。
- `stage_repairs` 按 SKILL.md「Phase 2」第二张表补对应 Stage，与 Stage 2 缺章分开处理。

## 2. 需要原文时建立或校验索引

完整旧成果直接使用，纯增强无需建索引；全新或部分完成且仍需读取原文时运行（只补文风时按 style-profile-generator.md 单独建索引）：

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/build_chapter_index.py" \
  --source "{拆文目录}/原文/原文.txt" \
  --output "{拆文目录}/chapter_index.csv" \
  --locator-path "原文/原文.txt"
```

同源索引直接复用且不重写。原文变化、重建后章号对不上或旧成果章号对不上时，按 [index-rebuild.md](index-rebuild.md) 处理。

## 3. 生成只读计划

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/manage_analysis_run.py" plan \
  --root "{拆文目录}" \
  --intent continue
```

- `continue`：补缺失语义章及缓存失效批次；已有语义但缺摘要时用旧成果投影。
- `enhance`：把还没有完整批次缓存的已拆章做成 `REUSE-{起章}-{止章}` 批次，从旧成果提取跨章观察。逐章成果已覆盖全书时原文读取数为 0；仍有缺章时计划照样列出这些章的 `RAW` 批次，照计划处理，或先问作者是否只增强已拆范围（加 `--chapters`）。
- 已有摘要永不覆盖；整本重拆须换新目录。
- 逐批派发加 `--next 1` 只取下一批，确认进度用 `--next 0` 只看 `remaining_batches` 与 `summary_gaps`；不带 `--next` 输出全部批次。
- 作者只要拆某一段时加 `--chapters 起-止`（可与 `--next` 同用）：这段拆完即停，不标 `stage2`；按 author-facing「全部拆完」只汇报这一段，再问作者是否接着拆其余章节。
- 计划原文读取数为 0 时不得派发原文任务；`RAW` 只覆盖缺失章和缓存失效批次，`REUSE` 只读计划列出的旧成果；黄金三章深拆属于已有语义成果，无需重读前三章原文。

## 4. 执行与提交一个批次

`chapter-extractor` 只处理计划中一个批次。**主会话不中转内容**：派发时照抄计划里这一批的字段，路径前加 `{拆文目录}/`，不另选、不推算：

- `batch_id`、`input_kind`、`source_files`、`chapter_chars`、`min_plot_points`；
- `input_file`：子代理输出路径 `_analysis_cache/输入-{批次ID}.md`；
- `handoff_cache`：计划算好的「本批起章之前最近的已提交批次」，为空就不给；子代理只读其中 `### 跨批状态`。

子代理写完输出文件后只回一行 `BATCH_WRITTEN` 回执。主会话**不 Read 这份输入文件**，直接提交；提交被拒时重新派发同一批（原样给字段并附错误码，让子代理用 Edit 只改出错处，结构整体错乱才重写）。提交成功后删掉输入文件。`commit` 由主会话逐个执行，不并发跑。

**派发方式**：默认第 2 档有限并行（每轮用 `plan --next 3` 取 3 批并发派发，整轮提交完再派下一轮），不请作者在三档里选。作者问起能不能更快或更稳、或明确要求时，才按 author-facing「作者问起怎么拆」切换：

1. **串行**：用 `plan --next 1`，上一批提交成功再派下一批。
2. **有限并行（默认）**：每轮用 `plan --next 3` 同时派 3 批，同轮共用本轮开始前最近的已提交批次作 `handoff_cache`，整轮提交完再派下一轮。
3. **不限批次顺序**：同时在跑的子代理最多 12 个（以环境上限为准）；少于上限一半时用 `plan --next {在跑数＋补派数}` 补派（跳过已在跑的批次号）。遇到限流、超时或报错，把上限减半后再补派。多本书同拆时按书轮流派，总并发不超过同一上限。

子代理不可用时主会话自己写批次：先读 [stage2-extraction.md](stage2-extraction.md)，提取规则与包裹标记照其中「批次提交格式」：

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/manage_analysis_run.py" commit \
  --root "{拆文目录}" \
  --input "{拆文目录}/_analysis_cache/输入-RAW-4-6.md" \
  --batch-id "RAW-4-6" \
  --range-sha256 "{plan 输出值}" \
  --source-file "{plan 列出的来源}"
```

`REUSE` 批次不传 `--range-sha256`（完整增强可只输出 `REUSED_CHAPTERS` 与跨章观察；需补摘要时输出紧凑章节块）。

## 5. 失败、拆分和重试

模型输出不完整时不提交。批次过大或连续失败时拆批（可用 `--at` 指定切分章）：

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/manage_analysis_run.py" split \
  --root "{拆文目录}" --batch-id "RAW-4-6"
```

拆批后重新运行 `plan` 继续处理子块。

## 6. 中断恢复

先重新运行 `plan`（已成功的批次不会重复出现）。若缓存已完整，但摘要或进度最后一步尚未落盘：

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/manage_analysis_run.py" repair-progress --root "{拆文目录}"
```

缓存缺结束标记或范围 hash 失效时报告错误并重跑相应批次。

## 7. 阶段标记与后续时刻

Stage 1 黄金三章与快速预览落盘后标 `stage1`；计划不再有批次、全部摘要落盘后标 `stage2`：

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/manage_analysis_run.py" mark-stage --root "{拆文目录}" --stage stage2
```

Stage 3–5 的取料（`digest`）与标记见 [synthesis-inputs.md](synthesis-inputs.md)，Stage 6 见 [style-profile-generator.md](style-profile-generator.md)，全部拆完后的收尾检查见 [final-checks.md](final-checks.md)。
