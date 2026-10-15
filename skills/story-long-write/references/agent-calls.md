# agent-calls.md：spawn 子代理的调用方式

只在要 spawn 对应 agent 时读；主会话自己写正文、自己排纲时不读。调用时机见各流程；下列 prompt 列明必传内容。Antigravity 用 `invoke_subagent` + 同名 `TypeName`。

## narrative-writer：写一章

全章细纲交给写手统筹编排，默认同一 session 按前后两组交付：按实际叙述顺序在自然转场或因果停顿处分组，不在一句对话或同一动作中间截断，可交错情节点但不增删批准内容、不拆逐点字数配额；写手先把前组写到工作目录 `前组.md`，主会话只调用一次 `storyctl.py wordcount checkpoint --file {segment} --project {项目根} --chapter {N}`，把 `actual / remaining_user_range` 连同后组交回同一写手，两组按原文拼接，不回改前组追字数。作者明确要求一次成文时执行安排填「全章」，直接落盘，不跑 checkpoint。

组装脚本的输出（`====` 以上）就是 prompt 骨架。**主会话填九槽**（搜 `［主会话填］`）：执行安排 ／ 本章意图 ／ 作者本轮要求 ／ 本章技法（只填类别）／ 本节速记 ／ 涉及角色（列名字）／ `genre_prose_card` ／ 必读设定 ／ `style_resolution`；外加脚本标出的条件槽（降档不成立的情绪与节奏；限定范围记忆适用时补查）。`author_preferences` 由脚本注入，只作低优先级倾向。空槽以外一字不改，整份照抄进 Agent prompt。比喻语义复核照抄：共享当场可见属性、带出人物或场景、且不单装饰声音外貌情绪才留，否则改成动作、物件、声音或后果；服从文风与 style_resolution。脚本**跑不起来**时读 [writer-prompt-fallback.md](writer-prompt-fallback.md) 手动组装，报 `Fallback: build_writer_prompt -> 手动组装`。

## story-architect：定设定、出卷纲、出一批细纲（换新上下文）

先跑 `{PYTHON} {skill 根}/scripts/build_architect_brief.py --project {书目录} --task world`（卷纲 `--task volume --volume {N}`，细纲 `--task outline --chapters {A-B}`，一批最多 10 章），只取输出里的任务包路径，不读包的内容。交接前确认作者在对话里定下的方向、偏好和否掉的方案都已写进 `设定/`。

Prompt：`项目目录：{dir}\n任务包：{任务包路径}\n先完整读取任务包，按包里的流程与模板完成；作者已定的方向、设定和要求都在 设定/，对话内容不会传给你\n交付后只回任务包开头要求的几项`

收回后主会话：设定提案拿给作者逐项确认，按作者意见改文件；新卷纲跑 `outline_view.py --check --strict {卷纲路径}`（往旧卷纲追加单元去掉 `--strict`），细纲每章跑 `check-outline-contract.js`；失败把报错原样交回同一 agent 修一次。按 workflow-volume.md / workflow-outline.md 的汇报模板用故事话告诉作者，不转述任务包。

## story-architect、character-designer：题材定位与角色细化（可选）

定方向以和作者来回讨论为主，默认主会话自己做；复杂世界观、多线结构、强反转工程或作者明确要求时才派：
- `Agent(subagent_type: "story-architect", prompt: "项目目录：{dir}\n任务类型：题材定位\n查询参数：{作者选定的方向与对标信息}")`
- `Agent(subagent_type: "character-designer", prompt: "项目目录：{dir}\n任务类型：角色设定\n查询参数：{主角设定信息}")` — 辅助角色设定和语言风格档案

## consistency-checker：写正文后的事实核对

Prompt：`项目目录：{dir}\n检查范围：{本次写作的章节}\n检查类型：事实冲突+伏笔断线+角色属性不一致\n本章新增申报：{申报表原样粘贴，无则写 0}；同时核对正文有无未申报的跨章事实，逐处列原文和细纲出处。只读与新增项和本章出场角色相关的设定、角色卡与追踪条目。冲突按 S1-S4 报出，申报项逐条给出登记/修复/先问作者的建议\n状态：last_committed_chapter={N}，state_revision={R}（取自 tracking_commit.py check）`

## narrative-writer：审查+去AI味

Prompt：`项目目录：{dir}\n任务描述：审查+去AI味\n检查分工：你负责语义去味及原定自检；最终文件扫描由主会话执行\n检查范围：{本次写作的章节}\n文风路径：{设定/文风.md 全文路径}\nstyle_resolution：{与写作一致的裁决}\n作者偏好：{本章 query 输出的 lines，无写「无」}\n触发本次审查的检测结果：{chapter check 里 blocking 与语义类 advisory 的行号和类别，原样粘贴}\n所选 Gate：{按检测类别选，如 B 句式、G 解释腔；类别不明写 A-G}\n删除优先：每条 AI 味项先判能否删除，删后不丢伏笔/钩子/角色/情节/必要信息的直接删，会丢才润色\n按你的 7 Gate 与对话自检执行，台词里的工整否定不因脚本豁免而跳过\n删除测试：按 deslop-gates.md「写法抽查」执行，报告列候选数/删改数/保留理由`

## narrative-writer：超字一次净删（compress-once）

Prompt：`项目目录：{dir}\n任务描述：净删压缩\n正文：{正文路径}\n删除区间：{chapter check 给的 remove_to_internal_band}\n只删不增：优先删重复解释、装饰排比、无功能微动作；全部情节点、事实、因果、情绪兑现、钩子都保留，不改写成新句\n文风路径：{设定/文风.md 全文路径}`

## narrative-writer：改写一章（大修）

Prompt：`项目目录：{dir}\n任务描述：改写已写章节\n正文：{正文路径}（原稿已备份）\n细纲：{细纲路径}\n改动范围：{局部：哪几段或哪个场面，要改成什么／整章：按细纲重写}\n作者本轮要求：{作者原话要点}\n不动的部分：{局部修改时其余段落一字不改}\n衔接：{前一章结尾与后一章开头各一两句}\n文风路径：{设定/文风.md 全文路径}\nstyle_resolution：{与写作一致的裁决}\n作者偏好：{prose_style 查询的 lines，无写「无」}\n不借改稿新增细纲外的剧情；交付后回：改了哪些段、新增申报（无写 0）`

## story-explorer：写前对标召回

召回降档不成立、项目已部署 story-explorer 时，可一次召回文风/模块材料（不可用就按 benchmark-recall.md 自己召回）：
- 查询类型：`benchmark_style_load`；传入项目目录、章节号、目标基调/字数和爽点类型。
- 需要返回：`style_profile_path`、`style_profile_summary`、`selected_emotion_module`、`rhythm_reference`、来源路径、匹配章节、锚点片段、`gaps`。
- `gaps` 分流：`no_benchmark` → `custom_style` 为真则用 `设定/文风.md` 写、情绪/节奏取本书内部材料，否则标「无对标参考」；`missing_primary_contract` → 按 `repair_action` 修复（重跑拆文或导入）并停止生成，自定义文风不豁免；`benchmark_book_missing` → 停止核对登记名，不换书；`conflict` / `module_rhythm_conflict` → 意图里说明冲突并按情绪模块/节奏的权威执行；profile_missing → custom_style 为真则用本书文风继续，否则停止；`profile_degenerate` → 有本书文风就用，没有回默认；`tone_match_failed` → 只用整书文风。其余字段原样进 writer prompt，`gaps` 原值保留在写前准备记录里。
- 主会话另行直接读 `设定/文风.md`：含实质内容时作为本书风格基准；但不豁免情绪/节奏缺失。
