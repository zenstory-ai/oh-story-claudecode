# DSH（DeepSeek Harness）部署

`target_cli` 含 `dsh` 时，由 SKILL.md Phase 2 完整读取并依次执行本文件。路径检查、幂等重跑、残留清理、部署标记、模板占位符、项目指令合并和报告遵循 SKILL.md 的公共规则。`references/dsh/` 提供 AGENTS 模板与角色注册清单。

## 宿主能力边界

DSH 当前以「项目文件 + 子代理派发」方式接入：会话内有委派类工具（spawn/fork 子会话），可按 `.claude/agents/*.md` 的人设 spawn 子代理；**没有 hooks 自动拦截**（`.claude/settings.local.json` 的 hooks 注册对 DSH 不生效；DSH 侧日后若提供 hooks 桥接插件可另行挂载，届时以插件为准），大纲守卫、去味检查按 skill 内软约束执行。子代理派发没有会话级 preset 选择：角色人设通过 prompt 注入（一次派发 = 一个 child 会话，人设正文 = persona 文件全文，任务 prompt 跟在其后）。

## 部署清单（机械可检查）

| Source path | Target path | Owner class | Merge mode | Validation check |
|-------------|-------------|-------------|------------|------------------|
| （复用 claude-code 部署产物）`references/templates/agents/*.md` 等 6 项 | `.claude/agents/*.md`、`.claude/hooks/`、`.claude/rules/`、`.claude/skills/story-setup/references/agent-references/`、`.claude/settings.local.json` | story-setup managed | 缺失时按 deploy-claude-code.md 对应清单补齐，已就位时校验即可 | 7 个 agent frontmatter 可解析且 `name:` 与角色名一致；agent-references 含子目录完整 |
| `skills/story-setup/references/dsh/agents.json` | 本 skill 包自带，不复制到项目 | story-setup managed | 随 skill 包存在 | JSON 可解析；`roles[].persona_path` 与 `.claude/agents/` 一一对应 |
| `skills/story-setup/references/dsh/AGENTS.md.tmpl` | `AGENTS.md` | user+managed | managed block merge | contains DSH story skill routing sections（标题行含 `网文写作工具集（DSH）`） |
| repository `skills/{browser-cdp,story*}/` | `skills/{browser-cdp,story*}/` | story-setup managed for known skill names | replace known skill dirs only | 14 `SKILL.md` files exist |

## DSH 部署算法

1. **角色资产复用 claude-code 部署产物**：检查项目 `.claude/agents/` 下 7 个角色定义与 `.claude/skills/story-setup/references/agent-references/` 完整性；缺失或 malformed 时按 deploy-claude-code.md 的对应清单补齐（CLAUDE.md 管理块与 hooks 注册按其文件规则顺带执行，多端部署不重复做）。不重写一份 DSH 人设。
2. 复制仓库当前 `skills/` 下 14 个含 `SKILL.md` 的 story skill 目录到项目 `skills/`（与 generic 同规则；项目 `skills/` 已就位时核对 14 个 `SKILL.md` 存在即可，仅替换 story-setup 管理的已知 skill 目录）。
3. 用 `skills/story-setup/references/dsh/AGENTS.md.tmpl` 按 SKILL.md「项目指令合并」写入项目根 `AGENTS.md`（`--host dsh`）。
4. `.story-deployed` 的 `target_cli` 写入 `dsh` 或多端组合；`references_dir` 确认含 `.claude/skills/story-setup/references/agent-references`（DSH 角色按此 canonical 路径读资料；多端用逗号拼接）。
5. 用 `skills/story-setup/references/dsh/agents.json` 核对注册物：7 个 persona 文件存在、frontmatter `name` 可解析且与 `roles[].name` 一致；核对结果如实写进安装报告。

## 验证

- 检查根 `AGENTS.md` 含 DSH 段（标题行含 `网文写作工具集（DSH）`）
- 按 `agents.json` 核对 `.claude/agents/` 7 个角色存在且 frontmatter 可解析
- 按 `agents.json` 的 `references_dir` 核对 agent-references 含子目录完整，角色内引用的 `story-setup/references/agent-references/<file>.md` 均可解析
- 检查 `skills/` 下 14 个 story skill 目录存在且 `SKILL.md` 可读
- 当前运行时的委派类工具（subagent/spawn 类）可用性如实报告；不可用时角色注册仍然成立，涉及角色的 skill 走 solo/direct 并说明

## 安装报告必须提示

DSH 的角色 spawn 是「委派工具 + 人设注入」：story-review 等 skill 按注册清单读取 `.claude/agents/*.md` 人设正文注入子会话 prompt，不依赖会话级 preset 选择；注册物缺失或损坏时审查降级 solo。hooks 不生效：写正文前的大纲守卫、每章去味由 Agent 按 skill 约定自检执行。部署后新开会话使 AGENTS.md 路由生效。
