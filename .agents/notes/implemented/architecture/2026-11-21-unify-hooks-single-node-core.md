# Agent Note: 五端 Hook 引擎统一收口到单一 Node.js 共享核

Status: implemented
Date: 2026-11-21
Supersedes: 2026-07-15-hook-guard-failure-semantics.md

## Problem

仓库此前为五个支持 Hook 的宿主（Claude Code、Codex、OpenCode、Antigravity、ZCode）维护着三门语言的平行实现：

1. **Codex（Python）**：`skills/story-setup/references/codex/hooks/story_codex_hook.py`（1,720 行）几乎逐行手抄了 `story_hook_core.js`（1,386 行），只多了 `find_changed_prose_files()` 与 `compact_summary()` 两个 30 行级辅助函数，却迫使仓库长期维护 `check-hook-regex-sync.sh`（471 行正则 AST 同步锁与变异测试）、`test-prose-net-parity.sh`（1,050 行跨语言逐字 diff）和 `check-codex-adapter.sh` 的 Python AST UTF-8 编码守卫。
2. **Claude Code（Bash + Node 桥）**：`.claude/hooks/` 包含 10 个 Bash 脚本（1,080 行）外加 `story_hook_cli.js`（217 行），为满足无 Node 环境的纯 Bash 大纲拦截回退（`2026-07-15-hook-guard-failure-semantics.md`）重复实现了目标路径抽取、空细纲字节计数、伏笔表 awk 解析、`stagedMarkdownWarnings` grep 和 `LC_ALL=C` / GBK 区域安全体操，连带维护 `check-hook-locale-safety.sh`（80 行）和 Part D Bash↔JS parity 矩阵。
3. **OpenCode（Bash pre-commit）**：`references/opencode/pre-commit.sh`（90 行）保留了最后一份 Bash 版 `stagedMarkdownWarnings`。

与此同时，`storyctl.py chapter check` 已硬性要求 Node.js 18+（缺 Node 无法提交任何章节），OpenCode、ZCode、Antigravity 也早已统一运行在 Node.js 之上。继续为「无 Node 的原生 Claude Code」和「Python 版 Codex Hook」维护 4,500+ 行多语言镜像与同步守卫，维护成本远大于收益。

## Decision

- **声明 Node.js 18+ 为全宿主统一 Hook 运行时**：覆盖 [2026-07-15-hook-guard-failure-semantics.md](2026-07-15-hook-guard-failure-semantics.md) 中「Claude Code 写正文阻断守卫必须保留纯 Bash 无 Node 回退」的决定。所有五个 Hook 宿主（Claude Code、Codex、OpenCode、Antigravity、ZCode）统一复用同一份 `story_hook_core.js`（继续按 `scripts/shared-assets.json` 分发各自自包含副本，由 `sync-shared-assets.py` / `check-shared-files.sh` 锁字节一致）。
- **扩展共享核 `story_hook_core.js`**：新增 `detectStoryGaps(root)`、`analysisIncomplete()`、`discoverIncompleteAnalyses(root)`、`FORESHADOW_NORMAL_STATUSES` / `FORESHADOW_WARN_STATUSES`，修复 `resolveTarget()` 在 POSIX 下对 Windows 盘符路径的绝对路径分类（issue #184），并导出 `DESLOP_SKIP_MARKER`。所有内部 `spawnSync("git", ...)` 显式传 `windowsHide: true`。
- **Codex 迁移到 Node 薄适配器**：
  - 将 `skills/story-setup/references/codex/hooks/story_hook_core.js` 登记进 `scripts/shared-assets.json`。
  - 新增 `skills/story-setup/references/codex/hooks/story_codex_hook.js` 实现 6 个 Codex 事件（含 `findChangedProseFiles()` 与 `compactSummary()`，所有 Git 子进程传 `windowsHide: true`），保留原有 Codex JSON 输出信封。
  - 删除 `story_codex_hook.py` 与 `scripts/generate-codex-hooks.py`（`hooks.json` 已通过 launcher 路由，无需改动；`merge-codex-hooks.py` 的 `MANAGED_COMMAND_MARKERS` 继续保留 `.codex/hooks/story_codex_hook.py` 以清理旧版 v17 注册）。
  - 更新 `codex/hooks/run-story-hook.sh` 与 `run-story-hook.cmd` 改探 `node`（缺席时 fail-open 退 0）。
