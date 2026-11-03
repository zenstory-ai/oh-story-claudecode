# agent-calls.md：spawn 子代理的调用方式

> 谁读：主会话派子代理时读：定方向编排后续时刻、交 story-architect 出设定或纲、交 narrative-writer 写或改一章。

下文只给目标角色与 prompt；调用参数按 SKILL 顶部的当前宿主映射，不照搬其他宿主工具字段。

## narrative-writer：写一章

跑 workflow-chapter「写前准备」的组装脚本，`====` 以上就是 prompt（槽位只由脚本定义）；填完所有 `［主会话填］`（核对报告末尾给出个数），其余一字不改，整份原样交给写手。脚本跑不起来时修数据或环境重跑；修不好就由主会话自己写这章，不手拼 prompt。

## story-architect：定设定、出卷纲、出一批细纲（换新上下文）

先跑 `{PYTHON} {skill 根}/scripts/build_architect_brief.py --project {书目录} --task world`（卷纲 `--task volume --volume {N}`，细纲 `--task outline --chapters {A-B}`，一批最多 10 章），只取输出里的任务包路径，不读包的内容。交接前确认作者在对话里定下的方向、偏好和否掉的方案都已写进 `设定/`。

Prompt：`项目目录：{dir}\n任务包：{任务包路径}\n先完整读取任务包，按包里的流程与模板完成；作者已定的方向、设定和要求都在 设定/，对话内容不会传给你\n交付后只回任务包开头要求的几项`

收回后主会话：设定提案拿给作者逐项确认，按作者意见改文件；新卷纲跑 `outline_view.py --check --strict {卷纲路径}`（往旧卷纲追加单元去掉 `--strict`），细纲每章跑 `check-outline-contract.js`；失败把报错原样交回同一 agent 修一次。按 workflow-volume.md / workflow-outline.md 的汇报模板用故事话告诉作者，不转述任务包。

## character-designer：细化某个角色（可选）

定方向、定设定都只走上面的 story-architect 任务包，不另派。作者明确要求细化某个角色时才派：`character-designer`，Prompt：`项目目录：{dir}\n任务类型：角色设定\n查询参数：{要细化的角色与作者的要求}` —— 产出角色卡与语言风格档案，主会话拿给作者确认后写进 `设定/角色/`。

## consistency-checker：写正文后的事实核对

Prompt：`项目目录：{dir}\n检查范围：{本次写作的章节}\n检查类型：事实冲突+伏笔断线+角色属性不一致\n本章新增申报：{申报表原样粘贴，无则写 0}；同时核对正文有无未申报的跨章事实，逐处列原文和细纲出处。只读与新增项和本章出场角色相关的设定、角色卡与追踪条目。冲突按 S1-S4 报出，申报项逐条给出登记/修复/先问作者的建议\n状态：last_committed_chapter={N}，state_revision={R}（取自 tracking_commit.py check）`

## narrative-writer：审查+去AI味

Prompt：`项目目录：{dir}\n任务描述：审查+去AI味\n检查分工：你负责本次检测触发的定点语义修复及原定自检；最终文件扫描由主会话执行\n检查范围：{本次写作的章节}\n文风路径：{设定/文风.md 全文路径，没有写「无」}\n作者偏好：{本章 query 输出的 lines，无写「无」}\n触发本次审查的检测结果：{chapter check 里 blocking 与语义类 advisory 的行号和类别，照录}\n执行边界：按写手资料 deslop-gates「按检测类别或问题限定范围」与三层方法修复；不扩大为完整故事诊断或新增剧情设计；原文有依据的承接与详略可改，无依据的设计缺口只报告\n验收：在完整场景中复读改动，说明原文问题、具体修法和有功能写法的保留理由，不用固定删减率`

## narrative-writer：超字一次净删（compress-once）

Prompt：`项目目录：{dir}\n任务描述：净删压缩\n正文：{正文路径}\n删除区间：{chapter check 给的 remove_to_internal_band}\n只删不增：优先删重复解释、装饰排比、无功能微动作；全部情节点、事实、因果、情绪兑现、钩子都保留，不改写成新句\n文风路径：{设定/文风.md 全文路径}`

## narrative-writer：改写一章（大修）

Prompt：`项目目录：{dir}\n任务描述：改写已写章节\n正文：{正文路径}（原稿已备份）\n细纲：{细纲路径}\n改动范围：{局部：哪几段或哪个场面，要改成什么／整章：按细纲重写}\n作者本轮要求：{作者原话要点}\n不动的部分：{局部修改时其余段落一字不改}\n衔接：{前一章结尾与后一章开头各一两句}\n文风路径：{设定/文风.md 全文路径，没有写「无」}\n作者偏好：{prose_style 查询的 lines，无写「无」}\n不借改稿新增细纲外的剧情；交付后回：改了哪些段、新增申报（无写 0）`

## story-explorer：写前对标召回

召回降档不成立、已部署 story-explorer 时可用（不可用就按 benchmark-recall.md 自己召回）：查询类型 `benchmark_style_load`，传入项目目录、章节号、目标基调/字数和爽点类型；要它返回 `style_profile_path`、`style_profile_summary`、`selected_emotion_module`、`rhythm_reference`、来源路径、匹配章节、锚点片段、`gaps`。`gaps` 的处理见 benchmark-recall.md。
