# Agent Note: 退役断链三层灵感库并收口五端 Hook 版本提醒、参考漂移与测试/发布清账

Status: implemented
Date: 2026-11-21
Related: [2026-09-22-inspiration-library-em-pipeline](../feature/2026-09-22-inspiration-library-em-pipeline.md)、[2026-09-23-inspiration-library-takeover](2026-09-23-inspiration-library-takeover.md)、[2026-11-21-unify-hooks-single-node-core](../architecture/2026-11-21-unify-hooks-single-node-core.md)、[2026-11-21-ci-meta-checks-and-test-slimming](2026-11-21-ci-meta-checks-and-test-slimming.md)

## Problem

在 PR #559 收口全仓库到 Node.js 18+ 运行时与单核 Hook 后，对全仓代码、文档、契约与清单的复核暴露出几处高置信漂移与死代码：

1. **三层灵感库（`inspiration_index.js` / `inspiration-library.md`）已与下游完全断链**：消费侧（长篇写作、开书、卷纲、细纲、写手）已不再召回 `灵感库/`，只消费拆文 `剧情/情绪模块.md` 的 EM 机制卡本身；但拆文侧仍留着 1,271 行索引脚本、116 行参考文档和 711 行测试，并在 `story` / `story-long-analyze` / `doc-budget.json` 中占位。
2. **五端 Hook 的 `agents_version` 过期提醒仅在 Claude Code 生效**：`CURRENT_AGENTS_VERSION` 和 `readSentinel` 写在 `story_hook_cli.js` 里，Codex、ZCode、OpenCode、Antigravity 四个 Hook 宿主启动时不检查 `.story-deployed` 的 `agents_version`；同时 `story_hook_core.js` 的 6 条硬阻断规则（`voice-contrast`、`negation-parade`、`not-is-comparison`、`reverse-not-is`、`trailer-ending`、`trailer-summary`）缺少跨文件全规则一致性测试，ZCode Hook 回归仍是含 `sleep 2` 的 Bash 脚本 `test-zcode-hooks.sh`。
3. **`agent-references/`、`shared-references.json` 与 `current-contract.json` 存在漂移与死字段**：`shared-references.json` 重复登记了 `derived_groups`，导致 `agent-references/long-emotional-methods.md` 未与 canonical 同步；`agent-references/format-and-structure.md` 残留过时 `visible_chars_v1` 与旧句长规则；`current-contract.json` 和 `lint-repo.py` 保留了不再使用的 `topic_decision_phase` 与 `required_outline_sections`。
4. **文档、资产与发布清单残留历史口径**：`story-short-write/references/short-format.md` 仍带 Python 字数片段；`story-review` / `story-deslop` / `story-import` / `story` / `zcode/AGENTS.md.tmpl` 残留已淘汰的 `技术备注：` 口径；`outline-template.md` 错写「四个小节」；`UPGRADING.md` 把 `agents_version: 45` 标成 v0.10.5；`demo/封面-剑道独尊.png` 体积达 3.1 MB；`.clawhub/publish.json` 给 6 个纯 JS Skill 误标 `bin:python`，给 `story-publish` 漏标 `bin:node`。

## Decision

1. **彻底退役三层灵感库管道，保留单书 EM 机制卡**：删除 `skills/story-long-analyze/scripts/inspiration_index.js`、`skills/story-long-analyze/references/inspiration-library.md`、`scripts/test-inspiration-index.py`，清理 `story-long-analyze` / `story` / `doc-budget.json` / CI / 文档中的入口与注释。`scripts/test-handoff-contracts.py` 改为直接解析 `stage3-plot-rhythm.md` 中的 EM 机制卡模板，保留拆文到写作端的 EM 卡交接契约验证。
2. **五端 Hook 共享 `agents_version` 过期提醒并补齐 6 规则跨文件测试**：把 `CURRENT_AGENTS_VERSION`、`readSentinel(root)`、`agentsVersionNotice(root, opts)` 上移到共享核 `story_hook_core.js` 并同步五端；Claude Code、Codex、ZCode、OpenCode、Antigravity 全部在会话起点/首轮上下文检查 `.story-deployed`。在 `scripts/test-story-hook-core.mjs` 补齐 6 条阻断规则与 `check-ai-patterns.js` 的跨文件一致性测试，并将 `scripts/test-zcode-hooks.sh` 迁为无 `sleep` 的 `scripts/test-zcode-hooks.mjs` 并入 `node --test` Hook 套件。
3. **清理契约死字段与参考漂移**：删除 `scripts/current-contract.json` 与 `scripts/lint-repo.py` 中的 `topic_decision_phase` 和 `required_outline_sections`（并在 `test-current-skill-contracts.py` 断言二者被 `manifest-key-unknown` 拒绝）；清理 `scripts/shared-references.json` 重复派生组并同步 `agent-references/`。
4. **统一纯 Node 文档、白话汇报口径与 ClawHub 清单**：`short-format.md` 字数统计改为 `node -e`；清理各 Skill 及 ZCode 模板中的 `技术备注：` 要求；修正 `outline-template.md` 与 `UPGRADING.md`；将 `demo/封面-剑道独尊.png` 压缩至 ~142 KB；删除过时迁移文档 `docs/reference-workflow-cleanup.md`；在 `.clawhub/publish.json` 中移除 6 个纯 JS Skill 的 `bin:python`、为 `story-publish` 补 `bin:node`，并按 `clawhub_release.py` 递增受改动已发布 Skill 的 patch 版本与 `packageDigest`。

## Alternatives considered

- **保留灵感库脚本并重新接线到写作端**：可以复用既有索引与闭包校验逻辑；但写作端已在 v0.8–v0.10 收口为直接消费对标书的 `剧情/情绪模块.md` 与热路径 35K 预算约束，重接会重新引入多层维护与上下文开销，因此选择退役。
- **只在 Claude Code 保留 `agents_version` 过期检查**：实现最省事、不动另外四端 Hook；但多宿主升级后用户无法在 Codex / ZCode / OpenCode / Antigravity 收到过时提醒，违背五端共享核的设计目标，因此统一进 `story_hook_core.js`。
- **继续保留 Bash 版 `test-zcode-hooks.sh`**：免去迁移工作量；但依赖 `sleep 2` 拖慢三平台 CI 且与其余四端 `node:test` 测试不一致，迁到 `node:test` + `fs.utimesSync` 后跨平台更稳且耗时从 ~3.5s 降至 ~0.4s。

## Consequences

- **收益**：净删超 2,000 行断链死代码与过时文档；五端 Hook 具备一致的 `agents_version` 升级提醒与完整的 6 规则正文兜底一致性守卫；ZCode Hook 回归零 `sleep` 并入三平台 `node --test`；`agent-references/` 与 ClawHub 运行时依赖声明恢复准确。
- **代价**：若未来确需跨书灵感索引，需要基于当前写作端消费路径重新设计，不能直接恢复旧 `灵感库/` 目录协议（单书 `拆文库/{书名}/剧情/情绪模块.md` 的 EM 卡格式不受影响）。
