# Google Antigravity 部署

`target_cli` 含 `antigravity` 时，由 SKILL.md Phase 2 完整读取并依次执行本文件。路径检查、幂等重跑、残留清理、部署标记、模板占位符和报告遵循 SKILL.md 的公共规则。`references/antigravity/` 提供 Always-On Rule、named-group hooks 与 I/O adapter；写后 findings 经 session artifact 交给 PreInvocation/Stop。

## 部署清单（机械可检查）

| Source path | Target path | Owner class | Merge mode | Validation check |
|-------------|-------------|-------------|------------|------------------|
| current package skill root + `scripts/deploy-antigravity-skills.py` | `.agents/skills/{browser-cdp,story*}/` | story-setup managed for 14 known skill names | atomically replace known dirs; preserve unknown skills; never write through symlink | 14 real skill directories with valid `SKILL.md` exist |
| `skills/story-setup/scripts/generate-antigravity-agents.mjs` + Claude agent sources | `.agents/agents/agent-name/agent.md`（`agent-name` 为实际名称） | story-setup managed for 7 known agent definitions | generate then atomically replace known definitions; preserve unknown user agents | 7 Markdown agents parse; exact Antigravity tool names; `mainAgent: false`, `subagent: true` |
| `skills/story-setup/references/antigravity/rules/oh-story.md` | `.agents/rules/oh-story.md` | story-setup managed | replace | `trigger: always_on`; under 12,000 characters |
| `skills/story-setup/references/antigravity/hooks/hooks.json` | `.agents/hooks.json` | user+managed | replace only top-level `oh-story` group | valid Antigravity named-group schema; user groups preserved; idempotent |
| `skills/story-setup/references/antigravity/hooks/{story_antigravity_hook.js,story_hook_core.js}` | `.agents/hooks/` same names | story-setup managed | replace | Node syntax valid; core byte-identical to shared source; hook contract tests pass |
| `skills/story-setup/scripts/merge-antigravity-hooks.py` | deployment helper only | story-setup helper | execute | atomically replaces only `oh-story`, preserves user groups, idempotent |

## 部署 Antigravity Agents

- 先确认 `node` 在 PATH（agent 生成与 hooks 均依赖 Node）；缺失则停止 Antigravity 部署，不留半成品，提示安装 Node 后重跑。
- Agent 正文以 Claude Code Markdown 为真源。部署时调用 `scripts/generate-antigravity-agents.mjs`，把 Claude 工具名、模型档、reference 根和调用术语确定性转换为 Antigravity 2.0 契约；不得原样复制 Claude frontmatter。
- 执行 `node "{story-setup skill目录}/scripts/generate-antigravity-agents.mjs" --source "{story-setup skill目录}/references/templates/agents" --dest "{项目}/.agents/agents"`。生成器先渲染全部 7 个 agent，再原子替换 `.agents/agents/agent-name/agent.md`（`agent-name` 为实际名称）并清理旧版同名扁平 `.md`；保留其他用户 agent，源 frontmatter 异常时不留半更新目录，也不沿 managed agent symlink 写出项目外。
- 校验 7 个 `.md`：`name` 与父目录一致；`mainAgent: false`、`subagent: true`；模型只用 `flash` / `pro`；工具只来自官方名称 `view_file`、`find_by_name`、`grep_search`、`write_to_file`、`replace_file_content`、`multi_replace_file_content`、`run_command`；不得残留 `Read/Glob/Grep/Write/Edit/Bash` 或 `.claude/skills/` 前缀（只用 `.agents/skills/`）。
- 只读 agent（`consistency-checker`、`story-explorer`）无写文件或命令工具；`chapter-extractor` 只有读取与写文件、无命令工具；其余按 Claude 真源能力边界映射。
- Antigravity 用 `invoke_subagent`（`TypeName`、`Role`、`Prompt`）异步调用子代理，完成后由 `send_message` 唤醒主会话；`agy` CLI 只读子代理未暴露 `find_by_name`/`grep_search` 时，主会话在 `Prompt` 传入具体文件路径供 `read_file`（`view_file`）读取。部署后新开会话并用 `story-review` 验证 full/lean；无法解析 custom agent 时走 solo/direct fallback。

## Antigravity 部署算法

Antigravity 2.0 使用项目 `.agents/` 根，部署时创建 `.agents/skills`、`.agents/agents`、`.agents/rules`、`.agents/hooks` 并合并 `.agents/hooks.json`，部署 Skills、Always-On Rule、7 个 subagents 与 Hooks；不改 `~/.gemini/`。

