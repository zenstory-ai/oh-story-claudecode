# 升级指南

## 当前版本

- `setup_skill_version: 1.2.10`
- `agents_version: 29`

`.story-deployed` 缺失任一字段，或 `agents_version` 缺失 / 非整数 / 小于 `29`，都视为待更新部署。直接重新运行 `/story-setup`（Codex 用 `$story-setup`，Antigravity 用 `/skills` 或自然语言点名）；不在运行时逐级兼容历史模板。如项目 `agents_version` 大于 `29`，说明本地 story-setup 比项目旧：先更新 oh-story-claudecode，不得用 v29 降级覆盖。历史版本改动见仓库根目录 `CHANGELOG.md`。

## 升级策略

| 策略 | 适用场景 | 行为 |
|------|----------|------|
| 覆盖部署 | 全新项目 | 写入当前 agents/hooks/rules/reference bundle |
| 合并部署 | 已有项目 | 替换 story-setup 管理文件，合并用户维护文件 |
| 手动更新 | 只更新特定文件 | 仅建议熟悉部署契约的维护者使用 |

推荐始终重新运行 story-setup，让部署器按 owner class 处理文件。

### 自嵌套残留

部署清单的 Source 相对 skill 包、Target 相对项目根，两个基准目录在 skills-only 端会重合；经 `.agents/skills → ../skills` 等 symlink 加载时，路径文字不同也可能指向同一目录。部署器会先按 realpath / samefile 语义拒绝同对象与「目标位于源目录内」的递归复制，再删掉已有的 `agent-references/agent-references/`（可能多层）或 `skills/story-setup/skills/` 残留。

OpenClaw / Reasonix / generic 三条路径的 skill 副本在项目 `skills/` 里，重跑时执行的就是项目里那份，自动清理到不了：先手动删掉上述目录。要让项目里的 skill 文本本身更新，还需要更新 oh-story-claudecode 后，用新包覆盖项目 `skills/` 下这 13 个目录。

## 文件所有权

### story-setup 管理，可替换

这些文件由 story-setup 管理，不含用户自定义内容：
- `.claude/hooks/` — 所有 hook 脚本与 `lib/` 辅助库
- `.claude/agents/` — 所有 agent 定义
- `.claude/rules/` — 所有 path-scoped 规则
- `.claude/skills/story-setup/references/agent-references/` — Agent 参考资料副本
- `.agents/skills/{13 known skills}/`、`.agents/agents/agent-name/agent.md`（7 个已知 `agent-name`）、`.agents/rules/oh-story.md`、`.agents/hooks/{story_antigravity_hook.js,story_hook_core.js}` — Antigravity 项目内真实 Skills、生成 Agents、Always-On Rule 与 Hook runtime；同目录其他用户 Skills/Agents 保留
- `skills/{13 known skills}/` — OpenClaw / Reasonix / generic 的项目 skill 副本，仅覆盖 oh-story 已知名称
- `.zcode/skills/{13 known skills}/`、`.zcode/commands/{13 known commands}.md` — 仅覆盖 oh-story 已知名称
- `.zcode/hooks/story_zcode_hook.js` — ZCode 专用 Hook runner

### 用户与 story-setup 共同维护，只合并管理块

这些文件可能含用户自定义内容：
- `CLAUDE.md` — 按 marker/section 合并，用户独有 section 保留
- `.claude/settings.local.json` — 按 command 识别 story hooks；已存在的受管 command 会迁移到当前模板的 event/matcher/timeout/if（例如 v25 的 Bash 正文 pre-guard），其他用户 hook 与配置保留
- `AGENTS.md` — ZCode/OpenCode/Codex/OpenClaw/generic 按 marker/section 合并
- `.zcode/config.json` — 仅按事件、matcher 和 process args 去重合并 oh-story Hooks，其他字段保留
- `.agents/hooks.json` — 仅替换顶层 `oh-story` named group，其他用户 hook groups 保留

### 用户状态，不覆盖

- `{书名}/正文/`、`正文.md`
- `{书名}/设定/`、`大纲/`、`追踪/`
- `.active-book`

## v29 当前契约

