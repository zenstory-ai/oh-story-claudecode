# 长篇拆文运行、提交、索引重建与收尾检查

## 状态与脚本

运行脚本三个：`build_chapter_index.js`（机械章界与 hash）、`inspect_existing_assets.js`（只读查旧/新成果与缺口）、`manage_analysis_run.js`（计划、提交、拆批、恢复与标阶段）；Stage 4 另用 `render_relation_chart.py` 画关系图。带 `author_message` 时按 [author-facing.md](author-facing.md) 转述，不贴 JSON 或错误码。

`chapter_index.csv` 是章界唯一依据；状态唯一落在 `_progress.md` 的 `story-long-analyze:runtime-state` 受管区；`_analysis_cache/` 存恢复证据。既有 `schema_version: 2` 原值保留（只供报告，不否定旧成果）。计划只打标准输出，不另存文件。

## 1. 先检查目录

```text
node "{story-long-analyze skill 根}/scripts/inspect_existing_assets.js" --root "{拆文目录}" --compact
```

路径错即停；空目录 `new_analysis`；完整旧项目 `direct_use`（不建索引不读原文）；部分项目看 `semantic_coverage.missing_ranges`，混存标 `mixed_sources: true` 仍可复用；`stage_repairs` 按 SKILL.md「Phase 2」补对应 Stage。

## 2. 建立或校验索引

需读原文时建/校索引（完整旧成果或纯增强不建；原文变化或错位见下文「原文变化与章号对不上」）：

```text
node "{story-long-analyze skill 根}/scripts/build_chapter_index.js" --source "{拆文目录}/原文/原文.txt" --output "{拆文目录}/chapter_index.csv" --locator-path "原文/原文.txt"
```

## 3. 生成只读计划

```text
node "{story-long-analyze skill 根}/scripts/manage_analysis_run.js" plan --root "{拆文目录}" --intent continue
```

- `continue`：补缺章与缓存失效批次，有语义缺摘要则投影；`enhance`：为缺完整缓存的已拆章建 `REUSE` 批次提取跨章观察（有缺章同步列 `RAW`，或加 `--chapters` 只增强已拆段）。
- 已有摘要永不覆盖；整本重拆换新目录。参数：`--next 1` 取下一批、`--next 0` 看余量、`--chapters 起-止` 只拆指定段（拆完即停不标 `stage2`）。原文读取为 0 不得派原文任务；黄金三章深拆已属语义成果不重读。

## 4. 执行与提交一个批次

`chapter-extractor` 每次只做 1 批；**主会话不中转内容**，照抄计划字段（路径加 `{拆文目录}/`：`batch_id`、`input_kind`、`source_files`、`chapter_chars`、`min_plot_points`、`input_file`=`_analysis_cache/输入-{批次ID}.md`、`handoff_cache` 仅读 `### 跨批状态`）。子代理写完只回 `BATCH_WRITTEN`，主会话不 Read 文件直接逐个 `commit`（不并发），被拒原样重派附错误码定点修补，成功后删输入文件。

派发默认第 2 档有限并行（作者问起按 author-facing 切换）：① 串行 `plan --next 1`；② 有限并行（默认）`plan --next 3` 同轮派 3 批共用轮前 `handoff_cache`；③ 不限顺序最多 12 并发（限流/超时上限减半，多书共用）。子代理不可用时先读 [stage2-extraction.md](stage2-extraction.md) 自写，再提交（`REUSE` 不传 `--range-sha256`）：

```text
node "{story-long-analyze skill 根}/scripts/manage_analysis_run.js" commit \
  --root "{拆文目录}" --input "{拆文目录}/_analysis_cache/输入-RAW-4-6.md" \
  --batch-id "RAW-4-6" --range-sha256 "{plan 输出值}" --source-file "{plan 列出的来源}"
```

## 5. 失败、拆批与中断恢复

输出不完整不提交；批次过大或连续失败先拆批（可加 `--at`）再重 `plan`；中断恢复先 `plan`，缓存已全但摘要/进度未落盘则 `repair-progress`（缺结束标记或 hash 失效则重跑该批）：

```text
node "{story-long-analyze skill 根}/scripts/manage_analysis_run.js" split --root "{拆文目录}" --batch-id "RAW-4-6"
node "{story-long-analyze skill 根}/scripts/manage_analysis_run.js" repair-progress --root "{拆文目录}"
```

## 6. 阶段标记

黄金三章与快速预览落盘标 `stage1`；无剩余批次且摘要齐备标 `stage2`（Stage 3–5 见 [synthesis-inputs.md](synthesis-inputs.md)，Stage 6 见 [style-profile-generator.md](style-profile-generator.md)）：

```text
node "{story-long-analyze skill 根}/scripts/manage_analysis_run.js" mark-stage --root "{拆文目录}" --stage stage2
```

## 原文变化与章号对不上

`build_chapter_index.js` 因原文变化非零退出，或报 `chapter_mapping_ambiguous`、`index_would_shrink` 时读本节，并按 [author-facing.md](author-facing.md) 转述 `author_message`。

- **原文变更**：作者确认后加 `--rebuild`（自动沿用已有章号口径含 `--fold-prologue`；前段错位或缩水时不写索引）。追加新章只标新增/变动 `pending_chapters`；改已拆章只让该批缓存失效不覆旧摘要（刷新须删该章摘要与对应缓存再续跑）。
- **旧成果章号错位**：写新索引前脚本核对旧章界，对不上即停（`plan` 遇错位索引亦拒）。有楔子给三选，无楔子给后两项：
  1. **按旧章号继续（推荐）**：加 `--fold-prologue` 把楔子/序章/引子/第0章并进第 1 章（输出 `folded_into_first_chapter`），沿用旧成果并在报告「还不确定的地方」注明。
  2. **按新章号重拆**：把除 `原文/` 外所有按旧章号写的产物（`章节/`、`剧情/`、`角色/`、`设定/`、`人物关系图/`、`快速预览.md`、`概要.md`、`拆文报告.md`、`文风.md`、`_analysis_cache/批次-*.md`、`_progress.md`）挪进 `_analysis_cache/legacy/旧章号/` 后从 Stage 0 重拆。
  3. **换新目录整本重拆**。
- 口径建错先删 `chapter_index.csv` 重建（`--rebuild` 不改口径）。连载跳号/重号按序连续编 `chapter`、原号留 `source_chapter` 并在 `numbering_anomalies` 报行号；正文短句误判标题时请作者修原文后 `--rebuild`。

## 收尾检查

拆完后逐项核对，通过后再按 [author-facing.md](author-facing.md)「全部拆完」汇报（检查结果不写入汇报）：

- 重跑检查器与计划器：完整项目为 `direct_use`，本次范围 `continue` 无待处理批次；
- 完整管道及续跑确认 `拆文报告.md`「文风一句话」已按 `文风.md` 补齐（单补旧文风不改旧报告）；
- 核对受保护路径：常规增强/恢复未改写旧 `章节/`、`剧情/`、`角色/`、`设定/`、`文风.md`，仅补缺项与 `_progress.md` 受管区；既有 `schema_version` 未变；
- 新投影的情节点序列、主题、基调、类型与「涉及」字段可被导入与写作读取；
- 回填过 `选题决策.md` 时，只改了题材匹配选题那一行。
