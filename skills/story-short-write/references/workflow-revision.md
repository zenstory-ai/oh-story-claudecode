# Phase 4：短篇精修打磨

本文件中的 `scripts/` 与 `references/` 路径均相对本 skill 根目录。

Phase 3 写手只做内容覆盖与格式自检（该分工随写作 prompt 传入）。Phase 4 去味由一个执行者（下方 narrative-writer 或主会话）按 `references/short-deslop.md` 自检清单完成；一致性检查职责不变。S1/S2 与 blocking 必须修，S3 与 advisory 建议看，S4 仅提示。最终扫描与交付验收由主会话对落盘文件执行，修改后只复核改动、重跑受影响检查，不另开整轮去味。

加载 `references/writing-workflow.md` 中的精修清单完成检查。
重点：开头钩子、情绪曲线、反转铺垫、每句话价值、格式规范、AI 腔。文件模式依次运行 `node scripts/check-ai-patterns.js --check --fail-on=blocking 正文.md`、`node scripts/check-outline-copy.js --outline 小节大纲.md 正文.md`、`node scripts/normalize-punctuation.js 正文.md`、`node scripts/check-degeneration.js --check 正文.md`，blocking 或确属细纲照搬先改正文再复扫；功能性写法可保留。

全部落盘后运行 `node scripts/check-delivery-contract.js --json --min-chars {MIN} --max-chars {MAX} --sections {N} {短篇目录}`。exit 0 才可交付；exit 1 只按 `repair_scope` 最小修复并重跑受影响的质量检查与本命令，最多 2 轮；仍失败则停止，按下方交付说明告诉作者哪项没达标、差多少。exit 2、脚本缺失或不可执行时不得声称交付契约通过。它只验字数、节数与排版。

#### Agent 调用：narrative-writer（去AI味）+ consistency-checker

已部署对应 agent 时可 spawn：
- `Agent(subagent_type: "narrative-writer", prompt: "项目目录：{dir}\n任务描述：去AI味+格式检查\n检查分工：你负责本次语义去味及原定自检；最终文件扫描由主会话执行，不在子代理内重复\n检查范围：{正文文件}\nstyle_resolution：{与写作一致的本次文风裁决，含全文路径}\n作者偏好：{query 命中的 prose_style/story_design 项}\n篇幅：短篇\n卖点保留：第一人称审判句、火葬场预告、心死式章尾留，只删中立作者讲解与空洞升华\nAI味等级：{轻度/中度/重度；未分级按轻度}\n删除优先：每条 AI 味项先判能否删除——删后不丢伏笔/钩子/角色/情节/必要信息的直接删，会丢才润色（删除受比例上限与本次字数范围下沿约束，跌破改降AI重写）\n必须检查：检查是否连续使用头皮发紧/眼皮一跳/心口一沉/胃里翻涌等精致戏剧反应，能写普通动作/普通感觉就写普通动作/普通感觉；已有手机/聊天记录/公告/账单/病历/证据截图等信息，保留为角色看到或处理的场内载体，不改成叙述者解释；任务卡点只在角色本来有要办的事且能加重情绪/证据/关系/反转时使用，不为自然感补流程")`
- `Agent(subagent_type: "consistency-checker", prompt: "项目目录：{dir}\n检查范围：{正文文件}\n检查类型：事实冲突+伏笔断线+角色属性不一致")`

agent 不可用时主会话直接执行。

**正文洁净规则**：自检（字数、禁用词、格式）结果只在对话里说明，不落盘成文件，**绝对不能**附到正文末尾，正文不得出现 `<!-- 自检 -->` 等检查标记。

**交付说明（给作者看）**：只用大白话，按三块写：
1. 写了什么：标题、一句话核心钩子或反转、总字数、几节。
2. 要作者拍板的事：每件写成一句问题并附推荐默认（如「结尾要不要再留个小反转？默认不留」）；没有就省略。
3. 下一步可选：精修某段、去 AI 味、换平台改写等。

自查结果只写一句（如「自查过字数、分节和常见 AI 腔，都过了」；没过就说哪项差多少）。不写脚本名、检查 ID、字段名、参数或大纲表格格式。
