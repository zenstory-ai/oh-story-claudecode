# Agent Note: Skill 运行时脚本统一收口到零依赖 Node.js 18+

Status: implemented
Date: 2026-11-21

## Problem

此前用户侧 Skill 的运行时脚本同时依赖 Node.js 18+ 与 Python 3 两套环境：

1. **双运行时维护与调用摩擦**：正文检测、标点整理、大纲验收、扫榜抓取与五端 Hook 核都已是 Node.js，但追踪事务（`tracking_commit.py`）、字数口径（`wordcount_core.py`）、作者记忆（`author_memory_commit.py`）、单章生命周期（`storyctl.py`）、取段与组装器（`outline_view.py`、`build_writer_prompt.py`、`build_architect_brief.py`、`build_outline_brief.py`）、部署辅助（`story-setup/scripts/*.py`）、发布校验（`check-publish-format.py`）与长篇拆文索引（`story-long-analyze/scripts/*.py`）仍是 Python。
2. **Skill 文档充斥 `python3 → python → py` 探测样板**：几乎每条 CLI 命令都要包一层 `for PYBIN in python3 python py` 探测循环，在 Windows Store stub 与多宿主 shell 环境下脆弱且消耗热路径上下文。
3. **跨语言重复镜像**：`check-outline-contract.js` 为避免子进程调用 `wordcount_core.py`，不得不维护一份独立的字数目标与口径正则副本；`storyctl.py` 每次章节检查都要从 Python 跨进程拉起多个 Node.js 检测器。

唯一真正依赖 Python 生态的脚本是 `skills/story-long-analyze/scripts/render_relation_chart.py`（依赖可选的 `matplotlib` 渲染人物关系 PNG 图）。

## Decision

- **全部纯标准库 Skill 运行时迁移到零依赖 Node.js 18+ CommonJS `.js`**：
  - **Wave D2（`story-setup` 与 `story-publish`）**：将 7 个 Python 脚本迁移并收拢为 5 个 `.js` 脚本（`copy-path-safety.js`、`deploy-antigravity-skills.js`、`merge-project-instructions.js`、统一 `--host claude|codex|antigravity` 的 `merge-hooks.js`、`check-publish-format.js`），使 `/story-setup` 与 `/story-publish` 完全零 Python 依赖。
  - **Wave D1 + D1b（核心写作 / 导入 / 审稿 / 短篇）**：将 `wordcount_core.py`、`tracking_commit.py`、`author_memory_commit.py`、`outline_view.py`、`storyctl.py`、`build_writer_prompt.py`、`build_architect_brief.py`、`build_outline_brief.py` 全部迁移为 `.js` 并删除 `.py` 原件与同步副本；`check-outline-contract.js` 改为直接 `require("./wordcount_core.js")` 消除正则镜像；`storyctl.js` 与 `build_writer_prompt.js` 在同进程内 `require()` 共享模块，并通过 `process.execPath` + `windowsHide: true` 调用检测器。
  - **Wave D3（`story-long-analyze`）**：将 `build_chapter_index.py`、`inspect_existing_assets.py`、`manage_analysis_run.py`、`inspiration_index.py` 迁移为 `.js` 并删除 `.py` 原件；保留 `render_relation_chart.py`（`matplotlib` 绘图唯一 Python 例外，保留 `PYBIN` 探测）。
- **保持跨平台确定性语义不变**：统一采用 UTF-8 `Buffer.byteLength` 字节预算、Unicode NFC 规范化、原子临时文件写入、Windows 保留文件名校验、子进程 `windowsHide: true` 与基于 `O_CREAT|O_EXCL` + `Atomics.wait` 的文件锁；所有既有回归测试集保留原断言，通过 `node` 驱动新 `.js` 运行时验证等价性。
- **同步共享清单与宿主适配层**：更新 `scripts/shared-assets.json`、各 Skill 文档与 Agent 真源模板，重新生成 OpenCode / Codex / ZCode / Antigravity 适配层并同步共享副本；仓库开发脚本（`scripts/` 下的测试与生成器）保持现有 Python/Node 混合不变，不影响用户写作项目运行时。

## Alternatives considered

- **维持 Python + Node 双运行时现状**——最强理由：Python 标准库对文本处理成熟、已有脚本长期稳定，无需投入一次完整迁移与回归验证成本。否：所有主流编程 Agent（Claude Code、Codex、OpenCode、Antigravity、ZCode）及本项目 Hook 与检测器已强依赖 Node.js 18+，用户只装 Node 即可跑通除关系图外的全部写作、导入、审稿、部署、发布与拆文流程；继续保留双运行时会让每个 Skill 持续背负 `PYBIN` 探测样板与跨语言重复逻辑。
- **连同 `render_relation_chart.py` 一起用 Node 重写图表渲染**——最强理由：可彻底归零 `skills/` 下的 `.py` 文件。否：纯 Node 生成带中文字体回退的力导向/布局关系 PNG 图需要引入重型 native 依赖（canvas/sharp）或手写排版引擎，违反运行时零外部 npm 依赖原则；该脚本本身属于 Stage 4 可选出图环节，独立保留为唯一可选 Python 能力代价最小。
- **同步重写 `scripts/` 下的仓库测试与代码生成器为 Node**——最强理由：仓库内外彻底单语言。否：`scripts/` 仅供本仓库 CI 与维护者使用，不随 Skill 部署给作者；保留现有 Python 回归测试壳（调用 `node` 执行运行时 `.js`）可避免测试与被测实现同时重写带来的盲区。

## Consequences

- **收益**：
  - 用户写作项目运行时统一为单一 Node.js 18+ 依赖（仅可选人物关系图 `render_relation_chart.py` 需要 Python + matplotlib）。
  - `skills/` 下去除绝大部分 `for PYBIN in python3 python py` 探测样板，热路径文档更清爽。
  - `check-outline-contract.js` 复用 `wordcount_core.js` 消除跨语言口径镜像，`storyctl.js` / `build_writer_prompt.js` 减少跨语言进程桥接。
  - `merge-hooks.js` 将三端 hook 合并器收拢为单一实现，保留旧版清理标记兼容存量项目升级。
- **代价与兼容边界**：
  - Node.js 18+ 成为全部写入/部署/发布/拆文 Skill 的统一前提（此前 `storyctl` 与五端 Hook 已要求 Node.js 18+）。
  - 既有写作项目升级后需按常规重跑 `/story-setup` 以刷新 Agent 模板中对 `tracking_commit.js` / `manage_analysis_run.js` 的指令引用。
  - `scripts/bench/deploy.py` 保留对历史 tag（`.py` 部署脚本）的向后回退分支，确保跨版本 benchmark 对比可用。
