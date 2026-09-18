# Agent Note: 决策笔记的目录与结构由脚本守卫，不靠评审肉眼

Status: implemented

## Problem

`.agents/notes/` 的约定（状态目录 / 分类目录 / 日期文件名 / `Status` 行 / 四个必需小节）写在 AGENTS.md 里，但没有任何东西在 CI 上验证它。第一批骨架合入前，main 上已经先落了三篇笔记（#429、#432、#433），其中一篇首行少了 `# Agent Note:` 前缀，评审没有发现——约定一旦只靠人读，第一次漂移就会发生在第一批。

## Decision

- `scripts/check-agent-notes.py` 遍历 `.agents/notes/`，校验：路径为 `<status>/<category>/<yyyy-mm-dd-topic>.md` 且两级目录名在白名单内；首行 `# Agent Note: <标题>`；`Status:` 与所在目录一致；`## Problem`、`## Alternatives considered`、`## Consequences` 必有；`implemented` / `rejected` 须有 `## Decision`，`proposed` 须有 `## Proposal`，二者不并存；禁止 `INDEX.md` / `README.md` 之类手工索引。任一违规退出码 1。
- `scripts/test-agent-notes.py` 在临时目录逐类构造违规笔记，断言每一类都被拦、合法笔记通过。
- 两者接进 `.github/workflows/cross-platform.yml` 的 static-check job，紧跟 `test-static-check.py`；`scripts/README.md` 与 `CONTRIBUTING.md`「CI 检查」同步登记。
- 校验只管形状，不管内容：不检查 `来源` 行、不检查 Alternatives 是否真实存在过、不检查 Decision 是否与 main 一致——这些仍是评审的事。

来源：本 PR（#431）

## Alternatives considered

- **只靠 AGENTS.md 文字约束 + 评审**——最强理由：零脚本、零维护成本，笔记是给人和 agent 读的散文，形状不重要。否：main 上第一批就漂移了一篇，而且 agent 在写笔记时并不会主动重读约定；机械形状恰恰是脚本最擅长、人最容易漏的。
- **复用 `static-check.py` 的 Markdown 解析加一段规则**——最强理由：不新增脚本。否：`static-check` 面向 skill 文档（frontmatter、引用可达性），笔记不在 `skills/` 下、也没有 frontmatter，硬塞进去会把两套目标混在一个守卫里；独立脚本 80 行，边界清楚。
- **同时校验 `来源` 行必须指向存在的 commit**——最强理由：能拦「编造的被否方案」。否：需要完整 git 历史（浅层 clone 会误报），而且「来源」在 proposed 阶段本来就没有；留给评审。

## Consequences

- **收益**：形状漂移在 PR 上就红，评审只需读内容；新增状态或分类时改脚本里的白名单即可。
- **代价与已知上限**：多一个 CI 步骤（<1s）；脚本不理解内容，`Decision` 写成愿望句、`Alternatives` 只有一条稻草人方案都过得去。若将来笔记数量大到需要索引，`INDEX.md` 禁令要与 AGENTS.md 第 4 条一起重新裁定。

## Verification

`python3 scripts/check-agent-notes.py` 在本分支输出 `OK (13 notes)`；`python3 scripts/test-agent-notes.py` 十个用例全过。
