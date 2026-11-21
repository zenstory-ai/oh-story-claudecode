# Agent Note: 长篇写作运行时管道精简（零正文与开篇质量回退）

Status: implemented
Date: 2026-11-21
Related: [最小版重建（被否决，确立质量硬边界）](../../rejected/architecture/2026-11-02-long-write-minimal-rebuild.md)、[在 0.9.2 上清理（0.10.0）](2026-11-03-long-write-0-10-cleanup.md)、[细纲必填收到九个字段](../simplification/2026-09-25-outline-core-fields.md)

## Problem

`story-long-write` 在 0.10.x 迭代中保留了一批一次性迁移工具、历史过渡期兼容分支与无真实故障举证的散文/流程校验逻辑：

1. `convert_outline_format.py`（414 行）是 v0.9→v0.10 的可选一次性格式转换脚本，工作流从不调用，且旧格式卷纲/细纲本来就由解析层原生兼容。
2. `template_fence.py`（58 行）及 `scripts/current-contract.json` 的 `template_fences` 清单仅服务于 `build_architect_brief.py` 读取 5 处静态模板块；此前配套的 `check-reference-routing.py` 已在 Track A 退役。
3. `storyctl.py` 维护了基于 `over_length_baseline.json` SHA-256 指纹的 `COMPRESSION_REQUIRED` 强拦截门禁，额外引入跨调用临时状态与拒收摩擦，而真正的创作提示只需保留 `compress-once` 删除字数区间与 `<50%` 的 `BELOW_ACCEPT_FLOOR` 安全底线。
4. `check-outline-contract.js`（603 行，跨 `story-long-write` / `story-import` 双副本）承载了大量非结构化巡检：`--supply` 检查排纲笔记是否含「写纲前查缺」标题、pre-0.10 的 `outline.plotpoint-release` / `outline.plotpoint-release-ratio`、`outline.release-brevity` 与 `outline.contract-risk` 枚举检查。
5. `outline_view.py`（414 行，双副本）仍保留 v0.8 前的 `--stage outline` / `批次底稿` 分支（排纲笔记早已迁至 `.story/排纲笔记/`），以及 `IMPERATIVE`（W1）、`LEAK`/`POINTER`（E4）散文正则启发式告警。
6. `build_architect_brief.py` 依赖脆弱的 `SKILL.md` blockquote 抓取器与 `template_fence.py`；`build_writer_prompt.py` 槽位说明和注释冗余。

同时，[2026-11-02 最小版重建被否决的复盘](../../rejected/architecture/2026-11-02-long-write-minimal-rebuild.md) 证明不能削弱正文技法参考、开篇规划深度（`分场`、`目标情绪`、`主角目标/关键选择`）或无 Bash 权限子代理的任务包/上下文切片器。

## Decision

在严守质量硬边界（不动 `writing-craft.md`、`dialogue-mastery.md`、场景技法、`outline-template.md` 核心字段与 `分场`、以及 `narrative-writer.md` / `story-architect.md` 模板，`agents_version` 保持 `45`）的前提下，只裁减无收益或已过时的运行时管道代码：

1. **删除一次性/过度抽象脚本**：
   - 删除 `skills/story-long-write/scripts/convert_outline_format.py` 与 `skills/story-long-write/scripts/template_fence.py`。
   - 从 `scripts/current-contract.json`、`scripts/lint-repo.py` 与 `scripts/test-current-skill-contracts.py` 移除 `template_fences` 校验；`skills/story-setup/UPGRADING.md` 注明历史转换脚本可按需从 `v0.10.5` tag 取用；`skills/story-long-write/references/outline-template.md` 移除对该脚本的指向。
2. **移除 `storyctl.py` 超长 SHA-256 基线拦截**：
   - 删除 `BASELINE_FILE` (`over_length_baseline.json`)、`_body_digest`、`_record_over_baseline` 与 `COMPRESSION_REQUIRED` 拒绝逻辑。
   - 完整保留 `chapter check` 返回的 `compression` 删除字数区间与 `compress-once` 指引、`<50%` 的 `BELOW_ACCEPT_FLOOR` 底线、`accept-current-length` 与 `--force`。同步更新 `workflow-chapter.md`、`tracking-transaction.md`（并同步到 `story-review`）及 `scripts/test-chapter-completion-lifecycle.py`。
