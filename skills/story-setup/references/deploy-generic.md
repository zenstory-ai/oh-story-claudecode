# 通用 Web AI / 其他 Agent 部署

`target_cli` 含 `generic` 时，由 SKILL.md Phase 2 完整读取并依次执行本文件。路径检查、幂等重跑、残留清理、部署标记、模板占位符、项目指令合并和报告遵循 SKILL.md 的公共规则。

## 部署清单（机械可检查）

| Source path | Target path | Owner class | Merge mode | Validation check |
|-------------|-------------|-------------|------------|------------------|
| `skills/story-setup/references/generic/AGENTS.md.tmpl` | `AGENTS.md` | user+managed | managed block merge | contains generic story skill routing sections |
| repository `skills/{browser-cdp,story*}/` | `skills/{browser-cdp,story*}/` | story-setup managed for known skill names | replace known skill dirs only | 14 `SKILL.md` files exist; OpenClaw-compatible frontmatter |
| repository `skills/story-setup/references/agent-references/` | 随上一行整份 skill 拷贝落地，本行 no-op | story-setup managed | 不单独复制 | every reference resolves |

## 通用 Web AI / 其他 Agent 部署算法

通用路径面向可读取项目文件的 NarraFork、Web AI、自定义 Agent，只部署 `AGENTS.md` 与项目本地 `skills/`。原生 hooks/agents 不部署；检查按 skill 软约束执行，分工走 solo/direct fallback。

1. 复制仓库当前 `skills/` 下所有包含 `SKILL.md` 的 story skill 目录（14 个：`browser-cdp` 与 `story*`）到目标项目 `skills/{skill-name}/`；仅替换这些 story-setup 管理的已知 skill 目录（`status: safe` 时按 SKILL.md 先清理各已知目录内源端已删除的旧文件），保留用户其他目录。项目副本是整份 skill 拷贝，agent references 只使用当前规范前缀 `skills/`。
2. 用 `skills/story-setup/references/generic/AGENTS.md.tmpl` 按 SKILL.md「项目指令合并」写入项目 `AGENTS.md`（`--host generic`）。
3. `.story-deployed` 的 `target_cli` 写入 `generic` 或多端组合；`references_dir` 对 generic 写 `skills/story-setup/references/agent-references`。
4. 安装报告提示项见下方「安装报告必须提示」。

## 验证

- 检查 `AGENTS.md` 含通用 story skill routing sections
- 检查 `skills/` 下 14 个 story skill 目录存在，且每个 `SKILL.md` 可读
- 按源目录相对路径核对 `skills/story-setup/references/agent-references/`，含子目录

## 安装报告必须提示

generic 不部署平台专属 hooks/custom agents；大纲守卫、commit 提醒、session/compact 注入等硬拦截与多 agent 协作都按 skill 内软约束或 solo/direct fallback 执行。
