# scripts/ —— 仓库开发脚本索引

这些是开发本仓库（skill 套件本体）用的**守卫 / 测试 / 代码生成**脚本，**不是** skill 运行时脚本（运行时脚本在各 skill 自己的 `scripts/` 下，如 `story-deslop/scripts/check-ai-patterns.js`，跨 skill 字节同步）。

- 绝大多数由 CI 自动跑（`.github/workflows/cross-platform.yml`）。提交前本地一把梭的完整命令见 [CONTRIBUTING.md](../CONTRIBUTING.md)「CI 检查」。
- **改名 / 移动任一脚本**，要同步改 `.github/workflows/*.yml`、`CONTRIBUTING.md`、本文件，以及调用它的兄弟脚本（见下方「何时跑」里的调用关系）。

## 静态守卫（check-*）

| 脚本 | 检查什么 | 何时跑 |
|---|---|---|
| `static-check.sh` + `static-check.py` | 结构化验证 frontmatter、Markdown 路径/锚点、Agent 引用、references 可达性；除基础组件 `browser-cdp` 外禁止跨 Skill 文件引用 | CI |
| `skill-numbering.py check` | 工作流 Step/Phase/Stage 编号策略、引用绑定、SKILL.md 裸编号/子步骤小数守卫 | CI；改工作流结构后 |
| `check-current-skill-contracts.sh` + `.py` + `current-contract.json` | 从结构化 manifest 校验当前版本、Phase、schema、主产物与细纲契约；保留 legacy/path 守卫并拦截缺主产物后的静默替代 | CI |
| `check-shared-files.sh` | 调两个显式 manifest 验 runtime/reference 副本，拦截未声明 exact/near-copy，并检查 setup profile 契约与消费可达性 | CI |
| `check-reference-similarity.py` | 对跨 Skill Markdown 做行级 Jaccard/containment 近似扫描；高相似派生关系必须在 `shared-references.json` 的 `derived_groups` 说明来源与分化原因 | CI（由 check-shared-files 调用） |
| `check-agent-reference-consumers.py` | 从 story-setup Agent 模板做引用可达性遍历，同时验证唯一 profile 清单、long/short 所有权与 story-architect 不维护第二份 inventory | CI（由 check-shared-files 调用） |
| `check-short-analysis-scope.py` | 保证 story-short-analyze 只路由短篇源文观察标尺，拦截旧混合手册、长篇结构口令和推荐百分比回流 | CI（由 check-shared-files 调用） |
| `check-scan-runtime-policy.sh` | scraper 输出文件名依赖本地日期 helper；CDP 探测/Windows 监听解析的源码策略 | CI；这些依赖方向无法由隔离 helper 测试证明 |
| `check-story-setup-deployment.sh` | story-setup 部署/运行时回归（慢，>2min） | CI |
| `check-doc-budget.sh` + `doc-budget.json` | 热路径 SKILL/references/agent 模板的去空白字数预算与路径合计上限；超了要么删等量旧文本，要么显式调高 budget | CI；增删热路径正文后 |
| `check-hook-regex-sync.sh` | `detect-story-gaps.sh` 伏笔状态检测行为 | CI |
| `check-hook-locale-safety.sh` | 部署 hook 在 Windows 中文 GBK 区域的字节安全 | CI |
| `check-python-invocation.sh` | 技能文档禁止裸调 `python3`（须 python3→python→py 探测） | CI |
| `check-claude-adapter.sh` | Claude marketplace 与 15 个 skill 的一一映射；可选真实 CLI strict validate | CI（静态）；`CLAUDE_REAL_CHECK=1`（真实 CLI） |
| `check-opencode-adapter.sh` | OpenCode 适配层同步 + commands/agents/config 结构 + plugin 行为回归 | CI + sync CI（调 sync-opencode.py） |
| `check-openclaw-skills.sh` | OpenClaw AgentSkills/frontmatter 兼容性 | CI |
| `check-codex-adapter.sh` | Codex 适配层：repo skills symlink、agent TOML、hooks 与跨平台 launcher | CI（调 generate-codex-agents.py 验生成确定性） |
| `check-antigravity-adapter.sh` | Antigravity 2.0 适配层：项目 Skills、生成 Agents、Always-On Rule、named-group Hooks 与行为回归 | CI（调 generator、merge 与 hook tests） |
| `check-zcode-adapter.sh` | ZCode plugin/marketplace、Skills/Commands/Hooks 与部署锚点 | CI |
| `check-reasonix-adapter.sh` | Reasonix plugin manifest（schema、15 Skills、版本与 skills/story/VERSION 同步） | CI |

## 测试回归（test-*）

