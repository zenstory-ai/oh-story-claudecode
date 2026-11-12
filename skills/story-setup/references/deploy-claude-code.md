# Claude Code 部署

`target_cli` 含 `claude-code` 时，由 SKILL.md Phase 2 完整读取并依次执行本文件。路径检查、幂等重跑、残留清理、部署标记、模板占位符和报告遵循 SKILL.md 的公共规则。

## 部署清单（机械可检查）

| Source path | Target path | Owner class | Merge mode | Validation check |
|-------------|-------------|-------------|------------|------------------|
| `skills/story-setup/references/templates/CLAUDE.md.tmpl` | `CLAUDE.md` | user+managed | managed block merge | contains story skill routing sections |
| `skills/story-setup/references/templates/hooks/` | `.claude/hooks/` | story-setup managed | recursive replace | `session-*.sh`, `detect-story-gaps.sh`, `validate-story-commit.sh`, `guard-outline-before-prose.sh`, `check-prose-after-write.sh`, `story_hook_core.js`, `story_hook_cli.js`, `lib/common.sh`, `lib/sentinel.sh` exist；`story_hook_core.js` 与 OpenCode/ZCode/Antigravity 副本字节一致 |
| `skills/story-setup/references/templates/rules/*.md` | `.claude/rules/*.md` | story-setup managed | replace | every rule contains `paths` frontmatter |
| `skills/story-setup/references/templates/agents/*.md` | `.claude/agents/*.md` | story-setup managed | replace | 7 agent files exist |
| `skills/story-setup/references/agent-references/*.md` | `.claude/skills/story-setup/references/agent-references/*.md` | story-setup managed | replace | every `story-setup/references/agent-references/*.md` reference resolves |
| `skills/story-setup/references/templates/settings-hooks.json` | `.claude/settings.local.json` | user+managed | replace managed registrations by stable hook identity | hook JSON valid；旧 matcher 注册已迁移、当前模板命令各一份、用户 hook 保留 |
| `skills/story-setup/scripts/merge-claude-settings.py` | 部署时执行，不复制到项目 | story-setup helper | execute | 替换已知 story hook 注册、保留用户 hooks/顶层字段，v24→v25 迁移与重复执行幂等 |
| `skills/story-setup/scripts/copy-path-safety.py` | 每个递归复制步骤前执行，不复制到项目专用目录 | story-setup helper | execute | JSON 仅 `copy_allowed: true` 时允许复制；symlink 同对象 no-op；target 位于 source 内时停止 |
| generated sentinel | `.story-deployed` | story-setup managed | replace | contains `agents_version`, `setup_skill_version`, `target_cli`, `resolver_strategy`, `references_dir` |

`references/templates/hooks/` 内容：8 个 hook 脚本模板 + `story_hook_core.js`（正文网/大纲守卫/连续性/commit 侦测的共享实现，与 OpenCode/ZCode/Antigravity 同一份）+ `story_hook_cli.js`（bash hook 调核的 node 桥）+ `lib/common.sh`/`lib/sentinel.sh`。正文兜底 `check-prose-after-write.sh` 限 PostToolUse Write/Edit；`cat>`/`tee` 等 Bash 写正文在 Claude 端仅运行写前守卫。

## 部署 CLAUDE.md

按 SKILL.md「项目指令合并」写入项目根 `CLAUDE.md`：`--host claude-code`，模板 `references/templates/CLAUDE.md.tmpl`。

## 部署 Hooks

- **递归复制完整目录树**：将 `skills/story-setup/references/templates/hooks/` 复制到用户项目 `.claude/hooks/`
- 必须保留子目录 `lib/`，其中：
  - `lib/common.sh` 提供 `project_root`、`discover_active_book`、`discover_all_books`
  - `lib/sentinel.sh` 提供 `.story-deployed` 字段读取
- 只需对 `.claude/hooks/*.sh` 设置执行权限（`chmod +x`）；`lib/*.sh` 由 hook `source`，不要求可执行位

## 部署 Rules

- 读取 `skills/story-setup/references/templates/rules/` 下所有 `.md` 文件
- 复制到用户项目的 `.claude/rules/` 目录

## 部署 Agents

