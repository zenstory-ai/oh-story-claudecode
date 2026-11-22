# Agent Note: 收拢 CI 元检查、迁移原生 Node 测试并精简跨平台流水线

Status: implemented

## Problem

仓库的 `scripts/` 与 `.github/workflows/` 长期累积了大量低收益元检查、薄 shell 包装层和慢速 Bash 套 Node 测试：

1. **高维护成本的文风/元规则正则警察**：13 个静态检查脚本总计约 5,700 行，其中大量逻辑用于检查散文措辞（如 `check-current-skill-contracts.py` 里的 23 条 `LEGACY_RULES` 与 NLP 启发式、`check-author-reports.py` 直接违背 `AGENTS.md`「不设禁词守卫，靠评审守住」、`check-reference-gates.js` 自身文档即承认不能证明模型遵守、`check-reference-routing.py`、`check-reference-similarity.py`、`check-short-analysis-scope.py`、`check-agent-notes.py` 以及 1,000 行的 `skill-numbering.py` 自动重排引擎）。这些脚本每次改 Markdown 措辞都频繁误报，却很少拦住真正的运行时损坏。
2. **重复工作流与无意义的薄壳**：`.github/workflows/sync-opencode.yml` 与 `cross-platform.yml` 完全重复；`static-check.sh`、`check-current-skill-contracts.sh`、`test-long-analyze-runtime.py`（14 行 `runpy` 壳）和 `check-doc-budget.sh`（Bash 包 inline Node 再探 Python 的三明治）徒增跨平台摩擦。
3. **Bash 循环启动数百次 Node**：`test-ai-patterns.sh`（1,683 行，约 157 次 `node` 子进程）、`test-degeneration.sh`（381 行）、`test-outline-copy.sh`（384 行）在 Windows Git Bash 下极慢且难以定位单条用例。
4. **跨平台 CI 大量复制粘贴**：`.github/workflows/cross-platform.yml`（332 行、117 个 step）把同一批测试手写复制了三遍（`static-check`、`windows`、`macos`），且 Node 版本在三端不统一（22 vs 20）。

本决定同步取代 [2026-09-18-agent-notes-format-guard.md](../../testing/2026-09-18-agent-notes-format-guard.md) 中通过 CI 守卫 `.agents/notes/` 格式的决定：笔记规范保留在 `AGENTS.md` 并由评审把关，不再维护独立 CI 守卫脚本。

## Decision

1. **删除冗余工作流与薄包装层**：
   - 删除 `.github/workflows/sync-opencode.yml`（已由 `cross-platform.yml` 的 `check-opencode-adapter.sh` 覆盖）。
   - 删除 `scripts/static-check.sh` 与 `scripts/check-current-skill-contracts.sh`；移除 `scripts/test-static-check.py` 的 shell launcher 测试。
   - 将 `scripts/test-long-analyze-runtime-refactor.py` 直接重命名为 `scripts/test-long-analyze-runtime.py`，移除 `runpy` 转发壳。

2. **合并真故障守卫到 `scripts/lint-repo.py`，退休文风警察**：
   - 新增统一入口 `scripts/lint-repo.py`（默认全跑，支持 `--only static|contracts|shared|numbering|agent-refs`），只保留能防止真实运行时损坏的四类检查：
     - `static`：完整吸收原 `static-check.py`（frontmatter、精确链接/锚点、`subagent_type`、未链接章节猜测、除 `browser-cdp` 外的跨 skill 隔离、死 reference）。
     - `contracts`：从 `check-current-skill-contracts.py` 精简保留硬运行时锚点——`current-contract.json` schema（`template_fences` 作为可选字段以向前兼容）、`setup_skill_version` / `agents_version` 对齐（frontmatter、`.story-deployed` sentinel、`UPGRADING.md`、7 个 spawn-capable skill）、`progress_schema_version` 锚点、`demo/拆文库/盘龙` 主产物非空、`quality-rubric.md` 与内置 fallback 维度一致。同步精简 `scripts/test-current-skill-contracts.py`。
     - `shared`：吸收 `check-shared-files.sh` 与 `check-agent-reference-consumers.py`，调用 `sync-shared-assets.py check`、`shared-references.py check` 并校验 `agent-references` 前缀、profile 与可达性；保留全部 `scripts/shared-assets.json` 自包含副本不变。
     - `numbering`：用约 25 行正则守卫替代 1,000 行 `skill-numbering.py` + `test-skill-numbering.sh`，继续拦截 `skills/**/*.md` 代码围栏外的 `Step/Phase/Stage N.M` 小数标签。
   - 保留 `scripts/check-plugin-packaging.py`、`scripts/test-plugin-packaging.py` 与 `scripts/test-handoff-contracts.py`。
   - 退休 `check-agent-notes.py`、`test-agent-notes.py`、`check-author-reports.py`、`check-reference-gates.js`、`check-reference-routing.py`、`check-reference-similarity.py`、`check-short-analysis-scope.py`、`skill-numbering.py`、`test-skill-numbering.sh` 以及已被吸收的原脚本。

