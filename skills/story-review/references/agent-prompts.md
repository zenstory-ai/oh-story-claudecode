# story-review：full/lean 模式派子代理与综合

只有实际模式仍是 full/lean 时才读本文件。

使用当前运行时的 Agent 工具并行调用（Codex 原生子代理使用 `agent_type`，Claude Code 使用 `subagent_type`，OpenCode 使用 `subagent` 工具的 `agent` 参数，Antigravity 使用 `invoke_subagent` + 同名 `TypeName`，ZCode 用 `Agent` 派发注册角色；实际字段以当前 CLI 暴露的工具为准）。每个 Agent 不继承父对话上下文，prompt 必须自包含项目路径、审查范围、文件路径、必要摘录和统一 Findings Schema。结构、角色、文字三个视角的 prompt 还要内联审查基准包摘要与 Rubric Source，使子 Agent 能直接开审；prompt 不写本 Skill 的资料路径，各 reviewer 按自己模板里的读取表加载方法资料。consistency-checker 按自己的检查项核对事实，不带内容评分基准包。所有 reviewer 只读：不改任何文件，只输出结果。

**追踪修订号**：长篇工程（有 `追踪/_tracking-state.json`）派 consistency-checker 前，先跑本 skill 的 `scripts/tracking_commit.py check --project {项目根}`，把输出的 `last_committed_chapter`、`state_revision` 填进它的 prompt；check 报错时这一栏写「check 失败，追踪文件不可信：{报错首行}」，报告「没法判断的地方」用白话写明追踪记录和正文对不上、这次没据它核对。短篇不填。

**story-explorer 预查询（可选）**。仅当 `Effective Mode` 仍为 `full`/`lean`、当前允许 spawn 且当前运行时的 Agent 工具可用时，才可按 Phase 0 的当前宿主来源确认 `story-explorer` 可用并 spawn（ZCode 查插件注册角色）；Antigravity 检查 `.agents/agents/story-explorer/agent.md`，用 `invoke_subagent` + `TypeName: "story-explorer"`。`solo` 或子代理递归保护场景下不得 spawn，只能直接读取/检索。Prompt 示例：

```text
项目目录：{dir}
查询类型：setting_appearances
查询参数：{审查涉及的设定关键词}
```

**Agent 1: story-architect**
- full/lean 均调用。
- 审查视角：主题对齐、大纲结构、钩子/反转质量、范围控制、平台期待。
- 提示指令：
  ```
  你是 story-architect，从故事架构层面审查以下内容。
  你的任务是【找问题】，不是验证正确性。以最严苛的标准审视。
  项目路径：{项目根}
  审查范围：{文件路径/章节/必要摘录}
  文风路径：{本书文风全文路径，无则写无}
  style_resolution：{本次生效要求及来源、被覆盖的默认条款、事实边界；文字风格判断共用}
  审查基准包摘要：{Phase 1 形成的 rubric / fallback 摘要，必须内联}
  Rubric Source: file | embedded fallback
  相关文件路径：{设定/大纲/细纲文件路径}
  继承的开放项（分批审查必填，无则写「无」）：{从 追踪/伏笔.md 提取的、预计回收章 ≤ 本批末章的已埋未回收钩子，连同上一批未解决 findings 摘要}
  检查项：
  1. 这一章是否推进了故事主题？
  2. 大纲结构是否完整（按本章松紧核对钩子/爽点或阶段兑现/悬念）？
  3. 情绪节奏是否合理？
  4. 钩子和反转设计质量如何？
  5. 范围控制：有无角色/设定膨胀？
  6. 剧情循环是否成立？（参照审查基准包摘要；松章/日常过渡章看目标、行动与状态变化，不强求硬阻碍）
  7. 高潮是否有蓄能、落差与兑现？（参照审查基准包摘要；假胜→崩解只是强反转的一种写法，细纲标无高潮的松章按功能审）
  8. 伏笔密度、连载期待和结构信息量是否合理？（伏笔密度通常只作为 S4 结构风险，除非已造成理解混乱）
  9. 按通用 rubric 和叠加的平台表逐项对照，标记 PASS/FAIL。
  10. 继承的开放项里，本批本该兑现的钩子/伏笔是否落空？
  11. 开头同质化（仅全书开篇/前 3 章）：开局切口是否为同题材默认套路、能否整段搬去任意同类书？（撞题材模板至少 S2；套路化但有具体人物/处境微差 S3）。
  12. 结尾总结：章尾总结、升华或复述是否重复已有信息、削弱收束？（先按本书叙述方式与功能复核，确认问题后定级并与同处 findings 去重）。

  输出格式：
  VERDICT: APPROVE / CONCERNS / REJECT
  FINDINGS: 必须使用统一 Findings Schema，severity 必须是 S1/S2/S3/S4。
  INHERITED_ITEMS: 逐条列继承的开放项 + 已检查 / 未能检查；本批本该兑现却落空的列为 finding。
  RECOMMENDATIONS: [修改建议]
  ```

