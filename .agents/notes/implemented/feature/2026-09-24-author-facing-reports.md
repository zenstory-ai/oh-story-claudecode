# Agent Note: 给作者的报告只讲故事，不讲工程

Status: implemented

## Problem

真实会话测试里，交给作者的报告满是作者看不懂、也用不上的工程细节：脚本名和通过/失败清单（`check-ai-patterns.js` …）、字段与状态名（`visible_chars_v1`、`last_committed_chapter`、`state_revision`）、内部清单与严重度代号（S1–S4、Gate、「7 Gate」）、没有故事标签的裸编号（F057、E015、REL-001），甚至把 flag 名（`accept-current-length`）当选项让作者选。story-import 的导入完成报告曾经写出 `visible_chars_v1`、`imported_through_chapter=6`、F001–F007 / E001–E010 和「`tracking_commit.py init` 与 `check` 均通过」，作者读完仍不知道该核对什么、下一步说什么。

根因有两层：一是模板本身把内部结构原样暴露（story-review 报告开头强制逐字输出 `Requested Mode` / `Effective Mode` / `Fallback` / `Rubric Source`，Severity Counts 用 S1–S4；deslop 问题表带 Gate 列；导入报告写「唯一结构化 state + 派生快照 + 固定 7 栏上下文」）；二是模板没写清「哪些不能写」，模型就把内部自检结果、校验命令一并念给作者。

## Decision

- **报告写给作者**：每份作者可见的报告/消息模板只讲四件事——做了什么（故事语言）、发现了什么（白话 + 作者原文举例）、要作者决定什么（问题 + 自然语言选项 + 推荐默认）、下一步怎么说。脚本名、字段名、flag、状态码、内部清单名不进正文；编号只能以「故事描述（ID）」出现。确需保留的执行细节（如审稿降级原因、作者记忆回执）只放块尾一行「技术备注：」。
- **模板显式标注**：作者可见模板写在普通 ```` ```md ```` 围栏里，上一行加 `<!-- author-report -->` 标记，`scripts/check-author-reports.py` 只扫紧跟标记的围栏，拦截已知内部名、脚本/配置文件名、flag、snake_case / kebab-case 标识符（`/story-*`、`$story-*` 命令除外）、英文工程词、S1–S4、Gate 与裸编号；块尾技术备注豁免且只能一行。编号必须挂故事标签，「描述（ID）」与「ID（描述）」两种写法都放行。`REQUIRED` 列出必须带模板块的文件，防止标记被悄悄删掉。作者记忆回执例外：整条回复就是模板两行，写成围栏块时模型把围栏原样回给了作者（发版前实测 2/2），改用行内示例后 2/2 为纯文本两行，所以 `author-memory.md` 不用围栏、不在 `REQUIRED` 里。围栏信息串原先直接写成 `author-report`，发版前实测审稿报告整份连围栏回给了作者；同一本书用 v0.7.10 的 ```` ```md ```` 模板审则没有，改成「标记行 + ```` ```md ````」后复测为纯文本（各 1 次）。守卫现在拒收信息串为 `author-report` 的旧写法。守卫注册在 `cross-platform.yml` 的 static-check job，`--self-test` 自带正反例。规则只有这一份：`static-check.py` 的 author-report 检查加载本脚本的 `check_block`，不另维护词表（两份词表曾对编号写法要求相反，且各有漏词）。
- **本次覆盖的 skill**：
  - story-review：新增「报告面向作者」小节；S1 → 必须改、S2 → 建议改、S3/S4 → 可以不改；reviewer 名与 APPROVE/CONCERNS 换成「这次怎么审的」「总体判断」；新增「需要你决定」「没法判断的地方」；Mode / Fallback / Rubric 收进块尾技术备注。统一 Findings Schema 保留为 reviewer 与综合裁决之间的内部格式。
  - story-import：导入完成报告改成「导进来了 / 我整理出了 / 请你核对 / 需要你决定 / 下一步：说『日更』就从第 N+1 章接着写」；质量检查清单明确是自检、不念给作者；未部署环境的二选一和对标缺资料的提示改成白话。
  - story-deslop：检测表去掉 Gate 列（Gate 换算保留为内部计数说明），润色结果改成等级 → 改了什么 → 字数 → 改前改后 → 需要你看一眼。
  - story（路由）与作者记忆协议：新增「回执怎么告诉作者」——先一句人话（「记住了：《书名》的对话一律用「」」），机器回执放技术备注行；预算提醒不原样贴，改说哪几条习惯写正文时可能顾不上；查询降级不再标 `Fallback: agent unavailable -> direct lookup`。协议是 `author-memory-reference` 共享组的 canonical，四个副本经 `shared-references.py sync` 同步。
  - story-short-analyze：续跑三选一与完成消息改成作者问法，不报字段名和 Stage 编号；结构计数不达标时先自己补，补不出来才用故事话告诉作者缺什么。
  - story-long-scan / story-short-scan：扫榜报告标为作者模板并加一行原则（没采到的榜用一句话说明，不贴脚本名与 SKIP）；短篇报告补上 skill 开头要求的可信度与复扫时间。
  - story-cover：新增交付消息模板；问输出目录时不把 `BOOK_DIR` 变量名抛给作者。
- story-long-write、story-long-analyze、story-short-write、story-setup 的作者报告由并行改动按同一原则处理，本篇不覆盖其细节。

## Alternatives considered

- **全文扫描所有 skill 文档里的工程词**——最强理由：不用维护标记，覆盖面最大。否：SKILL.md 本身就是写给 agent 的操作说明，脚本名、字段名是合法且必要的指令内容，全文扫描会满屏误报，最后只能靠白名单，失去意义。
- **在运行时对模型输出做后处理过滤**——最强理由：直接拦住真正发给作者的文本，而不是只管模板。否：本产品是 Markdown 工作流，没有统一的输出拦截层；各宿主 hook 能力不一，且过滤只能删词、不能把「F003」改写成「玉佩的来历」，治标不治本。
- **把工程细节整段删掉，不留技术备注**——最强理由：作者界面最干净。否：审稿降级原因、作者记忆回执在报 bug 和核对「是否真的记住了」时有用；限定为块尾一行，既可查又不打扰阅读。
- **保留 S1–S4 但在旁边加中文解释**——最强理由：与 reviewer 内部 schema 一一对应，排序无歧义。否：作者只关心「要不要改」，三档白话足够决策；内部仍用 S1–S4 排序，转写发生在综合裁决之后。

## Consequences

- **收益**：作者读报告就知道要核对什么、拍板什么、下一步说什么；新增或修改作者模板时，常见工程词会在 CI 被拦下。
- **代价与已知上限**：守卫只查带标记的模板块，模型临场自由发挥的回复仍可能夹带黑话，只能靠模板里的原则句约束；中文工程腔（如「派生视图」「固定 7 栏」）规则拦不住，靠评审。英文工程词清单与裸编号正则需要随新术语增补。story-deslop SKILL.md 净减约 185 字，仍在预算内；story-review、story-import 不在热路径预算表内。

## Verification

`python3 scripts/check-author-reports.py --self-test`；`python3 scripts/check-author-reports.py`；`bash scripts/check-shared-files.sh`（作者记忆协议四个副本一致）；`bash scripts/check-doc-budget.sh`。
