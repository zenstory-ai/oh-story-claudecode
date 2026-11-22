# Agent Note: 确定性硬底线与有摩擦软门禁分层

Status: implemented
Date: 2026-11-21
Related: [2026-11-21-unify-hooks-single-node-core.md](2026-11-21-unify-hooks-single-node-core.md), [2026-10-15-deslop-three-layer.md](2026-10-15-deslop-three-layer.md), [2026-11-03-long-write-0-10-cleanup.md](2026-11-03-long-write-0-10-cleanup.md)

## Problem

在长篇与短篇写作全链路中，运行时守卫（五端 Hook、`check-ai-patterns.js`、`storyctl.js`、`tracking_commit.js`、`author_memory_commit.js` 以及大纲/阶段/交付契约检查）把两类本质不同的问题混成了同一层硬阻断（exit 1 / exit 2 / 拒绝写入或提交）：

1. **100% 确定性结构/完整性底线**：例如未展开的 shell 变量、首建长篇缺/空细纲、首建短篇缺小节大纲、`_tracking-state.json` 缺失或损坏、正文退化（AI 自指/拒绝语/占位符/工程词泄漏/紧邻复读/截断）、未闭合 HTML 注释与非标机械标点、严重欠字（`<50%` 目标字数）、数据行损坏或节标断号。这类问题客观确定，误杀率接近零，必须硬拦。
2. **启发式文风、结构偏好与软容量约束**：例如上一章毒句式欠账锁住下一章写入、7 条 AI 句式风格规则（`em-dash` 旁白、`trailer-summary`、`not-is-comparison`、`reverse-not-is`、`voice-contrast`、`negation-parade`、`trailer-ending`）直接阻断提交、跳章顺序锁或手工微调 `追踪/上下文.md` 修订号直接挡写正文、追踪/作者记忆的单字段字节帽与派生视图漂移直接判死、以及长/短篇大纲与交付的次要字段和边缘字数直接 exit 1。

把第二类问题当作硬锁导致三个真实痛点：合法的创作选择（如悬疑留白、有意跳章补写、多主角长记账、自定义细纲列、手工编辑派生 Markdown）被迫通过删改好文本或造假字段去“讨好脚本”；Antigravity `stop` Hook 在仅有风格提醒时强行拉回重生成，诱发无意义反复重写；写正文前置门禁把上一章风格债务变成下一章写入死锁。

## Decision

将全部写作运行时门禁统一按**「确定性硬底线（HARD） + 有摩擦软门禁（SOFT / Review-and-Ack）」**分层，兼顾零损坏底线与创作自由度，同时保留足够摩擦防止 Agent 静默忽视风险：

### 1. 五端 Hook 共享核与适配器（`skills/story-setup/references/**`）

- **`story_hook_core.js`（同步全部 5 份副本）**：
  - `proseBlockReason()` 仅保留 100% 确定性硬拦截：未展开 shell 变量、首建长篇缺/空（`<30` 字）`细纲_第N章.md`、首建短篇缺 `小节大纲.md`、`_tracking-state.json` 缺失/非法 JSON/`schema_version !== 4`/缺整数 `state_revision` 或 `last_committed_chapter`；Claude `analysis-input-guard` 保持 exit 2 硬沙箱。
  - 新增 `prosePreWriteWarnings()`、`formatPreWriteAdvisory()` 与 `inspectTrackingCheckpoint()`：上一章毒句式欠账（仍尊重 `<!-- 去味:跳过 -->` 与 `.deslop-whitelist`）、跳章顺序（`last_committed_chapter !== chapter - 1`）与手工修改 `追踪/上下文.md` `状态修订` 不一致，统一下沉为非阻断结构化写前复核提醒；`continuityFindings()` 仍同时报告硬/软追踪状态。
  - 新增 `proseDegenerationFindings()` 与 `hasHardProseFindings()`，把确定性硬缺陷（`<200B`/截断/元信息泄漏/占位符/工程词/紧邻复读）与纯风格毒句式拆开。
- **五端适配器接线**：
  - Claude Code `story_hook_cli.js`：`pre-tool-prose-guard` 仅硬拦 exit 2；软提醒输出 `hookSpecificOutput.additionalContext` JSON 并 exit 0。
  - Codex `story_codex_hook.js` 与 ZCode `story_zcode_hook.js`：软提醒走 `hookContext("PreToolUse", advisory)`（不带 `permissionDecision: "deny"`）。
  - Antigravity `story_antigravity_hook.js`：`pre-tool-use` 软提醒返回 `{ decision: "allow", reason }`；`stop` 仅在命中确定性硬缺陷时强制 `decision: "continue"` 1 次，纯风格发现不再强行拉回。
  - OpenCode `plugin.ts`：`execute.before` 仅硬拦时抛错；软提醒经 `pendingPreWriteWarnings` 挂载到 `execute.after` 的 `event.result.content`。

