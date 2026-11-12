# ZCode 部署

`target_cli` 含 `zcode` 时，由 SKILL.md Phase 2 完整读取并依次执行本文件。路径检查、幂等重跑、残留清理、部署标记、模板占位符、项目指令合并和报告遵循 SKILL.md 的公共规则。`references/zcode/` 提供 AGENTS、14 Commands、插件角色、workspace config patch 与严格 JSON Hook runner。

## 部署清单（机械可检查）

| Source path | Target path | Owner class | Merge mode | Validation check |
|-------------|-------------|-------------|------------|------------------|
| `skills/story-setup/references/zcode/AGENTS.md.tmpl` | `AGENTS.md` | user+managed | managed block merge | contains ZCode `$story-*` routing and capability-based fallback |
| `skills/story-setup/references/zcode/agents/*.md` | plugin manifest `agents` 注册（不复制到 workspace） | plugin managed | plugin update | 7 个同名专业角色已注册；仅有文件不代表可调用 |
| repository `skills/{browser-cdp,story*}/` | `.zcode/skills/{browser-cdp,story*}/` | story-setup managed for known skill names | replace known skill dirs only | 14 `SKILL.md` files exist and satisfy ZCode frontmatter limits |
| `skills/story-setup/references/zcode/commands/` | `.zcode/commands/` | story-setup managed for known command names | replace known command files only | 14 commands have valid names/frontmatter |
| `skills/story-setup/references/zcode/hooks/story_zcode_hook.js` | `.zcode/hooks/story_zcode_hook.js` | story-setup managed | replace | Node syntax valid; hook contract tests pass |
| `skills/story-setup/references/zcode/hooks/story_hook_core.js` | `.zcode/hooks/story_hook_core.js` | story-setup managed | replace | Node syntax valid; hook contract tests pass |
| `skills/story-setup/references/zcode/config.json.patch` | merge into `.zcode/config.json` | user+managed | merge by event+matcher+process args | JSON valid; 按下方「ZCode 部署算法」第 4 步 hooks 互斥分支校验——未装 oh-story 插件时 `hooks.enabled=true`、only supported events；已装插件时校验 `.zcode/config.json` 不含（或已移除）这批 oh-story hooks 注册 |

## Agent 边界

