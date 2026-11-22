# scripts/ —— 仓库开发脚本索引

这些是开发本仓库（skill 套件本体）用的**守卫 / 测试 / 代码生成**脚本，**不是** skill 运行时脚本（运行时脚本在各 skill 自己的 `scripts/` 下，已统一收口到零依赖 Node.js 18+ `.js`，仅长篇拆文可选关系图 `render_relation_chart.py` 保留 Python + matplotlib；跨 skill 副本按 `shared-assets.json` 字节同步）。

- 绝大多数由 CI 自动跑（`.github/workflows/cross-platform.yml`）。提交前完整的本地验证命令见 [CONTRIBUTING.md](../CONTRIBUTING.md)「CI 检查」。
- **改名 / 移动任一脚本**，要同步改 `.github/workflows/*.yml`、`CONTRIBUTING.md`、本文件，以及调用它的兄弟脚本（见下方「何时跑」里的调用关系）。
- `scripts/bench/` 是 v0.8 起的真实会话基准：确定性部署某个版本的包、用真实 CLI 跑冻结的书、统计每章耗时/token/正文指标。它要真实模型和凭据，不在 CI 里跑；用法见 [bench/README.md](bench/README.md)。

## 静态守卫（lint / check-*）

| 脚本 | 检查什么 | 何时跑 |
|---|---|---|
| `lint-repo.py` + `current-contract.json` | 仓库统一静态守卫（支持 `--only static\|contracts\|shared\|numbering\|agent-refs`）：① `static` 结构化验证 frontmatter、Markdown 路径/锚点、Agent 引用、references 可达性与除 `browser-cdp` 外的跨 Skill 隔离；② `contracts` 校验 `current-contract.json` schema、`setup_skill_version` / `agents_version` 对齐、`progress_schema_version` 锚点、`demo/` 主产物非空及 `quality-rubric.md` 维度一致；③ `shared` 调用 `sync-shared-assets.py check`、`shared-references.py check` 并检查部署 Agent 资料前缀、profile 归属与可达性；④ `numbering` 拦截 `skills/**/*.md` 代码围栏外的 `Step/Phase/Stage N.M` 小数标签 | CI（Linux）；提交前必跑 |
| `check-doc-budget.mjs` + `doc-budget.json` | 热路径 SKILL/references/agent 模板的去空白字数预算与路径合计上限（纯 Node ESM）；每次调用硬上限 35K（`path_ceiling`，豁免列 `exempt` 并写原因）；带 `agent` 字段的路径按角色计每次调用的实际加载量并自动计入模板预加载的 skill；`文件#小节` 只计一节，`generated` 运行拼包脚本计量，`branches` 默认互斥、会同时发生的登记进 `stacking` 取最坏组合 | CI（Linux）；增删热路径正文后 |
| `check-plugin-packaging.py` | Claude/ZCode/Reasonix catalog 与原生 manifest 的单 bundle 身份、版本锚点、默认组件发现和 14 个根 Skills | CI（三平台）；改 plugin packaging 后 |
| `check-python-invocation.sh` | 技能文档禁止裸调 `python3`（须 python3→python→py 探测） | CI（Linux） |
| `check-scan-runtime-policy.sh` | scraper 输出文件名依赖本地日期 helper；CDP 探测/Windows 监听解析的源码策略 | CI（Linux） |
| `check-story-setup-deployment.sh` | story-setup 部署/运行时回归（慢，>2min） | CI（Linux） |
| `check-claude-adapter.sh` | Claude marketplace、根 plugin manifest 与 14 个 skill 自动发现；可选真实 CLI 生命周期 | CI（静态）；`CLAUDE_REAL_CHECK=1`（真实 CLI） |
| `check-codex-adapter.sh` | Codex 适配层：repo skills symlink、agent TOML、Node hooks 与跨平台 launcher | CI（调 generate-codex-agents.py 验生成确定性） |
| `check-antigravity-adapter.sh` | Antigravity 2.0 适配层：项目 Skills、生成 Agents、Always-On Rule、named-group Hooks 与行为回归 | CI（调 generator、merge 与 hook tests） |
| `check-opencode-adapter.sh` | OpenCode 2.x 适配层同步 + commands/agents 结构 + 生成权限的 2.x 裁决矩阵 + plugin 行为回归 | CI（调 sync-opencode.py） |
| `check-openclaw-skills.sh` | OpenClaw AgentSkills/frontmatter 兼容性 | CI（静态）；`OPENCLAW_REAL_CHECK=1`（真实 CLI） |
| `check-zcode-adapter.sh` | ZCode plugin/marketplace、Skills/Commands/Agents/Hooks、角色生成一致性与部署锚点 | CI（Linux） |
| `check-reasonix-adapter.sh` | Reasonix plugin manifest（schema、14 Skills、版本与 skills/story/VERSION 同步） | CI（静态）；`REASONIX_REAL_CHECK=1`（真实 CLI） |