3. **将文档预算守卫与三个检测器回归迁为原生 Node（`.mjs`）**：
   - 将 `scripts/check-doc-budget.sh` 重写为纯 Node ESM `scripts/check-doc-budget.mjs`，并更新 `scripts/test-doc-budget.py`。
   - 将 `test-ai-patterns.sh`、`test-degeneration.sh`、`test-outline-copy.sh` 1:1 迁移为使用 `node:test` + `node:assert/strict` 的 `scripts/test-ai-patterns.mjs`、`scripts/test-degeneration.mjs`、`scripts/test-outline-copy.mjs`，消除冗余子进程与 Bash 路径兼容胶水，随后删除 3 个 `.sh` 原文件。

4. **重构 `.github/workflows/cross-platform.yml` 为两个清晰 Job**：
   - `repo-lint-and-adapters`（`ubuntu-latest`）：仓库守卫、元回归测试、策略守卫、`check-story-setup-deployment.sh`、7 宿主适配检查与采集脚本语法校验。
   - `cross-platform-runtime`（`matrix.os: [ubuntu-latest, windows-latest, macos-latest]`，三端统一 Node 22）：插件打包、原生 Node 测试、全部 Python/JS 运行时测试、Hook 与跨平台便携测试、以及非 Ubuntu 端的 Chrome CDP dry-run。

5. **同步更新仓库文档**：
   - 在 `AGENTS.md` 中将仓库定位更新为诚实的混合架构（「Markdown 写作方法与工作流契约 + 确定性运行时工具」），写明 Markdown 与代码的职责边界及新增守卫的举证门槛；更新 `CONTRIBUTING.md` 与 `scripts/README.md` 的命令与索引。

## Alternatives considered

- **保留所有现有守卫，仅把它们拼进一个大脚本**——最强理由：零覆盖率删减，不需要判断哪些规则是噪音。否：合并本身不会消除文风正则的误报和维护负担；`check-author-reports.py`、`check-reference-gates.js` 和 23 条 `LEGACY_RULES` 的问题在于它们在用脆弱正则管自然语言，而非文件数量多。
- **直接删掉 `shared-assets.json` 的跨 skill 副本，改为单份共享**——最强理由：可以一次性去掉同步清单和重复代码。否：各 skill 需保持独立安装自包含，且本次范围明确保留 `shared-assets.json` 副本体系不变。
- **把 `check-ai-patterns.js` 改成导出函数供 `.mjs` 进程内调用**——最强理由：测试可以再快几百毫秒。否：需要改动 `skills/` 下的运行时脚本并同步多份副本，超出本次 CI/测试精简边界；通过 CLI 执行并用进程内 JSON 断言已消除百余次冗余 `node -` 进程和全部 Bash 开销，同时保持对退出码与 >64KB stdout 管道排空的真实端到端覆盖。

## Consequences

- **收益**：净删约 4,000+ 行元检查/胶水脚本与约 200 行重复 CI YAML；本地和 CI 统一入口为 `python3 scripts/lint-repo.py` 与 `node scripts/check-doc-budget.mjs`；检测器回归可在三平台直接以 `node --test` 跑完并输出逐条用例结果；后续修改工作流文档不再被脆弱的散文正则阻断。
- **代价与已知边界**：
  - 决策笔记格式、作者报告禁词、近似参考文档 Jaccard 扫描、短篇分析措辞限制与长篇首屏路由表互查改回评审把关，不再由 CI 自动拦截。
  - 若以后需要大范围重排某 skill 的 Step 编号，不再有自动级联改写工具，需要手工更新或从 git 历史取回旧脚本。
  - 删除 `.github/workflows/sync-opencode.yml` 前需确认 GitHub 仓库分支保护未将旧 job 名 `check-sync` 设为必需状态检查。