- 读取 `skills/story-setup/references/templates/agents/` 下所有 `.md` 文件
- 复制到用户项目的 `.claude/agents/` 目录
- Agent 文件属于 story-setup 管理文件，可安全覆盖；只覆盖这 7 个 oh-story agent，目录里作者自己的 agent 保留
- Agent 正文以这里的 Claude Code Markdown 为真源，其他宿主的 agent 都由它转换而来
- **部署后必须新开会话**：agent 只在会话启动时注册；报告文案见下方「安装报告必须提示」。

### 部署 Agent References

- 递归复制 `skills/story-setup/references/agent-references/` 的全部 `.md`（含子目录）到项目内 `.claude/skills/story-setup/references/agent-references/`
- 校验：凡 agent 或 reference 中出现 `story-setup/references/agent-references/<file>.md`，源包与目标包都必须存在 `<file>.md`
- 部署到项目后，agent 内引用的参考资料必须走 `story-setup/references/agent-references/*.md` 这一本 skill 内复制路径；不要跨 skill 引用其他 skill 的 references。Claude Code 只使用当前规范前缀 `.claude/skills/`，不在运行时遍历历史备选路径。

## 合并 Hooks 注册到 settings.local.json

先看 `.claude/settings.local.json` 是否存在：存在则读取现有配置，后续合并；不存在则由 helper 创建新文件。

1. 按现有跨平台规则探测 Python：`for PYBIN in python3 python py; do "$PYBIN" -c "" 2>/dev/null && break; done`；无可用解释器时停止，不手写或简化合并。
2. 调用 `"$PYBIN" "{story-setup skill目录}/scripts/merge-claude-settings.py" --existing "{项目}/.claude/settings.local.json" --template "{story-setup skill目录}/references/templates/settings-hooks.json" --output "{项目}/.claude/settings.local.json"`。
3. helper 会移除所有已知 story-setup hook 的历史注册，再追加当前模板；因此 matcher/timeout/if 能随版本升级，同时混在旧 block 中的用户 hook 与未知顶层字段原样保留。写后解析 JSON，验证模板命令各一份、用户配置仍在，再复跑 helper 比较文件字节确认幂等。

## 部署标记补充

- `references_dir` 写 `.claude/skills/story-setup/references/agent-references`（多端时与其他端逗号拼接）。
- 同时创建一次性标记文件 `.claude/.agents-pending-restart`（空文件即可）。session-start.sh 在下一个会话启动时据此确认 agents 已随新会话注册，并自动删除该标记——用来向用户确认「重启已生效」。

## 验证

1. 验证 hooks 注册：
   - 检查 `.claude/settings.local.json` 中的 hooks 字段是否正确
   - 检查 `.claude/hooks/` 下的脚本是否存在且有执行权限
   - 检查 `.claude/hooks/lib/common.sh` 与 `.claude/hooks/lib/sentinel.sh` 是否存在
2. 验证 rules 路径：
   - 检查 `.claude/rules/` 下的规则文件是否存在且包含 `paths` frontmatter
3. 验证 agents：
   - 检查 `.claude/agents/` 下的 7 个 agent 定义文件是否存在
4. 验证 agent reference bundle：
   - 按源目录相对路径核对 `.claude/skills/story-setup/references/agent-references/`，含子目录，且已按 SKILL.md 清理源目录已删除的退役文件
   - 检查所有 `story-setup/references/agent-references/<file>.md` 都能解析到 deployed bundle

## 安装报告必须提示

- **重启提示（必须醒目，放进「你还需要做的事」第一条）**：本次部署写入了 `.claude/agents/`，但这些 custom agent 只在「会话启动」时才会被 Claude Code 注册成 `subagent_type`。**请新开一个 Claude Code 会话再开始写作**，否则当前会话里 story-review / story-long-write 等想 spawn `story-architect`、`narrative-writer` 等时会拿到「subagent_type 不可用」并降级 solo（单视角，失去多 agent 协作）。判断是否生效：新会话里跑 `/story-review`，报告开头「这次怎么审的」写着几个视角（完整审或精简审）即注册成功；若写着「我一个人审」说明还在旧会话或未注册。
- 重启后即可使用 `/story-long-write` 或 `/story-short-write`
