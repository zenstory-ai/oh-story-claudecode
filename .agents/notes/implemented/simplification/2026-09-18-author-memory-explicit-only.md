# Agent Note: 作者记忆捕获收敛为显式表达：移除推断写入管道

Status: implemented
Date: 2026-09-18
Issue: #436（出自 #429 评审讨论的扩展 B）
Related: [2026-09-18-author-memory-two-level-store](../architecture/2026-09-18-author-memory-two-level-store.md)

## Problem

捕获表原有两条由 agent 主动推断写入的管道：`repeated_correction`（同类修改反复
出现但作者没说是长期规则）和 `inferred_pattern`（从成稿或操作轨迹推断的模式），
写成 `pending` 进待确认清单。实际使用中偏好都是作者明确要求才记；推断管道的实际
产出只是攒待确认清单的审阅负担，不是记忆质量。文档又明说不装全量消息 hook，隐式
捕获本就承诺不了完整性——半吊子观察不如不观察。这与 #412「临时要求不写回长期
记忆」同向。

产品判断点：工具该不该在作者没开口的时候观察他。答案是不该。

## Decision

1. `normalize_preference`（所有新写入的入口）只接受 `WRITE_SOURCES =
   ("explicit_user", "accepted_suggestion", "manual")`；传 `repeated_correction` /
   `inferred_pattern` 直接报错并指路（范围含糊的原话用 `explicit_user` ＋
   `status=pending`）。原「推断来源必须保持 pending」的校验随之删除。
2. `SOURCES` 枚举保留这两个值，只为存量 state 仍能通过 `validate_state`、仍能
   `decide` / `forget`；`normalize_item`（读 state）继续按 `SOURCES` 校验。
3. 捕获表删掉两行，改为一行「作者原话像长期偏好但范围或稳定性含糊 → `pending`，
   唯一的待确认来源」和一行「同类修改反复出现、从成稿看出的模式 → 不记录、不推断」。
   `pending` / `decide` 机制保留（冲突候选与范围含糊仍需要）。
4. story / story-review / story-deslop 三处 SKILL.md 里「重复修正/推断先待确认」
   的句子改为「只记作者明确说的，不从反复修改推断」；docs/architecture 的待确认
   注释同步。回归测试断言五份参考副本与三份 SKILL 不再出现这两个来源名。

## Alternatives considered

**只改文档，工具端继续接受两个来源。** 改动面最小，且 issue 原文只要求「文档不再
引导使用」。不采用是因为产品判断既然是「不观察」，就该由工具兜底：agent 会漂移，
文档说不引导不等于不会写；拒写让决定可执行、可测试。存量兼容靠读端保留枚举即可。

**连 `SOURCES` 枚举一起删。** 最彻底。不采用是因为老库里已有这类条目，删枚举会让
`validate_state` 直接失败，整个工作区的记忆不可用——比多保留两个枚举值糟得多。

**删除 `pending` 状态。** 推断管道没了，待确认清单看似只剩冲突候选。不采用是因为
「作者原话范围含糊但可能稳定」仍需要一个不进 prompt 的暂存位，冲突候选也依赖同一
机制；`decide` 的确认路径是作者掌握决定权的体现。

## Consequences

- 待确认清单只会因作者自己的话而增长，审阅负担与作者表达量成正比，不再被 agent 的
  观察填满。
- 破坏性变更：新写入传旧来源直接失败。仓库内没有任何调用点生成这两个来源；部署到
  用户项目的 skill 副本重跑 `/story-setup` 后脚本与文档同版。记进 CHANGELOG `Changed`。
- 存量条目的 `source` 仍会显示旧值；`作者画像.md` 不渲染 source，作者无感。
- 放弃了「作者从不说、但行为一致」的偏好被自动发现的可能——按本次判断这本来就不该
  由工具替作者决定。
