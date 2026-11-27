# 对标文风召回（story-explorer · benchmark_style_load）

只在 `query_type` 为 `benchmark_style_load` 时读本文件；其他查询类型不读。输出同样遵守 agent 定义里的「纯 JSON、字符串转义」规则，原文锚点片段尤其要转义。

## 流程

加载对标书的情绪模块、节奏索引和文风，按本章情绪/基调选择参考章与原文锚点片段。

1. **解析输入**：项目目录 + 本章情绪/基调 + （可选）本章爽点类型 + （可选）本章目标字数
2. **主对标书选择**：
   - 先按项目目录名、`.active-book` 与本书设定识别当前作品；`拆文库/{当前书}/` 是 story-import 的本书分析，不是对标候选。历史误建的 `对标/{当前书}/` 也必须排除，并返回 `gaps.self_benchmark_ignored: true`
   - `Read 设定/题材定位.md`，提取 `主对标书` 字段
   - 若有且不是当前作品 → 用该书；若字段指向当前作品 → 忽略该字段并设置 `gaps.self_benchmark_ignored: true`
   - **路径一律用字段值逐字拼接**：不添加《》等任何装饰、不改一字——拼错时 Glob 只会不报错地返回空结果，与「书不存在」无法区分
   - **登记的主对标按步骤 3 探不到书目录**（目录下探不到任何文件）→ 返回 `gaps.benchmark_book_missing: true` 与 `expected_path`（原样写入实际探测的完整路径，供核对拼写），`results` 置空**停止**；不得改用其他书，也不得走下面的缺失回退。**书目录存在但缺 `文风.md` 不属于本情形**——照常进入步骤 4-6，由步骤 6 归类为 `profile_missing`
   - 若字段缺失或已忽略 → `Glob 对标/*/**/*`，从命中文件所属的书目录（`对标/` 下的第一层目录，排除当前作品）取字典序第一个，并在 `gaps.main_benchmark_unspecified: true` 提示主对标书未指定；**枚举条件是书目录下有文件，不是有 `文风.md`**——缺文风但资料完整的候选仍算命中
   - 若排除后无命中，继续向上找工作区根下的 `拆文库/*/**/*`，同样排除当前作品；仍无 → 返回 `gaps.no_benchmark: true`，`results` 置空，**不报错、不继续读文风**
3. **对标书路径查找（只判书目录有效性，不判文风）**：优先探 `{项目}/对标/{书名}/**/*`，回退探 `拆文库/{书名}/**/*`（向上找到工作区根，再下钻拆文库）；探针是目录下的任意文件——Glob 不接受纯目录模式，`{书名}/` 恒返回空。任一处命中文件即视为书目录有效，进入步骤 4；两处都无命中才是 `benchmark_book_missing`。**不得用 `文风.md` 兼作目录存在性探针**，缺文风由步骤 6 返回 `profile_missing`，调用方再按 `custom_style` 处理
4. **主产物探针与资料代际**：
   - 先探 `{对标书路径}/剧情/情绪模块.md` 和 `{对标书路径}/剧情/节奏.md`，两者都存在才进入当前权威召回。
   - 任一未命中时直接按下面两项返回并停止准备；`schema_version` 不参与新旧判断。两份主产物都存在时正常召回，缺少因果、双时间线或三维节奏等新增内嵌字段不阻断。
   - 缺 `剧情/情绪模块.md` → `gaps.missing_primary_contract: true`、`gaps.module_missing: true`，`repair_action` 写“重跑 /story-long-analyze Stage 3，补齐情绪模块”。
   - 缺 `剧情/节奏.md` → `gaps.missing_primary_contract: true`、`gaps.rhythm_missing: true`，`repair_action` 写“重跑 /story-long-analyze Stage 3，补齐节奏索引”。
5. **当前权威召回**：
   - 对存在的 `{对标书路径}/剧情/情绪模块.md`，从读者需求、情绪引擎或可复现模块中选择 1 条 `selected_emotion_module`，写入 `module_source_path`。
   - 对存在的 `{对标书路径}/剧情/节奏.md`，从关键信息推进、情绪触动点、爆发/冷却中选择 1 条 `rhythm_reference`，写入 `rhythm_source_path`。
   - 若两个权威文件都存在但对同一章节/模块的读者情绪或爆发点描述互相矛盾，保留两条原文摘要，并返回 `gaps.module_rhythm_conflict: true` 与 `gaps.conflict: "..."`；调用方按两个权威文件优先于 `拆文报告.md` / `故事线.md` 的规则处理，禁止自行改写
6. **读文风**：
   - `Read {对标书路径}/文风.md`
   - 不存在 → 返回 `gaps.profile_missing: true, expected_path: "..."`，**不继续后续步骤**；书目录本身有效，不得改填 `benchmark_book_missing`——调用方按 `custom_style` 决定继续或停止
   - 检查「生成记录」里的 `文风可用：否` → 返回 `gaps.profile_degenerate: true`，后续不把文风作为强约束
7. **可用性检查（只读可执行）**：
   - 本 agent 只有 `Read/Glob/Grep`，不能调用 Bash/stat。
   - 只读取文风文件「生成记录」：若明确写有 `文风可用：否` 或 `需重生` 等不可用标记 → `gaps.profile_stale: true` 或 `gaps.profile_degenerate: true`，并在 `stale_reason` 写明原因。
   - 原文文件缺失但已有有效锚点时不据此判不可用。不做文件时间比较；没有明确过期说明时 `profile_stale: false`。
