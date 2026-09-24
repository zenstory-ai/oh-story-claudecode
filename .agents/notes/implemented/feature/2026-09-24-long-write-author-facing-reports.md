# Agent Note: 长篇写作的作者汇报改说白话，模板加静态守卫

Status: implemented
Date: 2026-09-24

## Problem

真机端到端会话（Claude Code，部署 hooks）里，story-long-write 给作者的汇报和提问大量
夹带工程词，作者看不懂也无从选择：

- 字数不在范围时直接给出 `accept-current-length / revise-outline-or-target / discard`
  三个 storyctl 动作名，外加 `visible_chars_v1`、`borderline`、`within_user_band`、「内带 ±12%」；
- 一致性结论报「S3×3 + S4×5」，规划汇报出现「Constraint Lock」「安全七检⑥⑦」「供给自查」
  「契约检查器 required-fields plotpoint-table」；
- 状态说明里出现 `context.long_term_constraints`、`last_committed_chapter`、`state_revision`、
  「二档收编」，以及不带含义的 F0xx/E0xx/L1-03 编号。

根因在源头：workflow 文件规定汇报格式时直接写了这些内部名字（例如步骤 8「展示
`accept-current-length / revise-outline-or-target / discard`」、日更批末「汇报章数、字数、
漂移、供给反馈」、大修「报告 `internal_pass / borderline / …`」），模型照抄。规划、改细纲、
单章完成、停下时则根本没有汇报模板，模型把内部核对过程原样倒给作者。

同一批会话还暴露两处让作者困惑的规则矛盾：

- 「继续写」：SKILL.md 场景表和 workflow-daily 把它当日更触发词，「规划续接」又说
  「继续/继续写/按这个来」不扩大范围。作者刚规划完一卷说「继续写」，得到一张 6 项选项表。
- 追踪初始化时机：workflow-setup 说「无正文无 state 时任何一批细纲落盘后都初始化」，
  project-files 说仅规划不生成追踪，真机里改一份细纲也没初始化。

## Decision

1. SKILL.md 新增「面向作者的汇报」通则，所有流程的汇报、提问、停下说明只讲三件事：写了/改了
   什么（章名、发生了什么）；要作者定的事（一句白话问题＋白话选项＋推荐默认）；下一步。禁止
   脚本/字段/参数名、状态码、内部清单名；编号必带故事标签（「伏笔 F057（那封信的去处）」）；
   检查结果一句白话带过；回执、Notice、Fallback 等机器行放末尾一行；子 agent 返回的术语由主
   会话翻译。放在入口是因为它约束每个流程，只有 SKILL.md 每次都加载。
