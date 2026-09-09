# Phase 4：短篇精修打磨

本文件中的 `scripts/` 与 `references/` 路径均相对本 skill 根目录。

Phase 3 写手负责内容覆盖与格式自检，不提前执行完整语义去味；该分工须随写作 prompt 传入。Phase 4 的 Gate 检查由一个执行者完成（下方 narrative-writer 或主会话），保留原检查清单、所选 Gate 与内部三遍法；一致性检查职责不变。最终扫描及 delivery 验收由主会话对最终落盘文件执行，修改后只复核改动和重跑受影响检查，不另开整轮去味。

加载 `references/writing-workflow.md` 中的精修清单完成检查。
重点：开头钩子、情绪曲线、反转铺垫、每句话价值、格式规范、AI 腔。文件模式依次运行 `node scripts/check-ai-patterns.js --check --fail-on=blocking 正文.md`、`node scripts/check-outline-copy.js --outline 小节大纲.md 正文.md`、`node scripts/normalize-punctuation.js 正文.md`、`node scripts/check-degeneration.js --check 正文.md`。blocking 或确属细纲照搬先改正文再复扫；其他提示仅作读感复核，功能性写法可保留。

上述修改全部落盘后，运行 `node scripts/check-delivery-contract.js --json --min-chars {MIN} --max-chars {MAX} --sections {N} {短篇目录}`。exit 0 才可交付；exit 1 只按 `repair_scope` 最小修复并重跑受影响的质量检查与本命令，最多 2 轮；仍失败则报告检查 ID 并停止。exit 2、脚本缺失或不可执行时不得声称交付契约通过。本 verifier 只验用户字数、节数与排版形状，不替代正文质量判断。

#### Agent 调用：narrative-writer（去AI味）+ consistency-checker

精修阶段，如果项目已部署对应 agent，可 spawn：
- `Agent(subagent_type: "narrative-writer", prompt: "项目目录：{dir}\n任务描述：去AI味+格式检查\n检查分工：你负责本次语义去味及原定自检；最终文件扫描由主会话执行，不在子代理内重复\n检查范围：{正文文件}\nstyle_resolution：{与写作一致的本次文风裁决，含全文路径}\n作者偏好：{query 命中的 prose_style/story_design 项}\n删除优先：每条 AI 味项先判能否删除——删后不丢伏笔/钩子/角色/情节/必要信息的直接删，会丢才润色（删除受比例上限与字数下限约束，跌破下限改降AI重写）\n必须检查：检查是否连续使用头皮发紧/眼皮一跳/心口一沉/胃里翻涌等精致戏剧反应，能写普通动作/普通感觉就写普通动作/普通感觉；已有手机/聊天记录/公告/账单/病历/证据截图等信息，保留为角色看到或处理的场内载体，不改成叙述者解释；任务卡点只在角色本来有要办的事且能加重情绪/证据/关系/反转时使用，不为自然感补流程")` — 执行去AI味（7 Gate）和格式合规检查
- `Agent(subagent_type: "consistency-checker", prompt: "项目目录：{dir}\n检查范围：{正文文件}\n检查类型：事实冲突+伏笔断线+角色属性不一致")` — 执行一致性检查

如 agent 不可用，由主线程直接执行。

**正文洁净规则**：
- 自检（字数统计、禁用词扫描、格式检查）是过程动作，结果直接在对话里说明，不落盘成文件
- **绝对不能**把自检记录附加到正文文件末尾
- 正文中不得出现任何 `<!-- 自检 -->` 或类似的检查标记注释

不通过 → 回退补足。