| 脚本 | 测什么 | 何时跑 |
|---|---|---|
| `test-ai-patterns.sh` | 确定性 AI 句式检测器 `check-ai-patterns.js` 回归 | CI |
| `test-phase2-contract.js` | 短篇 Phase 2 首屏门禁、结构化产物验收、具名失败与定向 repair 回归 | Linux / Windows / macOS CI |
| `test-delivery-contract.js` | 短篇最终字数、节数、标记与空行交付契约回归 | Linux / Windows / macOS CI |
| `check-reference-gates.js` | 长短篇 Reference Gate 的首屏位置、完整读取语义与关键路由静态守卫（gate 是提示词，无运行时入口可断言） | Linux / Windows / macOS CI |
| `test-outline-contract.js` | 长篇细纲结构验收：字段、小节、五段式、四列情节点表与字数口径的正负例回归 | Linux / Windows / macOS CI |
| `test-degeneration.sh` | 模型退化检测器 `check-degeneration.js` 回归 | CI |
| `test-prose-net-parity.sh` | 正文兜底「轻量确定性网」Claude/OpenCode/Codex/ZCode parity | CI（调 check-hook-regex-sync） |
| `test-prose-backstop-hook.sh` | `check-prose-after-write.sh` 回归 | CI |
| `test-story-continuity.sh` | `detect-story-gaps.sh` 跨批连续性兜底回归 | CI |
| `test-tracking-commit.py` | 单权威追踪行为：原子 state、字数事件链、hash 失效、激活边界、幂等与并发提交 | CI |
| `test-storyctl.py` | `visible_chars_v1`、双层区间、提交记录与 demo 同口径证据 | Linux / Windows / macOS CI |
| `test-chapter-completion-lifecycle.py` | 公开 CLI 的 checkpoint、正常提交、欠长接受、超长单次压缩区间、blocking quality 阻断与下一章继续 | Linux / Windows / macOS CI |
| `test-author-memory-commit.py` | 工作区作者记忆行为：单事件回执、≤2KB 相关查询、证据候选、冲突替代、撤回、失败零写入、旧修订、幂等重放与派生修复 | CI |
| `test-codex-hooks.sh` | Codex hook 合成 stdin/stdout 契约 | CI |
| `test-static-check.py` | 真 frontmatter block、精确路径/锚点、跨 Skill 引用、fence、死 reference、Agent 与章节链接 fixture | CI |
| `test-current-skill-contracts.py` | current-contract manifest 类型/固定值与主产物 fail-fast 语义 fixture | CI |
| `test-shared-assets.py` | 共享资产 manifest 的 drift、sync、路径越界、basename 单一 owner 与未登记重复检测 | CI |
| `test-shared-references.py` | reference manifest 的别名、目录组、drift/sync、未登记副本与 Agent 消费链回归 | CI |
| `test-normalize-punctuation.js` | 标点归一化的只读检查、frontmatter/fence、CRLF、引号模式与幂等性 | CI |
| `test-scan-runtime.js` | CDP argv 边界/报错/JSON 契约与 7 个 scraper 无副作用 import | CI |
| `test-scan-runtime-policy.py` | 变异验证 scan/browser 静态策略不会被无关或死代码关键词骗过 | CI；改 `check-scan-runtime-policy.sh` 后 |
| `test-opencode-plugin.mjs` | 直接执行 OpenCode TypeScript plugin，验大纲守卫、Bash 绕过、写后检查与 compact 恢复 | 被 `check-opencode-adapter.sh` 调用 |
| `test-codex-cli-e2e.sh` | 隔离 HOME 后用真实 Codex CLI 检查 repo 15 个 skill 的发现结果 | CLI compatibility CI；需已安装 `codex` |
| `test-zcode-hooks.sh` | ZCode 严格 JSON Hook、正文守卫与连续性回归 | CI |
| `test-antigravity-hooks.mjs` | Antigravity Hook I/O、正文守卫、PostToolUse artifact 桥接、PreInvocation 注入与 Stop 单次续跑 | CI（Linux/Windows/macOS） |
| `test-antigravity-hook-merge.py` | `.agents/hooks.json` 顶层 `oh-story` 管理组替换、用户组保留与幂等回归 | 被 `check-antigravity-adapter.sh` 调用 |
| `test-antigravity-skills-deploy.py` | Antigravity 13 个已知 Skill 原子物化、未知 Skill 保留、symlink fail-closed/显式迁移与防穿透写回归 | 被 `check-antigravity-adapter.sh` 调用 |
| `test-charcount-portable.sh` | 跨平台字符统计命令在三平台 + Windows 的正确性 | CI（调 check-python-invocation） |
| `test-hook-encoding-portable.sh` | 部署 hook 在 Windows 中文系统的编码健壮性 | CI |
| `test-opencode-cli-e2e.sh` | 真实 OpenCode CLI 加载 smoke（repo skills 发现 / 15 commands / 7 agents / plugin） | CLI compatibility CI；需已安装 `opencode` |
| `test-skill-numbering.sh` | Step 重排级联安全、锚点 fail-closed、代码块引用、验证零写入/提交回滚、dry-run/write/幂等性 | Linux / Windows Git Bash / macOS CI |