8. **章节基调候选集**：
   - `Glob {对标书路径}/章节/*_摘要.md`
   - 用 Grep 工具按正则检索每个文件（下式是检索条件，不执行 shell）`Grep -hE '基调：(紧张|轻松|悲伤|热血|爽|甜|温馨|恐怖|压抑|其他)'`（**全角冒号**，不锚定行首）拿到该章所有情节点基调
   - 章基调聚合：众数；并列时按 grep 输出顺序取最早
   - 候选集 = 章基调 == 本章情绪/基调的章节列表
9. **相近基调兜底**（完全没有同基调章节时）：
   - 先从本章细纲/查询参数里判断更接近“紧张、热血、爽、甜、轻松、温馨、悲伤、恐怖、压抑”哪一类；不要写死对照表。
   - 选择一个最接近的基调重新筛候选集，并在结果里说明“使用相近基调兜底”。
   - 仍空 → `gaps.tone_match_failed: true`，跳过匹配章节读取，但仍返回整书文风、`selected_emotion_module` 和 `rhythm_reference`。
10. **多候选章节选择规则**（候选集多章时）：
   - L1 爽点类型最强匹配（调用方提供爽点字段时，对每个候选章读 `_摘要.md` 的「关键事件」判断）
   - L2 可读到的原文章节长度最接近本章目标字数（如提供）；本 agent 不用 Bash 统计，只用索引或已有资料注明的原文章长，拿不到时跳过 L2，不用情节点数或摘要字数代替
   - L3 章节号最小
11. **读匹配章节资料**：
   - 先 `Read {对标书路径}/章节/第K章_摘要.md`，提取本章基调序列、关键事件、爽点/情绪节点
   - 新版轻量摘要直接读取「信息变化」「状态变化」「章尾钩子」「三维节奏」字段；旧摘要缺这些字段时再读取「关键信息与扩写技法」表，作为 `matched_chapter_techniques` 的证据/补足；两者都不覆盖 `剧情/节奏.md`
   - 若 `{对标书路径}/章节/第K章_深度拆解.md` 存在，再读取并提取「可借鉴要素」+ 反应层 + 章尾钩子类型
   - 若同章深度拆解不存在（常见：只有黄金三章有深度拆解），不要失败；回退读取 `第1章_深度拆解.md`、`第2章_深度拆解.md`、`第3章_深度拆解.md` 中基调最接近的一章，或仅使用文风「可借鉴技巧」
   - 在 `gaps.matched_deep_dive_missing: true` 标记该回退
12. **抽取原文锚点片段**（从文风文件里）：
    - 从文风文件 `## 原文锚点片段` 段读出所有按基调标注的片段
    - 按本章情绪/基调选 1-2 段（精确匹配优先，无则取相近基调）
    - 完整传递 200-500 字原文（不要截断/概括）
13. **返回结构化 JSON**：`source_files` 只列本次实际读取的文件，示例路径按本次来源替换

## 缺失即停与降级

- 两份主产物（`剧情/情绪模块.md`、`剧情/节奏.md`）中任一缺失时，返回 `missing_primary_contract` 与 `repair_action`，停止准备。
- 登记的主对标书目录探不到时返回 `benchmark_book_missing` 与 `expected_path`，不换书。
- 书目录在、缺 `文风.md` 归 `profile_missing`，由调用方按 `custom_style` 决定继续或停止。

## 输出结构

```json
{
  "query_type": "benchmark_style_load",
  "results": {
    "style_profile_path": "对标/{书名}/文风.md",
    "style_profile_summary": "<≤200字 提取核心：标点习惯 + 对话技法 + 情绪交替模式>",
    "selected_emotion_module": "<从 剧情/情绪模块.md 选出的读者想看什么/情绪链/戏剧单元/可替换项/不可照搬；缺失时为 null>",
    "rhythm_reference": "<从 剧情/节奏.md 选出的关键信息推进/情绪触动点/爆发节奏/冷却参考；缺失时为 null>",
    "module_source_path": "对标/{书名}/剧情/情绪模块.md",
    "rhythm_source_path": "对标/{书名}/剧情/节奏.md",
    "matched_chapter_K": 14,
    "matched_chapter_techniques": "<匹配章摘要 + 深度拆解/黄金三章回退中的可借鉴要素，≤300字>",
    "anchor_excerpts": [
      {"tone": "悲伤", "source": "第14章 第7段（行 823-901）", "demo_point": "对话潜台词手法", "text": "<200-500字原文>"},
      {"tone": "热血", "source": "第8章 第3段（行 401-465）", "demo_point": "爽点铺放比", "text": "<200-500字原文>"}
    ]
  },
  "source_files": ["设定/题材定位.md", "对标/{书名}/剧情/情绪模块.md", "对标/{书名}/剧情/节奏.md", "对标/{书名}/文风.md", "对标/{书名}/章节/第14章_深度拆解.md"],
  "gaps": {
    "no_benchmark": false,
    "module_missing": false,
    "rhythm_missing": false,
    "module_rhythm_conflict": false,
    "conflict": null,
    "missing_primary_contract": false,
    "repair_action": null,
    "profile_missing": false,
    "profile_stale": false,
    "profile_degenerate": false,
    "stale_reason": null,
    "main_benchmark_unspecified": false,
    "benchmark_book_missing": false,
    "self_benchmark_ignored": false,
    "raw_text_unavailable": false,
    "tone_match_failed": false,
    "matched_deep_dive_missing": false
  }
}
```
