# AGENTS.md

本文件是 oh-story-claudecode 仓库自身的开发指引，给维护这个 skill 套件的 coding agent 读。它不是部署到用户写作项目里的那份 AGENTS.md；用户项目的 AGENTS.md / CLAUDE.md 由 story-setup 按 `skills/story-setup/references/*/AGENTS.md.tmpl` 生成，与本文件无关。

## 这个仓库是什么

一个网文写作 skill 套件：13 个 skill（`skills/<name>/SKILL.md` + `references/`），加上面向 Claude Code、Codex、OpenCode、OpenClaw、Antigravity、ZCode、Reasonix 七个宿主的适配层。产品是写在 Markdown 里的写作方法与工作流契约，不是运行时程序。`scripts/` 下是仓库自己的守卫、测试和代码生成脚本（索引见 [scripts/README.md](scripts/README.md)），不是 skill 运行时脚本。

## 改动前必须知道的规矩

- **frontmatter 单行键值**：`description` 不用 `|`/`>` 块，`metadata` 是单行 JSON，OpenClaw 依赖这一点。
- **不跨 skill 引用文件**：除基础组件 `browser-cdp` 外，一个 skill 的 SKILL.md / references 不得引用另一个 skill 的文件；共享内容走 `shared-references.json` / 共享资产清单登记。
- **热路径有字数预算**：SKILL.md、references 和 agent 模板受 `scripts/doc-budget.json` 约束，加正文要么删等量旧文本，要么显式调高预算并说明。
- **工作流编号是契约**：Step / Phase / Stage 编号与引用绑定由 `skill-numbering.py` 守卫，重排要跑它的级联而不是手改。
- **改 agent 模板或 CLAUDE.md.tmpl 后必须重新生成适配层**（OpenCode、Codex、Antigravity 等）并提交生成结果，否则适配层 CI 红。
- **skill 文档禁止裸调 `python3`**，须走 python3 → python → py 探测。
- **改名或移动任一 `scripts/` 脚本**，要同步 `.github/workflows/*.yml`、CONTRIBUTING.md、scripts/README.md 和调用它的兄弟脚本。
- 本文件不得出现 story-setup 用来识别已部署项目的标记文本（各端 AGENTS.md.tmpl 的标题行），否则在仓库根运行 story-setup 会把仓库误判为已部署项目。

完整规则、各宿主适配维护步骤与提交流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 验证

强制清单以 `.github/workflows/cross-platform.yml` 为准；提交前按 [CONTRIBUTING.md](CONTRIBUTING.md)「CI 检查」里的本地命令跑一遍与改动相关的守卫，至少 `bash scripts/static-check.sh`、`python3 scripts/skill-numbering.py check`、`bash scripts/check-doc-budget.sh`、`bash scripts/check-shared-files.sh`。

## 重要改动必须留笔记

决策笔记放在 `.agents/notes/{proposed,implemented,rejected}/{feature,bug-fix,simplification,architecture,process,testing}/yyyy-mm-dd-topic.md`，沿用 DeepSeek Harness 的 agent-notes 约定（方法见 https://github.com/czm15053/write-notes-like-deepseek）。正文中文，小节标题保留英文。

1. 非平凡改动（改了 agent 可观察的工作流步骤、跨 skill 契约、主产物或落盘格式、适配层结构、守卫脚本与 CI、测试策略）动手前，先在 `.agents/notes/` 里搜同主题旧笔记：有归属就地更新事实；没有就先写 `proposed/`，落地时随同代码在同一次提交里转 `implemented/`。纯机械改动（排版、改名、版本号、不改行为的补丁）直接提交，不写。
2. 每篇必有 `## Problem`、`## Decision`（现在时，只写已落地事实）或 `## Proposal`、`## Alternatives considered`（每个被否方案先写它最强的理由再写为何不用，没考虑过的不要编）、`## Consequences`（收益和代价都写）。
3. 禁止把一篇笔记改写成相反的决定：事实（路径、名字、默认值）就地改；决定翻转就另开一篇并互链。
4. 不建 `INDEX.md`，目录位置就是状态；检索用 `rg --hidden .agents/notes/`。