**ZCode 支持子代理与插件角色**：oh-story 插件通过 manifest 的 `agents` 注册七个专业角色；使用当前运行时的 `Agent` 工具，参数以其 schema 为准。不要创建 `.zcode/agents/` 或修改用户 home：官方用户级定义与插件注册不是 workspace 目录发现。独立 Skills 安装不会自动注册插件角色，缺角色时提示启用/更新 oh-story 插件，仍不可用才 solo/direct。依据：[插件](https://zcode.z.ai/en/docs/plugin)、[子代理](https://zcode.z.ai/en/docs/subagents)。

## ZCode 部署算法

项目部署 Skills、Commands、AGENTS.md 与 Hooks；不部署 `.zcode/agents` 或 `.zcode/rules`，插件角色随插件安装/更新注册。

1. 复制仓库当前 `skills/` 下 14 个包含 `SKILL.md` 的目录到 `.zcode/skills/{skill-name}/`；仅替换这些已知目录（替换前按 SKILL.md 清理各已知 skill 目录内源端已删除的旧文件），保留用户其他 Skills。ZCode 只使用当前规范前缀 `.zcode/skills/` 查找 agent references，不在运行时遍历历史备选路径。
2. 复制 `references/zcode/commands/*.md` 到 `.zcode/commands/`；仅替换 14 个同名命令，保留用户其他 Commands。
3. 复制 `references/zcode/hooks/story_zcode_hook.js` 和 `references/zcode/hooks/story_hook_core.js` 到 `.zcode/hooks/`。
4. 读取 `references/zcode/config.json.patch` 和现有 `.zcode/config.json`（如只有根 `zcode.json`，仍创建 `.zcode/config.json` 承载 oh-story 项目 Hooks，不改写根文件）：
   - 保留用户所有未知字段、MCP、plugins、skills/commands disable overrides；
   - **hooks 互斥（避免双触发）**：若本项目经已安装的 oh-story 插件运行（`.zcode-plugin/plugin.json` 的 `hooks.json` 已全局注册 SessionStart/PreToolUse/PostToolUse），则先从 `.zcode/config.json` 移除这批已知 oh-story hooks 注册、保留用户 hooks，再**跳过**下面的 `config.json.patch` hooks 合并，避免同一事件双触发。只有未装插件（直接克隆 / 手动导入 references）时才合并 hooks。不确定时以「ZCode 是否已通过本插件注册这套 hooks」为准；skills/commands/hook 文件/AGENTS 与 config 的非 hook 字段两条路径都照常部署。
   - 合并 hooks（仅未装插件时）：设置 `hooks.enabled: true`；用户已有更大的 `timeoutMs` 时保留，否则取模板值；对 `hooks.events` 的 SessionStart、PreToolUse、PostToolUse 按 `event + matcher + process command + args` 去重追加；不复制 ZCode 不支持的 PreCompact、PostCompact、SessionEnd、SubagentStop、Notification。注：ZCode 3.7+ 忽略项目级 `.zcode/config.json` 的 `hooks`（`config_project_hooks_ignored`），需安装插件或合入用户级 `~/.zcode/cli/config.json` 才会在运行时执行。
5. 将 `references/zcode/AGENTS.md.tmpl` 按 SKILL.md「项目指令合并」写入根 `AGENTS.md`（`--host zcode`）。
6. `.story-deployed` 的 `target_cli` 写入 `zcode` 或多端组合，`references_dir` 写 `.zcode/skills/story-setup/references/agent-references`。不创建 Claude 的 `.claude/.agents-pending-restart`。
7. 检查当前插件注册角色并如实报告：可用时按同名角色派发；缺角色时提示启用/更新插件后新开会话，不用重复部署 workspace 代替。Hook 需要 PATH 中可用的 `node`。

Plugin 安装不经过本算法：`.zcode-plugin/plugin.json` 暴露 Skills/Commands/Hooks 与七个角色。Plugin Skills 优先级低于 workspace `.zcode/skills`；升级后须从**更新后的插件副本**运行 story-setup，覆盖旧项目快照与 AGENTS 受管块；旧 setup 遮蔽插件时按 [升级指南](../UPGRADING.md) 留备份移出再部署。**Hooks 只能注册一份**：插件在场时，以 manifest 为注册源；workspace 同批注册按第 4 步清理。

## 验证

- 检查根 `AGENTS.md` 含 ZCode `$story-*` 路由、大纲守卫与按能力降级，不含固定 solo 指令
- 插件在场时检查七个专业角色的实际注册；只有独立 Skills 时允许缺角色并明确报告。角色资料从 workspace `.zcode/skills/story-setup/references/agent-references/` 读取；不创建项目 agent 目录或用户级定义
- 检查 `.zcode/skills/` 下 14 个 Skills 与 `.zcode/commands/` 下 14 个 Commands，验证 frontmatter 和命名
- 检查 `.zcode/hooks/story_zcode_hook.js`、`.zcode/hooks/story_hook_core.js` 存在且 `node --check` 通过
- 校验 `.zcode/config.json` JSON 与第 4 步互斥分支：未装插件时 enabled、事件和 process 路径符合模板；插件在场时没有这批 workspace 注册，保留用户 hooks。不得为通过校验把模板 hooks 再合回
- 检查 `.zcode/skills/story-setup/references/agent-references/` 完整且所有 reference 路径可解析
- 用 fixture 调用 SessionStart、PreToolUse deny/allow、PostToolUse，确认无发现时 stdout 为空、有输出时符合 ZCode 严格 JSON

## 安装报告必须提示

说明实际角色注册情况：可用时 full/lean 按所需角色派发，缺角色或工具才降级；未装插件时提示启用插件（或将 `hooks` 合入 `~/.zcode/cli/config.json`）才能启用运行时 hooks 与 7 个角色；Hook 依赖 PATH 中的 `node`。部署后新开会话刷新项目资料；插件角色模型继承主会话并设 `injectAgentsMd: false`，不移植 Claude 的单角色 inline hooks，拆文助手的单文件写入范围由角色正文约束，不承诺路径强隔离。
