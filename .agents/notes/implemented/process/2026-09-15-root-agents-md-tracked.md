# Agent Note: 仓库根的 AGENTS.md 与 CLAUDE.md 纳入版本管理

Status: implemented

## Problem

自仓库初始化起，`.gitignore` 忽略根目录的 `AGENTS.md`、`CLAUDE.md` 和 `.agents/*`（只放行 `.agents/skills`）。原因是仓库根曾兼作 story-setup 的部署 / 测试目录：这两个文件由 story-setup 按各端模板（`references/*/AGENTS.md.tmpl`、`templates/CLAUDE.md.tmpl`）生成给用户的写作项目，不是仓库自己的开发指引。结果是 coding agent 进仓库时没有任何被主动加载的维护者指引——规则只散在 `CONTRIBUTING.md` 与 `scripts/README.md` 的散文里，对 agent 等于没有规则。

## Decision

- 根目录 `AGENTS.md` 是唯一的维护者开发指引来源，纳入 git。
- 根目录 `CLAUDE.md` 只含一行 `@AGENTS.md` 导入，never 维护第二份正文。
- `.gitignore` 去掉 `AGENTS.md`、`CLAUDE.md` 两行，并增加 `!.agents/notes`，让 Agent Note 树随仓库版本化；`.agents/*` 的其余忽略保持。
- 根 `AGENTS.md` 严禁包含 story-setup 用来识别已部署项目的标记文本——例如「网文写作工具集（OpenClaw）」「网文写作工具集（Reasonix）」「网文写作工具集（通用 Agent / Web AI）」这类标题行（story-setup `SKILL.md` Phase 1 靠它们判断项目是否已部署）。含有这些标记会让 story-setup 把本仓库误判为已部署项目。
- 用户写作项目里的 `AGENTS.md` / `CLAUDE.md` 仍由 story-setup 从模板生成与合并，与本决定无关。

来源：维护者决定 2026-09-15

## Alternatives considered

- **继续忽略这两个文件，开发指引只放 `CONTRIBUTING.md`**——最强理由：零风险，永远不会与 story-setup 生成给用户项目的同名文件混淆。否：coding agent 不会主动读 `CONTRIBUTING.md`，写在散文里的规则对 agent 等于没有规则。
- **`AGENTS.md` 与 `CLAUDE.md` 各自维护正文**——最强理由：两端可以各说各的侧重点。否：必然漂移，仓库历史里已有多处「文档漂移」修复提交（如 5498710、7a3a12c）为证；一份正文一处导入。

## Consequences

- **收益**：进仓库的 agent 在会话开始就拿到维护者规则与 Agent Note 入口；Note 树随代码同批提交、同批评审。
- **代价与已知上限**：维护者在仓库根跑 story-setup 会把 `AGENTS.md` 标为已修改，需要 `git checkout -- AGENTS.md` 还原，这是接受的代价。若将来 story-setup 改为不再按标题标记识别部署状态，「禁止标记文本」这一条应同步收窄。

## Verification

`git check-ignore -v AGENTS.md CLAUDE.md .agents/notes` 应无匹配；`grep -n '网文写作工具集（' AGENTS.md` 应无输出。
