---
name: story-long-analyze
version: 1.0.0
description: "长篇网文拆文。保留黄金三章、逐章摘要、剧情、情绪、节奏、角色、设定和文风接口，以连续章节块完成因果、双时间线、关系与三维节奏分析；兼容旧成果直接使用、按需增强和断点续跑。含可选三层灵感库管道（灵感库、跨书灵感聚合、更新灵感库）。触发方式：/story-long-analyze、/长篇拆文、「帮我拆这本书」「拆这本书」「分析黄金三章」「深度拆解」「完整拆解」或提供小说文本文件路径。"
metadata: {"openclaw":{"source":"https://github.com/zenstory-ai/oh-story-claudecode"}}
---
# story-long-analyze：长篇网文拆文

你是网络小说结构分析师。

**核心原则：机械索引建立后复用；正常提取时每个原文块只读一次，同次产生逐章事实和跨章观察；失败重试按计划回看，聚合阶段复用落盘结果。**

> Agent 兼容性：只检查当前宿主的 agent；ZCode 查插件注册的同名角色，用 `Agent` 按实际 schema 派发，不要求 `.zcode/agents`。仅角色/工具缺失或调用失败时降级 solo/direct，报告 `Fallback: project custom agents unavailable -> solo`，不扫描其他 CLI 的目录或按宿主名固定降级。
>
> Spawn 版本提示（不阻断 spawn）：先读取项目根 `.story-deployed` 的 `agents_version`。与本版 `agents_version: 38` 不一致时（标记缺失、字段缺失/非整数、小于或大于 38）照常按当前宿主角色来源检查并 spawn，同时报告 `Notice: agents bundle 版本不匹配（项目 {N}，本版 38）` 并提示重新运行 `/story-setup` 后新开会话；大于 38 时额外提示先更新 oh-story-claudecode，不要用本地旧版 setup 降级覆盖。只有当前宿主角色缺失或不暴露调用能力时才降级 solo/direct。

## 分析边界

1. 只根据可读原文和已有资料下结论；缺失写“未知”或“文本未明确”。
2. 硬事实附章节、`source_locator` 或 5–15 字定位词；推断标证据等级。
3. 区分客观发生顺序、文本披露顺序、读者所知和角色所知。
4. 分开分析事件推进、读者情绪和篇幅安排，分数不能代替解释。
5. 只迁移抽象机制，不复刻专有设定、角色组合、关键事件链、标志性场面或原句。
6. 不为填字段虚构事实，不把结果倒推成人物早有计划。

## 对作者说话

对话回复、`快速预览.md`、`拆文报告.md` 和人物关系图按 [references/author-facing.md](references/author-facing.md) 写，讲清书中情节、阅读感受和可借鉴写法。内部字段、命令与质量指标留在运行资料中；编号带名称。脚本返回 `author_message` 时转述说明与选项。

## 运行约定

- `{PYTHON}`：依次试 `python3`、`python`、`py -3`，用第一个能运行的。`{story-long-analyze skill 根}` 是本文件所在目录，`{拆文目录}` 是 `拆文库/{书名}/`。
- 首次拆一本书时，把作者给的 TXT 存为 `{拆文目录}/原文/原文.txt`；若编码不是 UTF-8（常见为 GBK），先转成 UTF-8，否则子代理按行号读取时会乱码。
- 全文不足 2 万字或认不出章节标题时多半是短篇，建议作者改用 `/story-short-analyze`；作者坚持或由导入调用（篇幅已在导入时定好）时照常按长篇拆。

## 按时刻读

进入各阶段时只加载下表对应的说明，续跑或新会话通过落盘产物和 `_progress.md` 的阶段状态衔接。[references/author-facing.md](references/author-facing.md) 每个时刻都按需用。