### 2. 风格 Review-and-Ack 与状态提交软门禁（`story-deslop` / `story-long-write` / `story-review` / `story-import` / `story-short-write`）

- **`check-ai-patterns.js`（同步 4 份副本）**：7 条风格 `blocking` 规则全部降级为 `severity: "review_required"`（低频仍为 `advisory`，向后兼容 `<!-- 去味:跳过 -->` 与 `.deslop-whitelist`）。JSON 输出汇总 `blocking` / `review_required` / `advisory` 三档计数；`--fail-on=blocking` 在无硬阻断时退 0，新增 `--fail-on=review_required` 供需要严格退 1 的调用方使用。
- **`storyctl.js`（Review-and-Ack 有摩擦提交）**：
  - 硬阻断仅保留：`TOOL_ERROR`/`TOOL_UNAVAILABLE`（exit 3）、空章/不可读、`check-degeneration.js` blocking、未闭合 HTML 注释与非标机械标点（旁白 `em-dash` 不再在标点层重复硬拦，统一归口 `review_required`）、以及严重欠字 `BELOW_ACCEPT_FLOOR`（`<50%` 需 `--force`）。
  - `chapter check`：0 硬伤且存在 `review_required_items` 时返回 `status: "review_required"`（exit 0），JSON 与 `--plain` 逐条列出 rule ID、行号、摘录及 `--ack <rule-id>:<简短理由>` 指引。
  - `chapter commit` / `accept-current-length`：支持可重复 `--ack <rule-id>:<reason>`、单次 `--ack-all <reason>`、`--ack length:<reason>`（带外 50%–85% / >115%）与 `--allow-gap`。未逐类确认时返回结构化 `REVIEW_ACK_REQUIRED`（含 `unacknowledged_rules`）拒绝提交；确认后放行并输出 `acknowledged_reviews` 供章末白话汇报。
- **`tracking_commit.js`（同步 3 份）与 `author_memory_commit.js`（同步 2 份）**：
  - 常规单字段字节帽、列表条数帽及常规视图尺寸帽（`逐章记录 <= 3072B`、`上下文.md <= 12288B`、`assertion <= 120B`、`作者画像.md <= 12288B`、`变更记录.md <= 24576B`）降级为结构化 `warnings`；保留确定性 schema/引用完整性校验与每视图 **64 KiB (`65536` bytes)**（作者记忆 JSON 2 MB）防失控硬帽。
  - `check` 命令在派生 Markdown 与 JSON 漂移时默认退 0 并输出结构化 `drift_warnings`（提示询问作者吸回还是重建），传 `--strict` 退 2。
  - `tracking_commit.js` `draft`/`commit` 支持 `--allow-gap` 显式放行跳章/补交并给软告警，默认维持顺序防手误保护。

### 3. 长/短篇大纲与交付双轨契约（`story-long-write` / `story-import` / `story-short-write`）

- **`check-outline-contract.js`（同步 2 份）、`check-phase2-contract.js`、`check-delivery-contract.js`**：统一输出 `strict`、`ok`、`status`（`pass|warn|fail`）、`hard_failures`、`soft_warnings`、`findings`（`severity: "blocking" | "advisory"`）、向后兼容的 `failures`/`advisories`/`repair_scope` 与新增 `review_scope`，并统一支持 `--strict`（将 `soft_warnings` 升级为 exit 1）。
  - 长篇细纲 HARD：`outline.readable`、`outline.wordcount-target`、`outline.intent-fields-substantive`（`目标情绪` 与 `主角目标/关键选择` 不得缺失或占位）；SOFT：`outline.required-fields`、`outline.subsections`、`outline.five-act`、`outline.plotpoint-table`、`outline.setting-refs-exist`。
  - 短篇 Phase 2 HARD：核心文件可读、无模板占位符、核心五列表头完整、至少 1 行且列数对齐、含子事件、目标字数可解析；SOFT：平台/题材声明、反派契约、自定义列、分节字数合偏差、反转位置、卡点双标。
  - 短篇交付 HARD：正文可读、无模板占位符（含 `{...}`）、不严重欠字（`>=50% min_chars`）、节标序列连续无重复；SOFT：边缘字数（`50%–100% min_chars` 或 `> max_chars`）、节数/单节下限、节标风格、空行格式。
