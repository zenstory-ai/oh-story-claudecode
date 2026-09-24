# Agent Note: 写正文拦截文案给补零细纲名，shell 变量路径如实说「没解析出来」

Status: implemented
Date: 2026-09-24
Related: [2026-07-15-hook-guard-failure-semantics](../architecture/2026-07-15-hook-guard-failure-semantics.md)

## Problem

写正文前的大纲守卫拦截后，模型按拦截文案去补文件，文案有两处会把模型带偏：

- 缺细纲时文案写 `细纲_第{章号}章.md`（如 `细纲_第1章.md`），而规范名与 demo 都是补零的 `细纲_第001章.md`。守卫匹配时容忍补零差异，但模型照文案建出的文件名与项目里其他细纲不一致。
- 共享核 `extractProseTargets` 从 shell 命令里抽写入目标时按字面取路径。`PROJ=...; cat > "$PROJ/正文/第001章_x.md"` 的目标被拼成 `{项目根}/$PROJ/正文/...`，书目录不存在，于是报「缺少细纲（$PROJ/大纲/细纲_第1章.md）」——细纲其实在，模型会去补一份不需要的细纲，或在错误的位置建 `$PROJ` 目录。

## Decision

- JS 共享核 `story_hook_core.js` 的 `proseBlockReason`、Codex `story_codex_hook.py` 的 `prose_block_reason`、Claude `guard-outline-before-prose.sh` 的缺细纲文案都给三位补零的文件名（章号 ≥ 1000 时原样）；JS 核的三个部署副本由 `sync-shared-assets.py` 同步。
- 长篇正文目标在项目根之下的相对部分含未展开的 shell 变量或命令替换（`$VAR` / `${VAR}` / `$(cmd)`），且按字面拼出的书目录不存在时，仍然拦截（fail closed），文案改为「写入路径含未展开的 shell 变量……守卫无法确认对应细纲。改用字面项目路径重新写入」。JS 与 Python 逐字一致。Claude 的 bash 守卫对 Bash 命令本来就调用共享核，文件路径直写（Write/Edit）不会出现 shell 变量，不需另改。
- 测试：`test-prose-net-parity.sh` Part E 加 `$PROJ/正文/第001章_x.md`、`$(pwd)/book/正文/第001章_y.md` 与补零文件名断言（Python 与 JS 对比）；`test-codex-hooks.sh`、`test-opencode-plugin.mjs`、`check-story-setup-deployment.sh` 各加一条命令级用例。

## Alternatives considered

- **在守卫里解析同一条命令中的变量赋值（`PROJ=...;`）再展开**——最强理由：能判对细纲是否真的存在，合法写入不必重写命令。否：赋值可能来自 `export`、`$(...)`、上一条命令或环境，静态展开只能覆盖一小部分，还会引入按错值放行的风险；让模型改用字面路径更简单也更可靠。
- **遇到 shell 变量直接放行**——最强理由：不误拦合法写入。否：守卫对无法判定的正文写入一贯 fail closed（见 Related），放行等于给绕过守卫留了一个固定写法。

## Consequences

- **收益**：模型按拦截文案补出的细纲名与规范一致；shell 变量路径的拦截不再误导模型去补不存在的缺口。
- **代价**：含变量的合法写入仍被拦，模型需要改写成字面路径再执行一次。
- **已知上限**：只处理长篇 `正文/第N章*.md` 目标；文件名本身含变量（如 `第${N}章.md`）解析不出章号，行为不变。