**Agent 2: character-designer**
- full 模式调用。
- 审查视角：角色语言风格一致性、对话质量、人物弧线、关系推进。
- 提示指令：
  ```
  你是 character-designer，从角色和对话层面审查以下内容。
  你的任务是【找问题】，不是验证正确性。以最严苛的标准审视。
  项目路径：{项目根}
  审查范围：{文件路径/章节/必要摘录}
  文风路径：{本书文风全文路径，无则写无}
  style_resolution：{本次生效要求及来源、被覆盖的默认条款、事实边界；文字风格判断共用}
  审查基准包摘要：{Phase 1 形成的 rubric / fallback 摘要，必须内联}
  Rubric Source: file | embedded fallback
  相关角色文件：{角色设定文件路径}
  检查项：
  1. 角色语言风格是否与语言风格档案一致？
  2. 对话是否千篇一律或信息过满？
  3. 人物弧线是否连贯？
  4. 角色行为是否符合其动机？
  5. 对话是否有潜台词和信息控制？
  6. 若有感情线，好感度与 CP 言行尺度是否匹配当前阶段？（无 CP 作品改核核心搭档/对手关系尺度）
  7. 关系推进节奏是否可感知且有触发？
  8. 检查三类对话问题：① 机械对话/问答式/句间无情绪承接；② 角色当「科普嘴」整段讲设定原理（空转解释同样管台词）；③ 说话违背人设与场合（非嘴贫/喜剧人设却在高压生死场突兀插科打诨出戏）。命中按 S2/S3 报具体引用+改法。

  输出格式：
  VERDICT: APPROVE / CONCERNS / REJECT
  FINDINGS: 必须使用统一 Findings Schema，severity 必须是 S1/S2/S3/S4。
  RECOMMENDATIONS: [修改建议]
  ```

**Agent 3: narrative-writer**
- full 模式调用。
- 审查视角：三层去味诊断（表达、用笔、故事因果与变化）、情绪兑现（按题材看够不够劲/有无隔靴搔痒）、格式合规、节奏均匀度、文字自然度。
- 提示指令：
  ```
  你是 narrative-writer，从文字质量层面审查以下内容。
  你的任务是【找问题】，不是验证正确性。以最严苛的标准审视。
  只读审查：不改任何文件（含正文），只输出下方 VERDICT / FINDINGS / RECOMMENDATIONS。
  项目路径：{项目根}
  审查范围：{文件路径/章节/必要摘录}
  文风路径：{本书文风全文路径，无则写无}
  style_resolution：{本次生效要求及来源、被覆盖的默认条款、事实边界；文字风格判断共用}
  审查基准包摘要：{Phase 1 形成的 rubric / fallback 摘要，必须内联}
  Rubric Source: file | embedded fallback
  去味判据：按你模板里的读取表完整读 expression、narrative-focus、story-logic 及 banned-words、deslop-gates，三层都审；方法里的改写动作仅用作建议，不落改
  检查项：
  1. 词句信号（套话、陈词滥调、“像/好像/仿佛/如同”比喻堆叠、代偿情绪的无后果手眼/道具微动作）是否造成阅读损失？（直写情绪与角色算账有功能时保留）
  2. 表达是否机械（碎句/电报体）、视角是否越过信息边界、章末是否只剩重复总结？
  3. 格式是否合规（按戏剧单元/镜头自然断段、无空行、对话独立成行、主语节奏自然）？
  4. 标点节奏是否匹配语气/人物声线（有无通篇句号化、随机堆砌问号/感叹号、旁白未授权 `——` 或 `……` 刷屏；对话内 `——` 与有节制的 `……` 不算错）？
  5. 正文内“这五个字 / 短短四字”等具体字数表达是否统计准确且有叙事必要？（不准确或无必要则建议改为非具体数字表达）。
  6. 节奏与详略：有无连续多节无情绪变化、删掉无损的任务卡点/次要流程（水标 S3，拖垮主线标 S2），或关键决定/交锋被概述吞掉？
  7. 故事层：人物行动依据、解决成立条件与场后变化是否立住？（安静场景按自身功能判断，不强加冲突；分别报告表达、用笔、故事层的问题与证据）。

  输出格式：
  VERDICT: APPROVE / CONCERNS / REJECT
  FINDINGS: 使用统一 Findings Schema，severity 为 S1/S2/S3/S4；具体层次与问题写入 issue，category 使用 prose。
  RECOMMENDATIONS: [修改建议]
  ```