- narrative-writer 模板去掉逐段配额：「展开子事件」改为「展开推进单元」，删除「详写的子事件合计 ≥100-150 字」；情弦理论不再要求「每节至少拨一次」，任务、推理、手艺或等待链可连续展开。三端（Claude / OpenCode / Codex）产物同步。
- 短篇 reference bundle 改按场景功能判断篇幅与节奏：`short-genre-formulas.md` 去掉钩子密度的固定节距、「爽文章节 500-800 字/节」和「打脸密度每 3-5 节一次」；`short-emotional-methods.md` 去掉固定节距的情绪转向与打脸节拍；`short-suspense.md` 不再给每类小节设最低悬念等级；`short-reversal.md` 甜宠线不再要求每节一个甜点。
- `format-and-structure.md` 的小节结构不再设统一最低字数与「8-15 节 / 总字数 ÷ 1000」推算；小节长度与数量服从叙事职责，整篇由用户交付范围约束。

重新部署后需**新开会话**，custom agent 与 hooks 才会重新注册。

## v28 历史契约

- `agent-reference-profiles.md` 成为 story-architect 唯一资料清单；Agent 模板不再复制第二份 inventory。部署守卫会校验 Common / Long / Short 所有权、文件存在性和表外读取。
- 悬念、反转和质量标准改为 profile 专属：long 使用 `long-suspense.md`、`long-reversal.md`、`long-quality.md`，short 使用对应 `short-*` 文件；`agent-quality.md` 只保留跨体裁五维核心。
- 长篇题材资料改为 `long-genre-catalog.md` + `long-genre-mechanics.md`，不再把短篇三幕结构放进 Common；短篇继续使用 `short-genre-formulas.md`。
- `format-and-structure.md` 只服务短篇/import/setup；长篇改用独立 `long-format.md`，不再“只读同一文件的一部分”。
- 跨 Skill 近似副本由 `shared-references.json` 的 `derived_groups` 登记来源与分化原因；目录镜像清单必须覆盖 source tree 全部文件。

重新部署后需**新开会话**，custom agent 与 hooks 才会重新注册。

## v27 历史契约

- story-architect 保持单一 Agent 名称，但每次任务先选择 `long` / `short` reference profile，只加载 common + 当前篇幅资产；无法判定时显式返回 unresolved，不混合两套口径。
- `plot-core-methods.md` 由 story-architect 在卡文、剧情循环、五步高潮、过渡、长线期待和日纲推进场景中条件消费；部署守卫会拒绝没有 Agent 消费链的 reference。
- 长篇 profile 使用 `genre-prose-cards.md` 与 `long-emotional-methods.md`，短篇 profile 使用 `short-genre-formulas.md`、`short-paragraph-hooks.md` 与 `short-emotional-methods.md`，长篇不再继承每节 500–800 字等短篇默认值。
- setup reference bundle 的 profile 文件和语义别名属于 story-setup 管理资产；重新部署会替换旧 bundle，部署后必须新开会话。

重新部署后需**新开会话**，custom agent 与 hooks 才会重新注册。

## v26 历史契约

- 新增 Google Antigravity 2.0 项目部署：13 个 skill 真实复制到 `.agents/skills/`，7 个 Claude agent 真源确定性转换为 `.agents/agents/agent-name/agent.md`（`agent-name` 为实际名称），并安装 `.agents/rules/oh-story.md` Always-On Rule。
- Antigravity Workspace Hooks 只使用官方 `PreToolUse`、`PostToolUse`、`PreInvocation`、`Stop` 事件；写前门禁直接返回 allow/deny，PostToolUse 按协议只返回 `{}`，写后正文 findings 通过 session artifact 交给下一次 PreInvocation，Stop 最多续跑一次。
- `.agents/hooks.json` 按顶层 `oh-story` 管理组原子合并，不覆盖用户其他 hook groups；部署不写 `~/.gemini/`，也不依赖全局 skill 或 symlink 发现。已有 `.agents/skills` symlink 必须先明确确认才迁移为真实目录，helper 从不沿 symlink 写入其目标。
- Antigravity custom agent 通过 `invoke_subagent` + 同名 `TypeName` 调用；运行时无该能力时按既有 solo/direct 规则降级。外部 Hook API 没有 PreCompact/PostCompact，压缩后上下文恢复由 Always-On Rule 强制读取 `追踪/上下文.md`。