## 代码生成 / 同步

| 脚本 | 干什么 | 何时跑 |
|---|---|---|
| `sync-opencode.py` | 从 Claude agent 模板 + `CLAUDE.md.tmpl` 生成 `opencode/agents/` 与 `AGENTS.md.tmpl`；`--check` 只读验同步 | 改 agent 模板后手动跑；sync CI + 被 check-opencode-adapter 调 |
| `generate-codex-agents.py` | 从 Claude agent 模板生成 Codex `.toml` agents | 改 agent 模板后手动跑；被 check-codex-adapter 调验确定性 |
| `generate-codex-hooks.py` | 从 6 个 event 清单生成 `hooks.json`，POSIX/Windows 共用 launcher 负责解释器探测 | 改 Codex hook 注册后；被 check-codex-adapter 调验确定性 |
| `skills/story-setup/scripts/generate-antigravity-agents.mjs` | 从 Claude agent 真源生成 Antigravity `.agents/agents/agent-name/agent.md`（`agent-name` 为实际名称），转换官方工具名、模型档、reference root 与调用术语 | story-setup 部署时 + 被 check-antigravity-adapter 调验 |
| `skills/story-setup/scripts/merge-antigravity-hooks.py` | 原子替换 `.agents/hooks.json` 的 `oh-story` named group，保留所有用户 groups | story-setup 部署时 + merge 回归 |
| `skills/story-setup/scripts/deploy-antigravity-skills.py` | 把 15 个 oh-story Skills 物化为项目 `.agents/skills` 真实目录；只替换已知名、保留用户 Skill，symlink 需显式迁移且不穿透写目标 | story-setup 部署时 + materialization 回归 |
| `shared-assets.json` + `sync-shared-assets.py` | 为必须随 skill 独立部署的重复 runtime 脚本指定唯一源和目标 | 改共享 runtime 后跑 `sync`；CI 跑 `check` |
| `shared-references.json` + `shared-references.py` | 为自包含 Skill 的重复 reference 指定 canonical source、语义别名 target 与完整目录镜像；`derived_groups` 登记仍需独立演化的近似派生文件 | 改共享 reference 后跑 `sync`；CI 跑 `check` |

> 改了 `skills/story-setup/references/templates/agents/*.md` 或 `CLAUDE.md.tmpl`，必须重跑这两个生成脚本并提交结果，否则适配层 CI 红。详见 [CONTRIBUTING.md](../CONTRIBUTING.md)「OpenCode 模板同步」「Codex 适配维护」。

## 工作流编号维护

`skill-numbering.py` 默认扫描 canonical `skills/**/*.md`，用于阻止迭代插入把工作流编号累积成 `Step 1.3`、`Phase 2.5` 一类小数标签。

```bash
python3 scripts/skill-numbering.py audit          # 只读盘点；发现问题仍退出 0
python3 scripts/skill-numbering.py check          # CI 守卫；发现问题退出非 0
python3 scripts/skill-numbering.py fix --dry-run  # 先看完整 diff，不落盘
python3 scripts/skill-numbering.py fix --write    # 校验通过后一次性落盘
bash scripts/test-skill-numbering.sh              # 隔离 fixture 回归
```

维护策略：

- 只有形如 `### Step N` 的**显式 Step 标题**会自动重排；分组键是「文件 + 标题层级 + 最近父标题」，每组从 1 连续编号。
- 标题与可唯一绑定的 `Step N` 引用基于旧文本同时换号，包含 fenced code block 内的命令/示例引用，避免 `1.5 → 2` 后又被 `2 → 3` 二次级联。
- fractional Step 引用找不到本文件标题，或一个旧标签可能映射到多个新标签时，`fix` 会在任何写入前失败。多文件写入先全量校验/暂存并带回滚，不接受半套结果。
- 标题改号会改变 GitHub Markdown anchor；只要仓库内存在指向旧 anchor 的同文件或跨文件链接，`fix` 就在写入前 fail-closed，并报告每个 fragment，要求先显式更新链接后再重试。局部路径模式同样扫描仓库内入站链接。
- `Step N.M` / `Phase N.M` / `Stage N.M`、直接 `skills/*/SKILL.md` 中的裸小数标题及 bullet 小数子步骤由 `check` 报错，但不做猜测式自动修改。
- `references/` 手册本身的 `3.1` 章节/列表编号不属于工作流标签，不检查、不改写。如果管道 ID 需要插入中间阶段，使用语义名称或 `Stage 2A`，不用小数。
- 可在命令末尾传文件或目录做局部审计，例如 `... audit skills/story-cover/SKILL.md`；合入前仍须跑默认全量 `check`。