## 测试回归（test-*）

| 脚本 | 测什么 | 何时跑 |
|---|---|---|
| `test-static-check.py` | `lint-repo.py --only static` 与 `--only numbering` 的结构化 fixture 回归（frontmatter、路径/锚点、跨 Skill 引用、fence、死 reference、Agent、小数标签） | CI（Linux） |
| `test-current-skill-contracts.py` | `lint-repo.py` 硬运行时契约回归（manifest schema、sentinel、UPGRADING、spawn `agents_version`、`progress_schema_version`、rubric 维度一致） | CI（Linux） |
| `test-handoff-contracts.py` | 跨 skill 交接契约回归（拆文、扫榜、导入产物到写作端，写作端平台到审稿，派助手与派写手去味的字段和标签；含反向自检） | CI（Linux） |
| `test-doc-budget.py` | `check-doc-budget.mjs` 路径求和、超限、缺失文件、按节计量、拼包计量、叠加最坏组合与硬上限配置失败回归 | CI（Linux） |
| `test-shared-assets.py` | 共享资产 manifest 的 drift、sync、路径越界、basename 单一 owner、未登记重复检测与 `lint-repo.py --only shared` 集成 | CI（Linux） |
| `test-shared-references.py` | reference manifest 的别名、目录组、drift/sync、未登记副本与 `lint-repo.py --only agent-refs` 消费链回归 | CI（Linux） |
| `test-plugin-packaging.py` | 执行公开 packaging CLI，在临时仓库中变异 catalog/manifest/版本/组件过滤并断言结构化失败 | CI（三平台） |
| `test-agent-permissions.py` | 工具白名单、禁止优先、空列表/继承和不支持声明回归；`--opencode` 用真实 OpenCode 2.x + mock 模型验证每个 agent 实际拿到的工具与允许/拒绝执行 | CI（Linux）；CLI compatibility 跑真实 OpenCode |
| `test-ai-patterns.mjs` | 确定性 AI 句式检测器 `check-ai-patterns.js` 原生 `node:test` 回归（含 >64KB stdout 排空与篇幅缩放） | CI（三平台，`node --test`） |
| `test-degeneration.mjs` | 模型退化检测器 `check-degeneration.js` 原生 `node:test` 回归（含引号范围、meta-leak 与 skill 调用连线检查） | CI（三平台，`node --test`） |
| `test-outline-copy.mjs` | 细纲照搬检测器 `check-outline-copy.js` 原生 `node:test` 回归（31 例，含 `--require` 异常注入与完成记录豁免） | CI（三平台，`node --test`） |
| `test-phase2-contract.js` | 短篇 Phase 2 verifier 行为回归：设计字段、12 列大纲、字数区间、双轨 `hard_failures`/`soft_warnings` + `--strict`、具名失败与 repair_scope | CI（三平台） |
| `test-delivery-contract.js` | 短篇最终字数、节数、标记、空行及双轨 `hard_failures`/`soft_warnings` + `--strict` 交付契约回归 | CI（三平台） |
| `test-outline-contract.js` | 长篇细纲结构验收：新旧字段名与小节名、「这章怎么走」五行、三到五列情节点表、字数口径、双轨 `hard_failures`/`soft_warnings` + `--strict` 与正负例回归 | CI（三平台） |
| `test-normalize-punctuation.js` | 标点归一化的只读检查、frontmatter/fence、CRLF、引号模式与幂等性 | CI（三平台） |
| `test-scan-runtime.js` | CDP argv 边界/报错/JSON 契约与 7 个 scraper 无副作用 import；七猫、起点书库翻页与反爬字体解码 | CI（三平台） |
| `test-scan-runtime-policy.py` | 变异验证 scan/browser 静态策略不会被无关或死代码关键词骗过 | CI（Linux）；改 `check-scan-runtime-policy.sh` 后 |
| `test-scan-aggregate.py` | 扫榜聚合 `aggregate-rank.js` 的解析、去重、分布、样本不足标注与抽样取回原文回归 | CI（三平台） |
| `test-publish-format.py` | `skills/story-publish/scripts/check-publish-format.js` 回归：元信息与格式版本、字段取值、平台规则、标签/分类上限、书名长度提醒与中文路径只读行为 | CI（三平台） |
| `test-writer-pipeline.py` | 长篇取段器与 prompt 组装器公开 CLI：存量卷纲、新旧段头写法、退役历史、原生路径、必需资料与召回降档 | CI（三平台） |
| `test-style-precedence.py` | 书级表达豁免在深扫、标点整理、写后和下一章门禁中一致生效且不跨书 | CI（三平台） |
| `test-tracking-commit.py` | 单权威追踪行为：原子 state、字数事件链、hash 失效、激活边界、幂等与并发提交 | CI（三平台） |
| `test-storyctl.py` | `visible_chars_v1`、双层区间与作者范围、「字数目标」两端解析一致、章节检查状态与去味豁免、提交记录与 demo 同口径证据 | CI（三平台） |
| `test-chapter-completion-lifecycle.py` | 公开 CLI 的 checkpoint、正常提交、欠长接受、超长压缩建议与放行、硬伤阻断、`review_required` + `--ack` 放行与下一章继续 | CI（三平台） |
| `test-author-memory-commit.py` | 工作区作者记忆行为：单事件回执、交写手的行 ≤2KB、证据候选、冲突替代、撤回、失败零写入、旧修订、幂等重放与派生修复 | CI（三平台） |
| `test-long-analyze-runtime.py` | 长篇拆文单状态运行时：机械章节索引与逐章 hash、旧成果识别、只读计划、范围批次、旧章号与楔子对齐、原子提交、缓存恢复与关系图中文字体回退 | CI（三平台） |
| `test-story-hook-core.mjs` | 五端（Claude / Codex / OpenCode / Antigravity / ZCode）共享 Node.js 18+ 钩子核心 `story_hook_core.js` 原生 `node:test` 回归：正文兜底轻量网、写前大纲守卫与非阻断 `prosePreWriteWarnings` 软提醒、五端 `agents_version` 过期提醒、`拆文库/` 与 `对标/` 书目发现跳过、跨批连续性缺口、伏笔状态与跳过标记同步、Windows 驱动器路径与 OpenCode `pre-commit.sh` | CI（三平台，`node --test`） |
| `test-claude-hooks.mjs` | Claude Code 统一 Node hook CLI（`story_hook_cli.js` + `run-story-hook.sh`）原生 `node:test` 回归：全部 8 个事件、`analysis-input-guard`、缺 `node` fail-open 与真实 `zh_CN.GBK` 编码安全 | CI（三平台，`node --test`） |
| `test-codex-hooks.mjs` | Codex Node hook（`story_codex_hook.js` + `run-story-hook.{sh,cmd}`）原生 `node:test` 回归：合成 stdin/stdout JSON 契约、大纲守卫、写后兜底与 `windowsHide: true` 断言 | CI（三平台，`node --test`） |
| `test-codex-hook-merge.py` | Codex `hooks.json` 合并器的管理组替换、用户配置保留与幂等回归 | 被 `check-codex-adapter.sh` 调用 |
| `test-zcode-hooks.mjs` | ZCode 严格 JSON Hook、正文守卫、版本提醒与连续性原生 `node:test` 回归 | CI（三平台，`node --test`） |
| `test-zcode-agents.py` | ZCode 插件角色的工具白名单、禁止优先、模型继承、资料路径、无效输入零写入与生成漂移回归 | 被 `check-zcode-adapter.sh` 调用 |
| `test-antigravity-hooks.mjs` | Antigravity 注册命令的 shell/字面 argv 兼容性、Hook I/O、正文守卫、artifact 桥接与仅硬伤 findings 触发 Stop 单次续跑（纯风格不续跑） | CI（三平台，`node --test`） |
| `test-antigravity-hook-merge.py` | `.agents/hooks.json` 顶层 `oh-story` 管理组替换、用户组保留与幂等回归 | 被 `check-antigravity-adapter.sh` 调用 |
| `test-antigravity-skills-deploy.py` | Antigravity 14 个已知 Skill 原子物化、未知 Skill 保留、symlink fail-closed/显式迁移与防穿透写回归 | 被 `check-antigravity-adapter.sh` 调用 |
| `test-opencode-plugin.mjs` | 以 2.x `setup(ctx)` 直接执行 OpenCode TypeScript plugin，验大纲守卫、Shell 绕过、写后检查、compaction 注入与 `ctx.location` 定位 | CI（三平台，`node --test`）；被 `check-opencode-adapter.sh` 调用 |
| `test-claude-plugin-lifecycle.py` | 隔离 HOME 后用真实 Claude CLI 演练 13 个旧身份迁移为单 bundle、更新/卸载及无关插件保留 | `CLAUDE_REAL_CHECK=1`，由 `check-claude-adapter.sh` 调用 |
| `test-codex-cli-e2e.sh` | 隔离 HOME 后用真实 Codex CLI 检查 repo 14 个 skill 的发现结果 | CLI compatibility CI；需已安装 `codex` |
| `test-opencode-cli-e2e.sh` | 真实 OpenCode 2.x CLI e2e：repo 14 skills 发现 / 14 commands / 7 agents / 插件 active，并用 mock 模型验证写正文拦截、写后兜底与 compaction 注入 | CLI compatibility CI；需已安装 OpenCode 2.x |
| `opencode-mock-llm.mjs` | OpenAI 兼容 mock 模型：按剧本文件发出工具调用并记录请求，供 OpenCode CLI 真实测试驱动运行时 | 被 `test-opencode-cli-e2e.sh`、`test-agent-permissions.py --opencode` 调用 |
| `test-charcount-portable.sh` | 跨平台字符统计命令在三平台 + Windows Store stub 下的正确性 | CI（三平台） |

