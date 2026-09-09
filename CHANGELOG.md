# Changelog

All notable changes to this project will be documented in this file.

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

自 `v0.7.7` 起采用组织统一格式：版本标题写作 `## [X.Y.Z] - YYYY-MM-DD` 并在文末维护
compare 链接；小节名使用 Keep a Changelog 的六个英文类别（`Added` / `Changed` /
`Deprecated` / `Removed` / `Fixed` / `Security`），正文为中文。收紧到会拒绝旧输入的改动
记入 `Changed`。`v0.7.6` 及更早的小节保持原样。

## [Unreleased]

## [0.7.10] - 2026-09-09

> 本版 `agents_version: 30`（v0.7.9 为 29），`setup_skill_version: 1.2.10`。更新技能包后，在写作项目根重新运行 `/story-setup`（Codex 用 `$story-setup`），再新开会话，加载新版写手、检查规则和参考文件。此前使用 main v30 的项目也需重新部署。

### Added

- 长篇新增排纲供给自查、A/B/C 创作授权与写手自由区（#394）：批次开始前盘点角色、能力和场景材料，细纲明确得失、叙事疏密与允许展开的空间。
- 长篇新增写手 prompt 组装器与卷纲取段器（#395）：固定材料由脚本组装，主会话填写判断槽；按当前单元读取卷纲，同时保留全局约束与故事线。
- 短篇新增写前交付参数预检（#402）：生成正文前核对总字数、节数与用户指定的逐节下限是否能同时满足。
- `story-setup check` 新增只读环境检查，报告技能、agent、hook 和部署状态（#405、#408）。
- Dashboard 记住浏览位置与展开状态，并显示文稿行号（#391）。

### Changed

- 长篇新增物按后续义务分档：现场材料直接写，可复用事实申报收编，影响主线和既有结果的变更交作者裁定；写手交付实际时空表，默认保留分组写作的一次字数 checkpoint（#395）。
- 长短篇按需加载目录、初始化协议、对标召回与参考索引；去味规则集中维护，写手、语义审查者和最终扫描各有明确职责（#401、#415）。
- Claude Code / ZCode 市场统一为一个 `oh-story` 插件，包含全部 13 个 Skills（#393）。旧拆分插件用户按 [升级指南](skills/story-setup/UPGRADING.md#插件打包身份迁移v079-同版本修复) 迁移。

### Fixed

- 统一当前请求、本书文风、作者记忆、对标与通用参考的逐维优先级，写作、去味和审稿使用同一文风裁决（#412）。
- 修复文风覆盖导致整份 reference 停读的问题，保留技法和检查资料的任务读取条件（#415）。
- 去味仅执行指定 Gate；保留有功能的情绪直写与身体细节，撤销短篇身体词次数上限，避免为词频改坏“手机”“抬手”等正常表达（#403、#406、#415）。
- 细纲缺失或不可读时明确报告错误，排除细纲完成记录造成的照搬误报，并补充正文中的模型拒绝语与工程词检测（#398、#404）。
- 修复跨 CLI agent 权限映射、OpenCode 命令参数传递、OpenCode/ZCode 的 setup 检查路由，以及 Antigravity Windows hook 路径引号（#399、#411、#408、#396）。
- 分离运行脚本与共享参考的维护归属，保持部署副本一致。

## [0.7.9] - 2026-08-30

> 本版改了 narrative-writer 模板与短篇 reference bundle，`agents_version` 升到 29。升级后必须在写作项目根重新运行 `/story-setup` 并新开会话，否则拿到的仍是旧 agent 与旧参考文件。

### Added

- 新增细纲结构验收 `check-outline-contract.js`（#382）：新建 / 补建细纲落盘后运行 `node scripts/check-outline-contract.js --json --project {书目录} --chapter {N}`，只判必需字段、四个小节、五段式、四列情节点表和字数目标口径是否在场，不判内容好坏。失败返回具名检查 ID 与最小 `repair_scope`，最多两轮定向补齐；既有项目的旧细纲不因此阻断写正文。

### Changed

- 短篇改按场景功能分配篇幅与节奏（#384）：移除逐节最低字数（含题材速查表的「爽文章节 500-800 字/节」）、每节 3-5 个子事件、对白占比与话轮数、固定冲突间隔、固定钩子节距、固定高潮位置和题材包「每节必有」等机械配额，改用可阅文验证的标准——本场是否改变风险、信息、关系、资源、决定、行动或读者理解。任务、证据、手艺、等待、空间压力和无对白场景均可成立。整篇长度仍由用户交付范围与 `check-delivery-contract.js` 约束。
  *升级*：Phase 2 小节大纲三列改名为 `情节推进` / `场景形态` / `对白作用`。旧表头继续兼容，新建项目按新列名；旧项目不需要改表。
- 导语作为正文第一场（#384）：宅斗宫斗、民俗怪谈、沙雕脑洞的第 1 章从导语最后一拍的后果、选择或新行动继续，不重新搭景、不重说关键台词、不重演同一事件。
- 细纲的 `目标情绪` 与 `主角目标/关键选择` 不再接受 `[待补充]`（#383）：隔离实验显示只补这两个字段就能复现补齐全部字段的正文收益，补满其余字段与只补这两个不可区分。其余字段未知时仍写 `[待补充]`。
- 短篇拆文的节奏与对白指标改为描述性（#384）：情节节点不再按全文字数分档设目标数量，情感曲线不再要求每节至少一个节点，对话占比与条数只作同题材、同平台样本的观察数据，不设跨题材通过阈值；判断回到具体节点、状态变化和后果。

### Fixed

- 修 Codex CLI 0.151.0 下 `codex` E2E 误报仓库 skill 未被发现：0.151.0 起 `debug prompt-input` 改用 `Skill roots` 别名表加 `rN/<skill>/SKILL.md` 短路径渲染，测试只搜绝对路径。现在断言前先把别名展开回绝对路径；旧版 CLI 输出绝对路径且无该表，行为不变。

## [0.7.8] - 2026-08-28

> 升级后必须在写作项目根重新运行 `/story-setup` 并新开会话，否则拿到的仍是旧 agent 与旧参考文件名。本版把长短篇的参考资料按消费者拆分改名，并给长篇写正文、短篇构思与交付加了会阻断的门禁（见 Changed），补丁号不代表可以无脑升级。

### Added

- 新增 Google Antigravity 项目部署（#377）：13 个 Skills、7 个 custom agent、Always-On Rule 与 workspace Hooks 写入项目 `.agents/`；部署器不读写 `~/.gemini/`，`.agents/hooks.json` 只替换 `oh-story` 管理组并保留用户组。
- 新增跨 Skill 参考治理清单（#379）：`scripts/shared-references.json` 显式登记 canonical source、Skill 自包含副本、目录镜像与允许独立演化的派生关系；配套四道守卫检查未登记的精确副本、近似副本、Agent 消费可达性和短篇拆文的职责边界。
- 新增短篇 Phase 2 与交付的确定性验收（#379）：`check-phase2-contract.js` 检查设定与小节大纲的契约字段、12 列表格、子事件功能标签、字数合计、反转位置与付费点；`check-delivery-contract.js` 按用户给的字数范围、节数与排版形态验收成稿。失败返回具名检查 ID 与最小修复范围，最多两轮定向修复。

### Changed

- 长篇、短篇与短篇拆文的参考资料按消费者拆开并改名（#379）：悬念、反转、质量、题材与格式资料分成 `long-*`、`short-*`、`analysis-*` 三套，story-architect 按 `agent-reference-profiles.md` 选 profile，只加载 Common 加当前 profile，不再互相兜底。
  *升级*：自定义流程里引用旧文件名（`genre-catalog.md`、`reversal-toolkit.md`、`hooks-suspense.md`、`quality-checklist.md` 等）的地方要改成新名字。重新部署会替换整份 `agent-references` bundle。
- 长篇写正文与短篇构思前新增会阻断的 Reference Gate（#379）：当前阶段要求的 reference 必须分块读到 EOF，`rg` 检索或局部摘读不算读完；必需路径缺失或不可读时停止并报告路径，不允许先写正文再补读。
- 短篇总字数以用户给的范围为准（#379）：原先无条件的「总字数 ≥ 8000」不再覆盖用户明确范围；未给范围时才用 8000-20000 默认值。
- 情绪落地不再默认翻译成身体微动作（#376）：情绪优先落到选择、台词、策略、物件与实际后果，允许准确直写；三维度与动静节奏从逐段配额改为按需信息。新增 advisory `stock-reaction-tic`，只在同章聚集时提示做删除测试，不禁功能性身体描写。
- 发布 `agents_version: 28` 与 `setup_skill_version: 1.2.10`。

### Fixed

- 章节大纲以 UTF-8 BOM 开头时 `chapter check` 能正确识别「字数目标」，不再直接退出（#375）。

## [0.7.7] - 2026-08-26

> 补丁号不传达这一点：本版收紧了长篇章节完成条件。缺少合法「字数目标」不再回退到 3000；欠字不会自动添加独立剧情，超字只允许一次不新增语义的净删压缩；发现新增承诺、关系变化、支线或后续义务等独立故事内容时会阻止自动提交，改由用户决定接受、修改目标/细纲、返修或放弃。

### Added

- 新增工作区级作者记忆（#368）：用户明确要求记住的稳定偏好经确认后写入 `.story/作者记忆/`，保留原话证据、候选、冲突替代和撤回记录；普通写作只召回与当前任务相关的已确认条目，不与单本小说追踪混用。
- `story-cover` 在 Codex 中优先使用内置 ImageGen（#358），无需额外配置图片 API Key；其他 Runtime 继续使用 GPT-Image API 回退。
- 新增结构化 GitHub Issue Forms：确定性 Bug、输出质量 Case、功能请求分别收集复现步骤、具体输出证据和可验收结果，关闭空白 Issue。

### Changed

- 长篇正文改用 `storyctl.py` 的 `visible_chars_v1` 作为唯一字数口径（#370）：写作中只做一次测量 checkpoint，完成时统一检查长度与 blocking quality；只有提交追踪事务后才能进入下一章。
- 字数处置改为用户主导（#370）：欠字不自动灌水，超字最多压缩一次；仍在目标带外时由用户选择接受自然长度、修改目标或细纲、返修、放弃。旧输入缺少合法「字数目标」现在会停止，而不是静默回退到 3000。
- 新建、补建和改写细纲的情节点改为五列表格；story-explorer 对已登记但主产物缺失的对标 fail-closed，narrative-writer、story-architect、character-designer 按任务条件读取 reference（#362）。
- 仓库与安装地址迁移到 `zenstory-ai/oh-story-claudecode`；命令行安装改为 `npx skills add zenstory-ai/oh-story-claudecode -y -g`。
- 发布 `agents_version: 26` 与 `setup_skill_version: 1.2.8`。已部署项目需先更新技能包，在项目根重新运行 `/story-setup`，再新开会话。

### Fixed

- story-setup 不再把 `agent-references` 复制进自身或生成递归 `skills/story-setup/skills/`（#364）；复制前按 realpath / samefile 拒绝源目标同对象及目标嵌入源目录，并清理已知嵌套残留。
- Agent reference 表不再出现“列出了文件但实际不触发读取”的空转；对标缺失也不再静默换用另一本（#362）。
- Codex / OpenCode 生成器和 adapter 检查兼容 Python 3.9；macOS 系统 Python 不再因 `Path.write_text(newline=...)` 或缺少标准库 `tomllib` 而中断。
- 当前契约测试改为验证真实行为与失败边界，补齐清理守卫、部署复制和章节完成生命周期回归（#359、#370）。

### Security

- Dashboard 的 JSON 响应统一经过安全序列化并补充响应边界测试，避免项目名、路径或文件内容破坏响应结构（#369）。

## v0.7.6

> 这版的重点在正文那一段。写正文的专业 agent 有三条规则一直在空转：它被要求「写完必须立即统计字数」，可它的工具白名单里根本没有 Bash，那条命令跑不了，而同一句话又禁掉了唯一的替代手段——于是整个「字数达标是硬性要求」小节挂在一条无法执行的命令上；被要求「返回前报出句长分布」，同样无从计算，只能编，而主会话正拿这个数做质量校验。第三条更隐蔽：模板里「正文逐项展开细纲」是最高优先级的明令，而「可自由编排、合并穿插情节点」写在主 skill 里、从不进 spawn 提示词，子代理也不读主 skill——它只看见限制的半边，就按一个情节点一段平推成流水账。三条都已修好。同时新增细纲照搬检测：细纲把情节点写成成品散文句时，正文只剩誊抄，全章最好的几句其实在写细纲那一步就写完了，此前没有任何检测。**本版 `agents_version` 为 25**（v0.7.5 是 24），已部署的项目要重新跑 `/story-setup` 并新开会话。

### 升级须知（本版必读）

```bash
npx skills add zenstory-ai/oh-story-claudecode -y -g
```

然后在写作项目根目录重跑 `/story-setup`，并**新开一个会话**（专业 agent 只在会话启动时注册，正文 agent 这次改了工具白名单，不新开会话拿不到）。完整说明见 `skills/story-setup/UPGRADING.md`。

### 修复

- **正文 agent 的字数硬门槛终于能真的执行（#355）**。`narrative-writer` 的工具白名单是 `[Read, Glob, Grep, Write, Edit]`，没有 Bash。而它的规则写着「写完每章后必须立即统计字数」，给的是一条 Python 命令，还明令禁止模型估算——两头都堵死，「未达标的章节视为未完成」这句话背后没有任何可执行的判据。同一处的「返回前报出句长分布」也一样，数值只能是编的，而主会话拿它当质量校验的输入。现在给这个 agent 加上 Bash（同项目的 `story-researcher` 本来就有），字数和句长都报实测值，探测不到 Python 就明说「未完成机器字数验证」交主会话复核，不许声称已统计。实跑一章的对比：走子代理时首次落盘 2321 字就进了 2300–2530 的验收区间，全程没低于下限；不走子代理的对照组首次落盘 1663 字，不到下限的 73%，靠 26 次小幅增补才爬到 2350。

- **正文不再照着细纲的形状一项一段平推（#355）**。模板里「正文逐项展开本章细纲」挂在「最高优先级」标题下无条件生效，而放宽的那半边——可自由编排、合并穿插情节点——只写在主 skill 里，从来不进 spawn 提示词，子代理又不读主 skill。子代理只看得见限制，于是照着细纲的条目顺序一条一段推下去。现在拆成两条并列：内容层管「每项都要独立落地，不许漏、不许两项并一句」，形状层管「落地位置、顺序、断段由你定，可打散重排、把相邻几项缝进同一个连续动作，不要一项一段平推」，形状这半边同步写进 spawn 清单。实跑 1.81 句每段（原文基线 1.36），对照组 2.41。

- **`check-outline-copy.js` 一次传多章不再静默漏检**。两处调用点写的都是通配 `正文/第XXX章_*.md`，日更一批多章时会展开成多个正文路径，而脚本把第二个位置参数当成细纲——于是第 2 个正文被当作第 1 个正文的细纲，其余文件根本不检。两份正文之间几乎不可能有 16 字连续重合，脚本安静地退出，读起来就是「本批干净」。现在位置参数一律按正文处理，与同目录 `check-ai-patterns.js` 的口径一致，指定细纲改走 `--outline`。

- **Claude Code 上用 Bash 写正文也会被守卫拦下（#316）**。写正文前的大纲和追踪检查此前只挂在 Write / Edit 上，绕开它只需要一条重定向。现在常见的重定向、`tee`、`touch`、`cp`、`mv`、`install` 写入正文时会复用同一份共享判定，只读命令里的引号示例和 heredoc 里提到正文不拦，相对路径按 hook 的工作目录解析。这一面是**静态识别，不是 shell 沙箱**：环境变量拼出来的路径、运行时生成的命令、没列出的任意写文件程序都判不了，这类写入请改用 Write / Edit。

- **书目录发现不再无界扫描（#319）**。会话起点和结束时的自动发现会把整个项目翻一遍，深目录项目每次都要等。现在统一限制到项目下 4 层，并跳过隐藏目录和 `node_modules`，四端范围一致。`.active-book` 也不能再经目录符号链接指到项目外。

- **七猫大热榜的榜单周期不再混在一起（#340）**。日榜、月榜、总榜此前共用一套抓取，跑出来分不清是哪一档。现在 `--period day|month|all` 会写进文件头和文件名，改为按 URL 直达并校验页面上实际选中的那一档；分页器上的文字也不再被当成书名收进来。

- **起点采集补齐四个缺失字段（#339）**。字数、总推荐、签约状态、收费模式此前直接不采，页面上没有时现在明确写 `[待补]`，不留空让下游误以为是零。

