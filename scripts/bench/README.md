# scripts/bench —— 真实会话基准

v0.8 瘦身的每一项改动都要过这套基准：同一批冻结的书、同一个用例，用真实 CLI 会话把章写完，比较前后版本的耗时、token 和正文指标。决策背景见 `.agents/notes/implemented/architecture/2026-09-24-v0-8-lean-writing-loop.md`。

只有工具进仓库；fixture、主机凭据和运行产物都放在仓库外（默认 `~/.oh-story-bench`，可用 `BENCH_HOME` 改），不提交。

## 目录约定

```
$BENCH_HOME/
  hosts.json              各主机的可执行文件、模型与凭据文件路径（不含密钥本身）
  fixtures/<名字>/        冻结的书目录（设定、卷纲、细纲，可带已写正文与追踪）
  pkg/<版本>/             deploy.py export 导出的包
  runs/<批次>/            run.py 的产物：meta.json、每轮会话日志、隔离 HOME、项目快照
```

`hosts.json` 形如：

```json
{
  "claude-code": {"bin": "<claude 可执行文件>", "model": "<模型名>", "path": "<含 node 的 PATH>",
                  "env": {"ANTHROPIC_BASE_URL": "..."}, "env_files": {"ANTHROPIC_AUTH_TOKEN": "<密钥文件>"}},
  "codex": {"bin": "<codex 可执行文件>", "model": "gpt-5.6-sol", "inherit_env": true,
            "env": {"CODEX_HOME": "~/.oh-story-bench/codex-home"}}
}
```

Codex 主机**必须**用独立的 `CODEX_HOME`：目录里只放一个指向 `~/.codex/auth.json` 的软链接和最小 `config.toml`（只写模型）。直接用 `~/.codex` 会继承用户的插件（computer-use、浏览器）、`notify` 钩子和全局 skills——既污染测量，基准会话还会去操作用户的电脑。`run.py` 检测到没配或指向 `~/.codex` 时拒绝运行。

## 脚本

| 脚本 | 做什么 |
|---|---|
| `deploy.py export --ref <git ref> --out <目录>` | 从 git 导出某个版本的 `skills/` 与契约文件 |
| `deploy.py deploy --pkg <包> --host claude-code\|codex --proj <项目>` | 按 story-setup 部署清单确定性部署（skills、agents、hooks、rules、入口文档、部署标记），不经过模型 |
| `run.py --case <用例> --pkg <包> --host <主机> --out <runs目录> [--label <标签>]` | 复制 fixture、部署、`git init`，按 `cases.json` 的轮次跑真实会话；作者被问到时按 `follow_up` 回答，直到提交够章数 |
| `judge.py [--judge agy\|claude\|codex] coverage\|pairwise ...` | 评委（默认 Antigravity 上的 Gemini；必须与写手不同家族）逐条核对情节点是否落地、列越界新增；两版配对盲评，交换顺序各评一次，两次一致才算胜负；两版细纲不同时各附各的细纲 |
| `compare.py --base ... --cand ... --coverage ... --pairwise ...` | 汇总两个版本的效率与质量，按非劣效门槛给出通过/不通过 |
| `metrics.py <run目录>... [--table] [--tell <tell仓库>]` | 每章平均墙钟、累计输入/输出 token、主会话调用、工具调用、子 agent 次数、上下文峰值、压缩次数；每章字数、首次字数检查结论、检测器命中；给 `--tell` 时加人类区间越界项数 |

Claude Code 主机用隔离 HOME，会话与子 agent 转录都在 `<run>/home/.claude/projects/` 下，`metrics.py` 从那里取 token。Codex 主机用独立 CODEX_HOME（复用登录），token 取自 `--json` 输出的 `turn.completed`。

## 用例

`cases.json` 里每个用例指定 fixture、书目录名、要提交的章数、第一轮提示词和作者跟进话术。当前三个用例：

- `mid-daily`：demo 书第 21 章之后日更 3 章（成熟项目、有追踪、有对标）
- `open-xuanhuan`、`open-nvpin`：新开的书从第 1 章写到第 3 章（开篇章节、首次初始化追踪）

## 质量结论怎么下

效率指标可以直接比较；「正文变好/变差」不能只看本目录的计数。要下质量结论时按预注册协议来：先冻结协议和分析脚本，再产生数据；评委换模型家族；单份盲评；主指标用可数的量。
