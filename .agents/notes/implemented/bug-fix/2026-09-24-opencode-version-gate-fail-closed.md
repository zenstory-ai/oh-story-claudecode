# Agent Note: OpenCode 版本门改为 fail-closed，版本不明时停止部署

Status: implemented
Date: 2026-09-24
Related: [2026-09-23-opencode-v2-only](../architecture/2026-09-23-opencode-v2-only.md)（本篇翻转其中「命令不可用时继续部署」一条）

## Problem

#443 只适配 OpenCode 2.x。story-setup 的部署前置在 `opencode --version` 取不到或解析不出版本时继续部署，只在安装报告首行提示「未能确认版本」。发版前复查发现这条分支不安全：

- 1.x 不认 agents 的 2.x 原生 `permissions:` 规则列表，未知字段被忽略，三个只读 agent（`chapter-extractor`、`consistency-checker`、`story-explorer`）会拿到完整的写文件与 shell 权限。插件加载失败只是守卫缺席，权限失效会让只读 agent 真的改写项目。
- 1.x 被拦时，文档没有说 `.story-deployed` 怎么处理。只部署 OpenCode 的项目如果照常写入或抬高 `agents_version`，session-start 与各 skill 的版本提示就会认为项目已是当前部署，用户不会再被提醒重跑。
- story-review 按 `permission` 字段判断 OpenCode agent 是否完好，#443 后 agent 只有复数的 `permissions:`，模型可能把合法 agent 判成 malformed 并降级 solo。
- 多个 skill 写着「Claude/OpenCode 用 `subagent_type`」。OpenCode 2.x 的委派工具是 `subagent`，参数是 `agent`（2.0.16 二进制自带说明：`subagent` 取 `agent` 而不是 `subagent_type`）。

## Decision

- `skills/story-setup/SKILL.md`「OpenCode 部署前置」：主版本 < 2 或版本无法确定，都停止 OpenCode 部署。版本无法确定时请用户在自己的终端运行 `opencode --version`，用户在对话里确认是 2.x 才继续。
- 停止 OpenCode 部署时：target 只有 opencode，就不写、不更新 `.story-deployed`（已有的原样保留，不抬 `agents_version`），也不写任何 OpenCode 文件；多 target 时其它端照常部署，写入的 `target_cli` 不含 opencode，报告首行说明 OpenCode 未部署及原因，并告诉作者升级后重跑、选择把 OpenCode 加回来。
- 已部署项目重跑时，`target_cli` 不含 opencode 但项目里有 `.opencode/plugins/story-hooks.ts` 或 `.opencode/agents/`，用 AskUserQuestion 问是否加回 OpenCode；选加回先过版本门，通过后写回 `target_cli`。否则 sentinel 已是当前 `agents_version`、又以 `target_cli` 为准跳过探测，升级后的 OpenCode 永远不会重新部署，旧插件在 2.x 上静默失效。
- 升级命令先 `npm rm -g opencode-ai` 再装 `@opencode/cli`：两个包都提供 `opencode` 命令，不卸旧包时 PATH 上可能仍是 1.x。
- story-review 改为检查 `mode: subagent` 与 `permissions:` 规则列表；旧版单数 `permission:` 视为待重新部署。
- story-short-write、story-deslop、story-import、story-review 的委派说明改为「OpenCode 用 `subagent` 的 `agent` 参数」。
- `scripts/check-opencode-adapter.sh` 断言版本门文案存在：版本不明时停止、OpenCode-only 被拦时不写 `.story-deployed`，并拒绝旧的「解析不出版本 → 继续部署」；同时断言 story-review 按 `permissions:` 校验。

## Alternatives considered

- **保留「版本不明继续部署 + 报告首行提示」**——最强理由：沙箱里跑不了 `opencode` 的环境（命令不在 PATH、在 OpenCode 自身会话里被限制）也能完成部署，不打断用户。否：版本不明的最坏情况是 1.x，而 1.x 上只读 agent 会拿到写与 shell 权限，这是写坏项目的风险，不是体验降级；报告首行提示很容易被略过。改成请用户确认版本后继续，沙箱场景多一步对话，但仍能完成。
- **在 1.x 上改用单数 `permission:` 兜底生成一份 agent**——最强理由：1.x 用户也能得到只读约束。否：维护者已决定仓库不保留 1.x 分支代码（见 Related），而且 1.x 上写正文守卫插件仍然加载不了，部署下去也不完整。
- **被拦时仍写 `.story-deployed`，只把 `target_cli` 留空**——最强理由：保留一次部署尝试的痕迹。否：session-start 与 skill 版本提示按 `agents_version` 判断是否过期，写入当前版本号会让未部署的项目看起来已是最新，用户收不到重跑提醒。

## Consequences

- **收益**：1.x 或版本不明时不会再部署出权限失效的只读 agent；OpenCode-only 项目被拦后，下次会话仍会提示需要重跑 story-setup；多端项目被拦后，升级再重跑会被问到是否加回 OpenCode；story-review 不再把 2.x 合法 agent 误判为 malformed。
- **代价**：无法在部署环境里运行 `opencode --version` 的用户多一步确认；多 target 部署时 OpenCode 被拦会让 `target_cli` 少一项，要靠重跑时的加回询问补回；作者手动删了 `.opencode/` 的项目不会被问到。
- **已知上限**：版本门仍靠 skill 文本约束模型执行，没有脚本强制；`check-opencode-adapter.sh` 只守文案存在，不在真实 1.x 上跑部署。