1. 找到当前包 14 个已知 skill 目录（`browser-cdp` 与 `story*`），调用 `deploy-antigravity-skills.py --source "{当前 skill 包根}" --dest "{项目}/.agents/skills"` 原子物化。helper 只替换 14 个已知名称、保留用户其他 skills，源目标同 realpath 时 no-op。目标须为**真实目录**，不建 `.agents/skills → ../skills` symlink。
   - 若 `.agents/skills` 已是 symlink，helper 先停止且不沿链接写入。用 AskUserQuestion 说明：迁移会把链接可见 skills 复制到项目内真实目录、只更新 14 个 oh-story 名称、保留链接目标原样，但把 symlink 换成目录（可能产生较大 git diff）。仅在用户明确同意后加 `--migrate-symlink` 重跑，拒绝则停止部署并报告未获完整支持；多端部署或已有 Codex symlink 不得跳过此确认。
2. 按上方「部署 Antigravity Agents」运行生成器，原子更新 `.agents/agents/` 下 7 个已知定义并保留其他用户 agent；不从 home 搬运。
3. 复制 `references/antigravity/rules/oh-story.md` 到 `.agents/rules/oh-story.md`，验证 `trigger: always_on` 且小于 12,000 字符。该 rule 负责路由、硬约束与 compact 恢复；不用根 `AGENTS.md` 代替。
4. 复制 `references/antigravity/hooks/story_antigravity_hook.js` 与 `story_hook_core.js` 到 `.agents/hooks/`，验证 `node --check`。hook 命令以 `.agents/` 为工作目录，须写 `hooks/story_antigravity_hook.js`（勿写 `.agents/hooks/...`）；共享 core 须与 Claude/OpenCode/ZCode 源字节一致。
5. 合并 `references/antigravity/hooks/hooks.json` 到 `.agents/hooks.json`：探测 Python 3 调用 `merge-antigravity-hooks.py {项目}/.agents/hooks.json {skill目录}/references/antigravity/hooks/hooks.json`，只替换顶层 `oh-story` group、保留用户 groups，复跑比对字节确认幂等；禁止写入外层 `{ "hooks": ... }` schema。
6. 校验事件边界：只注册 `PreToolUse`、`PostToolUse`、`PreInvocation`、`Stop`（`PreToolUse`/`PostToolUse` 的 `matcher` 覆盖 `write_file|edit_file`、`write_to_file|replace_file_content|multi_replace_file_content` 与 `run_command`）。PreToolUse 每次输出 `decision`；PostToolUse 只输出 `{}`，正文 findings 经 `artifactDirectoryPath` 暂存并由下次 PreInvocation 注入；模型直接结束（`NO_TOOL_CALL` 或 `model_stop`）时 Stop 最多强制继续一次。无 SessionStart/PreCompact/PostCompact，首次上下文仅在首轮（`invocationNum=0` 且 `initialNumSteps<=1`）PreInvocation 注入，compact 后由 Always-On Rule 读 `追踪/上下文.md`。
7. `.story-deployed` 的 `target_cli` 写 `antigravity` 或多端组合，`references_dir` 写 `.agents/skills/story-setup/references/agent-references`。安装报告提示新开会话重扫 Skills/Rules/Agents/Hooks，并注明 Node 为 hook 依赖。

IDE 与交互式 `agy` 共用 `.agents/` 产物，仍需分别 smoke test。不依赖 `npx skills add -g` 写入的 `~/.gemini/*` 目录；仅支持项目内真实目录部署。

## 验证

- 检查 `.agents/skills/` 下 14 个 story skills 为真实目录且 `SKILL.md` 可读；`.agents/skills/story-setup/references/agent-references/` 完整
- 检查 `.agents/agents/` 下 7 个 Markdown agent 可解析，名称、模型档、官方工具白名单、只读边界与 `.agents/skills/` reference 前缀正确
- 检查 `.agents/rules/oh-story.md` 为 `trigger: always_on` 且小于 12,000 字符
- 检查 `.agents/hooks.json` 有效、顶层 `oh-story` group 恰有 PreToolUse/PostToolUse/PreInvocation/Stop，用户 hook groups 保留；检查 `.agents/hooks/story_antigravity_hook.js` 与 `story_hook_core.js` 语法有效
- 用 fixture 验证：PreToolUse 缺纲/追踪时 deny、普通写入 allow、commit advisory；PostToolUse stdout 恒为 `{}` 且把正文 findings 写进 session artifact；下一次 PreInvocation 注入 findings；Stop 对未处理 findings 最多 continue 一次；干净正文清除 pending state

## 安装报告必须提示

新开 Antigravity conversation 刷新 customization；Hooks 依赖 PATH 中的 `node`；外部 hook API 没有 PreCompact/PostCompact，compact 恢复由 Always-On Rule 读取 `追踪/上下文.md`；IDE 与交互式 `agy` 仍建议分别实机 smoke test；命令行写作从项目目录进入交互式 `agy`，确认 `/skills`、`/agents`、`/hooks` 已发现 oh-story 后再发任务；print 模式 `agy -p` 必须带 `--add-dir "$PWD"`（实测 agy 1.2.10 带上才加载工作区 `.agents/` 的 14 个 skills、7 个 agents 与 hooks，不带则都不加载，可能回退写入 `~/.gemini/antigravity-cli/scratch/`），测试后检查 scratch 无意外小说产物。