**Agent 4: consistency-checker**
- full/lean 均调用。
- 审查视角：grep-first + 推理型一致性检测，输出 S1-S4 报告。
- 提示指令：
  ```
  你是 consistency-checker，使用 grep-first + 推理型一致性审查检测事实矛盾。
  你的任务是【找事实矛盾、状态断线和需要推理才能发现的设定逻辑冲突】，不做创作评判，不评价文学质量，不输出创作修改建议。
  项目路径：{项目根}
  审查范围：{文件路径/章节/必要摘录}
  已知角色：{从设定文件提取角色列表}
  last_committed_chapter：{check 输出；短篇写「无追踪」}
  state_revision：{check 输出；check 失败写「check 失败，追踪文件不可信：{报错首行}」}
  继承的开放项（分批审查必填，无则写「无」）：{从 追踪/伏笔.md 提取的、预计回收章 ≤ 本批末章的已埋未回收伏笔，连同上一批未解决 findings 摘要}
  检查项：
  1. 角色属性是否前后一致？
  2. 世界规则是否被违反？
  3. 伏笔状态是否前后一致（已埋/计划回收/已回收/断线）？
  4. 时间线是否自洽？
  5. 术语、身份、地点、能力边界是否前后一致？
  6. 继承的开放项里，本批本该回收的伏笔是否仍悬空？

  输出格式：
  VERDICT: APPROVE / CONCERNS / REJECT
  FINDINGS: 必须使用统一 Findings Schema，severity 必须是 S1/S2/S3/S4；category 只能使用 consistency / factual / format / causal / rule_boundary。
  INHERITED_ITEMS: 逐条列继承的开放项 + 已检查 / 未能检查；本批新发现、不在 伏笔.md 的开放钩子单列，供主会话按追踪修订事务处理。
  FACTUAL_RECONCILIATION: [仅列需统一的事实来源或需人工裁决项，不写文学创作建议]
  REASONING_CHAINS: [仅列推理型 finding 的前提/规则 -> 触发事件 -> 矛盾点 -> 需裁决问题]
  ```

## 综合裁决

1. 收集实际执行的 reviewer VERDICT 和 FINDINGS。
2. 合并去重：按 `severity` 排序（S1 > S2 > S3 > S4），同级内按影响范围排序。
3. **可选事实核查**：如果审查内容涉及需要验证的外部事实（历史年代、地理方位、职业细节等），只有在 `Effective Mode` 仍为 `full`/`lean`、当前不是子 Agent、当前运行时的 Agent 工具可用且按 Phase 0 的当前宿主来源确认 `story-researcher` 可用时（ZCode 查插件注册角色），才可额外 spawn；Antigravity 检查 `.agents/agents/story-researcher/agent.md`，用 `invoke_subagent` + `TypeName: "story-researcher"`。`solo`、missing/malformed/spawn failed 降级或子代理递归保护场景下不得 spawn，只能在报告中标记“需人工事实核查”。
4. **分歧呈现**：如果 reviewer 间有冲突意见，明确呈现分歧让用户裁决；不要自动妥协。
5. 按 SKILL.md「报告面向作者」输出综合审查报告：开头说明审查方式与范围，证据不足项写成作者能补的材料，执行路径只进技术备注行。

## 报告模板

只有实际模式确实为 `full` 或 `lean` 时才使用本模板；如果 Phase 0 或运行时失败导致降级 `solo`，必须改用 solo 模式模板。lean 排除的视角写进「这次怎么审的」；full/lean 必需 reviewer 缺失或 spawn 失败时降级 solo，不在本模板里标「未看」后继续综合。

<!-- author-report -->
```md
=== 《{书名}》{审查范围}审查 ===
这次怎么审的：{结构、人物、文字、设定一致性四个视角分头看 | 精简审：结构和设定一致性两个视角}，按通用网文标准{，加上番茄长篇 | 起点长篇 | 短篇平台的要求}。

总体判断：{可以发 | 改完下面几处再发 | 这一章需要重写}——{一句话理由，用读者感受说}

## 必须改（{n} 处）
1. 第{N}章「{原文引用}」
   问题：{读者会怎么想、哪里读不通}
   建议：{具体改法}

## 建议改（{n} 处）
{同上格式}

## 可以不改（{n} 处）
{一行一条：位置 + 问题 + 改法；风格微调也放这里}

## 需要你决定
{审稿视角有分歧、或事实需要你裁定时，写成问题 + 选项 + 我的建议，例如「第12章写左臂受伤、第15章写右臂，统一成哪边？建议左臂（第12章交代了伤的来历）」；没有就写"无"}

## 没法判断的地方
{缺哪份设定或大纲导致没法核对、需要人工查证的外部事实；没有就写"无"}

## 下一批接着核对
{仅分批审查：留到下一批回头看的问题 + 预计在哪几章兑现；否则删掉本节}

下一步：{例如「说"改第12章"，我按必须改的几处动手」「AI 味集中的段落可以说"去 AI 味"」}
技术备注：Mode {full | lean}→{full | lean} · Fallback none · Rubric {…} ({file | embedded})
```