重新部署后需**新开 Antigravity conversation**，使 Skills、Rules、Agents 与 Hooks 重新扫描；IDE 与交互式 `agy` 建议分别 smoke test。

- 长篇字数只由 `storyctl.py` 的 `visible_chars_v1` 运行时入口测量。写作中只增加一次纯 `checkpoint`，最终 `chapter check` 同时返回长度与现有 blocking quality；用户带内可提交，`under` 禁止自动补写并由用户接受自然长度或改目标/细纲/放弃，`over` 默认只做一次不新增语义的净删型压缩并复检，仍带外则交由用户决策。tracking 提交后才进入下一章。
- Claude、OpenCode、Codex、ZCode 的正文 Hook 不再各自解析细纲、计算字符数或执行旧 90% 欠账提示；Adapter 只保留正文内容网，避免与 `storyctl` 形成第二套字数口径。
- narrative-writer 与 story-architect 使用显式字数口径，不再填写逐情节点数字配额，也不在缺少目标时回退 3000 字；后半段只能完成尚未写的批准情节点，完成即停，不为字数新增独立剧情。
- 使用 `story-import` 导入时按 `storyctl wordcount measure` 记录已写章节的当前口径长度；无法执行 Python 3/CLI 时明确停止，不用模型估算代替。
- 工作区新增 `.story/作者记忆/`：只有带原话证据、经过确认的稳定偏好才进入作者画像；候选、冲突替代和撤回保留审计记录。它与单本小说追踪隔离，当前指令、本书设定和硬门禁优先。
- story-explorer 遇到已登记但主产物缺失的对标时 fail-closed，不再静默换用另一本；narrative-writer、story-architect、character-designer 的 reference 表改为按任务条件读取，避免列出但不触发。
- 新建细纲的情节点使用五列表格记录内容、功能、人物、约束与落点；不再把逐点字数配额当正文编排指令。存量细纲仍可继续日更，只有新建、补建或改纲时采用新格式。
- 部署器在复制前按 realpath / samefile 拦截源目标同对象和目标嵌入源目录，并清理已知嵌套残留；OpenClaw / Reasonix / generic 的项目内旧副本需按本页“自嵌套残留”先手动处理。

重新部署后需**新开会话**，custom agent 与 hooks 才会重新注册。

## v25 历史契约

- Claude Code 的正文前置守卫现在也注册到 Bash：常见的重定向、`tee`、`touch`、`cp`、`mv`、`install` 写入正文时复用共享 JS 核识别目标并执行大纲/追踪门；只读命令里的引号示例与 heredoc 正文提及不拦，并按 hook `cwd` 解析相对路径。该面是**静态 best-effort 识别，不是 shell 沙箱**：环境变量间接路径、运行时生成命令与未列出的任意写文件程序无法可靠静态判定；这类写入应改用 Write/Edit。Bash 命令面依赖 node，node/共享核异常时显式告警后 fail-open；Write/Edit/MultiEdit 的纯 bash 兜底不受影响。
- Codex Python 与共享 JS 的书目录发现统一限制为项目下 4 层，并剪枝隐藏目录、`node_modules`，避免 SessionStart/Stop 无界扫描和跨端发现范围漂移。
- narrative-writer 与部署 reference 增加“普通名词不用引号强调”的 Gate B；合法对话、直接引用、书名/代号和场内系统载体原文保留。
- narrative-writer 的工具白名单加入 `Bash`：字数统计、句长分布、`check-ai-patterns.js` 与 `check-outline-copy.js` 复扫都要确定性数值，缺工具时这几条规则整条空转。字数与句长必须报实测值，探测不到 Python / node 时如实声明“未完成机器验证”，不得声称已统计或已运行脚本。
- narrative-writer 的细纲消费规则拆成两条并列：内容层（每项独立落地、不许漏、不许两项并一句）与形状层（落地位置、顺序、断段自定，可打散重排，不要一项一段平推）。形状半边同步进 `story-long-write` 的 spawn 清单。
- 细纲「情节细化」新增**复沓锚句**字段：必须一字不差进正文的原话逐行列出并注明落点，没有写“无”。存量细纲缺该字段时按“无锚句”处理，行为与此前一致，不必回头补。

重新部署后需**新开会话**，custom agent 与 hooks 才会重新注册。