3. **精简 `check-outline-contract.js`（同步 `story-import` 副本）**：
   - 保留结构与消融实证核心检查：`outline.readable`、7 个必填字段、`outline.intent-fields-substantive`（`目标情绪` 与 `主角目标/关键选择`）、4 个小节、五段式五行、3–5 列表头结构、`outline.setting-refs-exist`、与 `wordcount_core.py` 同构的 `outline.wordcount-target` / `字数范围` / `字数口径` 解析。
   - 删除 `--supply` 模式、pre-0.10 `outline.plotpoint-release` / `outline.plotpoint-release-ratio`、`outline.release-brevity`、`outline.contract-risk`。同步更新 `workflow-outline.md` 与 `scripts/test-outline-contract.js`。
4. **精简 `outline_view.py`（同步 `story-import` 副本）**：
   - 保留 `--toc`、`--chapter`、`--unit`、`--contract`、`--history`、`--check [--strict]`、新旧作用域解析（`<!-- 全卷 -->` / `<!-- L1-01 -->` / 旧 `> 作用域：`）、`is_unit_card()`、`unit_chapter_range()`、`chapter_unit_in_volume()`、`slice_arc()` 与结构性检查（E1/W2、E2、E3）。
   - 删除 `--stage outline` / `批次底稿` 分支及 `IMPERATIVE`（W1）、`LEAK`/`POINTER`（E4）散文正则检查。同步更新 `workflow-outline.md`、`build_architect_brief.py` 与 `scripts/test-writer-pipeline.py`。
5. **精简任务包与写手组装脚本（保留无 Bash 子代理支撑）**：
   - `build_architect_brief.py` 内联围栏读取辅助函数替代 `template_fence.py`，以静态 6 行 `NEW_ADDITION_TIERS` 常量替代脆弱的 `SKILL.md` blockquote 抓取，去除 `批次底稿` 分支。
   - `build_writer_prompt.py` 压缩冗长注释与重复槽位说明，完整保留标题学习、7 栏状态校验、文风/对标判定、上一章结尾截取、召回降档、题材卡匹配、「作者已定」与作者记忆代查。

## Alternatives considered

- **直接删除 `outline_view.py`、`build_architect_brief.py`、`build_writer_prompt.py`，让子代理直接读原文件**。最强理由：可以一次再砍掉约 1,000 行脚本。不采用：`story-architect` 与 `narrative-writer` 模板工具集不含 Bash，无脚本预切片会导致直接整读 30K 卷纲与前章全文，击穿 35K 加载硬上限并丢失 v0.8 的 39% token/耗时收益。
- **同步删除 `storyctl.py` 的 `compression` 区间计算或 `BELOW_ACCEPT_FLOOR`**。最强理由：进一步简化 `chapter check` 输出。不采用：`compression` 区间为「超字一次净删」提供确定性删减目标，不写临时文件也无拦截成本；`<50%` 底线拦截的是明显截断/未写完的事故稿，成本极低。
- **保留 `check-outline-contract.js` 的 `--supply` 校验**。最强理由：能机械确认排纲笔记存在「写纲前查缺」标题。不采用：只查标题存在无法判断查缺质量，却带来约 100 行维护代码与双副本负担，不符合 `AGENTS.md` 的举证门槛。

## Consequences

- **收益**：净删约 1,400+ 行（含双副本物理行数）过时脚本与冗余测试；去除了超长写章的隐藏指纹状态拦截和脆弱的 Markdown 抓取耦合；为后续运行时统一到 Node 减少大量无效迁移面；`agents_version` 保持 `45`，零 7 宿主适配层抖动。
- **代价**：极少数希望批量把 v0.9 卷纲/细纲改写成 v0.10 视觉格式的存量用户需从 `v0.10.5` tag 取用旧转换脚本（不影响直接读写与续写）；老卷纲中若仍内嵌「作用域：批次底稿」段，不再通过 `--stage outline` 单独拉出。