## 代码生成 / 同步

| 脚本 | 干什么 | 何时跑 |
|---|---|---|
| `sync-opencode.py` | 从 Claude agent 模板 + `CLAUDE.md.tmpl` 生成 `opencode/agents/` 与 `AGENTS.md.tmpl`；`--check` 只读验同步 | 改 agent 模板后手动跑；被 `check-opencode-adapter.sh` 调 |
| `generate-codex-agents.py` | 从 Claude agent 模板生成 Codex `.toml` agents | 改 agent 模板后手动跑；被 `check-codex-adapter.sh` 调验确定性 |
| `generate-zcode-agents.py` | 从 Claude agent 模板生成 ZCode 插件 Markdown agents；继承模型、保留工具白名单，不移植 inline hooks；`--check` 只读验同步 | 改 agent 模板后；被 `check-zcode-adapter.sh` 调用 |
| `skills/story-setup/scripts/generate-antigravity-agents.mjs` | 从 Claude agent 真源生成 Antigravity `.agents/agents/agent-name/agent.md`，转换官方工具名、模型档、reference root 与调用术语 | story-setup 部署时 + 被 `check-antigravity-adapter.sh` 调验 |
| `skills/story-setup/scripts/merge-hooks.js` | 统一合并 Claude / Codex / Antigravity 宿主 hook 配置（`--host claude\|codex\|antigravity`），原子替换管理组并保留所有用户配置 | story-setup 部署时 + merge 回归 |
| `skills/story-setup/scripts/deploy-antigravity-skills.js` | 把 14 个 oh-story Skills 物化为项目 `.agents/skills` 真实目录；只替换已知名、保留用户 Skill，symlink 需显式迁移且不穿透写目标 | story-setup 部署时 + materialization 回归 |
| `skills/story-setup/scripts/copy-path-safety.js` / `merge-project-instructions.js` | Node.js 18+ 部署路径安全校验与项目指令模板合并 | story-setup 部署时 + 被 `check-story-setup-deployment.sh` 调验 |
| `shared-assets.json` + `sync-shared-assets.py` | 为必须随 skill 独立部署的重复 runtime 脚本指定唯一源和目标 | 改共享 runtime 后跑 `sync`；CI 由 `lint-repo.py --only shared` 跑 `check` |
| `shared-references.json` + `shared-references.py` | 为自包含 Skill 的重复 reference 指定 canonical source、语义别名 target 与完整目录镜像 | 改共享 reference 后跑 `sync`；CI 由 `lint-repo.py --only shared` 跑 `check` |

> 改了 `skills/story-setup/references/templates/agents/*.md` 或 `CLAUDE.md.tmpl`，必须重跑相关宿主的生成脚本并提交结果，否则适配层 CI 红。详见 [CONTRIBUTING.md](../CONTRIBUTING.md)「OpenCode 模板同步」「Codex 适配维护」「ZCode 适配维护」。
