# Codex 部署

`target_cli` 含 `codex` 时，由 SKILL.md Phase 2 完整读取并依次执行本文件。路径检查、幂等重跑、残留清理、部署标记、模板占位符、项目指令合并和报告遵循 SKILL.md 的公共规则。

## 部署清单（机械可检查）

| Source path | Target path | Owner class | Merge mode | Validation check |
|-------------|-------------|-------------|------------|------------------|
| `skills/story-setup/references/codex/AGENTS.md.tmpl` | `AGENTS.md` | user+managed | managed block merge | contains Codex story skill routing sections |
| `skills/story-setup/references/codex/agents/` | `.codex/agents/` | story-setup managed | replace | 7 TOML agent files parse and contain `name`/`description`/`developer_instructions` |
| `skills/story-setup/references/codex/hooks/hooks.json` | `.codex/hooks.json` | user+managed | replace managed registrations by stable hook identity | hook JSON valid; all stale direct/launcher registrations removed, current 6 registrations present exactly once |
| `skills/story-setup/references/codex/hooks/{story_codex_hook.py,run-story-hook.sh,run-story-hook.cmd}` | `.codex/hooks/` 同名文件 | story-setup managed | replace | Python/shell/cmd launcher 文件齐全 |
| `skills/story-setup/scripts/merge-codex-hooks.py` | 部署时执行，不复制到项目 | story-setup helper | execute | 替换已知管理注册、保留用户 hooks 与未知顶层字段，结果幂等 |
| `skills/story-setup/references/agent-references/` | `.codex/skills/story-setup/references/agent-references/` | story-setup managed | replace | every reference resolves |

## 部署 Codex Agents

- 读取 `skills/story-setup/references/codex/agents/` 下所有 `.toml` 文件，复制到用户项目 `.codex/agents/`
- Agent 文件由 story-setup 管理，可覆盖。Claude Code Markdown 是正文真源；仓库根 `scripts/generate-codex-agents.py` 确定性生成 `references/codex/agents/` TOML，部署只复制这些产物
- 校验每个 TOML 都能解析，且包含 Codex 必需字段：`name`、`description`、`developer_instructions`
- 只读职责 agent（`consistency-checker`、`story-explorer`）必须保留 `sandbox_mode = "read-only"`；`chapter-extractor` 要写批次输入文件，不设只读沙箱
- **部署后必须 trust + 新开 Codex 会话**（报告文案与 fallback 规则见下方「安装报告必须提示」）；hooks 未在 `/hooks` 信任前会被 Codex 静默跳过，包括写正文前的大纲守卫；若运行时返回 `unknown agent_type`，调用方必须降级 solo/direct 并报告 fallback。
- 将 `skills/story-setup/references/agent-references/` 同步复制到 `.codex/skills/story-setup/references/agent-references/`，作为 Codex agent 的项目内参考资料主路径。Codex 只使用当前规范前缀 `.codex/skills/`，不在运行时遍历历史备选路径。

## Codex hooks.json 合并算法

Codex 项目 hooks 部署到 `.codex/hooks.json`；运行脚本部署到 `.codex/hooks/story_codex_hook.py`、`run-story-hook.sh`、`run-story-hook.cmd`。JSON 只负责定位项目根与传递 event，解释器探测由平台 launcher 统一处理。

1. 定位当前 story-setup skill 目录，读取 `references/codex/hooks/hooks.json` 作为唯一当前模板，读取项目 `.codex/hooks.json`（不存在时视为空对象）。
2. 按现有跨平台规则探测可用 Python：`for PYBIN in python3 python py; do "$PYBIN" -c "" 2>/dev/null && break; done`；无可用解释器时停止，不手写或简化 JSON 合并。
3. 调用 `"$PYBIN" "{story-setup skill目录}/scripts/merge-codex-hooks.py" --existing "{项目}/.codex/hooks.json" --template "{story-setup skill目录}/references/codex/hooks/hooks.json" --output "{项目}/.codex/hooks.json"`。该 helper 会识别旧直调 `story_codex_hook.py`、当前 `run-story-hook.sh` 和 `run-story-hook.cmd` 三类管理身份，先移除所有已知管理注册，再追加当前模板。
4. 保留用户已有的非 story-setup hooks、matcher 块与未知顶层字段。重复执行必须幂等；禁止再按原始 `command` 字符串追加去重，否则 v17 直调命令会与 v18 launcher 双重注册。
5. 写入后解析 JSON 验证：旧直调 `story_codex_hook.py` 命令数为 0，当前模板 6 个注册各存在且仅存在一次，用户 hook 与未知顶层字段仍在。然后提示用户：项目 `.codex/` 层需要被 Codex trust，非 managed command hooks 还需要在 `/hooks` 中 review/trust 后才会运行；Windows 下走 `commandWindows`，launcher 从当前目录向上定位项目 `.codex/hooks/`，与 POSIX 路径的嵌套目录行为一致。

## AGENTS.md 与部署标记

- 将 `references/codex/AGENTS.md.tmpl` 按 SKILL.md「项目指令合并」写入根 `AGENTS.md`（`--host codex`）。
- `.story-deployed` 的 `target_cli` 写入 `codex` 或多端组合，`references_dir` 写 `.codex/skills/story-setup/references/agent-references`。

## 验证

- 检查 `AGENTS.md` 含 Codex story skill routing sections
- 检查 `.codex/agents/` 下 7 个 `.toml` agent 定义文件存在并可解析
- 检查 `.codex/hooks.json` 存在且 JSON 有效，Unix `command` 仅通过 `run-story-hook.sh` 启动，Windows `commandWindows` 仅通过 `run-story-hook.cmd` 启动；不存在直调 `story_codex_hook.py` 的注册
- 检查 `.codex/hooks/story_codex_hook.py`、`run-story-hook.sh`、`run-story-hook.cmd` 存在，Python 语法有效，POSIX/Windows launcher 能从嵌套 cwd 定位项目根
- 按源目录相对路径核对 `.codex/skills/story-setup/references/agent-references/`，含子目录，且已按 SKILL.md 清理源目录已删除的退役文件

## 安装报告必须提示

Codex 需要 trust 项目 `.codex/` 配置层，并在 `/hooks` review/trust 非 managed hooks——**未信任前 Codex 静默跳过这些 hooks，写正文前的大纲守卫也不生效，且不报错**；自动化里的 `codex exec` 可加 `--dangerously-bypass-hook-trust`；部署后新开 Codex 会话让 custom agents 生效；若当前运行时仍返回 `unknown agent_type`，按各 skill 的 fallback 规则降级 solo/direct。