- **Claude Code 收敛为单入口 launcher + Node 适配器**：
  - 扩展 `skills/story-setup/references/templates/hooks/story_hook_cli.js` 直接承载全部 8 个 Claude Hook 事件（`session-start`、`detect-story-gaps`、`session-end`、`pre-compact`、`post-compact`、`pre-tool-prose-guard`、`pre-tool-commit-advisory`、`post-tool-prose-check`）并保留 `analysis-input-guard`（避免牵动 `chapter-extractor.md` 与 `sync-opencode.py`）。
  - 新增薄启动器 `skills/story-setup/references/templates/hooks/run-story-hook.sh`：存在 `node` 时 `exec node "$CLI" "$EVENT"`；缺少 `node` 时在 `session-start` 输出一条明确告警并在 `pre-tool-prose-guard` 写 stderr 告警后 fail-open（exit 0）。
  - 删除 10 个旧 Bash 脚本及 `lib/common.sh`、`lib/sentinel.sh`。
  - `settings-hooks.json` 全部指向 `run-story-hook.sh <event>`；`merge-claude-settings.py` 的 `MANAGED_HOOK_SCRIPTS` 新增 `run-story-hook.sh` 并保留全部 8 个旧 `.sh` 脚本名以确保旧项目平滑升级。
  - `agents_version` 从 44 升至 45。
- **OpenCode `pre-commit.sh` 瘦身**：改为 15 行内 POSIX `/bin/sh` 包装，调用 `.opencode/plugins/lib/story_hook_core.js` 的 `stagedMarkdownWarnings(root)`，缺 `node` 或核时静默 fail-open。
- **退役跨语言同步/区域守卫并收敛测试**：删除 `check-hook-regex-sync.sh`、`test-prose-net-parity.sh`、`check-hook-locale-safety.sh`、`test-prose-backstop-hook.sh`、`test-story-continuity.sh`、`test-hook-encoding-portable.sh`、`test-codex-hooks.sh`；以 `node --test` 原生测试 `scripts/test-story-hook-core.mjs`、`scripts/test-codex-hooks.mjs`、`scripts/test-claude-hooks.mjs` 承接全部行为回归（含 `FORESHADOW_STATUSES` / `DESLOP_SKIP_MARKER` 同步校验、真实 `zh_CN.GBK` 区域、Windows 盘符路径及 `windowsHide: true` 断言）。

## Alternatives considered

- **在 Claude `run-story-hook.sh` 中保留 30 行纯 Bash 缺细纲兜底（缺 Node 时启用）**——最强理由：原生二进制装法的 Claude Code 若用户尚未装 Node.js，首次写正文仍能拦住明显缺细纲的情况。否：即便保留缺细纲兜底，空细纲、追踪检查点、欠账门与 `storyctl chapter check` 仍依赖 Node.js 18+，用户无法完成任何一章的提交流程；保留第二份 Bash 路径判断与 JSON 抽取会重新引入 GBK/盘符/路径漂移测试面，违背「单一实现零漂移」目标。改为 `session-start` 与 `pre-tool-prose-guard` 显式告警引导安装 Node.js 18+，语义清晰且五端一致。
- **继续保留 Codex Python Hook，只收敛 Claude Code Bash Hook**——最强理由：Codex 用户若机器上已有 Python 但未装 Node，不受影响。否：OpenAI Codex CLI 本身通过 Node/npm 或自带环境运行且 `storyctl` 已要求 Node.js 18+；留下 Python 镜像会让 `check-hook-regex-sync.sh` 与 `test-prose-net-parity.sh`（1,521 行）继续存在，省不掉核心维护债务。

## Consequences

- **收益**：
  - 净删约 3,500+ 行重复实现与跨语言同步守卫，五端 Hook 逻辑全部归于同一份 `story_hook_core.js`。
  - 彻底消除 Bash/awk/grep 的 GBK 多字节编码与 `LC_ALL=C` 维护负担；Node.js 原生 UTF-8 处理跨平台一致。
  - 新增/修改一条写作守卫规则只需改 `story_hook_core.js` 并同步共享副本，零跨语言漂移。
  - 测试转为 `node --test` 进程内执行，速度显著提升且三平台一致。
- **代价与兼容边界**：
  - 极少数未安装 Node.js 18+ 的原生 Claude Code 或 Codex 环境，写正文前置守卫会 fail-open（同时在会话起点与写正文触发时明确告警）；已有写作项目需在升级包后重跑 `/story-setup` 刷新 `.claude/hooks/` 与 `.codex/hooks/`（`agents_version` 44 → 45）。
  - 升级清理依赖 `merge-claude-settings.py` 与 `merge-codex-hooks.py` 长期保留旧脚本标记名。

## Verification

- `python3 scripts/sync-shared-assets.py && bash scripts/check-shared-files.sh`
- `node --test scripts/test-story-hook-core.mjs scripts/test-claude-hooks.mjs scripts/test-codex-hooks.mjs scripts/test-antigravity-hooks.mjs scripts/test-opencode-plugin.mjs`
- `bash scripts/test-zcode-hooks.sh`
- `bash scripts/check-story-setup-deployment.sh`
- `bash scripts/check-opencode-adapter.sh && bash scripts/check-codex-adapter.sh && bash scripts/check-claude-adapter.sh`
- `python3 scripts/test-style-precedence.py && python3 scripts/check-agent-notes.py`
