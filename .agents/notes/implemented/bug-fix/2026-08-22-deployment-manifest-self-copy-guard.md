# Agent Note: story-setup 部署清单两列基准目录不同，同对象复制一律 no-op

Status: implemented

## Problem

story-setup 部署清单的 `Source path` 相对正在执行的 skill 包，`Target path` 相对用户项目根，两个基准目录从未写明。skills-only 端（OpenClaw / Reasonix / generic）的项目副本是整份 skill 拷贝，重跑时执行的就是项目里那份，两侧落到同一目录；Codex / Reasonix 经 `.agents/skills → ../skills` symlink 加载时，路径文本不同也指向同一目录；OpenCode 行的裸相对源在首次部署后会命中项目里刚写下的目标。照字面复制会把 `agent-references/` 嵌进自身，重跑几次就撑满磁盘（#363）。

## Decision

- `skills/story-setup/SKILL.md` 在清单前写明两列基准目录。执行清单每一行以及各端部署算法里的每个递归复制步骤之前，must 先把通配符具体化为单个源/目标，再用同级 `scripts/copy-path-safety.py` 检查：脚本按 realpath 语义跟随已有 symlink，两侧都存在时用 `samefile` 核对文件系统对象。
- 读取其 JSON：`status: same` 即 no-op，禁止复制；仅 `copy_allowed: true` 时可以复制；`source_missing`、`unsafe_target_within_source`、`filesystem_identity_error` 必须停止该步骤并报告。只转绝对路径或比较字符串不算检查完成；无法运行脚本时只能用当前环境的文件系统 API 做完全相同的检查，无法确认就停止，never 尝试复制。
- 部署前 must 删除自嵌套残留（四个 references 根下多出的 `agent-references/` 层，可能多层；以及 `skills/story-setup/skills/`），并在安装报告里列出删掉的路径。
- skills-only 三端的 repository `agent-references/` 行显式写成 no-op（随整份 skill 拷贝落地，不单独复制）。
- 例外：skills-only 端已有的残留自动清理到不了（重跑执行的是项目里那份 `SKILL.md`），README / UPGRADING 写明用户手动删；项目里的 skill 文本要靠新包覆盖 `skills/` 下 13 个目录来更新。
- 守卫：`scripts/check-story-setup-deployment.sh` 内置自复制探测器，只在含 `Source path` + `Target path` 表头的清单表内判定，散文分支要求两个路径在 16 字窗口内夹「到」；探测器先跑一组正负 fixture 自检再扫 `SKILL.md`。

来源：ef6ff7b (#364)

## Alternatives considered

- **探测器全文扫「同一路径出现两次」**——最强理由：覆盖面广、实现最简单。否：对全仓 396 个 `.md` 误报角色关系模板与 CHANGELOG 叙述；收窄到清单表内 + 邻接窗口后零误报，且仍精确报出原文件 4 处。
- **文档只写「删完重新安装并重跑 setup」**——最强理由：一句话即可。否：skills-only 端重跑执行的是项目里的旧 skill，带不进新包内容；改为分开说明手动清理与用新包覆盖。
- **只做字符串或绝对路径比较**——最强理由：不依赖脚本。否：symlink 场景路径文本不同但同对象。

## Consequences

- **收益**：三端重跑幂等；CI 在清单文本层就拦住裸相同 Source/Target 的回退。
- **代价与已知上限**：每个复制步骤多一次脚本调用；探测器是启发式（只认清单表头与「到」短语），改表头格式或措辞会漏检，需同步 fixture；已有残留仍要用户手动清一次。

## Verification

`bash scripts/check-story-setup-deployment.sh`：fixture 自检必须恰好命中第 2、3、5、18 行，随后扫描 `SKILL.md` 零命中。