## v24 当前契约

- `.claude/rules/story-narrative.md` 删掉「禁止 AI 腔」红线块。该块只在 `拆文库/` `对标/` `设定/` 三个 path 下加载，正文目录根本不命中，五条规则也已由 narrative-writer 的 7 Gate / 禁止事项与 `check-ai-patterns.js` 的 blocking 规则覆盖。
- `.claude/rules/story-format.md` 的对话标签规则从「禁止「他说」「她道」」改为「避免对话标签机械化」：高频或公式化标签用动作/上下文替代，普通「说」低频使用可保留。此前该文件是全仓唯一把普通「说」判为违规的地方，与 `format-and-structure.md` 等 11 处口径冲突，且它正好在 `正文/` path 上加载。
- `.claude/agents/narrative-writer.md` 精简约 19%：删除与 7 Gate / 禁止事项重复的审查清单（story-review spawn 时会内联完整 rubric）、正文写作阶段的具体字数表达校验（移到审查侧）、以及 `……`/`——`、段间空行、章节元信息正则的重复陈述。写作规则本身未放宽，Gate A-G 与禁止事项口径不变。
- `.claude/hooks/guard-outline-before-prose.sh` 补上追踪检查点门，与 OpenCode / ZCode / Codex 同序：追踪状态缺失、schema 不是 4、续写状态卡修订号与 state 不一致、首建新章时上一章事务未提交，都拦下写正文。细纲/大纲门只在首建时判，追踪门对首建与续写都判。判定经 `.claude/hooks/story_hook_cli.js` 的 `tracking-checkpoint` 子命令调共享核，四端一份实现；需要解析 JSON，故 node 不在场时这道门放行（大纲/细纲门仍是纯 bash，无 node 也拦得住）。
  - **对已部署项目的影响**：v0.7.3 起就该迁移的旧追踪项目，此前在 Claude Code 上还能继续写，现在会被拦下。按提示走 `/story-import` 的「旧追踪项目迁移」重建 `追踪/` 即可，不必重跑全书拆解。

重新部署后需**新开会话**，custom agent 才会重新注册。

## v23 当前契约

- `story-import` 只把作者已有小说重建为写作工程：`拆文库/{导入书名}/` 迁移到正文/设定/大纲/追踪，不再自动登记成主/副对标，也不再复制到项目 `对标/`。只有用户明确选择、且来源为独立 `拆文库/{对标书名}/` 的外部作品才同步到 `对标/{对标书名}/`。
- 无外部对标时只跳过对标模块、节奏和文风召回；项目题材卡仍从本书题材信息生成，不再被对标分支误伤。对标主产物缺失继续 fail-fast，只有单个可选模块卡未命中时才局部跳过。
- 所有可能 spawn 项目 agent 的 Skill 都先读取 `.story-deployed.agents_version`：与 v23 不一致时**照常 spawn**，只在报告里提示版本不匹配、建议重跑 `/story-setup` 并新开会话。版本不匹配不阻断并行——bump 常常源于别的部署物变化而 agent 模板未动。真正降级 solo/direct 的信号是 agent 文件缺失或运行时不暴露 custom agent。
- 写作与导入只接受当前拆文产物：`剧情/情绪模块.md` 与 `剧情/节奏.md` 缺失时 fail-fast，并给出重跑 Stage 3+ / 重新导入的修复动作。
- 新建、补建、改纲的细纲只接受完整章节蓝图：缺少阶段位置、结构公式、禁止提前释放、内容概括、情节安排、人物关系、情节细化或结尾设定时，先补齐再写。旧版细纲缺这些字段不阻塞日更，回退消费旧字段（核心事件、情节点序列、目标情绪、章首/章尾钩子、字数目标）。
- 细纲字段是本章「要发生什么」的内容规格，不规定正文形状：各字段都要在正文里兑现，但正文可合并、穿插、重排情节点，不按条目顺序一条一段平推。细纲「结尾 / 结尾设定」写本章最后落在什么动作、画面或台词上，不写状态判词。
- 每个 agent adapter 只读取本目标的 canonical reference 路径：Claude `.claude/skills/`、OpenCode `skills/`、Codex `.codex/skills/`。
- `_progress.md` 恢复只接受 `schema_version: 2` 与章节边界表，不再执行隐式历史迁移。
- Codex hooks 升级使用稳定管理身份替换注册；会先移除旧直调 Python 命令与已有 launcher 命令，再写入当前 6 个注册，不会双重执行。
- 定制 hook 如果调用了已删除的 `discover_book_dir()`，请改为 `discover_active_book()`。当前版不再保留该兼容别名。
- `拆文库/` 的「未完成拆文」提醒按 `_progress.md` 的「最终状态」取值过滤：`completed` / `completed_with_errors` 不计入，其余取值与字段缺失、空文件、不可读一律按未完成上报。判定收在 `lib/common.sh` 的 `discover_incomplete_analyses()`。
- 被动版本更新提醒按 24h 节流提示本身；取不到 GitHub 时写入负缓存，同一窗口内不重复请求。