- **拆文的章节摘要不再被模板自己教出格式漂移（#349）**。输出模板里写的是 `类型{转折点/行动/…}`，小模型照着抄就输出成 `类型{行动}`；多标签怎么分隔、空字段怎么写，模板从来没说。现在讲明 `{}` 是占位标记不是要输出的字符，补了一个完整正确样例，并把三处约定写死：字段名后不加冒号括号、主题标签只填一个值、空字段统一写「无」。同一份要求还内联进了 Stage 2 的 spawn 提示词，**老项目不重新部署也能拿到**。已经落盘的摘要不因此作废，不用重新生成。

### 改进

- **细纲照搬检测（#355）**。细纲的情节点一旦写成成品散文句，正文就退化成誊抄——实测正文与细纲连续重合最高 13.5%、单段最长 40 字，且重合的多是叙述而非台词，等于全章最好的那几句在写细纲那一步就定死了，此前没有任何检测。新增 `check-outline-copy.js`：正文与同章细纲连续重合超过 15 字即报出位置和原片段，子代理落盘后自查、主会话收尾复扫，两边同一份实现。它只提供证据不自动改写——系统面板、誓词、案卷原话、固定专名本就该逐字一致。为此细纲的「情节细化」下新增**复沓锚句**字段：必须原样进正文的原话逐行列出并注明落在第几个情节点，既强制这些内容逐字落地，也让它们不被判成誊抄。存量细纲没有这个字段的按「无锚句」处理，行为和此前一样，不用回头补。

- **每次会话固定加载的文本又少掉两成（#352）**。日更路径下 `story-long-write` 的 SKILL.md 和 `workflow-daily.md` 会同时进上下文，后者用近 2000 字复述前者已经写全的规则（写前资料清单、题材卡召回、文风判据、字数验证、元信息扫描），文件结尾还自陈「完整逻辑见 SKILL.md」。删掉重复的那一份，权威留在 SKILL.md。同时把只有写正文才用得上的单章流程和质量检查下沉到 `workflow-chapter.md`，开书和回炉这两条根本不写正文的路径不再为它付费。各场景实际加载：开书 −30.3%、回炉 −40.9%、日更 −4.4%。正文手艺规则（细纲边界、爽点铺垫、去 AI 味 Gate）一条没动——PR #228 的盲评实测过，删那些会退步。

- **超长篇拆文有了一条能跑通的路（#350）**。此前「块」这个字同时指两件事：在哪里按叙事弧切，和一次读多少受上下文限制。同一段里既写着「每块 50-200 章」又写着「6-8K token 每块」，差三十到一百倍，于是 500 章以上的书三条路都无解，执行的人只会以为是自己操作错了。现在两轴拆开：语义分块只管叙事弧划分，处理批次给出子代理并行（10-20 章每批，降维回传，按批记进度可续跑）和主线程串行两条路。批次尺寸按实测反推——中文章节摘要约 5-7K token 每章，914 章按 15 章每批约 61 批可覆盖。500 章以下的既有路径没变。

- **拆文 Stage 6 不再二次切片（#333）**，只读 `_progress.md` 里已经定好的章节边界表。

- **`/story-review` 分批审查的结果不再丢（#343）**。新增 `.story-review/state.md`，上一批没解决的 findings 会继承到下一批。

- **正文里的普通名词不再被加引号强调（#315）**。`narrative-writer` 的 Gate B 补了这一条；合法对话、直接引用、书名代号、故事内系统界面的原文照常保留。

### 维护

- 新增 `scripts/check-doc-budget.sh` 与 `doc-budget.json`：给每个「每次会话或每章都要进上下文」的文件、以及三条路径的合计设了字数上限，进 CI 卡死。超了要么删等量旧文本，要么显式调高上限并在 PR 里写清为什么这段值得每个用户每次会话都付——让文档膨胀变成一次显式决定，而不是无声累积。
- 细纲照搬检测器接回归测试（12 例，覆盖锚句在片段头/尾/中间、片段整体等于锚句、锚句字段写「无」、存量细纲无该字段、一次传多章各自比对），三份跨 skill 副本锁字节一致，三个平台的 CI 都跑。
- `story-review` 版本号 1.1.0 → 1.1.1。

## v0.7.5

> 这版没有新功能，都是修问题和减开销。最要紧的一条：Claude Code 上写正文一直不检查追踪状态，而另外三端从 v0.7.3 起就检查，于是同一个工程在 Claude Code 上能一路写出没有追踪的章节。本版把这道检查补上，**代价是旧追踪的长篇项目在 Claude Code 上会开始被拦，必须先迁移 `追踪/` 才能继续写**，处置方式见下方升级须知。另外长篇写作每次触发都要整份加载的那份 SKILL.md 从 699 行降到 455 行，只有开书才用得上的三个阶段移成按需读取；正文规则里还有一条把普通的「他说」判成违规，与其余 11 处口径冲突，也一并改掉。**本版 `agents_version` 为 24**（v0.7.4 是 23），已部署的项目要重新跑 `/story-setup` 并新开会话。

### 升级须知（本版必读）

```bash
npx skills add zenstory-ai/oh-story-claudecode -y -g
```

然后在写作项目根目录重跑 `/story-setup`，并**新开一个会话**（专业 agent 只在会话启动时注册）。完整说明见 `skills/story-setup/UPGRADING.md`。

**旧追踪的长篇项目在 Claude Code 上会开始被拦。** `追踪/` 下没有 `_tracking-state.json` 的项目停在 v0.7.2 及更早的追踪结构上，从 v0.7.3 起就该迁移；此前在 Claude Code 上还能照常写下去，本版起会在写入前被拦住。拦截提示里带了迁移办法：走 `/story-import` 的「旧追踪项目迁移」，只重建 `追踪/`，**不必重跑全书拆解**，正文、`设定/`、`大纲/` 都不受影响。

### 修复

- **Claude Code 上写正文补回追踪检查（#305）**。同一本书、同一次写正文，在 OpenCode、ZCode、Codex 上会被拦下并告诉你怎么修，在 Claude Code 上却直接写了进去——追踪状态缺失、状态卡与实际进度对不上、跳着章号写，一概不拦。用户往往一路写出好几章没有追踪的正文，直到会话起点提醒或批末校验才发现，那时只能重新导入补救。原因是 v0.7.3 加的那四道追踪检查只进了共享 JS 核与 Codex 的 Python 实现，而 Claude Code 挂的是另一份纯 bash 守卫，四条一条都没有。现在 bash 守卫改调同一份共享核，四端判定一致、提示一致，续写和改稿也一并纳入判定。这道检查要解析 JSON、只能靠 node，机器上没有 node 时它不生效，细纲那道门则仍是纯 bash，任何情况下都拦得住。

- **正文里的普通「他说」不再被判违规（#312）**。`story-format.md` 把「他说」「她道」列为绝对禁止，是全仓唯一把普通「说」判成违规的地方，与 `format-and-structure.md` 等 11 处「普通说可保留」的写法冲突，而它的加载路径正好是 `正文/`，写正文时必定生效。现在改为「避免对话标签机械化」：高频和公式化的标签用动作或上下文替代，普通「说」低频使用可以保留。

- **删掉命中不到正文的「禁止 AI 腔」红线块（#312）**。`story-narrative.md` 里这一块只在 `拆文库/`、`对标/`、`设定/` 下加载，正文目录根本不命中；那五条规则也已由 narrative-writer 的 7 Gate、禁止事项和确定性检测脚本覆盖。

- **去 AI 味的自然文本基准不再教电报体（#312）**。story-deslop 的这张基准表停在三个月前的口径，仍写着「段落 1-3 句为主」，比语料校准早，等于去 AI 味的 skill 自己在把文字往电报体推。已按语料校准改写，并补了一行句内节奏。

### 改进

- **长篇写作每次触发的固定加载少掉三分之一（#269）**。`story-long-write` 的 SKILL.md 是这个 skill 唯一无条件整份进上下文的文件，`references/` 下那几十个文件都走「参考资料索引」按需读取。它上一版 699 行，其中开书三阶段（确认选题方向、核心设定、大纲搭建）占了 244 行——这三段每本书只跑一次，日更续写和单章写作都用不上，却每次触发都要加载。现在移进 `references/workflow-setup.md`，要开书时才读，SKILL.md 降到 455 行。留下的是每章都要用的部分：场景判断与停靠规则、单章写作流程、质量检查、参考资料索引。移动前后按字节比对过，单章写作与质量检查两节逐字未动。

- **narrative-writer 模板精简约两成（#312）**。每章 spawn 一次、整份常驻的正文 agent 模板从 36506 字节降到 29506 字节。删的是与 7 Gate、禁止事项重复的审查清单（`/story-review` spawn 它时本来就会内联完整评分标准），正文阶段的「具体字数表达校验」（移到审查侧），以及省略号、破折号、段间空行、章节元信息这几处的重复叮嘱——它们每章由归一化脚本自动处理。写作口径没有放宽，Gate A-G 与禁止事项不变。

### 维护

- 写正文守卫的 bash 那一面纳入跨端一致性断言。此前只锁 Codex 的 Python 与 JS 核，bash 侧没有任何断言，上面那处四端不一致正是从这个缺口漏过去的。新增断言按「同一个工程、同一次写入，两边拦不拦必须一致」比对十组工程状态，并逐个写明该拦还是该放行。
## v0.7.4

> 这版全是修问题，没有新功能。最影响使用的是三件事：导入自己的书以后，「对标」目录里装的是自己的设定；多端部署的项目每次开会话都被告知参考资料包缺了；拆文跑到文风统计那一步，Windows 上直接报错退出。另外把 spawn 的版本检查从硬门禁改成提示，版本对不上不再整体退回单线程。**本版 `agents_version` 为 23**（v0.7.3 是 22），已部署的项目要重新跑 `/story-setup` 并新开会话。

### 修复

- **导入的书不再被登记成自己的对标（#294）**。`story-import` 早先把「导入的书」和「对标的书」都写作 `{书名}`，本书的拆文结果就跟着被复制进 `对标/`，用户看到的就是「对标内容和自己设定一模一样」。现在两者彻底分开：本书拆文只用来重建正文、设定、大纲和追踪；只有明确指定的外部作品才进 `对标/`，没指定就不建这个目录。写作和跨书召回也会跳过历史上误建的 `对标/{当前书名}/`，老项目不会继续被污染。短篇里的本书分析改叫「本书续写基线」。

- **版本对不上只提示，不再阻断多 agent（#294）**。以前 `agents_version` 与当前包不一致，就整体退回 solo。但 bump 往往是别的部署物变了、agent 模板根本没动，为此牺牲并行不划算。现在照常 spawn，只在报告里提一句版本不匹配、建议重跑 `/story-setup`。真正退回 solo 的只剩两种情况：agent 文件确实缺失，或运行时不支持自定义 agent。

- **长篇字数只认细纲目标（#295）**。此前静态下限表（2000／3000 字每章）和 hook 的「细纲目标 × 90%」并存，是两套标准。删掉静态表，只留细纲目标这一条；细纲没写字数目标时按 3000 字每章兜底，同时提示补纲。

- **browser-cdp 不再教你批量关 Chrome（#295）**。原来的清理命令按可执行文件名杀进程，会把用户自己开着的浏览器一起关掉。改成先查出确属调试 profile 的 PID 再结束，macOS／Linux 和 Windows 各给了一条可以直接跑的命令。

- **黑岩扫榜同日不同频道不再互相覆盖（#295）**。male、female、all 三个频道当天共用一个文件名，跑完第二个就把第一个盖掉。文件名加上频道，非法的 `--channel` 直接报错退出。

- **重新部署不再认错平台（#297）**。story-setup 判断 OpenClaw 的依据之一是 skill 带没带 `metadata.openclaw`，可 13 个 skill 全都带，而 OpenClaw、Reasonix、通用三条路径部署出来的 `skills/` 长得一模一样。等于拿自己部署的东西当判据，把 Reasonix 和通用项目统统认成 OpenClaw。Reasonix 那头恰好相反：判据找的几个文件，它的部署压根不生成，已经装好的项目反而认不出来。现在三端各按自己 `AGENTS.md` 的标题行区分，这是唯一互不重叠的标记；已部署的项目还会优先读 `.story-deployed` 里记着的 `target_cli`，不再每次重新猜。

- **多端部署不再每次开会话喊缺文件（#299）**。多端的 `references_dir` 是用逗号连起来的几条路径，会话起点却当成一条路径去找，于是装得好好的项目每次都被告知资料包缺失，真缺了哪条反而看不出来。改成逐条查，只报确实缺的那条。

- **Windows 上文风统计不再必挂（#300）**。这一步会先找可用的 Python，找到的可能是 Windows 原生版本，而样本路径写的是 `/tmp/...`。原生 Python 把它当成 `C:\tmp\...`，和 Git Bash 写文件的地方不是一处，自然就找不到。改成项目内的相对路径。同一处原先要求全程追加写，重跑时上一轮的样本会留在文件里，统计出来的是两轮混在一起的结果；现在第一段覆盖写。

- **目录不再被当成章节（#301）**。不少原文开头带一份目录，里面的「第N章」和正文里的一样顶格，建章节边界表时每一章会被数两遍。这张表是后面几个阶段唯一的切分依据，错一次会一路错下去。现在按行距把开头的目录整块剔掉：目录里相邻两条只隔一两行，正文章节之间隔着整章的篇幅。落表前还会检查章号连不连得上。多卷书每卷都从第一章重起是正常写法，这种重复不会被自动合并。

- **审查的两份评分标准重新对齐（#307）**。story-review 有一份内置标准，读不到文件时用；另有一份 `quality-rubric.md`。两边各自长歪了：文件那份多「任务卡点」，内置那份多「标点节奏」和「具体字数表达校验」，还有三个维度叫法不一样。方向也别扭，读得到文件时用的反而是少两条的旧版。现在补齐成同样 18 项，并加了断言，再分叉会被 CI 拦下。

### 维护

- 补上 `tracking_commit.py` 的 `context` 字段说明：`init` 收六项，`commit` 只收四项，`recent_chapters` 和 `next_chapter_commitments` 提交时由工具自己算。以前只能从示例里猜，照 `init` 的样子写 `commit` 会被直接拒掉（#306）。
- OpenCode 的 agent 模型要在覆盖前先缓存，这句话原本写在后面的小节里，照顺序执行就晚了。在覆盖那一步就地加了提示（#298）。
- `format-and-structure.md` 标题写「5 条绝对禁止」，底下列了 8 条，三份副本一起改（#306）。

## v0.7.3

> 长篇追踪改单一权威事务模型：`追踪/_tracking-state.json` 是唯一结构化状态，所有追踪写入走 `tracking_commit.py`，续写状态卡与伏笔/时间线/角色快照都是工具整份生成的派生视图，日更每章必读从五个文件收缩到三项。Dashboard 目录树改按需加载；章节概要改叙事化、原文引用改精选。**v0.7.2 及更早的长篇项目必须先迁移 `追踪/` 才能继续写**，见下方升级须知。**本版 `agents_version` 为 22**（v0.7.2 发的是 21），已部署项目需重新运行 `/story-setup` 并新开会话。

### 升级须知（长篇在写项目必读）

重跑 `/story-setup` 后，检查每本书是否有 `追踪/_tracking-state.json`。没有就是旧追踪结构：日更会停下，OpenCode / ZCode / Codex 上写正文会被 hook 拦。

迁移**不需要重跑全书拆解**，正文、`设定/`、`大纲/`、`拆文库/` 都不受影响，只重建 `追踪/`：走 `/story-import` 的「旧追踪项目迁移」——数出最后完整章号 N，从旧追踪文件与最近几章正文反推当前状态，构造 `last_chapter=N` 的初始化事务跑一次 `init`。旧结构会被按原样整体移入 `追踪/_旧追踪存档/`，不删除、不参与解析。完整说明见 `skills/story-setup/UPGRADING.md`。

### 新增

- **Dashboard 按需加载目录树（#273）**：目录树改为展开时才拉取子节点，大工程首屏不再一次性扫全树；顺带修短篇标准工程识别与懒加载回归，搜索读取失败改为显式标记而不是静默吞掉。

### 修复