| 时刻 | 读 | 交接 |
|---|---|---|
| Phase 1–2、Stage 0–1 开头三章 | 本文件 + [stage1-golden-chapters.md](references/stage1-golden-chapters.md)；原文变了或章号对不上时加 [index-rebuild.md](references/index-rebuild.md) | 黄金三章与快速预览落盘，标 `stage1` |
| Stage 2 逐批提取 | [pipeline-ops.md](references/pipeline-ops.md)；子代理不可用、自己写批次时加 [stage2-extraction.md](references/stage2-extraction.md) | 全部摘要落盘，标 `stage2` |
| 补缺 / 增强（检查器给出 `repair_stages`、`enhance_existing`，或写作端请作者来补拆） | 本文件「Phase 2」两张表，再按缺的那个 Stage 读下面对应一行 | 只补缺的产物，各自标阶段 |
| Stage 3 剧情与节奏 | [synthesis-inputs.md](references/synthesis-inputs.md) + [stage3-plot-rhythm.md](references/stage3-plot-rhythm.md) | 节奏与情绪模块落盘，标 `stage3` |
| Stage 4 角色与设定 | [synthesis-inputs.md](references/synthesis-inputs.md) + [stage4-characters-settings.md](references/stage4-characters-settings.md) | 角色与设定落盘，标 `stage4` |
| Stage 5 主报告 | [synthesis-inputs.md](references/synthesis-inputs.md) + [stage5-report.md](references/stage5-report.md) | 报告落盘，标 `stage5` |
| Stage 6 文风 | [style-profile-generator.md](references/style-profile-generator.md) | `文风.md` 落盘，标 `stage6` |
| 全部拆完 | [final-checks.md](references/final-checks.md) | 按 author-facing「全部拆完」汇报 |
| 灵感库（作者提出「灵感库 / 提炼灵感 / 跨书灵感聚合 / 更新灵感库」时） | [references/inspiration-library.md](references/inspiration-library.md) | 只写 `灵感库/`，不改拆文产物 |

## Phase 1：确认对象并检查目录

没有书名或原文时询问书名、平台和原文路径；已有完整成果直接使用时不强制索要原文。已有目录先运行只读检查器：

```text
"{PYTHON}" "{story-long-analyze skill 根}/scripts/inspect_existing_assets.py" --root "拆文库/{书名}" --compact
```

路径错误必须停止。已有摘要一律不覆盖：要重拆某章就删掉它的 `章节/第N章_摘要.md` 和覆盖它的 `_analysis_cache/批次-*.md`（只删摘要会从缓存原样补回），整本重拆就换一个新目录。`schema_version` 只报告，不作为新旧门禁，也不得在复用时改写。新旧投影混存要报告来源，但不要求重拆。

## Phase 2：按检查结果走哪条路

| `recommended_path` | 做什么 |
|---|---|
| `new_analysis` | 全新小说：Stage 0 建索引 → Stage 1 → 停下来问 → Stage 2–6 |
| `continue_partial` | 部分完成：缺索引时补建；Stage 1 产物（前三章深度拆解、`快速预览.md`）缺哪份补哪份，已有的不覆盖，齐了标 `stage1`；再 `plan --intent continue` 只补缺章，按 Stage 3–6 补齐 |
| `direct_use` | 完整旧成果：直接使用，不建索引、不读原文；作者明确要求增强时才 `plan --intent enhance` |
| `repair_stages` | 逐章成果已齐，只缺后面的产物：按下表逐项补 |
| `enhance_existing` | 有逐章成果但不成套：总章数不明时先建索引再检查；缺摘要时 `plan --intent continue` 从旧成果补（不读原文）；作者要求增强时用 `--intent enhance` |

| `stage_repairs` 代码 | 补哪一步 |
|---|---|
| `stage3_emotion`、`stage3_rhythm` | Stage 3：补缺的那份（情绪模块或节奏） |
| `stage6_style` | Stage 6：文风 |
| `stage3`、`stage4`、`stage5`、`stage6` | 没标完成：产物都在且合格就只 `mark-stage`，不重写；缺了才重做 |

