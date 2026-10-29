# Agent Note: OpenCode 2.2 起 skill 与 Code Mode 工具改用调用验证权限

Status: implemented

Related: [2026-09-23-opencode-v2-only](../architecture/2026-09-23-opencode-v2-only.md)（运行时权限测试「以工具清单为判定」的前提）

## Problem

CI 的 `cli-compat` 装 `@opencode/cli@latest`。OpenCode 2.2.0（2026-10-27）发布后，`scripts/test-agent-permissions.py --opencode` 在 main 上变红：只读的 chapter-extractor 等子代理清单里多出 `skill` 和 `opencode_worktree_remove`。2.1.4 上同一份 main 通过。

查 2.2.1 源码（`Tool.snapshot`）得到两处变化：

- `execute` 被拒时，原本藏在 Code Mode 里的工具改为直接暴露（上游 #59315）。我们的子代理都拒了 `execute`。
- 2.2 给每个 agent 追加一条针对浏览器 skill 的 `action: skill` deny 规则，资源是具体 skill，于是 `skill` 的最后一条匹配规则不再是全局 deny，列表不再摘掉它。调用时 `skill` 仍按被加载的 skill 逐个判权限，我们的 `"*"` deny 照样拦住。

所以「模型收到的工具清单就是运行时判定」这条前提，对这两类工具不再成立。

## Decision

- `test_opencode_runtime` 判清单前先去掉 `skill` 和 `opencode_worktree_remove`，其余断言不变。
- `skill` 改用真实调用验证：测试项目放一个 `.opencode/skills/probe/SKILL.md`，每个清单里有 `skill` 的子代理调用它，断言拿不到 `SKILL_CANARY`；继承全部工具的对照 fixture 调用同一个 skill 必须拿到，证明拒绝来自权限而不是没发现 skill。
- `opencode_worktree_remove` 断言只在 agent 有 `edit` 时出现（它的权限键就是 `edit`）。
- agent 模板不改：在模板末尾显式 `action: skill` deny 也挡不住它进清单（2.2 的追加规则排在后面），而调用本来就被拒。

## Alternatives considered

- **CI 钉住 `@opencode/cli@2.1.x`**：最强理由是立刻变绿、不碰测试。不用：用户装的是最新版，钉版本等于不再测用户实际跑的运行时，问题只是被推迟。
- **在 agent 模板里加显式 skill deny**：最强理由是从配置源头收紧。不用：实测 2.2.1 上无效，清单照样出现 `skill`。

## Consequences

收益：测试在 2.1.4 与 2.2.1 上都通过，`skill` 的拒绝改由真实调用加对照组证明，比看清单更直接。

代价与遗留风险：`opencode_worktree_remove` 用 `edit` 权限判定。允许 `edit *` 的 narrative-writer、story-architect、character-designer、story-researcher 在 2.2 上能调用它删除 git worktree；2.1 时它藏在被拒的 Code Mode 里，子代理碰不到。现有权限格式只能按动作和资源路径写规则，拒绝它就要连文件编辑一起拒，所以本次只把它限定为「跟着 edit 出现」并记录在此，是否向上游反馈或另想办法待维护者决定。

## Verification

- `python3.12 scripts/test-agent-permissions.py --opencode <@opencode/cli 2.2.1>` 与 `<2.1.4>` 均通过。
- 改前 main 在 2.2.1 上报 `AssertionError: ('chapter-extractor', {..., 'skill', ...})`。