- **长篇追踪改单一权威事务模型（#269 #290 #289）**：`追踪/上下文.md` 成为固定 7 栏、硬上限 12288 字节的续写状态卡，每章由工具整份重建；全书历史移到 `追踪/逐章记录/第NNN章.md`（日更不读）；伏笔、时间线双视图、角色快照降为派生视图，检索走 story-explorer 按需查询。日更每章必读从五个文件收缩为三项，读取成本 O(N²)→O(N)。`narrative-writer` 不再写 `追踪/`；`/story-review` 新增追踪文件维护；SessionStart 加状态卡体积告警，四端同步。旧结构与 `_tracking-meta.json`、`时间线/事件库.json` 一并退役，不提供兼容层。
- **修上条留下的主流程断链**（发版前主流程审查，逐条实测复现）：
  - 回炉备份被守卫打死——守卫把「文件不存在」当成「首建新章」，于是 `workflow-revision` 规定的 `正文/第X章_..._原稿_{日期}.md` 备份必然撞上顺序校验，报「首建第5章前必须先提交第4章事务」，而回炉章号恒小于已提交章号，无解。章号已在追踪范围内时跳过顺序校验，跳章写作仍拦。
  - 旧项目没有迁移路径——日更让去 `story-import`，`story-import` 看到 `.active-book` 就答「别重跑、回去日更」，用户在两条命令之间来回弹。判据改用 `_tracking-state.json` 是否存在，并给出只重建 `追踪/` 的迁移步骤；`UPGRADING.md` 此前全文没提过本次追踪变更，补了完整一节。
  - 恢复指令不收敛——「任何失败都重跑同一 commit」只对写入失败成立；校验失败重跑结果不变，派生视图被改后重跑会撞 stale 而工具无 rebuild 子命令。按失败类型分开写，补上 `mode=revision` 整份重建这条实测可行的出路。`check` 失败时只往 stderr 打 ERROR、不输出 JSON，所以当前修订号改为直接读 `_tracking-state.json` 的 `state_revision`。
  - `story-explorer` 与 `consistency-checker` 被要求运行 `tracking_commit.py check`，但这两个只读 agent 按设计禁 Bash。改为消费调用方在主会话跑 `check` 后传入的值，权限边界不动，也不把随章数增长的完整 state 读进 prompt。
  - 部署的 `story-narrative` 规则教 agent 手写 `逐章记录/`、`上下文.md` 与伏笔「真实答案」，与同目录 `story-consistency` 规则正面冲突，且改设定就会触发；`伏笔.md` 是派生视图、没有该列，手写即让 `check` 报不一致。改成登记进事务。
  - Claude Code 的 bash 守卫与 JS 核在 `拆文库/` 豁免上漂移，同步收紧；欠账门取「上一章」用 readdir 原始顺序，回炉备份放行后会在哈希序文件系统上挑中未清洗的备份，四端统一排除并排序。
  - 五份平台 AGENTS 模板与三份 narrative-writer 仍把 `追踪/` 描述成含「时间线事件库」，而该文件是工具退役黑名单，建出来会让 commit/check 永久失败。
  - 守卫层：只读 agent 的 Bash 检测式只认「执行 \`cmd\`」，「运行 / 跑」完全绕过——上条的越权指令正是这样溜过全套 CI 的；正则补齐并按行豁免委派句式。一条断言禁止 story-import 描述旧追踪迁移，与本版行为相反，改为钉「迁移必须走存档重建」。回炉放行分支补了 parity 回归用例。
- **章节概要改叙事化、原文引用改精选（#275 #276）**：概要不再要求用「因为…所以…」串联，改为按时序讲清事件、原因、结果，优先保留改变走向的动作与结果、反常信息、跨章伏笔线索。原文引用只留关键转折、关键台词、写法样本，每章至多 8 条——实测引用占章节摘要 45.5%，而下游 Stage 3 事实溯源回原文、Stage 6 文风锚点从原文切片，均不消费逐节点引用。并行 chapter-extractor 与串行两条路径的要求收敛到一份模板。
- **Dashboard 隔离项目与拆文库节点预算（#268）**：两类目录不再共用同一份节点预算。此前超大项目先扫描耗尽预算后，拆文库即使真实存在也返回空数组，界面把「预算被另一类耗尽」显示成「拆文库为空」。现在各自持有扫描状态与预算，任一类触顶只截断自身。
- **短篇导入与篇幅分流（#285 #286 #287 #288）**：story-import 调用短篇拆解管道时不再声称对方「无停靠点」——它的 Phase 1 有字数路由和续跑三选一两个提问点，现改为四个 Step 逐条给导入场景取值，题材识别照跑（`genre_detected` 是阻断级必填）。篇幅分流补字数上界，此前「无章节分隔即短篇」不看字数，十万字裸文本会被建成单文件短篇工程。`选题决策.md` 补自动发现（写作与拆文此前都只看项目根，回填功能长期空转）。story-setup 加参考目录自检，检出 Windows 下 `npx skills add` 偶发的部分安装。

### 维护

- 参考资料解析顺序补 `.agents/skills`（Codex / Reasonix 实际扫描的 skill root），末层改写成「当前运行时加载本 skill 的目录」；story-setup Phase 2 写明部署幂等（#282）。
- README / README_EN 补方式一的升级说明与 Windows 部分安装的表现和修复方式。

## v0.7.2

> 本地工作台 `/story dashboard`（只绑 127.0.0.1、零生产依赖）；治细纲形状被正文照抄导致的生硬与章尾总结体；仓库质量门禁不再掩盖破坏性失败；修会话起点两处长期误报。**本版把 `agents_version` 发到 21，已部署项目需重新运行 `/story-setup` 并新开会话**——v0.7.1 发出去的是 20，不重新部署则 v0.7.1、v0.7.2 的正文与 hook 改动都不会生效。

### 新增

- **Story Dashboard 本地工作台**：`/story dashboard`（Codex 为 `$story dashboard`）从当前
  工作区启动零生产依赖的本地 Web UI，分开展示 `拆文库/` 与长短篇写作项目文件树，支持
  文件名搜索、Markdown 安全预览、白名单文本轻量编辑、快捷保存、确认删除和 mtime
  冲突保护；服务默认只绑定 `127.0.0.1`，路径规范化、真实路径校验和 2 MiB 上限防止
  越界读写。
- **真实 demo 驱动的浏览器测试**：把原有《盘龙》《曾将爱意私藏》拆文资产整理到
  `demo/拆文库/{书名}/`，把《让你管账号，你高燃混剪炸全网》工程整理到
  `demo/长篇/{书名}/`；Node API 回归与 Playwright 桌面/移动 E2E 都复制这批现有 demo
  到临时目录后执行，避免另造与真实产物脱节的 fixture。

### 修复

- **治细纲形状被正文照抄导致的生硬与章尾总结体（#255）**：细纲每个字段都是摘要原语，弱模型 1:1 渲染成一句一段就是电报体和逐拍交代。writing-craft 补「从细纲到正文」护栏——细纲是「要发生什么」的内容规格，不规定正文形状，正文可合并、穿插、重排情节点，把每个点演成场景而不是照抄概括语；开头补 anti-fingerprint；story-review 加同质化判断。细纲模板的「结尾 / 结尾设定」由「收束到什么状态」改问「最后落在谁的什么动作、画面或台词上」——真人语料实测长篇章末对话收尾约 29%、动作画面约 26%，明确的状态总结只占约 1%。部署 hook 的毒句式欠账门新增 `trailer-summary` 规则（文末 600 字窗口，四端同步）。
- **仓库质量门禁不再掩盖破坏性失败（#265）**：修 Dashboard、hook、adapter 与 contract 校验链路上的 fail-open 守卫、丢写竞态、扫榜部分失败上报不全与测试盲区。Dashboard 保存由 mtime 乐观并发改为版本校验并收进串行化写队列（同秒并发写会互相覆盖已接受的稿件）；扫榜单平台失败不再中止整轮，保留可用的部分结果并如实标注采集质量。
- **会话起点两处长期误报（#173）**：`拆文库/` 的「未完成拆文」提醒改按 `_progress.md` 的「最终状态」取值过滤，`completed` / `completed_with_errors` 不再计入——原实现裸数文件，拆完的书每次会话都被报一次；取值只认冒号后的状态本身，模板占位符与括注写法按未完成处理，宁可多报不漏报。被动版本更新提醒改为按 24h 节流提示本身（原实现只节流网络请求，同一版本每开一次会话提醒一次），curl 失败写负缓存，取不到 GitHub 的环境不再每次会话空等 5 秒。`/story` 路由表补上 `story-review`——此前 13 个 skill 里唯独审查没有路由行。

### 维护

- README / README_EN 聚焦当前用户路径，修正知乎盐言的英文拼写（#264、#266）。

## v0.7.1

> 正文「电报体」彻底治理——写入端做减法 + story-deslop 去抵抗 + 全套短句崇拜清扫（语料 + 五题材实测双证）；补同人 / 既有世界观命名护栏；Reasonix skills-only 适配 + 开书对标发现。

### 修复

- **正文电报体彻底修（#256，续 #254）**：#254 立了逗号流水句基线仍不彻底——报告人指出跑 `/story-deslop` 时模型把连续短句当「刻意节奏」而抗拒去电报体。本次三层做减法：
  - **写入端**：删「短句=果决热血 / 情绪密度高」奖励、开头事件密度的电报体范例（改逗号流水）；narrative-writer「心理外化 / Gate C / 情绪词默认外化」由绝对化改为设上限（模板 + opencode/codex 经 sync 脚本重生成，短篇题材包例外原样保留）。
  - **story-deslop 去抵抗**：anti-ai-writing 规则 3 删掉「连续短句只在三场合连用」的许可，只留「默认逗号长句 + 短句是偶尔的孤立重拍」；模式 9 峰值保护保留；修 story-review 评分表 / style-craft / style-profile 等下游镜像里矛盾的「连用短句」「句长拆短」残留。
  - **全套短句崇拜清扫**：39 文件普查、逐处判定，清「短句为主 / 多采用短句 / 短句占比 >70% / 见长就拆」等残留；示例句 after 由电报体改逗号长句，黑岩「一句一段」模板换成真实黑岩语料，短篇加整句上限修「盐言被拉成 130 字流水句」的过矫。
  - 证据：mongo 爆款语料实测叙述逗句比 1.2–1.74、连续短句 run 仅占 1.7–4.3%；codewhale + DeepSeek-V4-Pro 五题材实测旧规则全崩电报体、新规则全流畅 0 电报 run，且战斗峰值 / 情感克制 / 沙雕 deadpan 不退步。

### 新增

- **同人 / 既有世界观命名护栏（#257）**：character-basics 主角 / 配角卡、genre-catalog 同人流派、plot-special-topics 同人写作要点补命名一致性约束——原著角色沿用官方本名 / 译名，新角色贴合原著对应地域 / 文化的命名与译名风格，同一地域不混语系，不套用与设定不符的现代化 / 政治化名字（设定相对，现代设定同人不受限）。低成本兜底降低时代错位取名概率，非确定性修复。
- **Reasonix skills-only 适配 + 开书对标发现（#253，Closes #252）**：新增 `target_cli=reasonix`（复制 skills + `.agents/skills` symlink + Reasonix AGENTS.md，无 hooks/agents 走 solo/direct）；开书阶段新增「对标发现」主动扫 `拆文库/` 按题材推荐对标书（长篇 Phase 1 / 短篇 Phase 2）+ 卷纲提醒。

### 内部 / 语料治理

- **正文句长基线（#254）**：anti-ai-writing 规则 3 重写为「句长基线（短是工具，不是底色）」+ 语料校准注（qimao 125 本×前 8 章：逗号间 8.8–9.6 字、整句 22–24 字、逗号流水占叙述 74–80%）；banned-words 缓缓 / 微微 / 轻轻 / 淡淡 降为二级密度控制；清除各处「见长就拆 / 机械长短交替」配方。`agents_version` 升至 **20**。

### 升级

- 已部署项目重跑 `/story-setup` 刷新 references / agents 并**新开会话**；`agents_version` 20 已含 #254 + #256 的写作规则变更。

## v0.7.0

> 多端适配再扩两家（ZCode / Reasonix）· hook 核统一到共享 node 核 + 六端 parity 锁 · 长篇「剧情单元」概念统一并接入拆书产物 · 去 AI 味闸口机器化（毒句式确定性检测 + 欠账门）· 契约体检与脚本加固

### 新增

- **ZCode 3.3.4 原生适配（#234）**：新增 `.zcode-plugin/plugin.json` 与根 `marketplace.json`，把仓库作为 `oh-story` plugin 暴露 13 个 Skills、13 个 Commands 和严格 JSON Hooks；`story-setup` 新增 `target_cli=zcode`，部署 `.zcode/skills` / `.zcode/commands` / `.zcode/hooks`，安全合并 `.zcode/config.json` 与根 `AGENTS.md`。无第三方依赖的 Node hook runner 覆盖 SessionStart 上下文/连续性恢复、PreToolUse 大纲守卫与 commit advisory、PostToolUse 正文轻量确定性网；非空 stdout 只输出 ZCode 接受的严格 JSON，异常写 stderr 并 fail-open。ZCode 3.3.4 不执行项目/plugin custom agents、无 `.zcode/rules`/PreCompact/SessionEnd，涉及专业 Agent 的 Skill 与 story-review 明确降级 solo/direct，不伪造平台能力。
- **Reasonix 原生支持 Phase 1（#238）**：新增根 `reasonix-plugin.json` plugin manifest（version 钉住 `skills/story/VERSION`）与 README 安装说明；Reasonix 扫描 `.agents/skills`（与 Codex 共用的 `skills/` symlink）发现 13 个 skill，`check-reasonix-adapter.sh` 守卫 manifest。项目级 `story-setup` 部署与 hooks 留待后续阶段，当前涉及专业 Agent 的流程走 solo/direct。
- **短篇题材风格包按平台语料重建（#231）**：`story-short-write` 题材风格包从 4 个扩到 10 个（新增世情打脸、民俗怪谈、悬疑、甜宠、双男主、沙雕脑洞），按七猫/知乎/黑岩/点众四平台真实语料重建开头模式、爽点密度、对话风格、情绪模式与结尾模式，并修正世情题材误路由。

### 改进

- **长篇「剧情单元」概念统一并接入拆书产物（#246）**：把「剧情条 / 循环卡 / 正式情节循环 / 剧情段」五个混用叫法统一为**剧情单元**（卷纲里记为**剧情单元卡**），字段 循环ID/循环节拍/… → 单元ID/单元节拍/…（「循环」只保留节奏义如爽点循环）。拆书剧情单元接入卷纲/细纲：卷纲剧情单元卡新增「对标剧情参照」，对标节奏迁移改以剧情单元为选段单位，细纲分批边界改为「一批 = 一个剧情单元」，拆文侧 `剧情/README.md` 新增「剧情单元清单」索引（存量书可机械补建）。旧版卷纲/细纲/拆文库无这些字段一律不阻塞、按字段结构回退读取，仅在补纲/改纲时升级。story-long-write 场景表新增「补纲/扩纲」入口与卷纲锁定定义。
- **读者契约 + 终局储备推进模型（#237）**：用「读者契约 + 终局储备」双层推进模型替代原「成长预算」，放开单章爽感，治长篇推进过快导致后期无可写；Σ 字数预算契约（密/疏预算、Σ∈[章目标, ×1.1]）不变。
- **去 AI 味闸口机器化（无状态，#246）**：写后正文网新增确定性毒句式检测（「不是 A 而是 B」全家族、声线反差、否定排比、预告收尾），落盘即自动扫描并推回命中；写下一章前新增「毒句式欠账门」——上一章有未清 blocking 命中且未标 `<!-- 去味:跳过 -->` 豁免时拦截（判据现算自文件本身，不落任何状态文件，node 缺失或解析失败一律放行）。豁免标记冒号全半角均认，同时使写后网跳过该章毒句式推回（其余网照常）。`check-ai-patterns.js` 同步新增 voice-contrast / negation-parade / reverse-not-is / trailer-ending（blocking，经真人语料零误报校准）与 quote-emphasis-tic（advisory）。四端（Claude/OpenCode/Codex/ZCode）共享同一份判定，js↔py 逐字 parity 锁 + 引号占位对齐 check-ai-patterns.js。

### 重构

- **hook 核统一到共享 node 核 + parity 锁（#239 / #243）**：OpenCode 与 ZCode 收敛到同一份 `story_hook_core.js`（ZCode hook 564→198 行），Claude 的 4 个 bash hook 也把内嵌 python 收敛到该共享核（经 `story_hook_cli.js`），消灭此前唯一无守卫且已漂移的手抄实现；Codex 保留 python 实现，由 py↔js 逐字 parity 锁（`test-prose-net-parity.sh` A–E 层）钉住。补 node 缺失/损坏时的 fail-open 回归；大纲拦截保留纯 bash 兜底。
- **技能契约体检 + fail-fast（#242）**：新增 `check-current-skill-contracts.py` + `current-contract.json`，把版本锚点、Phase、schema、主产物路径与细纲必填项固化成 CI 契约，`agents_version` 成为运行时过期判定的唯一权威；对标主产物（`剧情/情绪模块.md` / `剧情/节奏.md`）缺失改 fail-fast，不再用旧产物静默降级。
- **仓库脚本加固（#233）**：共享文件/OpenCode 同步检查改只读 + 写安全，适配器生成器原子发布 + 异常回滚，新增四端真实 CLI 安装的兼容 workflow。

### 修复

- **Codex hook 空白 `.active-book` 首行当仓库根（#235）**：`.active-book` 首行为空时不再误把仓库根当活跃书目，对齐 bash oracle。

### 其他

- **去掉部署检查的文档措辞门禁（#240）**：删除「UPGRADING/README 必须写某句话」类脆弱措辞门禁，保留 `agents_version` 阈值等行为锚点。

### 发布准备

- 版本号升级到 `0.7.0`（`.claude-plugin/marketplace.json` + 根 `marketplace.json` + `.zcode-plugin/plugin.json` + `reasonix-plugin.json` + `skills/story/VERSION`）。`.story-deployed` 的 `agents_version` 本周期从 `17` 连续升到 `19`（#242 → 18，#246 → 19），`setup_skill_version` 为 `1.2.7`；本版含 hooks / agent 模板 / 项目规则模板的行为变更，已部署项目需重新运行 `/story-setup`（Codex 用 `$story-setup`）并**新开会话**获取，从 v0.6.22 升级重跑一次即到位。`UPGRADING.md` 新增 v18 / v19 条目，`README` / `README_EN` 版本说明收敛为最近 3 版（更早见 CHANGELOG）。

## v0.6.22

> 长篇题材正文提示卡 + 短篇投稿层 + 全套件文档瘦身（#226 / #227 / #228）

### 新增

- **题材正文提示卡（#226，合并 #222/#223/#224）**：`story-long-write` 新增 `genre-prose-cards/` 32 张番茄题材腔调卡 + 索引召回规范；写作时按 `设定/题材定位.md` 匹配召回单卡进写手，anti-leak 硬约束保证卡名/题材标签/置信度/条目/合规自评一律不进正文；narrative-writer 三端模板同步接入召回与按题材细化的文风指纹/Gate G 规则，chapter-extractor 模板新增 `chapter_formula` 逐章写法公式产物。
- **短篇投稿层（#227）**：`story-short-write` 新增 `submission-craft.md`——知乎盐选/小程序/番茄三路平台基调矩阵（视角、矛盾演进、章末钩子、结局质感）、导语门面单独打磨（四维骨架+黄金三角，150-220 字）、付费点卡脖子断点与反推法排细纲；`story-short-analyze` 拆解时顺带记录投稿层进拆文报告。合并前盲评 A/B 四维全胜（register +0.55、structure +0.58）。
- **deslop 任务卡点与比喻密度（#218）**：任务卡点只在改变信息/情绪/关系/代价/选择压力/伏笔/钩子承接时使用；新增 `metaphor-density-tic` advisory（像/仿佛/如同高密度堆叠检测）；朱雀定位为辅助信号，去 AI 味不越剧情边界。
- **generic Web AI 部署（#216）**：story-setup 新增 `target_cli=generic` 文件模式（复制 `skills/` + 通用 `AGENTS.md`，不声明平台原生 hooks/custom agents）；`story-long-write` 补通用环境 solo/direct fallback。

### 改进

- **长篇工作流防失控（#225）**：裸调用 `story-long-write` 不再自动进入正文/日更模式；开书流程默认停在大纲；日更批量有界；narrative-writer 只扩写细纲计划内情节点，不足时返回 `outline_underfilled` 欠账报告交主会话补纲；理顺 setup → import → long-write 的续写工程顺序。
- **全套件文档瘦身（#228）**：13 个 skill 系统审计后删除可证行为不变的冗余——逐字/同义重复、过期目录、失效行号锚、维护性注释、跨体裁死段、悬空指针，53 文件净 −32.9KB；同名副本组全部字节同步；Σ 字数预算契约、anti-leak、hook 锚点零触碰。
- **deslop 防检测器博弈（#220 / #221）**：吸收社区反 AI 思路但不做讨好检测器的硬规则；新增 `action-list-tic` advisory（监控镜头式动作链）；外部检测器明确为自检参考、不替代人工通读；恢复朱雀 AIGC 检测 CLI 致谢。

### 发布准备

- 版本号升级到 `0.6.22`（`.claude-plugin/marketplace.json` + `skills/story/VERSION`）。`.story-deployed` 的 `agents_version` 升级到 `17`、`setup_skill_version` 升级到 `1.2.6`；本版含 narrative-writer / chapter-extractor 部署模板更新（题材卡召回 + anti-leak + 大纲边界与 chapter_formula），已部署项目需重新运行 `/story-setup` 并新开会话获取。`UPGRADING.md` 新增 v17 条目，`README` / `README_EN` 版本说明收敛为最近 3 版（更早见 CHANGELOG）。

## v0.6.21

> 短篇写作参考栈瘦身：删掉长篇继承残留，建立短篇专属 format/craft/deslop/题材包体系（#206）

### 改进

- **短篇写作 references 清理（#206）**：`story-short-write` 删除 13 个长篇继承残留参考（角色、长篇结构、通用题材读者、开篇、状态追踪等），避免短篇写作继续被长篇规则误导。新增短篇专属基础层：`short-format.md`（硬格式/段落/标点/正文契约）、`short-craft.md`（短篇叙事姿态、情绪直给+体感焊接、三维度揉进、密度控制）、`short-deslop.md`（短篇去 AI 味，只杀真 AI 腔，不杀情绪烈度）。
- **题材包接管短篇风格（#206）**：新增 `genre-styles/追妻火葬场.md`、`复仇打脸.md`、`总裁豪门.md`、`宅斗宫斗.md` 四个短篇题材包，把开头模式、爽点密度、对话风格、情绪模式、结尾模式收束到题材本地；冷门题材仍可降级读取 `genre-writing-formulas.md`。
- **短篇/拆文 AI 规则边界显式化（#206）**：共享 `output-contract.md` 明确拆文报告质量门仍走 `story-short-analyze/references/anti-ai-writing.md`，短篇成稿去 AI 味走 `story-short-write/references/short-deslop.md`，避免两套规则继续靠“本地 AI 腔规则文件”这种隐式短语耦合。
- **部署模板同步短篇例外（#206）**：`story-setup` 的 narrative-writer Claude/OpenCode/Codex 模板同步短篇题材包例外：短篇需要“情绪词 + 体感/动作焊住”时不强制改成纯动作外化，只清理空泛无体感的 AI 情绪总结。

### 发布准备

- 版本号升级到 `0.6.21`（`.claude-plugin/marketplace.json` + `skills/story/VERSION`）。`.story-deployed` 的 `agents_version` 升级到 `16`、`setup_skill_version` 升级到 `1.2.5`；本版含 deployed narrative-writer 模板与 reference bundle 更新，已部署项目需重新运行 `/story-setup` 并新开会话获取。`UPGRADING.md` 新增 v16 条目，`README` / `README_EN` 更新 v0.6.21 版本说明。

## v0.6.20

> 长篇大纲补强：对标节奏迁移（激活死链接）+ 章节定位与张弛（破"每章像短篇"）（#198）

### 新增

- **对标节奏迁移（#198）**：对标书拆出的 `剧情/节奏.md` 过去只喂 Phase4 逐章文风、从不回流卷级结构；新增「一级结构=对标书剧情单元 + 关键点法 + 对标节奏迁移 M1-M5」（`outline-structure-theory.md`），卷纲模板加「对标结构坐标」表，Phase3 卷纲定稿前读对标节奏回流（按归一化关键点 1/4·中点·3/4 换素材排进本卷，保留情绪链+功能位、禁照搬桥段，并比对「不建议模仿」就地修正对标硬伤）。缺 `节奏.md`/`情绪模块.md` 时走 `章节摘要 + 拆文报告` 降级路径（多数真实拆文库都缺，已在 盘龙拆文库 端到端验证）。
- **章节定位与张弛，破「每章像短篇」（#198）**：顶层「每章一视同仁——钩子+爽点+悬念」逼模型把关系/铺垫/过场章都写成强钩子短篇；改为按章在一级结构里的位置分六型定位（高压/推进/修炼试错/关系回收/低压生活/信息整理），低压/关系/过场章允许无显性爽点、弱钩子，但每章保留往下看的理由（番茄追读红线），并加「禁情绪母题扎堆」底线（连续多章同母题才是真正疲劳源）。定位可留空=退化为推进章，非硬配额、非新教条；压力级=爆发烈度，与情绪强度分两轴；占比按题材分档（番茄短平快高压可到 30%+）。SKILL.md 大纲四检升五检、顶层质量要求/爽点密度/step9/三处 QA 按定位放宽，story-architect spawn 注入「章节定位契约」，并修复 `agent-references/quality-checklist.md` 漏同步（deployed agent 审查时实读）。盲评（同一新章按旧/新规则各写一版正文）：旧版判「工业爽文/每章必须钩子的流水线产物」，新版「关系章作者型写法」，编辑判定新版明显更适合高潮后呼吸位；字数预算 Σ∈[章目标,×1.1] 契约不动，关系回收章加「≥1情感密点」更严下限。

### 发布准备

- 版本号升级到 `0.6.20`（`.claude-plugin/marketplace.json` + `skills/story/VERSION`）。本版同步更新 `agent-references/quality-checklist.md` 与 `outline-methods.md` 的章节定位豁免，并在 `story-architect` spawn prompt 注入「章节定位契约」——部署 agent 无需重部署即按新定位排/审大纲；未 bump `agents_version`（本版无 hooks/agents/agent 模板结构变更，agent-references 内容在新项目部署或下次重部署自然生效）。`README` / `README_EN` 更新 v0.6.20 版本说明。

## v0.6.19

> Codex CLI 适配 + OpenClaw 兼容（#186）· 自定义文风 `设定/文风.md` 优先于对标（#194）· 模型退化/工程词泄漏检测（#173）· 碎句号/长段落检测 + 破折号按功能改写（#188）· 正文兜底 + 跨批连续性确定性网（#195）· OpenCode 子代理模型自动配置降本（#191）· 细纲按字数预算根治欠字反复回炉（#187）

### 新增

- **Codex CLI 适配 + OpenClaw 兼容（#186, #189）**：`$story-setup` 部署 `.codex/agents/*.toml`（由 Claude agent 模板经 `generate-codex-agents.py` 生成）与 `.codex/hooks.json`；Codex 就地用 repo 时扫 `.agents/skills`（symlink 到 `skills/`，#189 加 symlink 守卫并记 Windows `core.symlinks` 坑）。补齐 OpenClaw skills-only 兼容（单行 frontmatter + `metadata.openclaw` + `story-setup target_cli=openclaw`），并加固 OpenCode/Codex 适配漂移守卫（`check-opencode-adapter.sh` / `check-codex-adapter.sh`）。
- **自定义文风优先于对标文风（#194）**：每章写作前先读 `设定/文风.md`，含实质内容即进入「自定义文风模式」——它作权威风格基（句长 / 软标点 / 对话潜台词 / 情绪交替），对标 / 拆文 `文风.md` 降为参考（原文锚点 + 句长兜底）；`narrative-writer` 文风指纹新增「来源」字段，用户新增/改 `设定/文风.md` 后用新来源刷新句长带快照、不再被旧对标永久压住（三端模板 + `上下文.md.tmpl`）。
- **模型退化 + 工程词泄漏检测器（#173）**：新增 `check-degeneration.js`（4 份字节同步），确定性检测弱模型退化——逐字复读/打转、末尾截断、占位/拒绝语（`作为AI`/`我无法续写`/`（此处省略）`/乱码 �）、工程词漏进正文（`细纲`/`情节点`/`本章`/`下一章` 等）；每条 finding 带 `severity: blocking|advisory`（blocking 即重写、tier2 章节/歧义词只提示，对话行里的 tier1 工程词降级 advisory）。接入 `story-long-write`/`story-deslop`/`story-review`/`story-short-write` 收尾复扫，`story-review` 子 Agent prompt 补「继承的开放项」做跨批连续性。
- **碎句号/长段落检测 + 破折号按功能改写（#188）**：`check-ai-patterns.js`（4 份字节同步）新增碎句号（连续短叙述句无呼吸）、长段落（>200 字按镜头断段）检测，与破折号按功能改写建议（打断→动作 beat/短句、拖长音→省略或动作、插入说明→逗号/冒号，不一律改句号）；每条 finding 带 `severity`，混合行（叙述 + 引号内物件）不再被一个引号整行豁免，`story-review` 指定 em-dash 归口 `check-ai-patterns.js` 并与 normalize 去重。
- **正文兜底 + 跨批连续性确定性网（#195）**：新增 deployed hook `check-prose-after-write.sh`（PostToolUse Write/Edit 落盘后跑硬信号兜底——截断、拒绝语/AI 自指、工程词泄漏、逐行复读、字数欠账），即使主会话漏跑确定性收尾也能兜住；三端（Claude/OpenCode/Codex）轻量网 parity 守卫，Codex 用 Stop 回合末 git 改动集扫描；跨批连续性在会话起点提醒续写断线 / 章节撞名。
- **OpenCode 子代理模型自动配置（#191）**：`$story-setup` 含 `target_cli=opencode` 时检测 `opencode models` 并按等级为各写作 agent 写入 `model:` 字段，避免低成本 agent 继承主模型造成高额消耗；逐级 AskUserQuestion 选择，支持自定义输入/保留现有/跳过，优先按 `opencode models --verbose` 的成本分级、关键词作回退。

### 改进

- **细纲按字数预算编排，根治正文欠字反复回炉（#187）**：细纲情节点序列改为按字数预算编排——每点标密/疏给预算（密 ≥250、慢镜头爽点 400-600、疏 ≈40、铺垫 120-150），各点求和 Σ 落在 [章目标, 章目标×1.1]；写后字数验证对照预算定位欠账密点、一次性重写到位，不逐点挤牙膏反复回炉，并补 > 章目标×1.1 的超预算收敛分支；调 `story-architect` 时 spawn prompt 注入预算契约并在接收细纲后校验 Σ。

### 修复

- **大纲守卫识别 Windows 盘符绝对路径（#184）**：写正文前的大纲守卫 hook 正确识别 `C:\\...` 形式的 Windows 盘符绝对路径，避免在 Windows 上误判正文文件路径。

### 发布准备

- 版本号升级到 `0.6.19`（`.claude-plugin/marketplace.json` + `skills/story/VERSION`），`.story-deployed` 的 `agents_version` 升级到 `15`、`setup_skill_version` 升级到 `1.2.4`——本版含 deployed hook / agent 模板 / Codex 适配变更，已部署项目需重新运行 `/story-setup` 并新开会话获取。`UPGRADING.md` 新增 v15 条目，`README` / `README_EN` 更新 v0.6.19 题词。

## v0.6.18

> OpenCode CLI 完整支持（#151）· 内置版本更新提醒（#173）· 对话机械化/论文腔修复（#171）· 续写文风漂移每章自检（#168）· 新名词锚点（#175）· AI 句式硬门槛与 detector 复扫（#166）· 封面平台尺寸裁剪兜底（#176）· Windows 中文系统 hook 字节稳定（#164）

### 新增

- **OpenCode CLI 完整支持（#151）**：新增 `skills/story-setup/references/opencode/` 适配层（`plugin.ts` 写正文前大纲守卫、13 个 command 包装、`AGENTS.md.tmpl`、`pre-commit.sh`、`opencode.json.patch`），`scripts/sync-opencode.py` 由 Claude agent 模板自动生成 opencode 副本并经 `.github/workflows/sync-opencode.yml`（check-sync）守卫；6 个写作 skill + story-setup 的 agent 检测同时兼容 `.claude/agents/` 与 `.opencode/agents/`，agent 参考路径解析增加 `.opencode/skills/` 步骤。
- **内置版本更新检查（#173）**：不新增 skill，把更新检查折进 `/story` 路由——主动「检查/更新版本」读 `skills/story/VERSION` 比对 GitHub latest release，提示 当前→最新 + Releases/CHANGELOG，由 AskUserQuestion 决定是否更新（只通知、不自动安装）；session-start 增加被动提醒（每 24h 至多一次、curl 5s 超时、全程静默兜底、`STORY_NO_UPDATE_CHECK=1` 可关，仅落后才提示）。被动提醒走 deployed hook，仅 Claude Code；主动检查两端通用。

### 改进

- **对话机械化/论文腔/不分场合修复（#171）**：`narrative-writer` 参考表接入 `dialogue-mastery`（按需读取），审查清单新增对话质量逐项（机械对话/角色科普嘴/说话不分场合）、新增「写完后对话自检」收尾步使对话检查每章必跑；写前意图确认（`story-long-write` 3.3 / `workflow-daily` 2.4）新增「③对话声线基线」按本章基调收敛（高压 beat→搞笑声线让位、信息型配角不当科普嘴、逐句承接对方情绪）；`story-review` Agent2（character-designer）新增对话三症状独立审查。`dialogue-mastery.md`（4 份同步）补「每句回应上一句情绪」「Gate G 同样管台词」「场合例外声线让位」。
- **续写文风漂移（逗号结巴体）每章自检（#168）**：`narrative-writer` 新增「写完后文风自检」收尾步，取目标句长带粗测本章句段长/碎句比，漂移即按目标带把碎句合并回中长句重写（以 `文风.md`/原文锚点为准，不模仿可能已漂移的上一章）；目标句长带快照钉进抗 compaction 的 `追踪/上下文.md` 新增「## 文风指纹」区（首次写作从 `文风.md` 快照填入、之后不变），自检优先据上下文指纹判漂，闭合长会话 compaction 后丢失文风路径的盲区。
- **新名词/设定首次出现给读者锚点（#175）**：`anti-ai-writing.md`（6 份同步）Gate G/模式8 自检后补反向制衡「删解释腔 ≠ 把读者读懵」——新名词/设定首次出现仍要靠角色动作反应/对话半句/场景物理后果一笔带出当下作用，不整段讲来历、也不甩零信息生词，并给「蓝晶」示例区分「锚 vs 解释」。
- **AI 句式硬门槛 + detector 复扫（#166）**：`narrative-writer`、写作 skill、review/deslop 流程把「先否定再肯定」翻转句式列为硬禁令（文风召回/对标模仿/Gate B 软规则都不能覆盖）；`story-deslop`/`story-long-write`/`story-short-write`/`story-review` 携带本地 `check-ai-patterns.js`，文件模式在预检/交付前 `node scripts/check-ai-patterns.js --check <正文文件…>` 复扫到 0；narrative-writer 无 Bash 工具时只报告已自检、不谎称已运行脚本。detector 收敛误报：`是`-类连词（只是/可是/于是…）、either-or「不是A就是B / 也是B」与句尾反问「…，是吗 / 是吧 / 是嘛」不再被当成翻转句式（4 份同步副本 + 回归用例）。
- **封面：强制收集笔名 + 平台尺寸由裁剪兜底（#176）**：`story-cover` Step 1 缺书名/笔名先 AskUserQuestion 补全、不留空；`GPT_IMAGE_SIZE` 降级为「目标比例提示」（实测多数中转/聚合代理忽略 size，对任意请求都返回约 2:3 竖图）；新增 Step 3.5 居中裁剪+缩放（crop-to-fill），不论出图比例都确定性裁成平台精确像素（番茄 600×800），不变形、不依赖代理是否认 size；提示词书名/笔名留中心安全区（inner ~85%）。

### 修复

- **Windows 中文系统 hook 字节稳定（#164）**：根治 GBK 区域编码两层坑——python stdout 恒 cp936（改 `sys.stdout.buffer.write`）；导出 GBK 下 gawk/sed/grep/bash 通配 mis-decode UTF-8（7 个 deployed hook 统一 `export LC_ALL=C`（python-safe 放置）、`common.sh` book-name sed 包裹、全角冒号改 `(：|:)` 交替、全角空格 U+3000 处理）。新增真 GBK 区域端到端 CI（ubuntu/windows/macos）+ 静态 locale-safety 守卫 + python `print()` 禁用。
- **字数统计错误（#170）**：修复字数统计；`narrative-writer` Gate E 增「具体字数表达校验」（禁止正文中未经脚本核验的「这五个字」式字数断言，改非数字表述）。

### 文档

- **精简 README OpenCode 注意事项（#179）**：README / README_EN 把 #151 引入的「OpenCode 已知差异」5 条 bullet 压成一行（安装发现 + 重启 + 首次自然语言触发 + 「部分 hook 行为有差异，详见 CONTRIBUTING」），实现细节统一回填 `CONTRIBUTING.md`（detect-gaps/session-end/validate-commit/browser-cdp ESC），指针名副其实不丢信息。

### 发布准备

- `CHANGELOG.md` 新增 v0.6.18 条目；`.claude-plugin/marketplace.json` metadata.version 0.6.17 → 0.6.18；`skills/story/VERSION` 0.6.17 → 0.6.18（更新检查锚点，须与 release tag 一致）。
- story-setup `setup_skill_version` 1.2.3 / `agents_version` 14（v0.6.17 之后已 bump，本次不变）。由于 templates/hooks/rules/references 更新（含 OpenCode 适配层、对话/文风自检、detector 复扫、被动更新提醒），已部署项目需重新运行 `/story-setup`，并在部署后新开 Claude Code 会话。
- canonical source 位于 `skills/**`、`scripts/**`、`CHANGELOG.md` 和 `.claude-plugin/marketplace.json`；根目录 `.claude/` 仍视为 ignored 本地部署镜像。

## v0.6.17

> 用户反馈专项：长篇细纲升级为章节蓝图（#162）· 语气标点谱系（#161）· story-setup v13 部署刷新 · 汇入 v0.6.16 之后的深度限知、正文元信息、拆文模块链、review 一致性、段落/主语节奏等修复

### 新增 / 改进

- **长篇细纲升级为章节蓝图（#162）**：`story-long-write` 的 `大纲/细纲_第XXX章.md` 保留旧字段（核心事件、目标情绪、章首/章尾钩子、爽点、字数目标），新增内容概括（起因/发展/转折/高潮/结尾）、情节安排（主线/辅线/事件线/感情线/逻辑线）、人物关系和出场顺序、情节细化、结尾设定和钩子。
- **日更与导入消费新版蓝图**：日更准备层会显式读取内容概括、多线安排、人物出场、代价/收益与章尾承接；旧版细纲缺新版字段不阻塞，补建/回填未知项统一写 `[待补充]`；`story-import` 只从证据反推新版字段，不编造副线或关系。
- **细纲蓝图上下游贯通（#162 下游细化）**：把已有 craft reference 接进日更写作/核对闭环，复用现有字段、零新概念——`内容概括` 发展/转折按 `plot-emotion-system` 倒推法做爽点铺垫（不铺=空洞）；`视角/信息差` 经 `出场顺序` 的在场配角放大成差异化反应（`plot-core-methods` 集体震惊）；`情节点功能标签` 即 `commercial-core-methods` 目的词，驱动展开/带过详略。落在 `story-long-write` 写前准备（3.3/2.4）+ 对照细纲核对（每条带修复动作），`story-architect` 模板同步叫法对齐；不新增字段/文件，旧细纲仍非阻塞。
- **短篇小节大纲轻量增强**：`小节大纲.md` 增加结构段/五段功能、人物/关系变化、因果/逻辑链、结尾承接/钩子等字段，但不套长篇完整章节蓝图，避免短篇流程变重。
- **术语白话化（去自造黑话，语义不变）**：把作者面向的晦涩自造/借用复合词换成白话——蓝图兑现→对照细纲核对、三维度织入→三维度揉进、镜头断段→画面分段、最简记忆包→本节速记、质量门控→质量检查、准备层→写前准备、角色位抽象→看成功能位、五重驱动→五项驱动、孤立情节兜底→散落情节兜底、结构物件→贯穿道具、三现编排→三次出现、few-shot→范例片段、目标函数→目标、字数探针→字数检查 等；保留 功能位/信息团/目的词/戏剧单元/疏密分配 等行业真实术语；跨 skill 字节同构副本同步，本地守卫全绿。
- **语气标点谱系（#161）**：writer references、`narrative-writer`、`story-review`、`story-deslop` 增加“标点服务语气/人物声线”的规则：质问用问号，爆发峰值少量感叹；犹豫/未尽/打断/拖长改用动作停顿、短句或换行处理，正文产物不再使用 `……` / `——`；同时明确禁止通篇句号化和随机标点堆砌。
- **story-setup v13**：`setup_skill_version` 升级到 `1.2.2`、`.story-deployed` 的 `agents_version` 升级到 `13`；`story-architect` 产出新版章节蓝图，`consistency-checker` 消费逻辑线/人物关系变化/出场顺序/代价兑现，session-start 对 v12 及以下提示重新部署。
- **v0.6.16 后已合入改进汇总**：包含写正文前细纲守卫与 subagent solo 降级修复（#148）、深度限知视角/去解释腔/情绪烈度（#147/#152）、正文中禁止章节元信息（#155）、副对标书数量放宽（#157）、story-review 推理型一致性检查（#158）、拆文→可复用写作模块链（#149/#156）、清理过期市场指导（#160）、段落/主语节奏自然化（#159）。

### 修复

- **skill 指令一致性（左右互搏收敛）**：统一 `story-long-write` 日更读取列表与 `workflow-daily.md` 中 `剧情/情绪模块.md` / `剧情/节奏.md` 的缺失措辞——明确 v12 新契约缺失停下修复、仅 legacy 回退，消除与权威「缺失文件回退」规则的冲突；`story` 路由的「查故事资料 / 查资料」改为先做轻量 agent 可用性检查，不可用时降级直接 Read/Grep 并标注 `Fallback: agent unavailable -> direct lookup`，不再无条件直接 spawn。
- **标点规范化器边界修复**：`normalize-punctuation.js` 对紧跟开引号 / 开括号（`「『（(“‘`）的 `……` / `——` 删空处理，修复 `「……你回来了。」` 被误改成 `「，你回来了。」`、`「……」` 被改成 `「。」` 的问题；句末拖长、数字区间、冒号落点等既有行为不变（4 份副本保持字节一致）。

### 发布准备

- `CHANGELOG.md` 新增 v0.6.17 条目；`.claude-plugin/marketplace.json` metadata.version 0.6.16 → 0.6.17。
- 由于 story-setup templates/rules/references 更新，已部署项目需重新运行 `/story-setup`，并在部署后新开 Claude Code 会话。
- 根目录 `.claude/` 仍视为 ignored 本地部署镜像，不作为发布源；canonical source 位于 `skills/**`、`scripts/**`、`CHANGELOG.md` 和 `.claude-plugin/marketplace.json`。

## v0.6.16

> 扫榜全平台健壮性实测修复：番茄书名全回退 `bookId:xxx` 修复 + 题材/标签扩采 · 点众/七猫/刺猬猫书名与作品页链接修复 · 黑岩错误态细分 · 晋江补详情页核心指标采集 · 全平台连通性自检/质量信号 · 拆解管道合法性语境 · 写作流程破折号过滤 · prompt-cache 优化

### Bug 修复（扫榜）

- **番茄扫榜书名全回退 `bookId:xxx` 修复**：根因是详情解码把整页约 20 本一次性同步 XHR 塞进一个 eval，撞 `cdp-utils.ab()` 的 20s 硬超时 → 静默返回空 → 每本回退 bookId。改为分批解码（每 5 本）+ 多策略解析（内嵌 JSON `bookName` / `<title>` / og:meta），并加连通性自检与「标题解析率 / 数据质量」文件头标注（#144）。
- **点众扫榜书名是 UI 文字/简介串 → 重写**：改为按 `bookId` 聚合 anchor 解析（书名取「书名+评分」anchor 去尾部 `X.X分`、简介取最长 anchor、作者/状态/字数从卡片文本），实测书名 10/10、作品页链接 10/10（#144）。
- **七猫 / 刺猬猫作品页链接几乎全失修复**：`extractBookUrls` 旧版按 bookId 取到的是排名数字 / 空封面 anchor 当书名导致回填失败；改为取最像书名的 anchor + 书名归一回填，实测链接 20/21、10/10；七猫频道 tab 点击失败自动重试一次（#144）。
- **黑岩扫榜错误态误报修复**：把「接口超时 / CDP 断」「401 未授权」「服务端错误码」分开报错，不再一律误报「认证失败」+ 套用 DOM 选择器话术；加书名命中率质量门，字段改名时拦截而非静默写 undefined（#144）。
- **拆解管道补材料合法性语境**：消除对用户自有作品的过度拒绝（#143）。
- **长篇写作流程破折号过滤**：自动过滤破折号 + 修正规范化器误伤合法破折号（#139 / #141）。

### 改进（扫榜）

- **晋江补详情页采集**：列表取书名 / 作者 / `novelid` 后进 `onebook.php` 详情页，用 `fetch + TextDecoder('gb18030')` 解出 `itemprop` 微数据（收藏 / 营养液 / 积分 / 字数 / 状态，公开指标无需登录）；受 `--top` / `--detail-limit` 控量，`--list-only` 可跳过（#144）。
- **番茄题材 / 标签扩采**：题材取详情页 `categoryV2` 首个 `Name`、标签取简介开头 `【…】`（番茄 SSR 无评分字段，已移除评分声明）（#144）。
- **全平台扫榜健壮性统一**：浏览器型脚本统一连通性自检（CDP 未起 / 被重定向 → 可操作报错，替代误导性「结构已变」）、复杂 eval 走 base64（消除 shell 转义隐患）、输出文件头加质量信号（链接 / 书名 / 标题解析率、详情命中率）（#144）。

### 性能

- **削减 prompt-cache miss**：`story-deslop` / `narrative-writer` / `story-long-analyze` 拆解管道的提示词缓存未命中优化（#142）。

### 说明

- 扫榜修复均经真站实测（隔离 headless Chrome 逐平台跑通）+ sandbox 测试（番茄 31 / 晋江 10 断言）验证；`cdp-utils.js` 未改动，跨 skill 双副本仍字节一致。
- 本地守卫（shared-files / static-check 等）全绿。
- marketplace metadata.version 0.6.15 → 0.6.16。

## v0.6.15

> 拆文 demo 全量重做（盘龙长篇 / 曾将爱意私藏短篇）+ 新增 story-import 长篇续写工程 demo · story-import 框架修正（交付物＝写作工程，移除 `[导入反推]`）· 拆文契约/门控补强 · story-deslop/story-review 标点规范化（盐言「」保持有效）

### 改进

- **story-import（交付物＝写作工程）**：开篇与原则 1 明确「交付物是可续写的写作工程」——`拆文库/` 是工程的一部分（喂给 `对标/`）、非用完即弃的中间产物；Phase 1 新增「1.0 确认意图」，用户意图不明时主动询问「建写作工程 vs 只要拆文库分析」并分流（只要分析直接走 `/story-long-analyze`）。
- **移除 `[导入反推]` 约定**：删除 story-import 原「原则 3：标注导入来源」及所有 `[导入反推]` 标记/校验项，不确定字段统一改 `[待补充]`（`SKILL.md` + `structure-mapping-long/short` + `character-state-reverse` 同步）。
- **story-long-analyze 拆文契约补强 + 基调/主题标签枚举扩展**（#136）。
- **story-short-analyze 门控/计数口径补强**：情节节点计数口径明确（复合合并共用一个 N 编号、密度校验按最终 N 编号总数计）；Phase 7.1 AI 腔自检补源文豁免规则（跳过 `>` 引用行与表格原文直引列，只扫分析师本人措辞）（#136）。
- **banned-words 最毒句式补变体**：「不是A，（而）是B」标注「而」可省、省掉也算命中（6 份同步副本一并更新）（#136）。

### Bug 修复

- **标点引导纠偏（Issue #133）**：`story-deslop` / `story-review` 各自内置确定性 破折号/分隔线 规范化器 `normalize-punctuation.js`（skill 内复制一份、不跨 skill 引用）；盐言短篇「」引号保持有效、不被全局判错；写作 references 的 prompt 示例去掉「把 em-dash 节奏当首选散文模式」的教学。

### Demo 与文档

- **拆文 demo 按新契约全量重做**：`demo/拆文库-盘龙`（长篇拆文）、`demo/拆文库-曾将爱意私藏`（短篇拆文，替换原文缺失的「影子拳手」demo）。
- **新增 story-import 长篇续写工程 demo**：`demo/让你管账号，你高燃混剪炸全网`——番茄前 20 章逆向重建为可续写工程（正文 / 设定 / 大纲 / 追踪 / 参考资料），可直接 `/story-long-write` 日更续写第 21 章。
- **README / README_EN**：新增三个 demo 展示块（短篇拆文 / 长篇拆文 / 长篇续写工程）+ 交流群与 Discussions 链接（#131）。

### 工程

- **check-shared-files 守卫同名 script 副本**：跨 skill 同名脚本（如 `normalize-punctuation.js`）强制字节一致，防止复制副本漂移。

### 说明

- 同名共享文件改动均按 `check-shared-files.sh` 字节同步到全部副本；本地五道守卫（shared-files / python-invocation / story-setup-deployment / hook-regex-sync / static-check）全绿。
- marketplace metadata.version 0.6.14 → 0.6.15。

## v0.6.14

> 细纲后自动补全新设定/角色（防设定漂移）· Windows `python3` 跨平台修复（Store 占位程序 exit 49）· SessionStart hook 中文化 · 文档纠偏（README_EN / CONTRIBUTING）· 工程守卫加固（python 调用 / 语法 / 共享文件精度）

### 改进

- **story-long-write（细纲后自动建档）**：Phase 3 细纲段新增「细纲后设定补全」——每批细纲建完后扫描会复用的新具名角色/势力/关键设定，自动建 `设定/角色|势力|世界观` 档案 + `追踪/角色状态` 初始条目。按卷纲/细纲判断是否复用，一次性路人不建档；已存在按细纲增量补充、不覆盖；只填细纲已确定信息、留占位符、不杜撰。产物映射表补 `设定/角色|势力` 行；单章流程 step 11 增补「正文里首次引入的会复用角色」按同规则建档。（Closes #123）
- **SessionStart hook 中文化**：`detect-story-gaps.sh` 与 `session-start.sh` 面向作者展示的输出改为中文（保留 `[WARN]`/`[INFO]` 级别标记与 `/story-setup` 等命令名），降低非技术中文作者每次会话开始的理解成本。
- **dialogue-mastery 语言差异化表补全为 7 维**：原表只有 5 行，与同文件自查清单及 character-designer agent 写的「7 维差异化」矛盾；补上「身份影响措辞 / 进度影响态度」两维，4 个字节同步副本（long-write / short-write / agent-references / story-review）一并更新。
- **文档纠偏**：`README_EN` 安装命令补 `-g` 全局参数 + 全局/局部说明，短篇结构块纠正为真实文件名（`正文.md` / `小节大纲.md` / `拆文库/`，删不存在的 `References/`），对齐 `README.md`；`CONTRIBUTING` 把 CI 描述纠正为实际的 4 个守卫脚本 + `node --check`。
- **story 路由（多书切换）**：新增「切换/列出书目」意图与多书切换流程（扫描含 `追踪/`、`设定/` 的书目录，写回 `.active-book`）。

### Bug 修复

- **Windows 下 `python3` 触发 Store 占位程序 exit 49（修复 #121）**：真因是 Windows 上 `python3` 解析到 Microsoft Store 的 App Execution Alias 占位程序，在非交互子进程（Claude Code 的 Git Bash）里静默 `exit 49`，与中文路径无关。所有文档化的「跨平台字数统计」`python3` 调用改为解释器探测（`python3`→`python`→`py` 选可用者）；`validate-story-commit.sh` 的 `command -v python3` 守卫换成实跑探测（占位程序会让 `command -v` 误判存在）。（取代 #122）
- **agent 模板枚举漂移修复**：`story-architect` 情绪弧线对齐 emotional-arc-design（V形/倒V形/W形/递进/延迟满足/急转）、章首钩子改「按开篇策略选类型」、删残留玄学公式；`character-designer` 对话权力模式改 压制/反转/心死（对齐 dialogue-mastery）。

### 工程

- **跨平台 python 守卫**：新增 `scripts/check-python-invocation.sh`（禁止 `skills/` 里裸调 `python3`，覆盖 `-c`/`-m`/`<<`/脚本路径，放行探测列表与说明文字）与 `scripts/test-charcount-portable.sh`（构造中文路径 + 已知字数断言，`--stub` 模式塞入 exit-49 假 `python3` 复现 Windows 故障并断言回退到可用解释器）；`cross-platform.yml` 三平台接入，Windows 用 Git Bash 跑 stub 测试。
- **CI 语法守卫**：`cross-platform.yml` static-check 新增 `node --check`，覆盖全部 `*-scraper.js` + `cdp-utils.js` + `setup-cdp-chrome.js`（此前 0 覆盖，语法回归可直接进主干）。
- **采集脚本健壮性（7 个 scraper）**：`writeFileSync` 前补 `fs.mkdirSync(OUTDIR,{recursive})`（`--outdir` 指向不存在目录不再 ENOENT 丢数据）；裸 `main()` 统一包 try/catch + `process.exit(1)`；fanqie 额外补 per-category / per-channel try/catch（单品类/单频道失败不中断整轮）。
- **check-shared-files 精度提升**：`character-basics` / `character-design-methods` / `character-relations` 此前被整体豁免、漂移不报警；改为只排除 story-short-analyze 那份（带分析师视角 header 的有意分叉），其余副本仍强制字节一致，恢复对 writer↔writer 漂移的守卫。

### 说明

- 同名共享文件改动均按 `check-shared-files.sh` 字节同步到全部副本；三平台 CI 守卫全绿。
- `story-deslop` rubric 收紧仍在分支开发中，留待后续版本。

## v0.6.13

> write skill references 一致性修复 + 抽象概念可落地化（补真实网文例子 / 删黑话比喻）+ 同 skill 去重（指针化）+ agent 模板枚举漂移修复

### 改进

- **抽象概念可落地化**：两个 write skill 的理论 reference 把「只有定义没法照着写」的元概念补上具体网文例子或删掉空话——plot-emotion-system 提炼层级补「追妻文逐级抽象 + 换壳」贯穿例；plot-frameworks 故事构型补「萧炎打脸」例 + 小说四维自检改通俗四项 + 螺旋并线补可操作定义；style-commercial-theory（已改名）艺术化/极端化/代偿/观念错位/套路五写各补例；plot-core-methods 信息团 / 谜语人vs伏笔 / 升级三维度 / 金手指升华 补判据与例；emotional-arc-design 删「故事 = 情绪 × 世界」玄学公式、改三层情绪例；outline-structure-theory 选幕依据从悲剧体裁术语改按题材、删根/干/枝比喻列与八条线 placeholder；style-craft 删写意/神韵审美黑话；short genre-* 补基调自查/恋爱磨合/跨题材融合例并删修仙三境界等口号。
- **一致性修复**：短篇反转信息差阈值统一为 writing-workflow 三档（villain-and-reveal 改指针）；对话占比统一 45-65%（genre-writing-techniques 两处）；workflow-revision Step3 编号修复；SKILL 横切表 anti-ai-writing 括注改真实小节名 + 补「对话」行；long SKILL 两处锚点名对齐正文。
- **同 skill 去重（指针化）**：权力博弈对话（writing-craft→dialogue-mastery）、角色状态模板（artifact-protocols→state-tracking）、五幕式（plot-frameworks→outline-structure-theory）、阵营手牌法（plot-frameworks→plot-special-topics）各定单一真相源 + 同 skill 内指针，删重复块（净减约 130 行），不跨 skill 引用。
- **命名去误导**：`style-commercial-theory.md` → `commercial-core-methods.md`（全文讲卖点/商业策略不讲文风）；`format-and-structure.md` 标题「短篇格式规范」→「正文格式与小节结构」（承载全体裁通用排版硬规则，4 副本同步）。
- **F1 地图分层**：plot-core-methods 点明「新手村四势力（全量框架）vs 换地图三势力（精简版）」是分层而非矛盾，并提示换地图别丢变现/资源闭环渠道（3 副本同步）。
- **opening-design 短篇适配**：short SKILL 路由处注明「前3章」读作开篇首节~前1/3、七步法按目标字数等比缩放（不改字节锁定的 opening-design 本体）。

### Bug 修复

- **agent 模板枚举漂移**：story-architect 误导技巧「情感引导」→「情绪引导」、反转类型 5→7 补「认知/无反转」（与 reversal-toolkit 及拆文 `_meta.json.reversal_type` 契约对齐）；character-designer 关系命名「结盟型/权力型」→「联盟型/权威型」（与 character-relations 对齐）。

### 说明

- 同名共享文件改动均按 `check-shared-files.sh` 字节同步到全部副本；三道守卫（check-shared-files / static-check / check-story-setup-deployment）全绿。
- 暂缓项（需后续单独定方向）：`check-shared-files.sh` IGNORE 逻辑细化（character-* 在 write 侧已字节相同却被整体豁免，应改「按 skill 对」豁免，分类清单已备）、agent 模板少数 canonical-conflict 枚举（章首钩子7式 / 情绪弧线6种 / 语言风格5vs7维 / 对话权力模式）、agent 模板薄索引去重。

## v0.6.12

> 选题决策（开方）：扫榜→可行性判断→爆款原因假设→拆文回填 · references 按主题索引 + 检索可验证 · 女频长篇 playbook · 术语白话化（去自造比喻）· 工程守卫（CI 增检查 + 采集脚本健壮性）

### 改进

- **story-long-scan（选题决策）**：Phase 4 从「在对话里匹配」升级为产出持久的 `选题决策.md`——按「选题四步」给 2-3 个推荐选题（能爆的原因[待拆文验证] / 市场验证 / 差异化定位 / 可行性高·中·低 + 失败风险 + 验证动作 / 篇幅平台）。可行性按现有 `[数据稀疏]`/<15 样本门控封顶（样本不足不给「高」），内置知识模式一律「中」。方法见新增 `references/topic-decision.md`。
- **story-long-analyze（爆款原因回填）**：Stage 5 汇总报告产出后，若项目根有 `选题决策.md`，按题材关键词匹配回填对应选题的「能爆的原因」（引用本书 写法技巧/可借鉴套路/核心机制，标注为单本假设级支撑）；多匹配问用户、无匹配静默跳过、已填不覆盖。锚定 Stage 5 终态，不受 Stage 6（文风，失败容忍）影响。
- **story-long-write（消费选题）**：Phase 1 先查项目根 `选题决策.md`——存在则以可行性最高的选题为开书起点 + 看扫榜日期提示数据新鲜度；缺失则提示路径后回退原有选题提问。
- **story-long-write / story-short-write（按主题索引）**：两个 write SKILL.md 新增「按主题快速定位」横切主题索引（爽点/情绪/节奏/高潮/金手指/感情线/反转/人物/去AI味），每主题给一个权威文件 + 配套文件；爽点按「设计/翻盘/打脸/题材公式」意图分流。检索提升经 A/B 实测（带索引 vs 不带）。
- **story-long-write（女频长篇）**：新增 `references/female-audience-writing.md`——女频核心原则、文案结构、长线题材骨架、卷级感情节奏、多平台（番茄女生/起点女生/晋江/七猫）写法定位。
- **流程衔接补全**：story-setup、story-review 补「流程衔接」段（封面/浏览器工具等边缘 skill 不强加）；story `选题决策` 路由 → story-long-scan。
- **story-short-write**：`output-contract.md` 接入 Phase 2「对标上下文加载」+ 参考资料表（原为孤儿文件）。
- **术语白话化（去自造比喻）**：可行性灯→可行性高/中/低、开方/处方→选题建议、爆款基因→能爆的原因、粗/细格栅级→直述追踪粒度、逻辑闭环→前后能圆回来、状态语义→状态含义、新范式→新玩法、解构/原子事件→拆解/最小情节点、地图颗粒度→地图详略、好感度×关系阶段矩阵→对照表；`source of truth`→数据源、`Artifact`→产物；story-import `管线`→`管道` 统一。
- **README**：结构整理——list 化核心思路、前置项目文件结构、收拢知识体系段。

### 工程

- **CI**：`cross-platform.yml` static-check job 增加 `check-shared-files.sh`（跨 skill 同名副本一致性）+ `check-story-setup-deployment.sh`（部署完整性）守卫——此前仅本地运行，副本漂移可直接进主干无人拦。
- **采集脚本健壮性**：5 个排行榜采集脚本（刺猬猫/晋江/七猫/点众/黑岩）补错误处理——逐项 try/catch（单条失败不中断整轮）、页面结构变化时给明确「采集失败：页面结构可能已变」提示、中途失败已采部分仍落盘。纯 Node（fs/path/console），三端通用。

## v0.6.11

> story-short-analyze 输出契约 + Phase 7 门控验收 · 多对标书跨书召回（cross-book-recall）· write skill references 内容整理：反转类型对齐拆文枚举 + 跨书字段映射 + 去重瘦身

### 改进

- **story-short-analyze（短篇拆文）**：新增 `references/output-contract.md` 定义 analyze→write 输出契约——Stage→文件映射、`_meta.json` schema（含 `structure_counts`：beats/hooks/setup_clues/character_archetypes/reusable_structures/reversal_type）、下游消费规范。双副本与 story-short-write byte-equal，`scripts/check-shared-files.sh` 守护。拆文产物维持旧 3 文件名（拆文报告.md / 情节节点.md / 写作手法.md），不触及 story-short-write 既有读取。
- **story-short-analyze**：Phase 1 加字数探针（`<15000` 短篇 / `15000-20000` 灰区询问 / `>20000` 建议改长篇）+ lightweight resume（读 `_meta.json.last_stage_in_progress` + `stages_completed` 续跑）；题材识别扫不到时显式填 `genre_detected="通用"`。
- **story-short-analyze**：新增 Phase 7 门控验收——(7.1) 拆文报告 AI 腔自检；(7.2) `structure_counts` 数值/枚举校验（beats≥4 结构段、hooks≥3、reversal_type 在 7 枚举内）；(7.3) `output-templates.md` BLOCK 项扫描。`beats` 明确为结构段数（开端/发展/高潮/结局），情节节点 15-60 密度校验仍归 `情节节点.md`。`reversal_type` 枚举含「无反转」，甜宠/喜剧/报应型不被误伤（setup_clues 跳过阈值）。
- **story-short-analyze**：8 份 genre/character reference 注入「## 用作拆文标尺时」分析师视角 header（仅 analyze 侧分叉，`IGNORE_NAMES` 标注 intentional，不 cascade 进 writer）。
- **story-long-write / story-short-write（跨书召回）**：新增 `references/cross-book-recall.md`——项目根 `拆文库/` ≥2 本时启用多对标书跨书召回。三道防线：①副对标 `文风.md` 不读 ②角色/剧情/设定 模块只主对标 + 1 本同题材副对标 ③narrative-writer 输入只主对标。跨题材相关度由 agent 读「题材类型」字段自决（同题材/弱相关/不相关），不维护索引、不引入题材标号。长篇 4 个 + 短篇 2 个 HTML anchor 触发点，sync-source byte-equal 双副本。
- **story-long-write / story-short-write（references 内容整理）**：`reversal-toolkit.md` 反转类型 5→7，补「认知反转」（追妻/世情主力——全程恨结尾翻成爱）「无反转」（甜宠/喜剧/报应型，走甜度递进或报应兑现），与 analyze `_meta.json.reversal_type` 七值枚举字面对齐。`cross-book-recall.md` 加「拆文字段→写作参考」映射表（structure_counts 各字段回查对应 reference）。
- **story-long-write**：`narrative-units.md` 并入 `plot-emotion-system.md`（提炼层级零-四级 + 常见误区迁入，情绪模块/戏剧单元/卡片去重），减一份文件。

### Bug 修复

- 修复 story-short-analyze `beats≥4` 门控形同虚设——原注释标「情节节点数」但情节节点真实下限 15-60，门控永远通过；改为「结构段数」语义，阈值与定义对齐。
- 修复 story-short-analyze `reversal_type` 硬阻断会误伤无反转题材（甜宠/喜剧/报应型）——枚举补「无反转」并豁免 setup_clues 阈值。
- 修复 story-short-analyze 字数探针边界 `15000` 重叠（`≤15000` 与 `15000-20000` 都含 15000）——改非重叠 `<15000 / 15000-20000 / >20000`。
- 修复 cross-book-recall 触发条件与 `workflow-daily.md` 优雅降级口径冲突——主对标书字段缺失统一为「字典序第一本并提示」，不 fail-fast。
- 修复 story-long-write SKILL.md「五种反转类型」section-anchor 在 reversal-toolkit 改 7 类后静默失效——锚点同步为「反转类型」。
- 清理 story-short-write `style-craft.md` 孤儿（SKILL.md 0 引用、无 agent load；long-write 副本保留仍用）。

### 验证

- `scripts/check-shared-files.sh` 全过：output-contract.md / cross-book-recall.md / reversal-toolkit.md 各副本 byte-equal，0 mismatch。
- `scripts/static-check.sh` 13 skills 0 fail；`scripts/check-story-setup-deployment.sh` 通过（reversal-toolkit 3 副本含 agent-references 同步）；macos / windows / static-check 三套 CI 全绿。
- reversal_type 七枚举（视角/身份/动机/时间线/信息/认知/无反转）在 reversal-toolkit / output-contract.md / output-templates.md 三处字面一致。
- cross-book-recall 映射表字段名与 output-contract `structure_counts` 逐字匹配；narrative-writer agent prompt schema 零改动（`git diff` 确认）。
- 能力锚点回归：reversal-toolkit 原 5 类设置/揭示步骤未动；narrative-units 的「提炼层级」「戏剧性会磨损情绪不会磨损」「重构/微调」「常见误区」已进 plot-emotion-system；删 style-craft 前确认 short-write 0 live 引用。

## v0.6.10

> story-long-analyze 拆解管道修正 + 拆文产物按主题拆分 + 下游 story-import / story-long-write 同步对齐 · story-deslop rubric 收紧 + 禁用句式批量导入 · 对标书产物术语作者化

### 改进

- **story-long-analyze（长篇拆文）**：情节点下限统一到 10（原 SKILL.md 路由层与 chapter-extractor 校验层不一致：路由说 3-40，校验说 10-40——短章会被静默拆得过细或过粗）。5 处漂移位点全部对齐到 10-40。
- **story-long-analyze**：Stage 6 文风提取的句长/标点统计从「眼测」改为 `python3` 切句脚本（按 `[。！？]` 切句、桶化短/中/长句、统计标点密度）。Stage 6 由主线程跑，Bash 工具可用；句长 confidence 从 low 升到 high。
- **story-long-analyze**：Stage 4 拆为 4a / 4b / 4c——设定（世界观/金手指/势力）与 Stage 3 并行（数据源是 Stage 2 章节摘要 + 情节点，不依赖 Stage 3）；角色完整档案、角色关系串行依赖 Stage 3 合并后的角色实体。修正原并行图把「角色构建」放在 Stage 3 旁边的错误。
- **story-long-analyze**：概要.md 拆分两版——Stage 0 写 ~200 字 thin first-pass（基于章节标题 + 抽样开头/结尾），Stage 5 用完整剧情信息写 500-1000 字全书概要，覆盖 Stage 0 的首版。避免 Stage 0 在没读完全书的情况下硬凑高密度概要。
- **story-long-analyze**：新增 Stage 0.5 章节边界表，写入 `_progress.md`（`schema_version: 2`）。Stage 1/2/6 全部从该表取章节切片，不再各自跑 regex。旧 `_progress.md` 续跑时走 lazy migration——现场跑一次正则重建并写回，不破 `paused_after_stage1` 契约。章节正则补 `千` / `两`，支持 1000+ 章长篇。
- **story-long-analyze**：chapter-extractor 默认 haiku，质量校验失败（情节点 < 10、原文引用缺失、类型/基调超出枚举、角色名为昵称等 9 条自检）→ 主线程用 sonnet 重 spawn 一次。两份 chapter-extractor 模板（`.claude/agents/` + `skills/story-setup/.../templates/agents/`）内容对齐到自包含版本（不再引用 `output-templates.md`）。
- **story-long-analyze**：Stage 4 设定按主题拆分多文件输出——`设定/世界观/{背景设定,力量体系,地理,金手指}.md` + `设定/势力/{势力名}.md`，与下游 story-import / story-long-write 项目结构对齐，下游不再做 re-split。
- **story-import（已有小说导入）**：3.5 拆分步骤识别两种拆文库形态——`设定/世界观/` 子目录存在则 pass-through；只有单文件 `设定/世界观.md` 则走原 re-split 逻辑（早期拆文库或手动写的兜底）。
- **story-long-write（长篇写作）**：单章准备层读取路径从 `设定/金手指.md 或 世界观.md` 改为 glob `设定/世界观/*.md`，回退到单文件 `设定/世界观.md`、再回退 `设定/金手指.md`，全缺失则跳过不阻塞。项目结构文档同步更新到按主题拆分布局。
- **story-deslop（去 AI 味）**：rubric 全面收紧 + 从两份高信号来源 prompt（prompt_11257 / prompt_78650）批量导入禁用句式。Gate B 新增「不是 A，而是 B」「声音不大，却带着……」并把「如同」并入 仿佛 / 犹如 / 宛若 家族；新增「修饰词清扫」子块（形容词 / 定语 / 副词 / 指示代词 / 量词）；Gate C / D 把「重复语义」拆成 4 桶（形容词 / 近义词 / 含义 / 上下文主语）+ 加「多余场景 / 人物 / 物品描写」子块；Phase 4 报告加「字数协议」（原文 / 修订后 / 净变化 / 上限）+ 3 轮 stop rule + 「再检一次」尾检；Phase 4 明确文件路径模式——直接走 Edit / Write，对话里只 emit ≤200 字样本（避免长章节重发）；narrative-writer spawn 加 anti-recursion guard；明确「嵌入式提醒」模式仅 Phase 1+2。
- **story-deslop**：banned-words.md 新增「最毒禁用句式」表（毒级 ★★-★★★★★，仅来自两份 source prompt）；一级禁用补充 `如同` / `不容置喙` / `冰冷`；新增「书面腔→口语化」mini-table；新增「比喻分类」表（5 类，来自 prompt_78650）。anti-ai-writing.md 把「段落是否超过 3 句」改为网文段落规则（一句一段，≤4 分句，per prompt_78650）。6 份共享 reference 副本全部同步（涵盖 story-deslop / long-write / short-write / short-analyze / review / story-setup）。
- **story-setup / 日更文档（术语）**：Stage 6 产物在日更文档和 setup agent 模板里的称呼统一从「文风画像」改成 `文风.md`；把实现层的 metadata 语言换成作者向的「生成记录」契约。既有 agent JSON 字段保持兼容。
- **output-templates.md（小修）**：清掉 Stage 6 模板末尾的尾部空白，恢复 `git diff --check` 干净（writer-friendly 术语合并的遗留）。

### Bug 修复

- 修复 story-long-analyze 情节点下限漂移导致短章被过细切（路由层 3，校验层 10）。
- 修复 chapter-extractor 两份模板内容已经悄悄不一致（一份说「输出对齐 output-templates.md」，另一份说「不依赖外部模板」）。
- 修复章节正则 `第[一二三四五六七八九十百零0-9]+章` 对 1000+ 章长篇（盘龙 / 诡秘之主等）匹配失败的截断问题。
- 修复 story-long-write 日更循环读 `设定/金手指.md 或 世界观.md` 的扁平路径——拆文产物已经按主题拆到子目录后，这条扁平读取会 ENOENT 静默失败。
- 修复 story-deslop 英文触发词 `deslop` 与 `/oh-my-claudecode:ai-slop-cleaner` 冲突——删除该触发词避免误路由。
- 修复 story-deslop 综合判定规则 off-by-one：「五项 → 六项」（评估表实际包含 6 个指标）。
- 修复 story-deslop 「15% 上限」陈述与「分级删除上限 15/25/35%」不一致——统一改为「对应等级上限」。
- 修复 story-deslop Phase 1 报告的 排比 sample 归类错误（节奏 → 句式，对应 Gate B 而非 Gate D）。
- 修复 story-deslop 三遍法 ↔ Gate 的 1:1 映射叙述错误——实际是 overlap，重写为诚实的 overlap 表述。

### 验证

- F-codes（F1a/F1b/F2/.../F7）和 plan 上下文（`#F3-defer`）等开发期符号不外泄到 skill 文件——`grep -rn` 在 `skills/` 和 `.claude/agents/` 下 0 命中。
- 情节点下限：`3-40` 在 `skills/story-long-analyze/` 和两份 chapter-extractor 副本下 0 命中；`10-40` 在期望的 6 处全部命中。
- `python3` 切句脚本本地用真实中文小样本跑通：`sentences=6; short_lt15=66%; mid_15to30=33%; long_gt30=0%; avg_len=12; punct_density=15%`。
- 章节正则补全 character class 含 `千` + `两`：`grep -F` 在 `style-profile-generator.md` 行 55 唯一命中。
- 两份 chapter-extractor 副本 `diff -q` 空输出，byte-identical。
- 跨 skill 读取路径审计：story-long-write 已无扁平 `设定/世界观.md` / `设定/金手指.md` 单点读，全部走 glob + 回退链；story-import 既能 pass-through 新版子目录形态，也能 re-split 单文件版本。
- `_progress.md` 4 个状态值（`pending` / `paused_after_stage1` / `completed` / `completed_with_errors`）在 `pipeline-ops.md` 全部保留，无回归。
- `scripts/check-shared-files.sh` 全过（story-deslop 改动涉及 6 份共享 reference 副本，banned-words.md / anti-ai-writing.md 跨 skill 同步）。
- `scripts/check-story-setup-deployment.sh` / `scripts/static-check.sh` 通过；macos / windows / static-check 三套 CI 全绿。
- 「文风画像 → 文风.md」术语统一：日更文档与 setup agent 模板审计通过，既有 agent JSON 字段兼容性保留。

## v0.6.9

> story-cover 协议修复 + browser-cdp 同意握手 + story-review / story-setup 可靠性强化

### 改进

- **story-cover（封面生成）**：`images/edits` 流程改回正确的 `multipart/form-data` 形式（原 JSON-with-URL 仅在 yunwu 代理下歪打正着，对 OpenAI 直连必失败），文本字段用 `--form-string` 避免 `@` 前缀被误判为文件引用；自动版本号 `封面_v1/v2.png` 不再相互覆盖；落地 `.prompt.txt` 与 `.ref.txt` 旁注便于迭代；强制 `BOOK_DIR` / `PROMPT` 入口校验；`jq -n --arg` 拼 JSON 体规避中文/引号/换行的 shell 转义陷阱；`jq -er '.data[0].b64_json // empty'` 配合 `-s` 检查杜绝把 `"null"` 解码成 3 字节假 PNG；`jq`、`base64` 加入 `openclaw.requires.bins`。
- **story-cover**：删除已与 `references/cover-styles.md` 漂移的平台风格副本表，统一以参考文件为单一来源；新增 Step 1.5「题材判定」明确关键词命中 + 多匹配优先级 + 零命中默认都市的确定性规则；`API 配置` 段重写为环境变量速查表。
- **browser-cdp（浏览器操控）**：`setup-cdp-chrome.js` 在杀掉用户 Chrome 前先做明确的同意握手——TTY 走 readline 询问，skill 模式以 exit 3 + `NEEDS_CONSENT` 行回到 Claude Code 由 `AskUserQuestion` 询问，再以 `--yes` 显式确认。重排 `main()` 确保 Profile 复制在 Chrome 进程退出之后，避免 SQLite 写锁中复制导致 cookie 静默撕裂。
- **browser-cdp**：cookie 路径全覆盖（旧 `Default/Cookies` + 新 `Default/Network/Cookies` + `Login Data For Account`）；启动加固——端口校验、`--remote-allow-origins`、`--no-first-run`、`SingletonLock` 清理、超时后孤儿进程回收；新增 `--detect-only` / `--reset` / `--profile` 选项。
- **story-review（多视角审查）**：模式预检 + Agent 缺失/异常/过旧/启动失败的安全 solo 回退；reference 文件不可读时使用内置 rubric fallback；spawn 失败不再让 full/lean 半成品审稿继续；报告附带可机器校验的元数据。
- **story-setup（环境部署）**：sentinel v9 元数据 + 项目内 reference 路径双重校验；hook 包自包含化；新增 `scripts/check-story-setup-deployment.sh` 与 `scripts/check-hook-regex-sync.sh` 兜底回归。

### Bug 修复

- 修复 story-cover 在 `images/generations` 请求体中带 `response_format: b64_json` 的兼容性问题——`gpt-image-2` 始终返回 base64，该参数已被 gpt-image 系列拒收。
- 修复 story-cover 在 `BOOK_DIR` 未设置时静默落地到 CWD、`PROMPT` 未设置时报 `unbound variable` 等不友好行为，改为带说明的 `:?` 报错。
- 修复 browser-cdp 在不询问用户的情况下直接杀掉 Chrome 的破坏性默认。
- 修复 story-review 在用户项目尚未运行 story-setup 时直接失败而非降级 solo 模式。
- 修复 story-setup 短篇/长篇项目根目录解析在某些路径下不稳定的问题。

### 验证

- story-cover：双 bash block `bash -n` 全过；`jq -n --arg` 拼接含中文/引号/换行的 prompt 校验通过；`curl --trace` 证实 `--form-string` 不把 `@` 前缀当文件引用；端到端打 `yunwu.ai/v1`，文生图 2.9 MB / 图生图 3.1 MB 两个 1024×1536 PNG + 旁注文件齐全。
- browser-cdp：本地 fixture + Claude Code skill 模式 `NEEDS_CONSENT` 回环验证。
- story-review：tmux + Claude Code `/story-review` 单飞回退与 deployed-agent 满编 smoke 全过；3 个独立 read-only sub-agent 审查 + 1 轮 re-review 通过。
- story-setup：`scripts/check-story-setup-deployment.sh` / `check-hook-regex-sync.sh` / `check-shared-files.sh` / `static-check.sh` 全过；hook 模板 `bash -n` 全部通过。
- `claude plugin validate` 通过；GitHub CI：macOS / Windows / static-check 全绿。

## v0.6.8

> story-import 重构 + skill 自包含化 + 起点扫榜与 story-review 子 Agent 修复

### 改进

- **story-import（导入已有小说）**：按篇幅自动分流。长篇走 story-long-analyze 6 阶段管线 + 长篇结构迁移；短篇走 story-short-analyze + 短篇结构迁移（单文件 `正文.md`，不产 `追踪/`、`大纲/` 等长篇专属目录）。判定优先级：用户声明 > 章节结构 > 字数兜底 30000。
- **story-import**：长篇新增「角色状态反推」7 步算法，从拆书产物反推 `追踪/角色状态.md`，不重读原文。补齐 story-long-write 日更准备层依赖的角色状态文件，避免导入书永久走兜底分支。
- **story-import**：调用 story-long-analyze 时自动越过 Stage 1 停靠点，以「完整拆解、一次跑完、不要停下询问」模式驱动，确保 Stage 2-5 全套产物落地；停靠询问不透传给用户。
- **story-import**：skill 自包含化。原先跨 skill 引用 story-long-write / story-short-write 的 references（22+ 处 `../` 路径）全部清除——迁移所需模板（关系/题材定位/卷纲/角色状态）内联到 story-import 自己的 reference 文件，叶子引用文件（state-tracking.md、format-and-structure.md）以本地副本管理。

### Bug 修复

- 修复 story-review 子 Agent 读取 `quality-checklist.md` 等参考文件时按当前目录解析导致找不到的问题：story-review prompt 与 story-setup Agent 模板统一使用本 skill 内复制的 references 规范路径，并将 `agents_version` 升级到 v8 以提示既有项目重新部署。
- 修复起点中文网扫榜在 PC 站触发风控页时无法采集的问题：`qidian-rank-scraper.js` 默认改为移动端 SSR pageContext 抓取，并保留 CAPTCHA/CDP 回退。

### 验证

- story-import 篇幅分流、角色状态反推、跨 skill 引用清零均经独立验证；`scripts/static-check.sh` 13/13 PASS，`scripts/check-shared-files.sh` 0 mismatches。
- story-review / story-setup Agent 模板路径审计通过。
- 起点畅销榜实时采集成功并生成 Markdown。
- `node --check skills/story-long-scan/scripts/qidian-rank-scraper.js`
- GitHub CI：macOS / Windows / static-check 全绿。

## v0.6.7

> 拆书 skill 重构：长篇双模式合并 + 短篇去模式化

### 改进

- **story-long-analyze（长篇拆书）**：「快速 / 深度」双模式合并为单一拆解管道。「快速」不再是独立模式，而是管道跑完黄金三章（Stage 1）后的可停靠交付点——产出 `快速预览.md` 并询问是否继续全量拆解。确认后从 Stage 2 续跑，不重跑已完成阶段；`快速预览.md` 与终态 `拆文报告.md` 字段向上兼容。
- **story-long-analyze**：文档单一事实源。质量阈值、分块策略统一归 `material-decomposition.md`；运维内容（`_progress.md` 模板、错误处理、恢复机制）拆出为独立的 `pipeline-ops.md`。
- **story-short-analyze（短篇拆书）**：砍掉「标准 / 精细」双档，统一为单一全量拆解。双档在实操中无人遵守，连示范 demo 都没按标准模式产出。
- **story-short-analyze**：质量阈值收敛到唯一权威文件；管道阶段术语 `Phase 2-6` 对齐为 `Stage 2-6`，与长篇 Stage 体系一致；新增原文备份前置步骤。
- 黄金三章深度拆解产物由单文件拆为三个单章文件 `第N章_深度拆解.md`。
- 同步更新下游 skill：story-long-write、story-import、chapter-extractor agent 模板的拆书术语与文件名引用。

### Bug 修复

- 修复 `story-short-write` 指向「自检模式 / 拆文模式」的悬空引用——这两个入口在 story-short-analyze 中并不存在。
- 修复短篇拆书情节节点密度在三处文件给出不一致数值的问题，统一到唯一权威的字数分档表。

### 验证

- 长篇、短篇拆书各经独立验收，发现的问题已修复。
- 长篇新管道用《盘龙》开篇 23 章端到端实跑，Stage 1 停靠点、断点续跑、字段向上兼容均跑通。
- 全仓旧模式术语（快速模式 / 深度模式 / 标准模式 / 精细模式 / 自检模式）零残留。
- GitHub CI：macOS / Windows / static-check 全绿。

## v0.6.6

> 日更续写稳定性 + 伏笔 hook 降噪

### Bug 修复

- 修复长篇 `/story-long-write 日更` 在多次会话后，同一批次内用户回复“继续”可能跳出 `workflow-daily.md`、直接进入正文续写的问题。
- 修复日更流程偶发绕过真实项目文件、依赖聊天记忆写作的问题：每章开始前必须确认读取本轮 workflow 内的细纲、上一章正文、上下文、伏笔、时间线和角色状态/设定。
- 修复 SessionStart hook 把正常开放伏笔（`未埋` / `已埋`）当成问题提示，进而诱发全量伏笔审计和 token 膨胀的问题。
- 修复 `workflow-daily.md` 中裸 `SKILL.md` section 描述被本地 static-check 误判为断裂 section 引用的问题。

### 改进

- **story-long-write**：日更批量写作中，“继续 / 续写 / 日更”统一解释为继续当前 daily workflow，不重新进入场景选择，也不跳过状态筛选和意图确认。
- **workflow-daily**：正常批量执行时不再逐章询问“是否继续”；仅在细纲缺失、章节号冲突、请求范围超过已有细纲、用户要求改大纲/追踪等真实阻塞时暂停确认。
- **伏笔处理**：日更流程只处理本轮新增、推进、回收的增量伏笔；全量伏笔审计只由 `/story-review` 或用户明确要求触发。
- **story-setup**：`agents_version` 升级到 v7，既有项目重新运行 `/story-setup` 后可获得新版 hook/agent/rule。
- **CI/脚本**：`check-hook-regex-sync.sh` 从静态正则覆盖检查升级为行为级 fixture 校验，验证正常开放状态不报警、`已过期` 和异常状态报警。

### 验证

- `git diff --check`
- `bash scripts/check-hook-regex-sync.sh`
- `bash scripts/check-shared-files.sh`
- `bash scripts/static-check.sh`
- GitHub CI：macOS / Windows / static-check 全绿
- tmux + Claude Code 场景实测：构造 42 章长篇项目，执行 `/story-long-write 日更` 写第43章，再回复“继续”写第44章；两轮均保持在 daily workflow，读取必需上下文/伏笔/时间线/角色状态，未触发全量伏笔审计。

## v0.6.5

> 写作去 AI 味密度修复 + 对标路径说明统一

### Bug 修复

- 修复 Claude/Opus 4.7 下旧“三层展开”提示容易诱导的叠加式描写：同一动作/情绪不再按发生、感知、反应拆成多段重复描写
- 修复三维度织入后一段到底的问题：新增镜头断段、手机阅读密度和输出前密度重排规则
- 修复 Windows + DeepSeek/Claude Code 组合中字数统计偏差：优先使用 Python 字符统计，`wc -m` 仅作 macOS/Linux 备选，禁止模型估算和 `wc -c` 字节数

### 改进

- **story-short-write / story-long-write**：正文写作改为“三维度织入”，并明确按新动作/新物件/新信息/新对话断段
- **story-deslop**：将“重复描写去重”纳入 Gate C/D，不再用专项门禁堆叠规则
- **story-long-write / chapter-extractor / story-long-analyze**：长篇情节点密度统一为 150-200 字/个情节点，每章下限 10 个、上限 40 个
- **story-setup**：agents_version 升级到 v5，narrative-writer 模板同步新版场景写法、段落密度和跨平台字数统计规则
- **story-short-write**：统一短篇 `对标/` 与 `拆文库/` 路径说明：项目根 `拆文库/` 为原始产出，短篇目录 `对标/` 为当前作品引用视图

### 验证

- `git diff --check`
- `bash scripts/static-check.sh`
- `bash scripts/check-hook-regex-sync.sh`
- tmux + Claude Code 场景实测：对比旧三层、三维度织入、镜头断段和密度重排后的段落/句长指标

## v0.6.4

> 产线思路统一 — 核心思路集成 + 文件系统 + 准备层

### 新功能

- 新增 **state-tracking.md** 状态追踪协议文件（双 skill 共享）：最简记忆包提取逻辑（当前状态/历史因果/世界约束）+ 角色状态快照格式

### 改进

- **story-long-write SKILL.md**：
  - 新增"核心方法"section（4 条原则：先定情绪、验证过的模式、模块组装、只加载必需信息）+ 情绪-题材对照表
  - Phase 1 首问从"写什么类型"改为"让读者什么感觉"
  - Phase 2 开头加入"从目标情绪出发"和"角色位抽象"引导
  - Phase 3 大纲三检升级为四检（首条为情绪交付），细纲新增"目标情绪"字段
  - Phase 4 准备层前加入方法引导，写作技巧表新增"情绪验证"行
  - Phase 5 从单一检查改为双维度（情绪交付 + 技术质量）
  - 文件结构图升级：`对标/` 新增角色/剧情/设定结构化子目录；`追踪/` 新增 `角色状态.md`
  - Artifact 映射表新增 4 行（角色状态、对标角色/剧情/设定）
  - 单章写作 step 2 上下文读取从 7 扩展到 11 个文件源（含 `拆文库/` 回退路径）
  - 准备层 3.1（状态筛选）+ 3.2（模块召回）+ 3.3（指令确认）
  - 步骤重编号 1-10 连续无跳跃
  - narrative-writer prompt 注入准备层输出
  - Step 9（更新追踪）新增 `角色状态.md` 更新
- **story-short-write SKILL.md**：
  - 新增精简版"核心方法"section（3 条原则，不与执行规则重复）
  - Phase 2 引用改为"从目标情绪反推剧情"
  - 创作三检替换为 2 步准备层（记忆+召回 / 指令确认）
  - Phase 3 前新增简化文件结构说明

### 文档

- README.md 项目文件结构全面更新（长篇对标/追踪、短篇结构、拆文库说明），README_EN.md 长篇结构同步

## v0.6.3

> 引用完整性修复 + CI static-check 增强

### Bug 修复

- **story-long-write**: `genre-writing-formulas.md` 引用了不存在的 `genre-writing-techniques.md`，改为正确的 `style-craft.md`
- **story-long-write**: `format-and-structure.md` section 引用 `设计任务第 4 步` 在 long-write SKILL.md 中不存在，改为 `Phase 3 细纲`
- **story-short-analyze**: 补充缺失的 `anti-ai-writing.md` 和 `banned-words.md`（从 story-deslop 复制）

### CI 增强 (static-check.sh)

- **Check 6 收紧**: `references/` 下的反引号引用限制在 skill 内解析，防止跨 skill 断裂引用静默通过
- **Check 7 新增**: 裸 .md 文件名检测（非反引号、非链接、非代码块），不存在的文件报 FAIL，存在的报 WARN
- **Check 8 新增**: SKILL.md section 引用验证（三级匹配：子串 → 空格前缀剥离 → 字符级 fallback），断裂的 section 引用报 FAIL
- 脚本注释更新，准确描述全部 8 个检查项

## v0.6.2

> story-short-analyze skill v2.1.0

### 新功能

- 新增 **material-decomposition.md** 短篇拆解方法论：情节节点提取、爆点分析、写作手法（POV/对话/时间/信息/意象）、节奏分析、人物功能评估、共鸣分析（9层）
- story-short-analyze 升级为三件套架构（SKILL.md + material-decomposition.md + output-templates.md），对齐长篇拆文体系深度
- 新增**故事核**提取（一句话概括核心梗）
- 新增**爆点性/话题性**分析
- 新增**共鸣分析**（9层共鸣：情感/价值观/经历/社会现象/文化/普世价值/哲学思考/情感深度/人物深度）
- 新增**人物分类**（主人公/主动人物/被动人物/功能人物）

### 改进

- 短篇拆文管道从模糊 Phase 描述升级为 5 阶段管道表（Phase 2-6，含输入/输出/完成标志）
- 情节节点提取：密度公式（200-300字/个，15-60个全文）、6种节点类型、情绪标记（-9~+9）
- 爆点分析：6维度（铺垫/积累/延迟/爆发点/余波/印象）+ 期待感分析
- 写作手法：POV策略（含切换检测）、对话手法（占比/潜台词率/模式识别）、信息控制矩阵、意象追踪
- 人物功能标签（7种）、内在矛盾提取、弧线记录、人物分类（主动/被动人物）、关系演变追踪
- 可选模块：同类对比、平台适配评估（知乎/番茄/七猫）、详细节奏分析
- 质量门控：情节节点覆盖≥90%、情感曲线100%、写作手法≥5项、人物100%、共鸣≥3层
- 精细/标准双模式路由
- 术语全面对齐行业标准（故事核/爆点/共鸣/主动人物被动人物等）
- 新增**拆解思路**章节：核心原则（故事核驱动/读者视角/可借鉴性/爆点为中心/共鸣决定传播）+ 分析顺序 + 每阶段核心问题 + 拆解心态
- 新增分析维度：套娃反转质量检验、伏笔式反转、称呼变化追踪、主题意象群、重读发现、弹幕/评论互动、反差萌、倒计时框架、双视角叙事、双主人公结构
- 新增报应设计细分（主角设局 vs 反派自毁）、甜宠/喜剧类五维替代维度（反差萌浓度+甜度曲线）
- 新增灵活分节说明、反转密度异常检测、BE结尾评估标准（意难平≥8）、期待感分析
- **术语去抽象化**：清理 9 个自造词（心酸双峰/甜度阶梯/弹幕元叙事/反差萌循环/隐性反转/被动报应自循环/意象系统/二次阅读设计/称呼操控式），回归已有概念和日常描述
- 标杆拆文 demo：《我爸死后，我成了他的影子拳手》（套娃反转式，4层嵌套+5人物+12节点情感曲线）

## v0.6.1

### 新功能

- 新增 **chapter-extractor** 章节 Agent（Haiku）：客观白描铁律、动态密度公式（3-40范围）、100+项泛称黑名单（8类），支持并行章节提取
- story-long-analyze 管线重构：故事框架识别、两步法剧情聚合、3层置信度孤立情节兜底
- 管线鲁棒性：Stage 3-4 并行执行图、计数验证、completed_with_errors 部分失败容忍

### 改进

- 方法论深化：两阶段角色模型、别名4类分类、一人一实体原则、13种剧情类型、金手指8类分类
- 情节点密度从 8-15 扩展为 3-40 动态范围（150-200字/个）
- 新增智能分块（>500章）、关系提取改为从情节点提取、框架识别自检模板
- story-setup agents_version 升级到 v4（7 个 Agent）
- story-import 管道表同步更新

### 修复

- material-decomposition.md 目录名统一为中文（chapters→章节 等）
- output-templates.md 情节点密度修复（8-15→3-40动态范围）、孤立阈值同步
- SKILL.md 链接引用修正、质量门控指向权威来源（material-decomposition.md）
- 孤立情节兜底 output-templates.md 同步为3层置信度
- 全书概要长度对标 zenstory（300-600→500-1000字），补全长篇体系感描述要求
- SKILL.md 管道表 Stage 3 孤立兜底步数修正（4→6）

## v0.6.0

### 新功能

- 新增 **story-explorer** 只读查询 Agent（Haiku）：10 种查询类型（角色状态、伏笔、设定、时间线、进度、上下文加载等），被 story-long-write、story-review、story 路由集成调用
- 新增 **story-import** 逆向导入 Skill：4 阶段流水线（确认来源 → 深度分析 → 结构迁移 → 项目激活），将已有小说反向解析为标准项目目录结构
- story 路由表新增「查故事资料」和「导入小说」入口

### 改进

- story-setup agents_version 升级到 v3（6 个 Agent）
- UPGRADING.md 新增 v3 版本记录
- story-long-write、story-review、workflow-daily 统一 story-explorer 集成模式（部署检测 + 结构化 prompt + 回退机制）
- structure-mapping.md 新增势力/散落情节/悬念映射规则

### 修复

- structure-mapping.md 细纲反推表格格式修复（2 列 → 3 列 Markdown 表格）
- story-explorer context_load 增加备用逻辑（追踪文件缺失时扫描正文推断章节号）
- 统一所有调用点的参数命名为中文（项目目录/查询类型/查询参数）

## v0.5.0

### 参考文件操作手册格式重构（核心变更）

- 全 skill references 从「知识百科」统一转为「操作手册」格式：决策路由表 + 指令语气 + 质量检查清单
- 大文件拆分：character-design → basics + methods + relations；genre-frameworks → catalog + mechanics + readers + formulas；hook-techniques → chapter + suspense + paragraph；outline-arrangement → methods + conflict + structure-theory + rhythm；style-modules → craft + genre-modules + combat-face + commercial-theory；advanced-plot-techniques → core-methods + frameworks + special-topics + emotion-system
- 新增 writing-craft.md（306行）、format-and-structure.md（137行）、emotional-methods.md（179行）
- 13 个共享文件跨 skill (long-write/short-write/short-analyze/deslop) byte-for-byte 同步
- Agent 模板和 SKILL.md 索引全部更新为新文件名

### 新功能

- 新增 story-researcher 资料研究 agent（CDP 搜索+正文提取+多源交叉验证）
- 长篇写作新增场景路由（开书/日更续写/大修）+ 日更工作流 + 大修工作流
- story skill 路由表新增「查资料」入口
- story-review 审查流程新增可选事实核查路径
- static-check.sh 新增 Check 6：检测反引号行内悬空文件引用
- static-check.sh Check 5 增强：支持 `(subagent_type: xxx)` 格式匹配

### 改进

- 精简 story-short-write SKILL.md 22.8KB→13.7KB，新建 writing-workflow.md
- 长篇写作增加创作公式引用、分层摘要协议与扫榜新元素提取
- reference 文件拆分压缩 + 术语直白化

### 修复

- opening-design.md 恢复 6 个丢失知识点（鬼灭之刃范例/信息团排版/改进方向/创意正确展开/期待感三路径/卖点设计与验证）
- 全文件箭头风格统一（`-->` → `->`，21 处）
- character-relations.md `x` → `×` 符号修正
- story-outline.md 裸路径 → 全路径修复
- SKILL.md Phase 3 索引补全 genre-writing-formulas.md
- 9 项 bug 修复与改进（B-1~B-5/D-1~D-3/D-4）
- 悬空文件引用修复（artifact-protocols/agent 模板/publishing-guide）

## v0.4.1

- 新增 story-review 多视角对抗式审查 skill
- 跨 skill 去 symlink 化 + CI 一致性校验
- AI 模式适配 + deslop 量化 + 拆文格式指引
- 指令冲突修复（细纲策略、节长标准、反转百分比）
- 起点扫榜失效链接修复（新书榜拆分 + 三江 URL 迁移）
- grep 全角冒号匹配修复
- 补齐 banned-words.md + CI 增加 references 内部交叉引用检查
- 消除跨 skill 引用残留 + 同步共享文件差异

## v0.4.0

- 新增 story-setup 基础设施部署 skill
- 添加 skill 结构静态检查脚本 + CI 集成
- browser-cdp 跨平台支持（Windows/macOS/Linux）
- 长篇拆文 skill 多项改进
- 短篇拆文/短篇写作 skill 迭代验证改进
- 拆文输出统一到拆文库/{书名}/

## v0.3.0

- 新增 story-cover 封面生成 skill
- 添加 ClawHub marketplace metadata
- 扫榜脚本体系升级（5 平台采集 + 共享模块 + 安全加固）
- 采集脚本数据正确性修复
- 7 个 skill 流程衔接表中文化
- 交叉引用一致性 + 术语通俗化 + 4 个新参考文件

## v0.2.0

- 知识库整合打磨（文件合并/去重/去教程化/SKILL.md 修复）
- 长篇小说目录结构升级（编排/追踪目录 + artifact 模板）
- 扫榜能力增强 + 新增七猫采集
- 新增 CONTRIBUTING.md

## v0.1.0

- 初始版本：长篇/短篇写作、拆文、扫榜、去 AI 味、浏览器操控
- 用 52000+ 本真实数据增强知识库

[Unreleased]: https://github.com/zenstory-ai/oh-story-claudecode/compare/v0.7.10...HEAD
[0.7.10]: https://github.com/zenstory-ai/oh-story-claudecode/compare/v0.7.9...v0.7.10
[0.7.9]: https://github.com/zenstory-ai/oh-story-claudecode/compare/v0.7.8...v0.7.9
[0.7.8]: https://github.com/zenstory-ai/oh-story-claudecode/compare/v0.7.7...v0.7.8
[0.7.7]: https://github.com/zenstory-ai/oh-story-claudecode/compare/v0.7.6...v0.7.7
