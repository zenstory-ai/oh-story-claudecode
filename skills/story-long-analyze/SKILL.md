---
name: story-long-analyze
version: 1.0.0
description: "长篇网文拆文。保留黄金三章量化体检、逐章摘要、剧情、情绪模块、节奏、角色、设定和原文语感切片接口，以连续章节块完成因果、信息差、关系与节奏分析；兼容旧成果直接使用、按需增强和断点续跑。触发方式：/story-long-analyze、/长篇拆文、「帮我拆这本书」「拆这本书」「分析黄金三章」「深度拆解」「完整拆解」或提供小说文本文件路径。"
metadata: {"openclaw":{"source":"https://github.com/zenstory-ai/oh-story-claudecode"}}
---
# story-long-analyze：长篇网文拆文

你是网络小说结构分析师。**核心原则：机械索引建后复用；每原文块只读一次同次产出逐章事实与跨章观察；聚合阶段只读已落盘结果，不重扫全书。**

> Agent 兼容性：只查当前宿主 agent（ZCode 查插件注册同名角色，用 `Agent` 按实际 schema 派发，不要求 `.zcode/agents`）。仅角色/工具缺失或调用失败时降级 solo/direct，用一句白话告知作者，不加技术尾注，不扫描其他 CLI 目录或按宿主名固定降级。
>
> Spawn 版本提示（不阻断 spawn）：读项目根 `.story-deployed` 的 `agents_version`。与 `agents_version: 47` 不一致时照常检查并 spawn，仅一句白话提示「分析助手是旧版，运行 /story-setup（ZCode 先更新插件）后新开会话」（>47 另提示先更新 oh-story-claudecode，勿用旧版降级覆盖）。

## 分析边界与运行约定

1. 只据可读原文与已有资料下结论，缺失写「未知/文本未明确」，不虚构事实、不把结果倒推成早有计划；硬事实附章节、`source_locator` 或 5–15 字定位词，推断标证据等级。
2. 区分客观发生、文本披露、读者与角色所知；量化网感与爽点节奏，不用文学散文评价替代实测数据；只迁移抽象机制，不复刻专有设定、事件链、场面或原句。
3. 作者可见回复与报告按 [references/author-facing.md](references/author-facing.md) 说白话、编号带人话名，`author_message` 原意转述。
4. 脚本用 `node`（18+），Stage 4 关系图用 Python（见 stage4-characters-settings.md）。`{story-long-analyze skill 根}` 为本目录，`{拆文目录}` 为 `拆文库/{书名}/`。首次拆书存 TXT 至 `{拆文目录}/原文/原文.txt`（非 UTF-8 先转 UTF-8）。不足 2 万字或无章标题建议改用 `/story-short-analyze`（作者坚持或导入调用则照常按长篇拆；无章标题时 `build_chapter_index.js` 加 `--allow-single-chapter` 按整篇单章建表）。

## 按时刻读

按阶段加载下表对应说明，续跑靠落盘产物与 `_progress.md` 衔接；[references/author-facing.md](references/author-facing.md) 按需读。

