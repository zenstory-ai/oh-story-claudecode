# Agent Note: OpenCode 适配只支持 2.x，部署前按版本拦截

Status: implemented

## Problem

OpenCode 2.0（2026-09-11 起，npm 包 `@opencode/cli`，与停在 1.18.x 的 `opencode-ai` 分开发布）重写了服务端。我们的 OpenCode 适配按 1.x 写，在 2.0.15 上实测：

- 写正文守卫插件 default export 是 1.x 的 hook-map 函数，2.x loader 只收 `{ id, setup }` / `{ id, effect }`，报 `PluginModule.LoadError` 后只记一行 WARN，服务照常运行——大纲守卫与写后兜底整场静默失效（#440/#441）。
- `opencode.json` 的 `plugin` 数组填的是单文件路径，2.x 只接受目录，该项被丢弃（`configured plugin path must be a directory`）。
- 工具改名改参：`bash`→`shell`、`apply_patch`→`patch`、`write`/`edit` 的 `filePath`→`path`。
- 2.x 默认由一个后台服务进程服务多个项目，插件里的 `process.cwd()` 不再是用户项目；沿用 1.x 的项目根定位会把有细纲的合法正文写入误拦，写后兜底也扫错位置。
- `opencode debug skill`、`debug agent --tool` 被删，CI 的 e2e 与运行时权限测试在 2.x 上跑不起来；`opencode models --verbose` 没了，story-setup 的 Agent 模型分级依赖它取成本。

CI 一直绿，是因为 `cli-compat` 装的是 `opencode-ai@latest`，永远是 1.x；e2e 也只检查配置里有没有插件项，从不检查插件是否真的加载、钩子是否真的生效。

## Decision

- 只支持 OpenCode 2.x，仓库不保留 1.x 分支代码。
- `skills/story-setup/references/opencode/plugin.ts` 默认导出 `{ id: "oh-story.story-hooks", setup(ctx) }`：`ctx.tool.hook("execute.before")` 对 `write`/`edit`（`path`）、`patch`（`patchText`）、`shell`（`command` + `workdir`）抽取正文目标，命中拦截时抛错，运行时把错误作为工具结果回给模型；`ctx.tool.hook("execute.after")` 在 `status: completed` 时把兜底发现追加进 `result.content`；`ctx.session.hook("compaction")` 往摘要请求的 `system` 追加写作上下文位置。项目根取 `ctx.location.directory` 的 git toplevel，相对路径以会话目录（或 shell 的 `workdir`）为起点。共享核 `story_hook_core.js` 未改。
- 插件靠 2.x 自动发现 `.opencode/plugins/*.ts` 加载，`opencode.json.patch` 删除；story-setup「OpenCode 部署前置」从已有 `opencode.json(c)` 的 `plugin`/`plugins` 数组删掉指向 story-hooks.ts 的旧项。`lib/` 子目录只要不放 `index.*` / `server.*` / `tui.*` / `rpc.*` 就不会被当成插件包。
- `scripts/sync-opencode.py` 生成原生 `permissions:` 规则列表（`action`/`resource`/`effect`，Bash→`shell`，列表顺序即优先级）。
- story-setup 部署 OpenCode 前执行 `opencode --version`：主版本 < 2 停止 OpenCode 部署并给出 2.x 安装命令；命令不可用时继续但安装报告首行提示版本未确认。模型分级改用 `opencode api model.list`（JSON 含 `cost[]`/`limit.context`），回退 `opencode models`。验证项增加 `plugin.list` 中 `oh-story.story-hooks` 为 `active`。
- CI `cli-compat.yml` 安装 `@opencode/cli@latest`。`scripts/test-opencode-cli-e2e.sh` 先在项目外拉起后台服务，再断言 13 个 skill（`GET /api/skill` 的 `path`）、13 个 command、7 个原生权限 agent、`plugin.list` 中插件为 `active`；然后用 `scripts/opencode-mock-llm.mjs` 驱动真实 `opencode run`：无细纲的 write/shell/patch 被拦且模型收到拦截原因，有细纲的 write 落盘且模型收到兜底发现，`session.compact` 的摘要请求带 `Writing context: book/追踪/上下文.md`。
- `scripts/test-agent-permissions.py --opencode` 预热后台服务后对每个 agent 跑 `opencode run --agent`，以 mock 收到的工具清单为运行时判定（2.x 把整条 deny 的工具从清单里摘掉），并验证允许的 write/shell 真实执行、被拒的 write 得到 `No tool named "write"`。`check-opencode-adapter.sh` 的静态裁决矩阵改为独立复刻 2.x `whollyDisabled()`。
- `scripts/test-opencode-plugin.mjs` 以 `setup(ctx)` 注册钩子，且在项目外的 cwd 里调用 `setup` 与钩子，锁住 `ctx.location` 定位。
- 2.x 后台服务默认监听固定端口，开发机上已有 OpenCode 服务时隔离 HOME 里的服务起不来、请求一直重试。e2e 与运行时权限测试先用 `opencode service set port` 给隔离 HOME 钉一个空闲端口。

