# 长篇拆文运行、提交与恢复

## 唯一状态与三个脚本

生产运行只使用：

1. `build_chapter_index.py`：建立机械章界和逐章原文 hash；
2. `inspect_existing_assets.py`：只读识别旧成果、当前成果、缺章和修复阶段；
3. `manage_analysis_run.py`：只读计划，并负责批次提交、拆分、恢复、阶段标记和旧状态迁移。

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

完整旧成果默认直接使用和纯旧成果增强无需索引。全新、部分完成或明确重拆才运行：

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/build_chapter_index.py" \
  --source "{拆文目录}/原文/原文.txt" \
  --output "{拆文目录}/chapter_index.csv" \
  --locator-path "原文/原文.txt"
```

脚本只按 LF 计算物理行号，支持楔子、序章、第0章、任意正文起始章、番外、后记、多卷和中文大数。CSV 保存内部连续号、来源章号、卷、标题、行界、字符数、`chapter_sha256`、全源 hash 和解析器版本。

同源索引直接复用且不重写。原文变化时先非零退出；人工确认后加 `--rebuild`。重建会把上一版 CSV 原子保存为 `_analysis_cache/chapter_index.previous.csv`，供计划器判断实际变化章；它不是第二个状态表。追加新章时旧章 hash 保持稳定，输出仅列出新增或内容变化的 `pending_chapters`。会导致旧内部章号整体漂移，或旧摘要/深拆从序章、第0章、非第一章开始而身份无法确认时，返回 `chapter_mapping_ambiguous`，不得静默覆盖。

## 3. 生成只读计划

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/manage_analysis_run.py" plan \
  --root "{拆文目录}" \
  --intent continue
```

意图：

- `continue`：补缺失/失效语义章；已有语义但缺摘要时用旧成果投影；
- `enhance`：只读既有拆文成果形成 `REUSE-{起章}-{止章}` 批次，原文读取数必须为 0；
- `reanalyze`：忽略旧语义成果，按索引规划全部 `RAW-{起章}-{止章}`，并返回本次 `request_id`。

计划只存在内存和标准输出，`state_written` 必须为 `false`。每块最多 10 章、25,000 字符；批次 ID 直接使用章节范围。`RAW` 只覆盖缺失或逐章原文 hash 已失效的章，`REUSE` 只读取计划列出的旧成果。黄金三章深拆属于已有语义成果，可以生成缺失摘要，无需再次读取前三章原文。

明确重拆时，后续 `commit`、`split` 和恢复用的 `plan` 都传 `--request-id "{首次 plan 输出值}"`。同一请求 ID 的 completed 批次可复用；省略 ID 再执行 reanalyze 会生成新 ID，表示一次新的重拆请求。

## 4. 执行与提交一个批次

`chapter-extractor` 只读取计划中一个批次。把完整输出保存为临时 Markdown 后提交：

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/manage_analysis_run.py" commit \
  --root "{拆文目录}" \
  --input "{临时结果.md}" \
  --batch-id "RAW-4-10" \
  --range-sha256 "{plan 输出值}" \
  --source-file "{plan 列出的来源}"
```

`REUSE` 批次不传 `--range-sha256`。完整增强可以只输出 `REUSED_CHAPTERS` 与跨章观察；需要补摘要时输出同一套紧凑章节块。
明确重拆的提交另加 `--intent reanalyze --request-id "{plan request_id}"`。提交入口会再次检查 10 章与 25,000 字符上限；单个超长章仍允许独占。

提交顺序固定：

1. 在写文件前校验整批范围、标记和所有紧凑字段；
2. 对 `RAW` 再算当前范围 hash，与计划值不一致就拒绝；
3. 原子写入含完整模型输出和最终结束标记的批次缓存；
4. 只创建缺失的 `章节/第N章_摘要.md`，任何已有摘要都保留；
5. 最后更新 `_progress.md` 受管批次表为 `completed`。

每条成功行记录章节范围、输入类型、原文范围 hash、状态和缓存路径。受管区外的 BOM、换行、作者备注及既有 `schema_version` 必须逐字节保留。

## 5. 失败、拆分和重试

模型输出不完整时不提交。批次过大或连续失败时：

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/manage_analysis_run.py" split \
  --root "{拆文目录}" --batch-id "RAW-4-10"
```

也可用 `--at 7` 指定左右边界。脚本在同一个 `_progress.md` 受管区把父块记为 `superseded`，写入两个相邻子块。重新运行 `plan` 后继续使用子块，不会按位置编号覆盖旧记录，也不会把子块重新合成父块。

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

Stage 3–6 各运行一次。文件成功原子落盘后再标记：

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/manage_analysis_run.py" mark-stage \
  --root "{拆文目录}" --stage stage3 --output "剧情/节奏.md"
```

阶段完成只看约定产物存在且进度行完成；没有依赖 hash 或 Stage receipt。`mark-stage` 会按阶段检查：Stage 1 的黄金三章与快速预览、Stage 2 的全部摘要、Stage 3 的情绪模块与节奏、Stage 4 的角色与设定、Stage 5 的报告、Stage 6 的文风。Stage 6 的单独重建见 [style-profile-generator.md](style-profile-generator.md)，允许按索引定点读取 4–6 段原文，不重扫全书，也不触发其他阶段。

生成新的 `拆文报告.md` 前先执行：

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/manage_analysis_run.py" mark-stage --root "{拆文目录}" --stage stage5 --prepare
```

若旧报告存在，命令会完整复制到 `_analysis_cache/legacy/拆文报告.md`；已存在的首份备份不覆盖。当前旧报告与首份备份不同时，另存一份带内容 hash 的历史备份。其他旧产物与已有摘要不得覆盖。新报告落盘后再用不带 `--prepare` 的 `mark-stage` 标记完成。

## 8. 旧六脚本项目迁移

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/manage_analysis_run.py" migrate-legacy --root "{拆文目录}"
```

迁移只读取旧 checkpoint、receipt 和缓存；不会删除它们。只有旧 receipt 的输出 hash 能验证对应缓存完整时，才生成兼容缓存并在摘要齐全时写成功状态。旧缓存没有结束标记时不得直接补标记冒充完整；无法验证的项目列入 `historical_unverified`，按实际缺口继续计划。

## 9. 最终检查

- 再运行检查器和计划器；完整项目应 `direct_use`，继续意图应无待处理批次；
- 对比受保护路径 hash：旧 `章节/`、`剧情/`、`角色/`、`设定/`、`文风.md`、`拆文报告.md` 不得被增强或恢复流程改写；
- 允许变化的旧项目文件只有 `_progress.md` 受管状态区和 `_analysis_cache/` 新证据；
- 检查旧 `schema_version` 原值；
- 检查新投影的主题、基调、情节点类型和“涉及”字段能被导入与写作流程读取；
- 报告未执行的真实模型或跨平台检查，不得用静态 fixture 冒充。
