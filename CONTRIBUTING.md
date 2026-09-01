# 贡献指南

感谢你对网文写作 skill 包的关注，欢迎贡献。

## 仓库结构

```
skills/
├── story/                   # 工具箱路由
├── story-setup/             # 环境部署
├── story-import/            # 逆向导入
├── story-long-write/        # 长篇写作
├── story-long-analyze/      # 长篇拆文
├── story-long-scan/         # 长篇扫榜
├── story-short-write/       # 短篇写作
├── story-short-analyze/     # 短篇拆文
├── story-short-scan/        # 短篇扫榜
├── story-deslop/            # 去AI味
├── story-review/            # 多视角审查
├── story-cover/             # 封面生成
└── browser-cdp/             # 浏览器操控
scripts/                       # 开发守卫 / 测试 / 代码生成（完整索引见 scripts/README.md）
```

每个 skill 由一个 `SKILL.md`（入口）和 `references/` 目录（知识库）组成。

## 反馈与需求

- 可稳定复现的命令、文件、状态或 Runtime 异常：提交 **Bug 报告**。
- 文风、人物、节奏、逻辑或 AI 味不符合预期：提交 **输出质量 Case**，提供最小必要上下文、连续输出片段、具体问题位置和期望方向。
- 新能力或 Runtime / IDE 适配：提交 **功能请求**，说明真实使用问题、可验收结果；适配请求同时提供官方扩展或 Skills 文档。
- 使用方法、流程选择和一般交流：前往 [GitHub Discussions](https://github.com/zenstory-ai/oh-story-claudecode/discussions)。

Issue 是可采取行动的工作输入。缺少复现步骤、实际输出、具体问题位置或验收结果时，维护者会要求补充；长期无法补全的信息不会进入研发排期。不要提交 API Key、Token、个人信息、无权公开或不愿公开的书稿。

## Skill 格式

`SKILL.md` 开头必须有 frontmatter：

```yaml
---
name: skill-name
description: "一句话描述。触发方式：/skill-name、触发词1、触发词2"
metadata: {"openclaw":{"source":"https://github.com/zenstory-ai/oh-story-claudecode"}}
---
```

为兼容 OpenClaw，frontmatter 必须保持单行键值：`description` 不使用 `|`/`>` 块，`metadata` 必须是单行 JSON 对象。更长的触发说明放到正文中。

`references/` 中的文件由 skill 按需加载，不会全部塞进上下文。

## 如何贡献

### 改进现有 skill

1. Fork 仓库
2. 从 `main` 创建分支：`git checkout -b feat/your-feature main`
3. 修改对应的 `SKILL.md` 或 `references/` 文件
4. 提交 PR，说明改了什么、为什么改

### 新增 skill

1. 在 `skills/` 下创建目录，包含 `SKILL.md` 和 `references/`
2. 确保在仓库根目录运行 `npx skills validate` 无报错
3. 提交 PR

## CI 检查

PR 自动运行 `.github/workflows/cross-platform.yml`。static-check job 跑以下检查（全部强制）：

- `scripts/static-check.sh` — 结构化解析 frontmatter、精确 Markdown 路径/锚点、Agent 引用与 references 可达性；除基础组件 `browser-cdp` 外禁止跨 Skill 文件引用
- `python3 scripts/skill-numbering.py check` — 工作流编号连续性、引用可绑定性及小数标签守卫
- `scripts/check-current-skill-contracts.sh` — 按 `scripts/current-contract.json` 校验当前版本 / Phase / schema / 主产物 / 细纲契约，并拦截历史路径与静默兼容分支
- `python3 scripts/test-current-skill-contracts.py` — current-contract manifest 与主产物 fail-fast 语义回归
- `scripts/check-doc-budget.sh` — 热路径 SKILL/references/agent 模板的字数预算（按 `scripts/doc-budget.json`），防每次会话都要付的规则文本无声膨胀
- `scripts/check-hook-regex-sync.sh` — hook 伏笔状态检测行为
- `scripts/check-shared-files.sh` — 共享 runtime 资产清单 + 跨 skill reference 副本一致性
- `scripts/check-scan-runtime-policy.sh` — scraper 本地日期依赖与 CDP 源码策略守卫
- `python3 scripts/test-scan-runtime-policy.py` — 验证无关/死代码关键词不能骗过 scan/browser 策略守卫
- `scripts/check-story-setup-deployment.sh` — story-setup 部署完整性
- `scripts/check-claude-adapter.sh` — Claude marketplace 与 skill 映射检查
- `scripts/check-opencode-adapter.sh` — OpenCode adapter 同步、commands/agents/config 结构与 plugin 真实行为检查
- `scripts/check-openclaw-skills.sh` — OpenClaw 单行 frontmatter、`metadata.openclaw` 与可选真实 CLI 发现检查
- `scripts/check-codex-adapter.sh` — Codex repo skills symlink、custom-agent TOML、hook 生成确定性与 launcher 契约
- `scripts/test-codex-hooks.sh` — Codex hooks 合成事件测试
- `scripts/check-antigravity-adapter.sh` — Antigravity 项目 Skills 物化、Markdown agents、Always-On Rule、named-group Hooks 与合并/行为回归
- `node scripts/test-antigravity-hooks.mjs` — Antigravity 官方 Hook I/O、artifact 桥接和 Stop 单次续跑测试
- `scripts/check-zcode-adapter.sh` — ZCode plugin/marketplace、15 Skills/Commands、受支持 Hook 事件与部署锚点检查
- `scripts/test-zcode-hooks.sh` — ZCode 严格 JSON Hook 契约、正文守卫、连续性与跨平台 Node runner 测试
- `python3 scripts/test-storyctl.py` — `visible_chars_v1` 计数、双层区间、结构化 CLI 与 demo 同口径证据的运行时行为回归
- 采集脚本 `node --check` 语法校验

以上为代表性列举；**强制清单按 `.github/workflows/cross-platform.yml` 为准**，每个脚本的用途与触发时机见 [scripts/README.md](scripts/README.md)。另有 `.github/workflows/cli-compat.yml` 在相关 PR、每周定时和手动触发时安装官方当前版本，真实运行 Claude Code、Codex、OpenCode、OpenClaw 的无鉴权 smoke。

另有 windows / macos job 验证 cdp-utils 加载与 setup 脚本 dry-run。

提交前建议按 Linux CI 的强制清单本地跑一遍：

```bash
bash scripts/static-check.sh
python3 scripts/test-static-check.py
python3 scripts/skill-numbering.py check
bash scripts/test-skill-numbering.sh
bash scripts/check-current-skill-contracts.sh
python3 scripts/test-current-skill-contracts.py
bash scripts/check-doc-budget.sh
bash scripts/check-hook-regex-sync.sh
bash scripts/check-shared-files.sh
python3 scripts/test-shared-assets.py
python3 scripts/test-shared-references.py
node scripts/test-normalize-punctuation.js
node scripts/test-scan-runtime.js
bash scripts/check-scan-runtime-policy.sh
python3 scripts/test-scan-runtime-policy.py
bash scripts/test-ai-patterns.sh
node scripts/test-phase2-contract.js
node scripts/test-delivery-contract.js
node scripts/check-reference-gates.js
node scripts/test-outline-contract.js
bash scripts/test-degeneration.sh
bash scripts/test-prose-backstop-hook.sh
bash scripts/test-prose-net-parity.sh
bash scripts/test-story-continuity.sh
python3 scripts/test-storyctl.py
python3 scripts/test-author-memory-commit.py
bash scripts/check-story-setup-deployment.sh
bash scripts/check-claude-adapter.sh
bash scripts/check-codex-adapter.sh
bash scripts/check-opencode-adapter.sh
bash scripts/check-openclaw-skills.sh
bash scripts/test-codex-hooks.sh
bash scripts/check-python-invocation.sh
bash scripts/check-hook-locale-safety.sh
bash scripts/test-hook-encoding-portable.sh
bash scripts/test-charcount-portable.sh
bash scripts/test-charcount-portable.sh --stub

# 可选真实 CLI smoke（需分别安装对应 CLI）
CLAUDE_REAL_CHECK=1 bash scripts/check-claude-adapter.sh
bash scripts/test-codex-cli-e2e.sh
bash scripts/test-opencode-cli-e2e.sh
OPENCLAW_REAL_CHECK=1 bash scripts/check-openclaw-skills.sh
```

## 工作流编号规范

新增或调整流程步骤时，显式标题使用 `Step 1`、`Step 2` 这类连续整数；不要为了插入步骤创建 `Step 1.5` / `Phase 2.1` / `Stage 0.5`，也不要在 `SKILL.md` 用 `### 2.1` 或 `- 2.1` 代替明确的工作流标题。`references/` 手册自身的 `3.1` 章节/列表号不受此规则影响。

修改编号前先预览，再写入并复查：

```bash
python3 scripts/skill-numbering.py audit
python3 scripts/skill-numbering.py fix --dry-run
python3 scripts/skill-numbering.py fix --write
python3 scripts/skill-numbering.py check
```

自动修复只重排显式 Step 标题及可无歧义绑定的引用。无法绑定的 fractional Step 引用或一对多映射会让整个写入在落盘前失败；Phase、裸编号标题和 bullet 子步骤需要按语义手工命名。完整算法与局部路径用法见 [scripts/README.md](scripts/README.md#工作流编号维护)。

涉及 agent/skill/plugin/hook 协议的断言必须先核对对应项目官方文档，再以真实 CLI 输出复核；不要从其他 agent 的相似字段推断。

## 共享文件规范

部分文件跨 skill 共享（如 banned-words.md、anti-ai-writing.md），修改时必须同步所有副本。

- runtime 脚本的唯一源/目标定义在 `scripts/shared-assets.json`；先改 `source`，再运行 `python3 scripts/sync-shared-assets.py sync`。
- 同名 runtime 脚本只能属于一个 canonical group，且每个 target 必须保留 source basename；禁止用改名 target 绕过单一 owner。
- reference 文档的 canonical source、部署副本与目录镜像显式定义在 `scripts/shared-references.json`；先改 source，再运行 `python3 scripts/shared-references.py sync`。reference target 可用语义别名，但必须在 manifest 逐路径登记。
- `shared-references.py check` 还会按内容哈希扫描未登记的跨 Skill 精确副本；目录镜像的 `files` 必须完整覆盖 source tree，新增文件不能绕过 manifest。
- `check-reference-similarity.py` 会扫描跨 Skill 近似副本；仍需独立演化的历史派生文件必须在 `derived_groups` 登记成员与分化理由。新增副本必须选择“登记同步”或“形成真正独立内容”，不能靠改名绕过 owner。
- `story-short-analyze` 的 `analysis-short-*` 是源文观察标尺，不是写作 playbook；禁止重新引入长篇节点、卷级循环、推荐结构百分比或“每章必备”口令。由 `check-short-analysis-scope.py` 守卫。
- 提交前统一运行 `bash scripts/check-shared-files.sh`；未在 manifest 登记的重名 runtime 脚本会直接失败。

### 知识库贡献

最有价值的贡献类型：

- **实战数据**：各平台最新榜单分析、题材趋势变化
- **新题材框架**：新的题材写作公式、结构模板
- **去AI味规则**：新的 AI 痕迹模式、改写范例
- **平台规则更新**：投稿要求、推荐机制的变化

## 质量要求

- **操作性**：内容必须能让 AI agent 直接执行，不要写教程
- **简洁**：用表格和模板，不要长篇叙述
- **自包含**：运行时 Skill 禁止跨 Skill 路径引用。确需共享的 reference 以 canonical source + manifest 管理的本地部署副本发布，保证每个 Skill 可独立安装
- **中文**：所有内容用中文

## 提交流程

```
fork → branch → commit → PR → review → merge
```

- 一个 PR 聚焦一个改动
- commit message 用中文，格式：`类型: 简短描述`
- 类型：`feat`（新增）/ `fix`（修复）/ `docs`（文档）/ `refactor`（重构）

## OpenCode 模板同步

本项目同时支持 Claude Code、Google Antigravity、OpenCode、Codex、ZCode、OpenClaw 和 Reasonix（Phase 1）。OpenCode 的 agent 模板和项目指令模板由 `scripts/sync-opencode.py` 从 Claude Code 模板自动生成。

### 何时需要同步

当你修改了以下文件后，需要运行同步脚本：

- `skills/story-setup/references/templates/agents/*.md`（agent 定义）
- `skills/story-setup/references/templates/CLAUDE.md.tmpl`（项目指令模板）

### 同步步骤

```bash
python3 scripts/sync-opencode.py
python3 scripts/sync-opencode.py --check  # 可选：只校验，不改文件
bash scripts/check-opencode-adapter.sh
bash scripts/test-opencode-cli-e2e.sh  # 可选：需要本机已安装 opencode
```

脚本会：
1. 将 `templates/agents/` 下的 Claude Code agent 转换为 opencode 格式，写入 `opencode/agents/`
2. 将 `CLAUDE.md.tmpl` 复制到 `opencode/AGENTS.md.tmpl`，替换 `.claude/` 路径引用
3. 输出同步结果摘要
4. 可选真实 CLI smoke 会在临时项目里验证 13 个 slash commands、7 个 agents 与 `story-hooks.ts` 插件能被 OpenCode 解析加载

### CI 检测

PR 中如果修改了 Claude Code 模板文件，CI 会自动检测 opencode 模板是否同步，并额外检查 `opencode.json.patch`、13 个 command、7 个 agent 的结构以及 `plugin.ts` 的实际守卫/收尾行为。如果 CI 报错，请在本地运行同步脚本和 `bash scripts/check-opencode-adapter.sh`，再提交结果。

### 手动维护的部分

以下文件无法自动生成，需要手动维护：

- `skills/story-setup/references/opencode/plugin.ts` — hooks 逻辑
- `skills/story-setup/references/opencode/commands/` — slash commands
- `skills/story-setup/references/opencode/opencode.json.patch` — 配置片段

### sync-opencode.py 已知局限

运行同步脚本后需进行以下手动检查：

- **路径解析段**：已由 `fix_path_rules_section()` 自动处理，无需手动修复
- **agent 数量**：确认 `opencode/agents/` 下始终为 7 个文件

### OpenCode 关键兼容性问题

**Glob 不搜索隐藏目录**：opencode 的 Glob 工具不搜索 `.opencode/` 目录，这导致了以下设计决策：

- **agent-references** 部署到 `skills/story-setup/references/agent-references/`（非隐藏），而非 `.opencode/skills/`
- **agent 文件** 双份部署：`.opencode/agents/`（opencode 系统使用）+ `agents/`（Glob 可见副本）
- **subagent 检测**：所有 spawn agent 的 skill（story-review、story-long-write、story-deslop、story-import、story-long-analyze、story-short-write）只检查当前运行时的 canonical 目录：Claude `.claude/agents/`、OpenCode `.opencode/agents/`、Codex `.codex/agents/`、Antigravity `.agents/agents/`；不得因其他端文件存在而误判。ZCode 3.3.4 与 OpenClaw Phase 1 不部署项目 agents，走 solo/direct fallback。

**插件输出不可见**：opencode 插件的 `output.extra.system` 已移除（真实 API 中不存在此字段）。系统提示注入改用 `experimental.session.compacting` 的 `output.context` 传递写作上下文。

**session-start 系统提示注入不支持**：OpenCode 公开 Plugin API 中无 `chat.message` 或等效 hook，部署状态检测和写作进度无法在会话开始时注入模型上下文。用户可手动运行 `/story-setup` 查看状态。

**其它 hook 差异**：`detect-gaps`（缺口检测）插件未移植，会话开始不注入提示（仅保留 compact 摘要与写正文前的大纲守卫）；`session-end` opencode 无等价事件、暂不支持；`validate-commit` 改用 git 原生 `pre-commit` hook（适用于所有 CLI）。

### OpenCode 使用注意事项

- **首次部署后需要重启 opencode**：story-setup 部署的 `.opencode/commands/` 下的 slash command 在 opencode 重启后才会生效。退出 opencode 后执行 `opencode -c` 重新进入即可。
- **首次部署使用自然语言触发**：新项目中没有 slash command，需要用自然语言触发 story-setup（如「请使用 story-setup skill，帮我部署网文写作环境」）。
- **opencode 配置不热加载**：修改 `opencode.json`、agent 文件或 plugin 后均需重启 opencode。
- **browser-cdp 长耗时操作可能卡死**：opencode 无后台任务机制，长耗时浏览器操作需用户按 `ESC` 打断（SKILL.md 已内置超时包装指引）。

## OpenClaw 适配维护

OpenClaw 当前采用 **Phase 1 skills-only** 适配：

- canonical source 仍是仓库根 `skills/`；不要为 OpenClaw 维护第二份 skill。
- 所有 `SKILL.md` frontmatter 必须符合 OpenClaw/AgentSkills 约束：单行 `name`、单行 `description`、单行 JSON `metadata`，且 `metadata.openclaw` 存在。
- `metadata.openclaw.requires.bins/env/config/anyBins` 用于 OpenClaw load-time gating；例如 `story-cover` 通过 `GPT_IMAGE_API_KEY` 控制可见性。
- `story-setup target_cli=openclaw` 只部署项目 `skills/` 与 `references/openclaw/AGENTS.md.tmpl`，不部署 OpenClaw agents/hooks/plugin。
- OpenClaw 会在 session 启动时 snapshot eligible skills；变更后需要新 session 或等待 skills watcher 刷新。

### OpenClaw 检查步骤

```bash
bash scripts/check-openclaw-skills.sh
OPENCLAW_REAL_CHECK=1 bash scripts/check-openclaw-skills.sh  # 本机安装 openclaw 时可选
```

`OPENCLAW_REAL_CHECK=1` 会用临时 profile + 临时 workspace 创建隔离 agent，确认 OpenClaw CLI 能从 workspace `skills/` 发现 13 个 story skill；脚本结束后清理临时 profile。

### OpenClaw 已知边界

- **agents 暂缓**：OpenClaw 的 agent/session 模型与 Claude/Codex 项目内 agent 文件不同，暂不生成 OpenClaw Gateway agents。涉及 agent 协作的 skill 必须降级 solo/direct。
- **hooks 暂缓**：写正文前大纲守卫、commit 提醒、session-start/compact 注入未迁移为 OpenClaw hook/plugin；OpenClaw 下只作为 skill 流程软约束。
- **package 暂缓**：OpenClaw 可识别 workspace/personal/managed skill roots；现阶段不发布 OpenClaw 原生 plugin package。

## Google Antigravity 适配维护

Antigravity 2.0 与 `agy` CLI 共用 `.agents/` workspace customization，但发版前仍建议分别实机 smoke test。支持面全部由 `story-setup` 部署到写作项目，部署器不写 `~/.gemini/`：

- 15 个 Skills 物化到真实 `.agents/skills/{name}/`。`deploy-antigravity-skills.py` 只替换已知名称、保留用户 Skills；现有 symlink 默认 fail-closed，只有用户明确同意才迁移，且不得沿链接写到目标目录。
- 7 个 custom subagents 由 Claude Markdown 真源在部署时生成到 `.agents/agents/agent-name/agent.md`（`agent-name` 替换为实际名称）。工具名必须来自官方清单，调用用 `invoke_subagent` + 同名 `TypeName`；生成器只替换 7 个已知定义并保留其他用户 agent。
- Always-On Rule 固定为 `.agents/rules/oh-story.md`，文件必须小于 12,000 字符。它负责 skill 路由和 compact 后重新读取 `追踪/上下文.md`；不要假设 Antigravity 有 Claude 的 PreCompact/PostCompact。
- `.agents/hooks.json` 是顶层 named-group mapping。合并器只替换 `oh-story` group，保留所有用户 groups。当前注册 `PreToolUse`、`PostToolUse`、`PreInvocation`、`Stop`：PreToolUse 必须输出 `decision`，PostToolUse 必须精确输出 `{}`；写后 findings 存到本会话 `artifactDirectoryPath`，下一次 PreInvocation 注入，Stop 最多强制 continue 一次。
- `.agents/hooks/` 只管理 `story_antigravity_hook.js` 与共享 `story_hook_core.js`；后者由 `scripts/shared-assets.json` 锁字节一致，不手改副本。Hook 依赖 PATH 中的 Node。

检查步骤：

```bash
bash scripts/check-antigravity-adapter.sh
python3 scripts/test-antigravity-skills-deploy.py
python3 scripts/test-antigravity-hook-merge.py
node scripts/test-antigravity-hooks.mjs
```

若本机装有当前 Antigravity 2.0 / `agy`，再在临时写作项目运行一次 `story-setup`，新开 conversation，用 `/skills`、`/agents`、`/hooks` 验发现，并分别验证 IDE 与交互式 CLI。`agy 1.1.22 -p` 的 headless 进程会在静默鉴权前先扫描 workspace，鉴权后不重载 custom agents/hooks；实测会出现 `subagent not found` 或把普通模型输出写进 `~/.gemini/antigravity-cli/scratch/`，因此当前不作为支持入口或 smoke 手段。测试后检查并清理意外 scratch 产物。自动化不读写用户 global customization，也不替代这个实机步骤。

## ZCode 适配维护

ZCode 采用「原生 plugin + `story-setup` workspace 部署」双入口：

- `.zcode-plugin/plugin.json` 与根 `marketplace.json` 暴露同一组 15 Skills、15 Commands 和 ZCode Hooks；版本必须与 `skills/story/VERSION` 同步。
- `skills/story-setup/references/zcode/` 是 workspace 部署模板，包含 `AGENTS.md.tmpl`、Commands、`config.json.patch` 与无第三方依赖的 Node Hook runner。
- ZCode 3.3.4 只支持 `SessionStart`、`UserPromptSubmit`、`PreToolUse`、`PermissionRequest`、`PostToolUse`、`PostToolUseFailure`、`Stop`。不要复制 Claude 的 `PreCompact`、`PostCompact`、`SessionEnd`、`SubagentStop` 或 `Notification`。
- Hook stdout 为空表示放行；只要非空就必须满足严格 JSON schema。诊断只写 stderr，异常 fail-open；优先使用 `process` + `node`，不要引入 shell/Python launcher 的跨平台分支。
- 3.3.4 不执行项目级或 plugin custom agents，也不发现 `.zcode/rules`。不要生成 `.zcode/agents/` / `.zcode/rules/` 或默认写入用户 home；涉及专业 Agent 的 Skill 必须明确报告 solo/direct fallback。

### ZCode 检查步骤

```bash
bash scripts/check-zcode-adapter.sh
bash scripts/test-zcode-hooks.sh
bash scripts/test-prose-net-parity.sh
```

更新正文轻量确定性网时，必须同步 Claude、OpenCode、Codex、Antigravity、ZCode 五端，并让 shared-assets / parity / Antigravity hook 测试通过。

## Reasonix 适配维护

Reasonix（DeepSeek-Reasonix CLI）当前支持 skills + 原生 plugin manifest + skills-only 的项目级 `story-setup` 部署；hooks 与 custom agents 留待后续阶段（涉及专业 Agent 的 Skill 走 solo/direct fallback）：

- 根 `reasonix-plugin.json` 是 plugin manifest；`version` 必须与 `skills/story/VERSION` 同步（`check-reasonix-adapter.sh` 守卫）。
- Reasonix 原生扫描项目 skill root（`.agents/skills` 等，指向 `skills/` 的 symlink，与 Codex 共用）发现 15 个 skill。
- `story-setup` 的 `target_cli=reasonix` 走 skills-only 部署：复制 15 个 skill 到项目 `skills/`、写入 `references/reasonix/AGENTS.md.tmpl`，不部署 hooks/agents（与 OpenClaw / generic 同构，由 `check-story-setup-deployment.sh` 守卫）。改动 Reasonix 部署路径或模板时同步该守卫。
- 真实 CLI 校验 `reasonix doctor capabilities` 不在 CI 内，发版前可手动跑。

### Reasonix 检查步骤

```bash
bash scripts/check-reasonix-adapter.sh
```

## Codex 适配维护

本项目同时支持 Codex CLI（repo skills 发现 + `$story-setup` 项目部署）：

- repo-local skills：`.agents/skills` 是指向 `skills/` 的相对 symlink（`../skills`，agentskills.io 标准路径），Codex 扫描它发现 skill，别复制第二份。必须是有效相对 symlink（`check-codex-adapter.sh` 守卫 target=`../skills`；无效/绝对会让发现失效，见 openai/codex#11314）；Windows 需 git `core.symlinks=true`。OpenClaw 原生扫 workspace `skills/`，不依赖它。
- project deployment hooks：`skills/story-setup/references/codex/hooks/hooks.json` 面向 `$story-setup` 部署到写作项目。POSIX `command` 与 Windows `commandWindows` 都从当前目录向上寻找 `.codex/hooks/run-story-hook.*`，不依赖 Git 仓库；找到后由共享 launcher 统一完成事件白名单、解释器探测、`CODEX_PROJECT_DIR` 注入与 Python hook 调度。
- Windows hooks：Codex 在 Windows 下用 `%COMSPEC% /C`（cmd.exe）启动 `commandWindows`。当前注册命令用 PowerShell 做逐级向上定位，再调用 `run-story-hook.cmd`；因此嵌套工作目录与 POSIX 行为一致，而不是只支持项目根目录。改事件清单或 launcher 后必须重跑生成器和适配检查，禁止在六个注册项里手工复制探测逻辑。
- custom agents：`skills/story-setup/references/codex/agents/*.toml` 由 `scripts/generate-codex-agents.py` 从 `references/templates/agents/*.md` 生成。修改 Claude agent 模板后必须重新生成并提交。

### Codex 同步步骤

```bash
python3 scripts/generate-codex-agents.py
python3 scripts/generate-codex-hooks.py
bash scripts/check-codex-adapter.sh
bash scripts/test-codex-hooks.sh
```

### Codex 关键兼容性问题

- **hooks 信任门槛**：Codex project `.codex/` 配置层需要被 trust，非 managed command hooks 还需要用户在 `/hooks` review/trust 后才会运行。
- **hook JSON 契约**：`PreToolUse`、`PreCompact`、`PostCompact` 的普通 stdout 会被忽略；需要输出 JSON，如 `hookSpecificOutput.permissionDecision = "deny"` 或 `hookSpecificOutput.additionalContext`。
- **PreToolUse 不完整拦截**：Codex 官方说明当前 shell/edit 拦截不是完备安全边界；story hooks 只作为写作流程 guardrail，不能替代版本控制和人工审查。
- **agent 文件格式**：Codex custom agents 是 `.codex/agents/{name}.toml`，必需 `name`、`description`、`developer_instructions`；只读 agent 使用 `sandbox_mode = "read-only"`。
- **custom-agent 运行时注册**：`$story-setup` 写入 `.codex/agents/*.toml` 后，需要 trust 项目 `.codex/` 配置层并新开 Codex 会话。若当前 Codex 运行时仍返回 `unknown agent_type`（本地 `codex exec 0.141.0` 临时项目烟测可复现），skill 必须降级 solo/direct 并报告 fallback；自动化硬门槛是 TOML schema 与文件部署检查。
