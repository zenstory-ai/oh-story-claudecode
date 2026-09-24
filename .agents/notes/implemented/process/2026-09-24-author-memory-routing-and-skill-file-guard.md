# Agent Note: 项目指令模板加「与作者协作」三条：作者记忆路由、不改已装 skill、说写书的话

Status: implemented
Date: 2026-09-24
Related: [2026-09-18-author-memory-explicit-only](../simplification/2026-09-18-author-memory-explicit-only.md)、[2026-09-18-author-memory-two-level-store](../architecture/2026-09-18-author-memory-two-level-store.md)

## Problem

发版前在真实 Claude Code 会话里复查，发现三件事：

- 作者直接说「记住：这本书对话用直角引号」，两次都进了 Claude Code 自带的 auto memory（`~/.claude/projects/.../memory`），没有进 oh-story 的作者记忆；只有显式 `/story 记住` 才生效。捕获规则已收敛为只记作者明确表达（见 Related），这条路径就是唯一的写入口，必须可靠。宿主的系统提示本身就要求「用户让你记住就立刻存」，项目指令里不写路由，模型会先走宿主记忆。
- `author_memory_commit.py` 报错时，模型改了写作项目里已安装的 skill 脚本来绕过错误，再告诉作者「我做了最小修复」。已安装的 skill 文件归 story-setup 管理，下次部署会被覆盖；绕过的错误可能正是需要作者知道的数据问题。
- 部署报告、检查报告和日常回复里常出现脚本名、字段名、状态名，维护者要求面向不懂编程的作者时用写书的话说。

## Decision

- 部署到用户项目的指令模板新增「与作者协作」一节（中文模板在「Compact 后恢复上下文」前，Antigravity 规则为英文 `## Working with the author`），三条：
  1. 回复和报告用写书的话说，不向作者抛脚本名、字段名或状态名；只有报错时才附原始报错。
  2. 作者要求记住、忘掉或确认写作习惯/偏好时，走 story skill 的「作者记忆」，由它的脚本写入 `.story/作者记忆/`，不要存进编程工具自带的记忆（如 auto memory）；一次性要求直接照做，不记录。
  3. 不修改项目里已安装的 skill 文件（`SKILL.md`、`references/`、`scripts/`）；skill 脚本报错时停下，把报错和所执行的命令告诉作者，不自行修补绕过。
- 覆盖的模板：`templates/CLAUDE.md.tmpl`（OpenCode 的 `AGENTS.md.tmpl` 由 `sync-opencode.py` 生成）、`codex` / `zcode` / `openclaw` / `reasonix` / `generic` 的 `AGENTS.md.tmpl`、`antigravity/rules/oh-story.md`。
- story-setup 的安装报告与 `check` 诊断报告改为先写「现在可以做什么」「你还需要做的事」（写书的话，不出现路径与字段），文件清单等技术明细放到末尾的简短「部署明细」。
- 模板变化随 `agents_version` 31 发布，已部署项目重跑 story-setup 后生效。

## Alternatives considered

- **只改 story skill 的触发描述，让「记住」更容易命中 story**——最强理由：不动部署模板、零部署成本，修在 skill 自己身上。否：实测问题不是 story 没被触发，而是宿主系统提示里的记忆指令先被执行；只有常驻上下文的项目指令能与之竞争，skill 描述做不到。
- **用 hook 拦截对宿主记忆目录的写入**——最强理由：确定性，不依赖模型遵守文字。否：各宿主的记忆存储位置和工具不同（Claude 写 `~/.claude/projects/.../memory`，其他宿主各有机制或没有），七端各写一个拦截器成本高；项目目录外的写入也不在现有 hook 的职责里。
- **允许模型修补已装 skill，但要求事后报告**——最强理由：作者不用等维护者发版就能继续写。否：补丁会在下次 story-setup 时被静默覆盖，同一个错误会再出现；且模型绕过的错误常是作者数据问题（如记忆条目冲突），作者需要看到原始报错才能判断。
- **把三条规则写进各 skill 的 SKILL.md**——最强理由：规则跟着 skill 走，不依赖部署。否：「记住」路由恰恰发生在 story skill 还没被加载的时候，只能放在常驻的项目指令里；写进 13 个 SKILL.md 还要付热路径预算。

## Consequences

- **收益**：部署后的项目里，裸「记住：……」会走作者记忆；skill 脚本报错时作者能看到真实错误；报告对非程序员可读。
- **代价**：每个会话的项目指令多约 200 字；已部署项目要重跑 story-setup 才能拿到新模板。
- **已知上限**：三条都是文字约束，模型仍可能不遵守，没有自动化测试验证真实模型的路由行为；宿主记忆的系统提示若更强势，仍可能抢先。需要在真实会话里复测「记住：」一句是否进入 `.story/作者记忆/`。