有多项时按 Stage 顺序逐项补完并标记。情绪模块卡字段不全（灵感库登记报错）时，检查器不会报缺：作者同意后把旧 `剧情/情绪模块.md` 复制到 `_analysis_cache/legacy/`，按 Stage 3 只改出错的卡，再标 `stage3`。Stage 3–5 只用已有成果和批次缓存，不读原文；没有批次缓存的旧项目用 `digest` 取逐章字段，再加上已有剧情、关系资料。写作端「对标书还缺情绪/节奏分析」「缺文风」分别对应这里的 Stage 3、Stage 6。

### 固定交付接口

- `拆文报告.md`、`概要.md`、`快速预览.md`；
- `章节/第1章_深度拆解.md`、`章节/第2章_深度拆解.md`、`章节/第3章_深度拆解.md`，`章节/第N章_摘要.md`；
- `剧情/README.md`、`剧情/故事线.md`、剧情单元、`剧情/节奏.md`、`剧情/情绪模块.md`、`剧情/散落情节.md`；
- `角色/`、`设定/`、`人物关系图/`、`文风.md`；
- `chapter_index.csv`、`_progress.md`、`_analysis_cache/`。

`拆文报告.md` 是阅读入口。剧情单元管因果事实，`剧情/节奏.md` 管信息推进与三维节奏，`剧情/情绪模块.md` 管读者需求和复现机制，`角色/角色关系.md` 管关系事实，`文风.md` 管表达层。

## 各阶段要点

- **Stage 0 机械索引**：全新和部分完成且要读原文时建 `chapter_index.csv`（命令见 stage1-golden-chapters.md）。只按 LF 计物理行，目录与正文标题重复时先剔掉目录块；落表前校验章号连续、无重复和边界有效。脚本因原文变化或章号对不上停下时读 index-rebuild.md，把说明和选项转告作者（默认推荐按旧章号继续）。
- **Stage 1 黄金三章**：按索引读前三章，同一次阅读写三份单章深度拆解、可选 `_style-sample.txt` 和 `快速预览.md`，再运行 `manage_analysis_run.py mark-stage --stage stage1`。作者没要求一次跑完时按 author-facing「开头三章拆完、停下来问」询问；要求一次跑完、多本书一起拆或由导入自动续跑时不停。
- **Stage 2 逐批提取**：`plan` 出只读计划，每批派一个 `chapter-extractor`，默认有限并行（每轮 3 批），作者问起才解释并切换拆法；子代理自己读原文并写批次输入，主会话不转贴、不读它，直接 `commit`。细则见 pipeline-ops.md。
- **Stage 3–5**：用 `digest` 取料，不重读原文；怎么标阶段见 synthesis-inputs.md「阶段标记」；Stage 5 写新报告前先 `mark-stage --stage stage5 --prepare` 备份旧报告。
- **选题回填**：Stage 5 报告落盘后找 `选题决策.md`，只回填仍标记“待拆文验证”且题材匹配的项（查找位置与写法见 stage5-report.md）。没有「推荐选题」一节（只扫了榜）就跳过，不算无效；有推荐选题但缺少当前契约必需的“能爆的原因”等字段时返回 `invalid_topic_decision_contract`，提示重跑 `story-long-scan` Phase 5；文件不存在不影响拆文。
- **Stage 6 文风**：优先用已有 `文风.md` 和有效 `_style-sample.txt`，样本不足时按索引定点读 4–6 段原文，不重扫全书；只缺文风时直接运行，不重跑 Stage 1–5。取不到可核验原句时明确失败。

## 状态与旧项目

运行状态只有 `_progress.md` 受管区；既有 `schema_version: 2` 原值保留；`chapter_index.csv` 是机械索引；缓存是恢复证据。有阶段记录后 `最终状态` 由脚本写：Stage 3–6 都完成为 `completed`，否则新项目写 `pending`、旧项目保留原值（只改原有那一行）；会话 hooks 靠它判断拆文是否完成，不要手改。

全部完成后按 [references/final-checks.md](references/final-checks.md) 做收尾检查，再按 author-facing.md「全部拆完」向作者汇报。
