# 长篇拆文运行、提交、索引重建与收尾检查

## 状态与脚本

运行脚本：`build_chapter_index.js`（机械章界与 hash）、`inspect_existing_assets.js`（只读查成果与缺口）、`manage_analysis_run.js`（计划、提交、拆批、恢复、标阶段、`digest` 与 `prose-stats` 量化体检）；Stage 4 另用 `render_relation_chart.py` 画关系图。带 `author_message` 按 [author-facing.md](author-facing.md) 转述，不贴 JSON 或错误码。

`chapter_index.csv` 是章界唯一依据；运行状态唯一落在 `_progress.md` 的 `story-long-analyze:runtime-state` 受管区；`_analysis_cache/` 存恢复证据；既有 `schema_version: 2` 原值保留。计划只打标准输出。

## 1. 核对目录

按 SKILL.md「Phase 1–2」跑 `inspect_existing_assets.js --compact` 并依 `recommended_path` / `stage_repairs` 路由。

## 2. 索引与量化体检

需读原文时建/校索引，Stage 1/6 量化体检一律跑 `prose-stats`（禁目测估算）：

```text
node "{story-long-analyze skill 根}/scripts/build_chapter_index.js" --source "{拆文目录}/原文/原文.txt" --output "{拆文目录}/chapter_index.csv" --locator-path "原文/原文.txt"
node "{story-long-analyze skill 根}/scripts/manage_analysis_run.js" prose-stats --root "{拆文目录}" --chapters 1-3
```

## 3. 生成只读计划

```text
node "{story-long-analyze skill 根}/scripts/manage_analysis_run.js" plan --root "{拆文目录}" --intent continue
```

- `continue`：补缺章与缓存失效批次，有语义缺摘要则投影；`enhance`：为缺完整缓存的已拆章建 `REUSE` 批次提取跨章观察（有缺章同步列 `RAW`，或加 `--chapters` 只增强已拆段）。
- 参数：`--next 1` 取下一批、`--next 0` 看余量、`--chapters 起-止` 只拆指定段（拆完即停不标 `stage2`）。原文读取为 0 不得派原文任务；黄金三章深拆已属语义成果不重读。

## 4. 执行与提交一个批次

`chapter-extractor` 每次只做 1 批；**主会话不中转内容**，照抄计划字段（路径加 `{拆文目录}/`：`batch_id`、`input_kind`、`source_files`、`chapter_chars`、`min_plot_points`、`input_file`=`_analysis_cache/输入-{批次ID}.md`、`handoff_cache` 仅读 `### 跨批状态`）。子代理写完只回 `BATCH_WRITTEN`，主会话不 Read 文件直接逐个 `commit`（不并发），被拒原样重派附错误码定点修补，成功后删输入文件。

派发默认第 2 档有限并行（作者问起按 author-facing 切换）：① 串行 `plan --next 1`；② 有限并行（默认）`plan --next 3` 同轮派 3 批共用轮前 `handoff_cache`；③ 不限顺序最多 12 并发（限流/超时上限减半，多书共用）。子代理不可用时先读 [stage2-extraction.md](stage2-extraction.md) 自写，再提交（`REUSE` 不传 `--range-sha256`）：

```text
node "{story-long-analyze skill 根}/scripts/manage_analysis_run.js" commit \
  --root "{拆文目录}" --input "{拆文目录}/_analysis_cache/输入-RAW-4-6.md" \
  --batch-id "RAW-4-6" --range-sha256 "{plan 输出值}" --source-file "{plan 列出的来源}"
```

## 5. 失败、拆批、恢复与阶段标记

输出不完整不提交；批次过大或连续失败先 `split`（可加 `--at`）再重 `plan`；缓存已全但摘要/进度未落盘则 `repair-progress`。各阶段落盘后跑 `mark-stage`（Stage 1 含黄金三章、快速预览与 `_style-sample.txt`；Stage 3–5 见 [synthesis-inputs.md](synthesis-inputs.md)；Stage 6 见 [style-profile-generator.md](style-profile-generator.md)）：

```text
node "{story-long-analyze skill 根}/scripts/manage_analysis_run.js" split --root "{拆文目录}" --batch-id "RAW-4-6"
node "{story-long-analyze skill 根}/scripts/manage_analysis_run.js" repair-progress --root "{拆文目录}"
node "{story-long-analyze skill 根}/scripts/manage_analysis_run.js" mark-stage --root "{拆文目录}" --stage stage2
```

## 原文变化与章号对不上

`build_chapter_index.js` 非零退出或报 `chapter_mapping_ambiguous` / `index_would_shrink` 时读本节，按 [author-facing.md](author-facing.md) 转述 `author_message`。

- **原文变更**：确认后加 `--rebuild`（沿用旧口径含 `--fold-prologue`；前段错位或缩水不写索引）。追加新章标 `pending_chapters`；改已拆章只失效该批缓存不覆旧摘要。
- **旧成果章号错位**：写索引前核对旧章界，对不上即停（`plan` 亦拒）。有楔子给三选，无楔子给后两项：
  1. **按旧章号继续（推荐）**：加 `--fold-prologue` 把楔子/序章/引子/第0章并进第 1 章（输出 `folded_into_first_chapter`），沿用旧成果并在报告注明。
  2. **按新章号重拆**：将 `原文/` 外所有旧章号产物挪进 `_analysis_cache/legacy/旧章号/` 后从 Stage 0 重拆。
  3. **换新目录整本重拆**。
- 口径建错先删 `chapter_index.csv` 重建。跳号/重号按序编 `chapter`、原号留 `source_chapter` 报 `numbering_anomalies`；短句误判标题请修原文后 `--rebuild`。

## 收尾检查

拆完逐项核对，通过再按 [author-facing.md](author-facing.md)「全部拆完」汇报（检查不写进汇报）：

- 重跑检查器与计划器：完整项目为 `direct_use`，本次 `continue` 无待处理批次；
- 完整管道及续跑确认 `拆文报告.md`「文风一句话」已按 `文风.md` 补齐（单补文风不改旧报告）；
- 受保护旧产物未被改写，既有 `schema_version` 未变；新投影字段可被导入与写作读取；
- 回填 `选题决策.md` 时只改题材匹配行。