## 升级步骤

1. 在项目根目录重新运行 story-setup。
2. 确认 `.story-deployed` 写入 `agents_version: 29` 与 `setup_skill_version: 1.2.10`。
3. 确认目标 CLI 的 agents、hooks/rules 和 reference bundle 都通过安装验证。
4. 新开会话，使 custom agents 与 hooks 按当前文件重新注册。
5. **长篇在写项目必做**：检查每本书的 `追踪/_tracking-state.json` 是否存在。不存在就是旧追踪结构，按下方「追踪模型迁移」重建，否则写下一章会被拦。
6. 若已有拆文库或细纲不满足当前契约，先重新拆解/导入或补齐细纲，再继续写作。

## 导入项目的自对标清理（v23）

旧版 `story-import` 可能把作者自己的导入书误建成 `对标/{当前书名}/`，甚至把本书设定登记成“主对标”。升级不会自动删除用户文件，按以下边界人工核对：

1. 保留 `拆文库/{导入书名}/`；它是本书导入分析和重建工程的数据源，不是错误目录。
2. 以项目根 `设定/` 为本书正式设定。若 `对标/{当前书名}/` 的内容确认只是从本书 `设定/` 或 `拆文库/{导入书名}/` 复制而来，且没有人工补充，再删除这个误建目录。
3. 清理 `设定/题材定位.md` 中把当前书登记为主/副对标的字段；真实外部对标登记不动。
4. 若某个 `对标/{外部书名}/` 目录名看似外部作品，但内容实际来自当前书，删除这份错误视图，再从真正的 `拆文库/{对标书名}/` 重新同步；不要改名冒充修复。
5. 重新运行 `/story-setup`（Codex 用 `$story-setup`）并新开会话，使 v23 的 agent 模板生效；在此之前 spawn 照常工作，只会多一条版本不匹配提示。

## 追踪模型迁移（v0.7.2 及更早的长篇项目必读）

长篇追踪从「模型自由写多个 Markdown」改成 **`追踪/_tracking-state.json` 单一结构化权威 + `scripts/tracking_commit.py` 事务写入**。所有 Markdown（续写状态卡、逐章记录、角色快照、伏笔表、时间线双视图）都是由工具整份生成的派生视图，不再手写。

判断与后果：

| 情况 | 表现 |
|------|------|
| `追踪/_tracking-state.json` 存在且 `check` 通过 | 正常，无需处理 |
| 缺 `_tracking-state.json` 但已有正文 | 日更停止；OpenCode / ZCode / Codex 上写正文被 hook 直接拦截 |
| 存在但派生视图被手改 | `check` 报 `derived view differs from _tracking-state.json` |

迁移**不需要重跑全书拆解**：正文、`设定/`、`大纲/`、`拆文库/` 都不受影响，只重建 `追踪/`。执行 `/story-import` 的「旧追踪项目迁移」——数出最后完整章号 `N`，从旧追踪文件与最近几章正文重建当前状态，构造 `last_chapter=N` 的初始化事务跑 `tracking_commit.py init`。旧追踪结构会被按原样整体移入 `追踪/_旧追踪存档/`，不删除、不参与解析。

退役结构：`_tracking-meta.json`、`时间线/事件库.json` 及更早追踪文件不再被解析，`commit` 与 `check` 遇到会直接拒绝。

日常写作的两条硬约束：所有追踪写入都走 `tracking_commit.py`；派生视图被改动后用该章的 `mode=revision` 事务整份重建，不手改。