- 工作流参考文档同步写明 `hard_failures`（必改）与 `soft_warnings` / `review_required`（重点复核、可留理由放行）及 `--strict` 用法，全部保持在 `scripts/doc-budget.json` 现有预算内。

## Alternatives considered

- **把所有风格与结构检查全部降为无摩擦 advisory（`chapter commit` 直接静默放行，不设 `--ack`）**——最强理由：CLI 接口最简单，零二次命令成本，Agent 不会在提交阶段卡壳。否：纯静默告警在多轮长篇写作中极易被模型忽略，导致「不是……而是……」「声音不大却……」等高频 AI 腔在连续多章里无声复发。引入 `--ack <rule-id>:<reason>` / `--ack-all <reason>` 保持“必须看过具体行号与摘录并给出简短理由”的显式摩擦，同时不再强迫作者或 Agent 为了过脚本而毁掉真正合理的句子。
- **完全取消写前 Hook 提醒，把毒句式与跳章检查全留到 `chapter check` 阶段**——最强理由：写正文前路径更短，进一步减少 Hook 代码量。否：跳章写入或手工改过 `追踪/上下文.md` 时，如果在动笔前没有任何提醒，Agent 可能基于过期上下文写完整章才在提交时发现漂移；保留非阻断的 `prosePreWriteWarnings` 让模型在起笔前看到上下文风险，但不制造硬死锁。
- **把 `check-outline-contract.js` / `check-phase2-contract.js` / `check-delivery-contract.js` 拆成两个独立脚本（hard 脚本与 soft 脚本）**——最强理由：退出码与调用语义更单一。否：会翻倍脚本数量与跨 skill 共享同步面，且工作流里要多跑一轮进程；在同一脚本内用 `hard_failures` / `soft_warnings` + `--strict` 双轨分层，既兼容旧调用方字段又让严格回归测试（如 `test-handoff-contracts.py`）传 `--strict` 即可锁死全量模板契约。

## Consequences

- **收益**：
  - 确定性底线（文件损坏、空细纲、正文退化、严重欠字、节标断号、状态 schema 破坏）继续 100% 硬守，不降低数据安全与结构底线。
  - 文风、跳章、手工修订上下文、长字段记账、边缘字数与非核心大纲结构不再制造死锁，改为有明确理由记录的 Review-and-Ack 或可复核软告警。
  - 五端 Hook、三类契约检查和两套状态提交器共享清晰一致的 hard/soft 语义，`scripts/bench/metrics.py` 同步区分 `blocking/review_required/advisory`。
- **代价与兼容边界**：
  - 当正文命中 `review_required` 且 Agent 判断需保留时，提交流程需要显式传 `--ack` / `--ack-all`（并在章末白话汇报中告知作者），比纯 pass 多一次复核决策。
  - 外部脚本若曾依赖 `check-ai-patterns.js --fail-on=blocking` 或不带 `--strict` 的 `check-*-contract.js` / `*_commit.js check` 对软规则返回非零退出码，需显式切到 `--fail-on=review_required` 或 `--strict`。
  - `.clawhub/publish.json` 中 6 个改动 skill 与 `story` 路由 skill 随本次改动同步递增补丁版本并重新锁定 `packageDigest`。

## Verification

- `python3 scripts/sync-shared-assets.py check && python3 scripts/shared-references.py check && python3 scripts/lint-repo.py && node scripts/check-doc-budget.mjs`
- `node --test scripts/test-story-hook-core.mjs scripts/test-claude-hooks.mjs scripts/test-codex-hooks.mjs scripts/test-antigravity-hooks.mjs scripts/test-zcode-hooks.mjs scripts/test-ai-patterns.mjs scripts/test-degeneration.mjs scripts/test-outline-copy.mjs tests/dashboard-server.test.mjs`
- `node --experimental-strip-types --test scripts/test-opencode-plugin.mjs`
- `node scripts/test-outline-contract.js && node scripts/test-phase2-contract.js && node scripts/test-delivery-contract.js && node scripts/test-normalize-punctuation.js`
- `python3 scripts/test-storyctl.py && python3 scripts/test-chapter-completion-lifecycle.py && python3 scripts/test-tracking-commit.py && python3 scripts/test-author-memory-commit.py && python3 scripts/test-style-precedence.py && python3 scripts/test-writer-pipeline.py && python3 scripts/test-handoff-contracts.py && python3 scripts/test-current-skill-contracts.py && python3 scripts/test-static-check.py && python3 scripts/test-doc-budget.py`
- `bash scripts/check-story-setup-deployment.sh` 及全部 7 个宿主适配检查脚本（`opencode`、`codex`、`zcode`、`claude`、`antigravity`、`openclaw`、`reasonix`）
