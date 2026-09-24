# Agent Note: 短篇写前参数验收回归：Phase 3 文件自带命令，交付说明改给作者看

Status: implemented

## Problem

v0.7.10（#402）加了写前参数验收：生成正文前先确认总字数、节数和用户给的逐节下限能同时满足。#418 把 story-short-write 的 Phase 3 / 4 拆到 `workflow-draft.md` / `workflow-revision.md` 后，`workflow-draft.md` 只写「给 Phase 4 的交付命令加 `--check-contract` 先运行」，而命令本体只在 `workflow-revision.md`；`SKILL.md` 又规定 `workflow-revision.md` 到 Phase 4 才读。真实 Claude Code 会话里，模型第 23 次工具调用就写了正文，第 29 次才读 `workflow-revision.md`，全程没跑写前验收；随后花约 40 轮自写 Python 数字数、改稿，才挤进 4000-5000 的范围（落在 4010）。

同一次会话的交付报告逐条列出 `check-phase2-contract.js` 等五个脚本的通过结果和「固定 12 列小节大纲」，作者看到的是工程日志而不是故事。

## Decision

- `workflow-draft.md` 的「写前参数验收」自带完整命令 `node {skill 根}/scripts/check-delivery-contract.js --json --check-contract --min-chars {MIN} --max-chars {MAX} --sections {N} [--min-section-chars …] {短篇目录}`，标明在锁定参数后、写 `正文.md` 前必跑，位置在「写前准备」之前。exit 0 只说明参数能同时满足；exit 2 即冲突，停在写前用中文请用户选调整项。
- 批中测字数改为去掉 `--check-contract` 重跑同一命令，取其非空白字符数作整篇累计值（未写完 exit 1 属正常），各节分布仍用 `short-format.md`「字数统计」；明写不自写 Python 计数。写作中与交付时因此是同一把尺。
- Phase 4 的最终交付验收仍在 `workflow-revision.md`，不变。
- `workflow-revision.md` 新增「交付说明（给作者看）」：写了什么（标题、核心钩子或反转、字数、节数）、要作者拍板的事（一句问题附推荐默认）、下一步可选；自查结果收成一句大白话，不写脚本名、检查 ID、字段名、参数或大纲表格格式。交付验收失败也按这份说明告诉作者差在哪里。`workflow-design.md` 的 Phase 2 门禁同理：失败时说设计还缺什么，汇报构思只讲故事与待拍板问题。
- `scripts/check-reference-gates.js` 钉住：首屏门禁与 Phase 3 / 4 小节分别路由 `workflow-draft.md` / `workflow-revision.md`；`workflow-draft.md` 含带 `--check-contract` 与三项参数的字面命令且位于「写前准备」之前，不再出现「Phase 4 的交付命令」；`workflow-revision.md` 保留不带 `--check-contract` 的最终验收命令。旧版 `workflow-draft.md` 在该守卫下失败。
- 预算显式上调：`workflow-draft.md` 4600→4750、`workflow-revision.md` 1700→1850、`workflow-design.md` 2350→2400、「短篇执行指令」路径 11500→11950，理由登记在 `scripts/doc-budget.json`。

## Alternatives considered

- **把 `workflow-revision.md` 的读取提前到 Phase 3**——最强理由：一字不增，命令本来就写在那里。否：Phase 3 要多付整份精修细则的上下文，拆分的意义就没了；而且「读 A 文件去找 B 阶段的命令」本身就是这次漏跑的根因。
- **在 `SKILL.md` 首屏门禁里放命令**——最强理由：入口是唯一保证被读的文件。否：`SKILL.md` 只留路由，命令放进入口会让每个场景（含只构思）都付这段文本；Phase 3 本就要求完整读取 `workflow-draft.md`，放那里足够且位置更贴近动笔时刻。
- **交付说明只删掉脚本名、不给模板**——最强理由：改动最小、预算最省。否：只禁不立，模型会换成别的工程说法（检查 ID、字段名）；给出三块结构和一句总括范例才能稳定落到作者视角。

## Consequences

- 收益：写前验收有可直接执行的命令且排在动笔前，参数冲突能在写正文前暴露；写作中与交付用同一计数口径，不再靠自写脚本反复数字数；作者收到的交付说明只讲故事、字数、待拍板问题和下一步。
- 代价：四处预算合计上调约 800 字，每次短篇 Phase 3 / 4 会话多付约 450 字；守卫钉的是命令字面与相对位置，只证明文本在，不证明模型照做，遵从度仍需真实写作回放验证。
- `short-format.md`「字数统计」的整篇命令仍按码位计数（含换行），与交付口径的非空白字符不同；该命令与 `scripts/test-charcount-portable.sh` 及其他 skill 逐字绑定，本次只在 `workflow-draft.md` 把整篇累计值改走交付验收脚本，未动共享命令。
