# Agent Note: 长篇拆文收敛为单状态三脚本运行时

Status: implemented
Date: 2026-09-22
Issue: PR #386
Related: [2026-09-23-long-analyze-runtime-takeover](../simplification/2026-09-23-long-analyze-runtime-takeover.md)（接手收口：情节点密度、`reanalyze`、`migrate-legacy`、章节卡家族与局部失效追踪的决定已在该篇翻转）

## Problem

长篇拆文的旧实现同时维护计划 JSON、checkpoint、逐批 receipt、Stage receipt 和进度
文件。旧项目增强、批次拆分、原文局部变化或阶段中断后，这些状态可能互相冲突，造成
完成批次被重复分析、错误摘要被复用或阶段被误判完成。此外逐章摘要与「章节卡」两套
投影并存，消费方引用过不存在的字段。

## Decision

1. **生产运行收敛为三个脚本**：`build_chapter_index.py`（章界、物理行、全文与逐章
   hash、显式 rebuild）；`inspect_existing_assets.py`（只读判断旧成果、精确缺章、
   来源混存和阶段修复）；`manage_analysis_run.py`（只读计划、范围批次、原子提交、
   相邻拆分、缓存恢复和阶段状态）。
2. **唯一运行状态在 `_progress.md` 受管区**；`chapter_index.csv` 是当前机械索引，
   批次缓存只作恢复证据。新运行不再创建计划 JSON、checkpoint、
   逐批 receipt 或 Stage receipt。批次 ID 固定为 `RAW-{起章}-{止章}` /
   `REUSE-{起章}-{止章}`。
3. **逐章摘要换 14 字段事实 schema**（概要、因果、关键行动、局面结果、涉及人物、
   信息变化、状态变化、三维节奏、章尾钩子、证据、情节点类型、情节点标题、主题标签、
   基调），章节卡废除。逐章扩写技法层上收到 `剧情/节奏.md`——这本来就是
   project-files.md 钦定的「章节扩写技法聚合」权威位；黄金三章深度拆解保留逐章写法。
4. **新旧混存就地兼容**：inspect 报 `mixed_sources` 与逐章 `preferred_by_chapter`
   来源；`schema_version` 只报告、不作新旧门禁；消费侧字段级回退（缺关键行动/局面
   结果回退关键事件等）。只有旧成果时 `--intent enhance` 按需增强（Stage 3+ 从既有
   摘要聚合，原文读取可为 0）；显式重拆走 `--intent reanalyze` ＋稳定 `request_id`。
   旧摘要遇序章/第 0 章/非第一章起始且身份无法确认时返回
   `chapter_mapping_ambiguous`，禁止静默错配。
5. **Stage 6 可单独重建**：优先 `_style-sample.txt`，缺样本按索引定点读 4–6 段原文，
   不重扫全书；生成新报告前逐字节备份旧报告到 `_analysis_cache/legacy/`。

6. **批次提交格式写在 skill 自己的 reference 里**：`output-templates.md`「批次提交格式」给出
   `CHAPTER_START/END`、`REUSED_CHAPTERS`、`BATCH_OBSERVATIONS_START/END` 的包裹规则；原先只写在
   chapter-extractor 模板里，子代理不可用时主线程看不到，v0.7.11 发版前 solo 实测续拆旧库时
   提交被拒 3 次、靠读脚本源码才补齐标记。批次输入文件固定为 `{拆文目录}/_analysis_cache/输入-{批次ID}.md`，
   不写系统 `/tmp`。

## Review

署名审核意见（PR #386 评审轮）：

- **@worldwonderer**（2026-09-15，评审与复测反馈）：六脚本约 2381 行、46 处 hash
  校验、三处状态库应收敛为三脚本一状态库；批次 ID 改用章节范围；
  `legacy_benchmark_limited` 整条拿掉；截断/缺失批次缓存不得被完成行掩盖；旧摘要
  身份不明须显式报错不得静默错配；Stage 完成行须与必需产物共同判定；给出三个验收
  样本（旧完整/旧半成品/新旧混存），且原有受保护文件逐字节不变。
- **@ciel-oliver**（PR 作者，2026-09-17）：按上述条目分四部分逐项修复，另补局部
  重跑重复读取的修复与回归（`0f3edce`），请求复测。
- **cimiK**（接手 rebase 到 main `0ffe7db` 时的复核，2026-09-22）：
  1. `test-long-analyze-runtime.py` 的盘龙验收与旧项目局部变化两个用例硬依赖
     `.gitignore` 排除的 `demo/拆文库/盘龙/原文/原文.txt`，CI 环境无此夹具会红——
     **已随本提交修改**：两用例加原文缺席即跳过守卫，缺席时打印 SKIP 不静默；
     有夹具的环境仍跑全量验收；
  2. benchmark-recall (e) 匹配章平票裁决靠「情节点数量/原文章节估算字数」，新投影
     摘要通常单情节点且无字数字段，两信号同时钝化；`char_count` 已在
     `chapter_index.csv`，建议后续把字数信号改从索引取；
  3. #434 后 README 的 agent 描述表已移至 docs/architecture.md，本分支把
     chapter-extractor 的一行描述更新随迁（中英两份）。

## Alternatives considered

- **保留六脚本＋三处状态库（评审前形态）**：最强理由是职责切分细、各阶段独立可测；
  但状态分散正是重复分析与阶段误判的根源，且 46 处 hash 校验难以审计，按评审意见
  放弃。
- **批量迁移旧库到新 schema**：一次性对齐消费面最干净；但违背「旧成果原文件字节
  不变」的兼容底线，迁移成本转嫁给存量用户，改为就地兼容＋按需增强＋只读迁移证据
  （`migrate-legacy` 只新增缓存不动旧文件）。

## Consequences

收益：状态冲突面消失，断点恢复不重复调用模型；完整旧项目增强原文读取为 0 且受保护
文件逐字节不变；新旧摘要逐章混用且来源可见；追加新章只使新增章待处理。

代价：逐章摘要的 craft 层（扩写技法表、写法公式）上收聚合位，情节点密度从每章
10–40 条降为通常 1 条，非黄金三章不再有原文引用锚点——其唯一逐行消费者
（story-import 细纲映射）已同步改造并带旧字段回退；(e) 平票信号钝化见 Review 第 2
条，属可延后的小修。
