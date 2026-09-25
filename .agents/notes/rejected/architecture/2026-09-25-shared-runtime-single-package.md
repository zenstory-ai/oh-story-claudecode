# Agent Note: 共享运行时不打成单一部署包，维持每个 skill 自带真实副本

Status: rejected

## Problem

v0.8 瘦身提案（[v0.8 提案](../../implemented/architecture/2026-09-24-v0-8-lean-writing-loop.md) 第 2 节）列了一项「共享运行时只打一个包」：author memory、tracking、检测器、字数脚本在 5 个 skill 里各放一份拷贝，仓库冗余约 1.76MB（其中脚本约 0.94MB），改一处要 sync 全部副本。提案设想把它们做成一个 runtime payload，由 story-setup 部署到用户项目，各 skill 调用那一份。

## Decision

- 不做单一 runtime 包。共享脚本继续在每个用到它的 skill 里放真实副本，由 `scripts/shared-assets.json` 登记唯一 source，`sync-shared-assets.py sync` 同步，`check-shared-files.sh` 在 CI 拦漂移。
- v0.8 提案第 2 节的这一项以本篇结案。

## Alternatives considered

- **按提案实施**（新建 `story-runtime/` 收纳 author memory、tracking、字数与检测器脚本，由 story-setup 部署到项目固定位置，各 skill 改调那一份并删掉副本）：最强理由是单一源头，仓库少约 0.94MB 重复脚本，PR diff 变小，维护者不用再跑 sync。否，原因有三：
  - 它推翻 [跨 skill 拷贝笔记](../../implemented/architecture/2026-05-07-cross-skill-copies-not-symlinks.md) 的前提：每个 skill 必须能被独立安装和部署。OpenClaw、Reasonix、generic 这三类 target 是 skills-only，没有 story-setup 的运行时部署步骤；`npx skills add`、marketplace 单装一个 skill 时也拿不到 runtime 包。这些用户的写正文守卫、追踪提交和检测器都会直接失效。
  - 调研里的四个痛点（token、耗时、AI 味、概念复杂）都是用户侧的。重复副本只增加维护者的工作量，用户每次会话只加载自己那一份，不多付 token，也不多学一个概念。收益落在不需要的地方，代价由用户承担。
  - 现有 `shared-assets.json` + `check-shared-files.sh` 已经把漂移风险压到 CI：副本不一致直接红，owner 唯一。

## Consequences

- **收益**：所有 target（含 skills-only 平台与单装 skill）继续可用，不引入新的部署前置。
- **代价**：仓库继续保留约 1.76MB 重复内容，改共享脚本仍须 `sync-shared-assets.py sync` 并提交全部副本。
- **重访条件**：所有 target 都有可靠的运行时部署步骤，或 skill 安装机制原生支持跨 skill 依赖时再议；届时另开笔记并与本篇互链。
