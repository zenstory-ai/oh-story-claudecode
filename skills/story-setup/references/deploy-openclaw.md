# OpenClaw 部署

`target_cli` 含 `openclaw` 时，由 SKILL.md Phase 2 完整读取并依次执行本文件。路径检查、幂等重跑、残留清理、部署标记、模板占位符、项目指令合并和报告遵循 SKILL.md 的公共规则。

## 部署清单（机械可检查）

| Source path | Target path | Owner class | Merge mode | Validation check |
|-------------|-------------|-------------|------------|------------------|
| `skills/story-setup/references/openclaw/AGENTS.md.tmpl` | `AGENTS.md` | user+managed | managed block merge | contains OpenClaw story skill routing sections |
| repository `skills/{browser-cdp,story*}/` | `skills/{browser-cdp,story*}/` | story-setup managed for known skill names | replace known skill dirs only | 14 `SKILL.md` files exist; OpenClaw-compatible frontmatter |
| repository `skills/story-setup/references/agent-references/` | 随上一行整份 skill 拷贝落地，本行 no-op | story-setup managed | 不单独复制 | every reference resolves |

## Agent 边界

**OpenClaw 首版不部署 agents**：OpenClaw 只部署 skills，agent 协作相关 skill 必须按既有 fallback 规则降级 solo/direct，不要把 Claude/OpenCode agent frontmatter 直接复制成 OpenClaw agent。

## OpenClaw skills-only 部署算法

按以下步骤部署项目 skills：

1. 读取仓库当前 `skills/` 下所有包含 `SKILL.md` 的 story skill 目录（14 个：`browser-cdp` 与 `story*`）。
2. 写入目标项目 `skills/{skill-name}/`，仅替换这些 story-setup 管理的已知 skill 目录（`status: safe` 时按 SKILL.md 先清理各已知目录内源端已删除的旧文件）；保留用户在 `skills/` 下的其他目录。项目副本是整份 skill 拷贝，agent references 只使用当前规范前缀 `skills/`。
3. 每个 `SKILL.md` 必须满足 OpenClaw frontmatter 约束：`name` / `description` 是单行键值，`metadata` 是单行 JSON 对象且含 `metadata.openclaw`。
4. 用 `skills/story-setup/references/openclaw/AGENTS.md.tmpl` 按 SKILL.md「项目指令合并」写入项目 `AGENTS.md`（`--host openclaw`）。
5. `.story-deployed` 的 `target_cli` 写入 `openclaw` 或多端组合；`references_dir` 对 OpenClaw 写 `skills/story-setup/references/agent-references`。
6. 安装报告提示项见下方「安装报告必须提示」。

## 验证

- 检查 `AGENTS.md` 含 OpenClaw story skill routing sections
- 检查 `skills/` 下 14 个 story skill 目录存在，且每个 `SKILL.md` 包含单行 `name`、单行 `description`、单行 JSON `metadata.openclaw`
- 按源目录相对路径核对 `skills/story-setup/references/agent-references/`，含子目录

## 安装报告必须提示

OpenClaw 首版是 skills-only；未部署 OpenClaw agents/hooks，运行时硬拦截不可用，写正文前大纲守卫、commit 提醒、session/compact 自动注入只作为 skill 内软约束；OpenClaw 在 session 启动时 snapshot eligible skills，部署后如命令/skills 未出现，需新开 OpenClaw session 或等待 skills watcher 刷新。
