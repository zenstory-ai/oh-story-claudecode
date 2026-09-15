# Agent Note: agents_version 是部署物过期的唯一运行时权威

Status: implemented

## Problem

story-setup 把 hooks、agents、rules、agent-references 部署进用户项目，skill 包更新后已部署项目会静默落后。需要一个机制让 session-start 判断「该重跑 /story-setup 了」，同时不能因为 skill 文本改动（不影响部署物）就骚扰用户，也不能让旧 skill 包把更新的部署降级覆盖。

## Decision

- `.story-deployed` sentinel 含 `agents_version`（整数）、`setup_skill_version`、`target_cli`、`resolver_strategy`、`references_dir`。当前值的单一来源是 `scripts/current-contract.json`。
- `agents_version` 是唯一的运行时过期权威。`session-start.sh` 与 story-setup Phase 1 只比较它：缺失 / 非整数 / 小于当前 → 待更新，重跑 story-setup 覆盖 agents/hooks/rules/reference bundle；等于 → 已部署，AskUserQuestion 确认是否重部署；大于 → 本地 skill 比项目旧，must 停止、不写任何部署文件、never 降级覆盖。
- `setup_skill_version` 只做存在性检查，落后不触发重部署（设计如此）。不在运行时逐级兼容历史模板，升级 = 重跑。
- bump 规则：只在部署物行为变化时 bump；纯文本精简、只在 spawn prompt 内联的变更不 bump。bump 按发布节奏进行：开发期 PR 改了 agent 模板也保持未发布的版本号，发版 PR 统一抬版并更新 UPGRADING「当前版本」。
- 守卫：`check-story-setup-deployment.sh` 从 `current-contract.json` 读当前值，用 N-1 / N / N+1 三种 sentinel 分别断言 session-start 的 warn / 静默 / 拒绝降级，并断言 `setup_skill_version` 落后时不误报。

来源：3442428 (#7)、12a9655 (#240)、6af0529 (#359)、1e2488b (#395)、abe9663 (#416)

## Alternatives considered

- **让 `setup_skill_version` 参与比较**——最强理由：一处版本就够，语义直观。否：内容改动会误报「需要重新部署」，session-start 注释与部署检查都把这一条钉成设计意图。
- **每个改动 agent 模板的 PR 各自 bump**——最强理由：部署物变了就立刻让用户拿到。否：一个发布周期内多次逼用户重跑；6af0529「keep agent version release-gated」与 590d10e「保持未发布 agent 合同版本」都选择等发版统一抬版。
- **CI 用 grep 钉死 UPGRADING 必须写到某个版本号**——曾经存在，12a9655 去掉：测的是措辞不是行为，发版是否补 UPGRADING 由发版清单和人把关。
- **运行时逐级兼容旧模板**——UPGRADING 明确不做；部署器按 owner class 替换受管文件、合并用户文件即可。

## Consequences

- **收益**：用户只在部署物真变时被提醒；旧包不会覆盖新部署；`agents_version` 一处改动即可触发全端刷新提示。
- **代价与已知上限**：未发版期间 main 上的模板变更对已部署项目不可见，直到发版抬版（v0.7.10 的 UPGRADING 明说开发期用 main v30 的项目也要重跑）；阈值要跨 `session-start.sh`、story-setup `SKILL.md`、UPGRADING、`current-contract.json` 对齐，靠 CI 锚点而非单一引用。

## Verification

`bash scripts/check-story-setup-deployment.sh`（TS10 版本阈值 + N±1 sentinel 场景）；`bash scripts/check-current-skill-contracts.sh` 校验 manifest 与 SKILL.md 的版本一致。