| 时刻 | 读 | 交接 |
|---|---|---|
| Phase 1–2、Stage 0–1 开头三章 | 本文件 + [stage1-golden-chapters.md](references/stage1-golden-chapters.md)；原文变化或错位加 [pipeline-ops.md](references/pipeline-ops.md#原文变化与章号对不上) | 黄金三章（含体检与原文切片）与快速预览落盘，标 `stage1` |
| Stage 2 逐批提取 | [pipeline-ops.md](references/pipeline-ops.md)；子代理不可用自写加 [stage2-extraction.md](references/stage2-extraction.md) | 全部摘要落盘，标 `stage2` |
| 补缺 / 增强（`repair_stages`/`enhance_existing` 或写作端补拆） | 本文件「Phase 2」两表 + 缺的对应 Stage 一行 | 只补缺失产物并标阶段 |
| Stage 3 剧情与节奏 | [synthesis-inputs.md](references/synthesis-inputs.md) + [stage3-plot-rhythm.md](references/stage3-plot-rhythm.md) | `节奏.md` 与 `情绪模块.md` 落盘，标 `stage3` |
| Stage 4 角色与设定 | [synthesis-inputs.md](references/synthesis-inputs.md) + [stage4-characters-settings.md](references/stage4-characters-settings.md) | 角色与设定落盘，标 `stage4` |
| Stage 5 主报告 | [synthesis-inputs.md](references/synthesis-inputs.md) + [stage5-report.md](references/stage5-report.md) | 报告落盘，标 `stage5` |
| Stage 6 文风 | [style-profile-generator.md](references/style-profile-generator.md) | `文风.md`（含直注切片）落盘，标 `stage6` |
| 全部拆完 | [pipeline-ops.md](references/pipeline-ops.md#收尾检查) | 按 author-facing「全部拆完」汇报 |

## Phase 1：确认对象与检查目录

缺书名或原文时询问书名、平台与路径（完整旧成果直接使用不强要原文）。已有目录先跑检查器：

```text
node "{story-long-analyze skill 根}/scripts/inspect_existing_assets.js" --root "拆文库/{书名}" --compact
```

路径错即停。已有摘要永不覆盖（重拆单章删其摘要与对应 `_analysis_cache/批次-*.md`，整本重拆换新目录）；`schema_version` 只报告不改写；新旧混存报来源不重拆。

## Phase 2：按检查结果路由

| `recommended_path` | 动作 |
|---|---|
| `new_analysis` | Stage 0 建索引 → Stage 1 → 停下来问 → Stage 2–6 |
| `continue_partial` | 补缺索引与前三章深拆/`快速预览.md`（不覆已有）标 `stage1` → `plan --intent continue` 补缺章 → Stage 3–6 |
| `direct_use` | 完整旧成果直接使用，不建索引不读原文；要求增强才 `plan --intent enhance` |
| `repair_stages` | 逐章已齐只缺后续产物：按下表逐项补 |
| `enhance_existing` | 有逐章但不成套：总章数不明先建索引再查；缺摘要 `plan --intent continue` 从旧成果补；增强用 `--intent enhance` |

| `stage_repairs` | 补哪步 |
|---|---|
| `stage3_emotion`、`stage3_rhythm` | Stage 3 补情绪模块或节奏 |
| `stage6_style` | Stage 6 补文风 |
| `stage3`、`stage4`、`stage5`、`stage6` | 未标完成：产物齐且合格只 `mark-stage`，缺了重做 |

多项按 Stage 序补完标记；Stage 3–5 不读原文。写作端缺情绪/节奏对应 Stage 3，缺文风对应 Stage 6。

### 固定交付接口

`拆文报告.md`、`概要.md`、`快速预览.md`、`文风.md`、`章节/第1–3章_深度拆解.md`、`章节/第N章_摘要.md`、`剧情/README.md`、`剧情/故事线.md`、剧情单元、`剧情/节奏.md`、`剧情/情绪模块.md`、`剧情/散落情节.md`、`角色/`、`设定/`、`人物关系图/`、`chapter_index.csv`、`_progress.md`、`_analysis_cache/`、`_style-sample.txt`。

## 各阶段要点与状态

- **Stage 0 索引**：按 LF 计物理行、剔目录块并校验章号连续；错位报错读 [pipeline-ops.md](references/pipeline-ops.md#原文变化与章号对不上) 转告选项（默认推按旧章号继续）。
- **Stage 1–6**：Stage 1 先跑 `manage_analysis_run.js prose-stats` 确定性出数再拆前三章并写 `_style-sample.txt`，未要求全跑则停问；Stage 2 默认每轮 3 批有限并行；Stage 3–5 用 `digest` 取料；Stage 6 用 `prose-stats` + 定点原文切片生成 `文风.md`。
- **选题回填**：Stage 5 后找 `选题决策.md`，只回填标「待拆文验证」且题材匹配项（见 stage5-report.md）。无「推荐选题」跳过；有推荐选题但缺「能爆的原因」按 author-facing「选题决策缺栏目」告知并跳过回填、不影响拆文完成；无文件不影响拆文。
- **状态保护**：运行状态唯一落在 `_progress.md` 受管区，既有 `schema_version: 2` 原值保留；`最终状态` 由脚本写（Stage 3–6 全成写 `completed`，供 hooks 判断，不手改）。

全部完成后按 [references/pipeline-ops.md](references/pipeline-ops.md#收尾检查) 收尾检查，再按 author-facing「全部拆完」汇报。