2. 每个流程的汇报写成 `<!-- author-report -->` 标记的 ```` ```md ```` 围栏模板，放在该流程本来就要完整读取的
   workflow 文件里：
   - workflow-setup：规划交付后（开书、大纲、卷纲、细纲、补纲、改细纲），C 级缺口与设定互相
     冲突作为「要你定的事」问；对标书缺情绪/节奏分析时的白话停下说明。
   - workflow-chapter「向作者汇报」：写完一章、字数不在范围、新增内容要拍板（三档第③档）、
     停下。字数三选项改成「就按现在的长度收下（推荐）」「我改细纲或字数目标，再重写这章」
     「这章不要了」，模板外一行写明它们分别映射 `chapter accept-current-length`、回步骤 8、删正文
     与工作目录不提交。一致性修复只以「发现一处前后不一：…，已按前文改正」一句出现。
   - workflow-daily：批末汇报模板替代「章数、字数、漂移、供给反馈」；分流、漂移、盘点标明是
     内部核对。
   - workflow-revision：改完汇报模板；字数对比说「约 X 字，比原来多/少 Y 字」，不报状态码。
3. 守卫：`scripts/static-check.py` 对所有 skill 里 `author-report` 标记的围栏逐行扫工程词，规则调用
   `scripts/check-author-reports.py` 的 `check_block`（snake_case、kebab-case、脚本/数据文件名、
   命令行参数、S1-S4、不带故事标签的编号、commit/state/revision/Fallback 等英文术语、安全七检/
   供给自查/内带/用户带/收编/二档/三档等内部清单名），命中即 FAIL。`scripts/test-static-check.py` 用夹具证明块内命中报错、块外同词不报，
   并对真实仓库断言四个 workflow 文件各自至少有应有数量的模板且全部干净，防守卫空转。
4. 「继续写」一条规则：「继续」「按这个来」「确认方案」只续当前范围；「继续写」「接着写」指
   正文——下一章已有细纲时按写正文处理，但上一轮在规划就只问一句「要接着写第N章正文吗？」
   （默认是），不列选项表；缺细纲则问是否先补这一章细纲。workflow-daily 适用条件同步。
5. 追踪只在首次进入正文时初始化，规划阶段（开书、大纲、细纲、补纲）一律不建 `追踪/`；
   workflow-setup 两处「细纲后初始化」改掉，project-files 产物表改为「首次写正文前初始化」。
   workflow-chapter 本来就处理缺 state，无需改。
6. 顺手修两处失效引用：SKILL.md 指向的节名改为 workflow-chapter 实际的「字数测量权威」「质量
   检查」；workflow-daily 细纲补建指向 workflow-setup「Phase 3」而非 SKILL.md。

agent 模板（narrative-writer、consistency-checker）的返回对象是主会话，保留术语，不改。

## Alternatives considered

- **只在 SKILL.md 加一条通则，不写模板**：最省预算，改动最小。但原问题正是 workflow 里的
  汇报格式本身写着工程词，通则压不过更具体的格式指令；规划、单章完成等时机没有模板，模型
  自由发挥时最容易把内部核对原样倒出。所以通则和模板都要。
- **把所有模板集中到一个新 reference（如 author-reports.md）**：单点维护、不重复。但它得进
  Reference Gate 成为又一个必读文件，而且汇报发生在各流程末尾，模型跳读新文件的概率高；各
  流程模板内容本就不同，放在已完整读取的 workflow 里更可靠。
- **守卫扫整份 workflow 文件而不是只扫围栏**：覆盖面更大。但 workflow 正文是给模型的内部
  指令，必须写脚本名和字段名；全文扫描只会逼出大量豁免。用信息串标出「这段是说给作者的」
  是最小可验证面。
- **「继续写」一律直接写正文，不确认**：最少打扰。但规划刚结束时作者可能只是想继续规划下
  一段；一句带默认值的确认成本很低，而误写一章正文要回滚追踪。
- **追踪在首批细纲后初始化（保留原规则）**：开写第 1 章时少一步。但规划期不该留下事实状态，
  与 project-files、实际行为都矛盾；workflow-chapter 在进入正文时已处理缺 state，统一到这一处
  规则最少。

## Consequences

- 收益：作者看到的是故事层的话和可以直接回答的问题；字数、拍板、停下三类决策有固定问法
  和推荐默认；新写的模板一旦混进工程词，静态检查直接红。
- 收益：「继续写」在规划后不再弹选项表；追踪初始化只剩一条规则。
- 代价：热路径预算显式调高——SKILL.md 6900→7350、workflow-chapter 12300→13400、
  workflow-daily 11890→12250、workflow-setup 14700→14850、workflow-revision 2990→3100、
  project-files 4700→4800，相关路径预算同步上调（见 `scripts/doc-budget.json` 各条 why）。
  每个用户每次会话都为这几百字付费，换来的是汇报可读；模板只写骨架，不写示例长文。
- 代价：守卫只覆盖 `author-report` 标记的围栏，模板外的临场汇报仍靠通则约束；词表是黑名单，新
  出现的工程词要补进 `AUTHOR_REPORT_JARGON`。
