# Agent Note: 阻断守卫 fail-closed，Bash 命令面 best-effort fail-open

Status: implemented

## Problem

`guard-outline-before-prose.sh` 是部署到用户项目的唯一阻断 hook（缺细纲写正文时 exit 2）。四端 hook 逻辑收敛到共享 node 核 `story_hook_core.js` 之后，Claude 的 bash hook 靠探测 node 决定是否走核；而 Claude Code 官方推荐原生二进制安装（不带 node），探不到就静默放行会让阻断守卫退化成不存在——归核当轮就出现了这个回归，前后修了两次（node 缺席、node 在场但抽取抛错）。另一面，Bash 命令写正文的目标只能静态识别，做不成 shell 沙箱，需要明确它的失败语义。

## Decision

- **Write/Edit/MultiEdit 面（阻断）**：目标路径抽取优先走 node 共享核；node 缺席或抽空一律回落纯 bash JSON 抽取（按 `file_path` / `path` / `filePath` 优先级取值，还原 `\\` 转义与 UTF-8）；两条路径都抽不到才放行。阻断判定（章号、细纲 glob、exit 2）全部在 bash，never 依赖 node。never 用 python heredoc 兜底——`test-prose-net-parity.sh` 禁止 Claude hook 内出现 heredoc python，防止第 5 份手抄逻辑。
- **Bash 命令面（best-effort）**：`settings-hooks.json` 把守卫注册到 `Bash|Write|Edit|MultiEdit`；共享核只识别重定向、`tee`、`touch`、`cp`、`mv`、`install` 的写入目标，只读命令里的引号示例与 heredoc 正文提及不拦，相对路径按 hook cwd 解析。这是静态 best-effort 识别，不是 shell 沙箱：环境变量间接路径、运行时拼接的命令、未列出的写文件程序无法可靠判定，这类写入应改用 Write/Edit。node 或核异常时 must 在 stderr 显式告警后 fail-open。
- 总原则「宁可漏拦不可误伤」：判定层面的不确定 exit 0；但基础设施缺席（没有 node）不得转化为静默放行。
- 同一批落地的发现边界：书目录发现限制在项目下 4 层并剪枝隐藏目录与 `node_modules`；`.active-book` 按 realpath 比对容纳关系，不得经 symlink 逃出项目根。

来源：739a427 (#243)、3174916 (#348)、603de4a (#239)

## Alternatives considered

- **归核后全靠 node，探不到即放行**——最强理由：单一实现零漂移，三个 advisory hook 正是这样降级的。否：原生二进制装法没有 node，阻断守卫会把「缺细纲写正文」静默放过；这是已发生并被修复的回归。
- **python heredoc 兜底**——最强理由：归核前就是这么做的，从不依赖 node。否：重开一份手抄逻辑，破坏本轮刚建立的归核回归门。
- 仓库历史里未见「Bash 面也 fail-closed」被权衡的记录，只能看到「不是沙箱」的定位。

## Consequences

- **收益**：has-python/no-node 与坏 node 两种环境下阻断守卫仍 fail-closed；Bash 写正文纳入守卫覆盖。
- **代价与已知上限**：纯 bash 抽取是核之外的第二份实现，靠 parity 测试按「同一次写入 bash 拦不拦 == JS 核拦不拦」逐场景锁住；Bash 面对间接写入必然漏拦，用户只会看到告警。若 Claude Code 保证 node 在场，或 hook 能拿到结构化写入目标，应重访 bash 兜底的必要性。

## Verification

`bash scripts/check-story-setup-deployment.sh` 的 TS11b（恒退非零的假 node 垫片）与 TS11c（`node -e ''` 退 0、跑脚本退非零的坏 node）断言缺细纲仍 exit 2；`bash scripts/test-prose-net-parity.sh` 断言无 heredoc python 且经 `story_hook_cli.js` 调核。
