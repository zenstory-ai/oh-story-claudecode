# 子代理派发手册（agent-calls）

> 谁读：主会话需要派发 `story-architect` / `narrative-writer` / `character-designer` / `consistency-checker` / `story-explorer` 时读；主会话自己写时不读。

调用参数按 SKILL.md 顶部的当前宿主映射执行，不照搬其他宿主字段名。

---

## 1. story-architect：定设定 / 出卷纲 / 出细纲

先跑组装脚本生成任务包（只取输出路径，不把整份任务包读回主会话）：

- 定设定：`node {skill 根}/scripts/build_architect_brief.js --project {书目录} --task world`
- 出卷纲：`node {skill 根}/scripts/build_architect_brief.js --project {书目录} --task volume --volume {N}`
- 出细纲：`node {skill 根}/scripts/build_architect_brief.js --project {书目录} --task outline --chapters {A-B}`（最多 10 章）

Prompt：
```text
项目目录：{书目录}
任务包：{任务包路径}
先完整读取任务包（已内置对应 flow 手册、白话模板、流派包与本批卷纲取段），严格按包内要求落盘；作者已定的决定在 设定/题材定位.md。
交付后只回：写了哪些文件、核心要点、要作者定的事（无写「无」）。
```

收回后主会话验收：设定交作者逐项确认；卷纲跑 `outline_view.js --check --strict {卷纲路径}`（追加段去掉 `--strict`）并核对 `题材框架` 已补齐；细纲每章跑 `check-outline-contract.js`（硬失败退回同 agent 最多修一次）。用白话故事话向作者汇报。

## 2. narrative-writer：写一章

先跑 `node {skill 根}/scripts/build_writer_prompt.js --project {书目录} --chapter {N} --out`，`====` 以上即为 prompt 骨架（已自动附带匹配到的 `agent-references/genre-styles/{流派}.md` 路径与原文语感切片提示）。补齐全部 `［主会话填］` 后原样派发，不手拼替代。脚本报错先修数据，修不好则由主会话自写。

## 3. narrative-writer：审查去味 / 超字净删 / 改写一章

- **审查去味**（`chapter check` 命中 `review_required` ≥3 条或硬伤修一次未清时）：
  ```text
  项目目录：{书目录}
  任务描述：审查+去AI味
  检查范围：第 {N} 章
  流派包：{匹配到的 agent-references/genre-styles/{流派}.md}
  文风路径：{设定/文风.md 路径，无写「无」}
  作者偏好：{prose_style 查询 lines，无写「无」}
  触发项：{chapter check 报出的 blocking / review_required 行号与类别}
  执行边界：按 flow-drafting.md「正文笔法与竖屏网感」六条真AI味黑名单与三层方法定点修复，不误删正常网文短段、直写情绪与合理反应词；不新增剧情。
  ```
- **超字一次净删（compress-once）**：
  ```text
  项目目录：{书目录}
  任务描述：净删压缩
  正文：{正文路径} ｜ 删除区间：{remove_to_internal_band}
  只删不增：优先删重复解释、空洞铺陈、无关景物与冗余微动作；全部情节点、事实、爽点与章尾钩子完整保留。
  ```
- **大修改写**：
  ```text
  项目目录：{书目录}
  任务描述：改写已写章节
  正文：{正文路径}（原稿已备份） ｜ 细纲：{细纲路径} ｜ 流派包：{匹配到的 agent-references/genre-styles/{流派}.md}
  改动范围：{局部哪几段 / 整章按细纲重写} ｜ 作者本轮要求：{原话要点}
  衔接：{前章结尾与后章开头各一两句} ｜ 文风路径：{路径或「无」}
  不借改稿新增细纲外剧情；交付后回：改了哪些段、新增申报（无写 0）。
  ```

## 4. character-designer / consistency-checker / story-explorer（按需）

- **character-designer**（仅作者明确要求深化单人设时）：`项目目录：{书目录}\n任务类型：角色设定\n对象与要求：{角色与要求}`，确认后写进 `设定/角色/`。
- **consistency-checker**（申报非 `0` 或日更批末一次）：`项目目录：{书目录}\n检查范围：{章节}\n检查类型：事实冲突+伏笔断线+角色属性不一致\n本章新增申报：{申报表或 0}\n状态：last_committed_chapter={N}，state_revision={R}`。只读相关设定与追踪条目，按 S1–S4 报出并给登记/修复/先问作者建议。
- **story-explorer**（召回降档不成立时）：查询 `benchmark_style_load`，传项目目录、章号、目标基调与爽点类型，返回 `style_profile_path`、情绪模块、节奏、匹配章、**原文语感锚点片段**与 `gaps`。