来源：#443（修复 #440、#441）

## Alternatives considered

- **一个文件同时导出 1.x `server()` 与 2.x `setup()`**——最强理由：官方迁移文档给了这种双导出写法，1.x 用户（当前默认安装渠道仍是 1.x）不受影响。否：维护者明确不留旧代码；且 1.x 只从 1.18.29 起认对象形式，双导出也覆盖不全 1.x；两套钩子、两套工具名、两套参数名要长期并行测试。
- **agent 继续用 1.x `permission:` 写法，靠 2.x 的 legacy 迁移**——最强理由：一份文件两代都能读，改动最小。否：只支持 2.x 后这层兼容就是旧格式残留，且依赖上游 legacy 路径长期保留；原生 `permissions:` 与官方文档一致，生成器里映射一次即可。
- **保留 `opencode.json` 里的插件注册**——最强理由：显式声明比自动发现可见。否：2.x 对单文件路径直接丢弃并告警，要注册只能改成目录形式的插件包，比自动发现多一层结构却没有收益。
- **版本不符时照常部署、只在报告里提示**——最强理由：不打断多端部署。否：1.x 上插件加载失败是静默的，报告里一行提示很容易被忽略，写正文守卫缺席会直接影响产出；只有 `opencode` 命令不可用、无法判断时才降级为提示。
- **e2e 用 `--standalone` 私有服务器**——最强理由：每次调用独立、无需管理后台服务生命周期。否：冷启动时 location 的 agent/插件异步加载，`--standalone` 查询返回空列表、`run --agent` 报 Agent not found；且 standalone 服务的 cwd 恰好是项目，测不出 `process.cwd()` 回归。

## Consequences

- **收益**：2.x 用户恢复大纲守卫、写后兜底与压缩前上下文注入；CI 首次在真实 OpenCode 运行时上验证钩子与权限，「插件静默没加载」「服务 cwd 不是项目」两类回归都有负对照确认会变红。
- **代价**：仍在 1.x 的用户（`curl opencode.ai/install` 与 `npm i -g opencode-ai` 目前都装 1.x）必须升级到 2.x 才能用本适配，story-setup 会拦下并提示；已部署项目需重跑 story-setup 以替换插件与 agent，`agents_version` 按发版节奏在下一次发版时抬版，在那之前 session-start 不会提示。cli-compat 的 OpenCode job 多出 mock 模型与十余次 `opencode run`。
- **已知上限**：mock 模型只验证钩子与权限的运行时行为，不验证真实模型会不会选对工具；钩子抛错被回传给模型、`opencode run` 以 `$PWD` 定会话目录、location 资源异步就绪，这些是 2.0.15 的实测行为而非文档保证，由 e2e 断言兜住。

## Verification

- `bash scripts/test-opencode-cli-e2e.sh`（OpenCode 2.0.15）通过；把插件换回 main 上的 1.x 版本，报 `story-hooks plugin missing from plugin.list`；把 `ctx.location.directory` 换成 `process.cwd()`，报 `outlined write was blocked or not written`。
- `python3 scripts/test-agent-permissions.py --opencode <opencode 2.0.15>` 通过，7 个 agent 的工具清单与能力声明一致。
- `node scripts/test-opencode-plugin.mjs` 通过；`process.cwd()` 变体在该测试中失败。
- `bash scripts/check-opencode-adapter.sh` 通过。
- 默认服务端口被另一个 OpenCode 服务占用时，钉端口前 e2e 卡死，钉端口后 e2e 与权限测试均通过。
- 真实模型（MiMo `xiaomi/mimo-v2.6-pro`，OpenCode 2.0.15，`opencode run --auto`）逐场景实测，均符合预期：全新项目按 story-setup 部署（不写 `opencode.json`，插件 `active`）；1.x 时代的旧部署重跑 story-setup 后插件由 `failed` 变 `active`，`opencode.json` 只删掉 story-hooks 注册、保留用户字段，agent 自配的 `model:` 保留；无细纲写正文被拦后模型补细纲、补追踪再落盘，写后兜底点出的 AI 句式被模型修掉；shell heredoc 写正文被拦；从 `book/` 子目录起会话、相对路径写正文按项目根判定；narrative-writer 子代理里钩子同样生效；短篇缺小节大纲被拦；`/story` 命令正常路由；真实 compaction 摘要把 `book/追踪/上下文.md` 列为续写入口。
