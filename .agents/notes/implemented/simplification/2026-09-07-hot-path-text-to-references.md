# Agent Note: 热路径只留路由与铁律，工艺与阶段流程外移 references

Status: implemented

## Problem

narrative-writer 模板每章每次 spawn 都要付，近 300 行里铁律与技法混排；story-short-write 的 `SKILL.md` 对任何短篇场景无条件加载，其中构思阶段的框架模板与设计校验只在 Phase 2 用得上。长篇侧此前已按场景把流程下沉到 `workflow-*.md`（开书 -30%、回炉 -41%），但当时为了不 bump `agents_version` 故意没动 agent 模板，欠账累积。

## Decision

- **narrative-writer canonical 模板**（`skills/story-setup/references/templates/agents/narrative-writer.md`，OpenCode / Codex 副本由生成器同步）：约 110 行，铁律前置——细纲是唯一剧情蓝图、正文形状自主、新增物三档、字数不自测、元信息隔离、格式约定、不写追踪；工艺技法外移到 agent-references（`writing-craft.md` 等）；参考文件表按「按行判定，命中即读，未命中不预加载」组织；参考路径规则保持三端同步器识别的标准段形。spawn prompt 骨架由 `build_writer_prompt.py` 确定性拼装，主会话只填七槽。
- **story-short-write `SKILL.md`** 只留入口 Reference Gate、场景路由与产物契约；Phase 2 构思流程在 `references/workflow-design.md`，Phase 3 / 4 在 `workflow-draft.md` / `workflow-revision.md`，按阶段读取。入口门禁必须留在 `SKILL.md`。
- **长篇同构**：`SKILL.md` 只做场景路由，`workflow-setup` / `daily` / `chapter` / `revision` 按场景加载。
- 外移只搬不删：手艺规则一条不减。迁出文件在 doc-budget 保守全额计入，拆分不计作同阶段总量节省；条件参考用 `branches` 登记。

来源：1e2488b (#395)、9c40276 (#401)、fde1754 (#418)、1eae178 (#352)

## Alternatives considered

- **保留单文件全量加载、只靠预算压字**——最强理由：一个文件一次读完，不会漏读。否：1eae178 实测开书 / 回炉根本不写正文却要付 11k 字单章流程；预算只能压数量，压不掉场景错配。
- **模板精简与 `agents_version` 抬版同批**——最强理由：部署物变了就该立即刷新。否：1e2488b 让模板改动先落、抬版等相关 PR 定稿后统一，见 [agents_version 笔记](../process/2026-05-08-agents-version-sole-staleness-authority.md)。
- **顺手删掉重复的手艺规则**——最强理由：真重复。否：PR #228 盲评实测删那些会退步；只外移不删。

## Consequences

- **收益**：短篇 `SKILL.md` 39.6k → 11.4k 字节；写手定义 293 → 110 行；参考按需读，写前只付当前阶段的文本。
- **代价与已知上限**：一次任务要读多个文件，「读完再写」只靠 Reference Gate 文字约束（`rg` 摘读不算读完），弱模型可能跳读——#415 补的「preserve reference reads」就是为此；路由文字本身占预算（paths 的 `why` 登记 +900）。重访信号：若实测子代理漏读外移技法的比例回升（narrative-writer 的预算 `why` 记录过同一章 6 轮全部漏读 `writing-craft.md` 的历史），应把该条收回模板，而不是继续外移。

## Verification

`bash scripts/check-doc-budget.sh` 的「正文 agent 基础规则」「长篇日更主会话」路径合计；`python3 scripts/test-writer-pipeline.py`；`bash scripts/check-story-setup-deployment.sh` 的模板行为锚点。
