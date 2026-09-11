# 长篇拆文管道运维

本文件定义旧成果识别、机械索引元数据、连续批次提交、恢复和完成判定。分析字段模板见 [output-templates.md](output-templates.md)，质量方法见 [material-decomposition.md](material-decomposition.md)。

## `_progress.md` 模板

```markdown
# 深度拆解进度：{书名}
- 小说：{标题}
- 总章数：{N}
- 输出目录：{路径}
- 最终状态：{pending/paused_after_stage1/completed/completed_with_errors}
- schema_version: 2

<!-- story-long-analyze:chapter-index:start -->
## 机械章节索引
- parser_version: {由 build_chapter_index.py 写入}
- source_sha256: {hash}
- boundary_sha256: {hash}
- chapter_count: {N}
- empty_chapter_count: {N}
- index_status: complete

## 章节边界（`chapter_index.csv` 的兼容投影）
| 章号 | 标题 | 起始行 | 字数 |
|---|---|---|---|
| {N} | {标题} | {起始行} | {正文字符数} |
<!-- story-long-analyze:chapter-index:end -->

## 资料来源与兼容路径
| 资料 | 状态 | 覆盖范围 | 来源版本/路径 | 本次动作 |
|---|---|---|---|---|
| 旧逐章事实 | {可用/部分/缺失/冲突} | {章节} | {路径} | {直接复用/补缺/核证} |
| 旧剧情与故事线 | ... | ... | ... | ... |
| 旧节奏与情绪模块 | ... | ... | ... | ... |
| 旧角色、关系与设定 | ... | ... | ... | ... |
| 旧文风 | ... | ... | ... | ... |

## 阶段状态
| 阶段 | 状态 | 覆盖范围 | 产物 | 备注 |
|---|---|---|---|---|
| Stage 0 索引 | ... | ... | `chapter_index.csv` | ... |
| Stage 1 黄金三章 | ... | ... | `章节/*_深度拆解.md`、`_style-sample.txt` | ... |
| Stage 2 批次提取 | ... | ... | `章节/*_摘要.md`、`_analysis_cache/批次-*.md`、`_analysis_cache/复用提取-*.md` | ... |
| Stage 3 聚合 | ... | ... | `剧情/` | ... |
| Stage 4 关系设定 | ... | ... | `角色/`、`设定/`、`人物关系图/` | ... |
| Stage 5 主报告 | ... | ... | `拆文报告.md` | ... |
| Stage 6 文风 | ... | ... | `文风.md` | ... |

## 连续批次
| 批次ID | 输入类型 | 章节 | 来源hash | 逐章兼容投影 | 剧情点缓存 | 状态 | 重试原因 |
|---|---|---|---|---|---|---|---|
| REUSE001 | existing-results | 1-20 | 不要求 | 保留旧文件 | `_analysis_cache/复用提取-1-20.md` | {pending/success/failed} | {无/原因} |
| B001 | raw-original | 21-28 | {hash} | `章节/第21章_摘要.md` … `章节/第28章_摘要.md` | `_analysis_cache/批次-21-28.md` | {pending/success/failed} | {无/原因} |

## 增强分析覆盖
| 类型 | 已完成范围 | 待处理范围 | 证据不足/冲突 |
|---|---|---|---|
| 因果链 | ... | ... | ... |
| 客观事件与披露 | ... | ... | ... |
| 三维节奏 | ... | ... | ... |
| 有向关系 | ... | ... | ... |
| 机制条件 | ... | ... | ... |

## 失败与待核
| 类型 | 章节/阶段 | 原因 | 已尝试 | 后续动作 |
|---|---|---|---|---|

## 断点
- 最后已验证批次：{Bxxx/无}
- 下一操作：{动作}
```

`schema_version: 2` 沿用 current main，不因本次 PR 单独升级。机械索引区由 `build_chapter_index.py` 在标记范围内原子更新，其他内容保持不变。

## 启动时先分类

### 旧成果直接使用

用户只要继续对标、导入或写作时，检查对应旧文件是否可读并直接交给现有消费者。不创建索引、不补新字段、不要求原文，也不把旧目录迁移成新结构。

### 旧成果增强

先登记现有逐章事实、剧情、节奏、情绪、关系、设定、报告和文风的实际覆盖范围：

- 资料能直接支持结论：复用并记录来源；
- 有事实但缺因果、披露、三维节奏或机制条件：只基于旧资料补分析；
- 缺关键事实、来源冲突或无法判断具体写法：写未知、冲突或待核，不回读已覆盖章节原文。

新增观察先写 `_analysis_cache/`。旧成果二次提取使用 `复用提取-{起章}-{止章}.md`，未拆原文块使用 `批次-{起章}-{止章}.md`，两类缓存不得互相覆盖。不得覆盖旧逐章、剧情、角色、设定和文风文件。需要生成新的当前 `拆文报告.md` 时，先把已有同名报告复制到 `_analysis_cache/legacy/拆文报告.md`，再原子替换当前报告。

### 全新或部分完成

先对完整原文建立或校验机械索引，再比较实际文件和进度记录。文件存在、格式完整、范围正确且来源没有变化时进入 `existing-results`；只有缺失或损坏的章节进入 `raw-original`。旧进度格式不同不等于所有成果失效，黄金三章也属于可复用的已读章节。

## 运行计划门禁

`plan_analysis_run.py` 把检查结果和机械索引合并为 `_analysis_cache/run-plan.json`。它是语义调用的唯一调度依据：

- `direct_use`：返回完整旧成果，原文读取数为 0；
- `enhance_complete`：只建立已有成果二次提取批次，原文读取数为 0；
- `resume_partial`：已有章进入二次提取，缺章进入不重叠原文块；
- `new_analysis`：黄金三章读取一次，其余章进入不重叠原文块；
- `reanalyze_all`：只有用户明确要求重新拆文时使用，忽略旧语义成果并按新书执行。

重新生成计划时，先验证 `_analysis_cache/receipts/*.json` 列出的 source hash 与全部输出 hash。验证通过的新流程批次进入 `verified_batch_caches`，直接复用其批次缓存，不得因为机械投影出的 `章节/*_摘要.md` 已存在，就把这些章节再次送入 `existing-results` 二次提取；收据或缓存损坏时才降级到实际可用成果重新规划。

已有成果先按完整来源族选择：上游标准成果完整时整套使用；上游不完整而紧凑章节卡完整时整套使用紧凑成果；只有两类都不完整时才以上游逐章资料为先、用紧凑卡补缺。这样既保留标准接口优先级，也不把一套完整精简成果拆开后混入更冗长的旧摘要。

原文块默认不超过 10 章和 25,000 字符；长章自然缩到 1-5 章，短章通常为 5-10 章。单章本身超过 25,000 字符时独占一块并由计划标记 `oversized_single_chapter: true`。任何章出现在已有成果范围和原文块两边，或出现在两个原文块中，必须停止执行。

## 连续批次提交

每个批次遵循“校验后记进度”：

1. 从 `run-plan.json` 领取一个批次，不自行扩大或重排范围；
2. 调用 `manage_batch_checkpoint.py start`，登记 `running` 与尝试次数；
3. `raw-original` 读取该块原文一次并同时输出每章紧凑事实和批次观察；`existing-results` 只读取计划列出的旧成果文件；
4. 原文模式检查章号与 `CHAPTER_START/END` 一一对应；已有成果模式检查唯一 `REUSED_CHAPTERS` 范围且不存在逐章替换块；
5. 将 Agent 返回保存为临时 Markdown，调用 `scripts/commit_batch_output.py`；原文模式由脚本机械生成逐章兼容投影并保存批次缓存，已有成果模式只写批次缓存；
6. 工具重新读取并核对各文件 hash，写 `_analysis_cache/receipts/{批次ID}.json`，最后更新 `_progress.md` 和批次账本为 `success`。默认不覆盖内容不同的现有结果；只有人工确认旧结果无效时才传 `--replace`。

开始原文块示例：

```bash
"{PYTHON}" scripts/manage_batch_checkpoint.py start \
  --root "拆文库/书名" --batch-id RAW-003 \
  --start 21 --end 27 --input-kind raw-original \
  --source-sha256 {64位hash}
```

示例：

```bash
"{PYTHON}" scripts/commit_batch_output.py \
  --input /tmp/B001.md --root "拆文库/书名" \
  --batch-id B001 --start 21 --end 28 --input-kind raw-original \
  --source-sha256 {64位hash}
```

单文件采用临时文件加原子替换。多个文件无法构成真正事务，因此先写分析文件，再写提交凭据，最后更新 `_progress.md` 和批次账本；中断恢复后以凭据中的 hash 校验实际文件，不能仅相信进度行或账本状态。

批次调用失败时先登记：

```bash
"{PYTHON}" scripts/manage_batch_checkpoint.py fail \
  --root "拆文库/书名" --batch-id RAW-003 \
  --reason "输出截断" --split
```

`--split` 只替换 `run-plan.json` 中的失败父块，按 `chapter_index.csv` 字符量生成两个子块；父块写 `superseded`，其余成功收据保持有效。拆分边界写入 `_analysis_cache/batch-checkpoints.json`，重新生成计划时仍会保留，避免下次又合成同一个大块。

## 恢复算法

1. 读取 `_progress.md`，同时枚举实际产物；进度和文件冲突时以可验证文件为准，并记录冲突。
2. `paused_after_stage1` 且 Stage 0/1 文件完整时，从首个未完成 Stage 2 批次继续。
3. 找到标记 `success` 的批次后，读取 `_analysis_cache/receipts/{批次ID}.json`。原文模式验证逐章投影、批次缓存、章节范围和 source hash；已有成果模式只验证批次缓存、范围和输入 hash；通过则跳过。
4. 找到“文件或提交凭据已写但进度未提交”的批次后，用同一临时输入重新运行提交工具；内容与 hash 一致时只补齐缺失文件、凭据或进度，不重新调用模型。
5. 只有输出缺章、损坏、来源变化或校验失败时，才重做该批。大块连续失败时拆成两个子块；其他已验证批次不回退。
6. Stage 3–6 用 `commit_stage_output.py` 为 `aggregate`、`relationships`、`report`、`style` 分别记录输入依赖与输出 hash。恢复时先 `verify`，验证通过即跳过，不因索引完成就标记全流程完成。

阶段完成后把实际输入与输出逐项传入 `--dependency` / `--output`；恢复时先验证：

```bash
"{PYTHON}" scripts/commit_stage_output.py verify \
  --root "拆文库/书名" --stage aggregate
```

若 `chapter_index.csv` 已与当前 source hash、解析器和边界完全一致，只是进度标记尚未写入，索引脚本会补写机械索引区且不重写 CSV；这是“索引已落盘、进度未提交”的确定性恢复。

## 来源变化

相同 source hash 和 parser version 时复用 `chapter_index.csv`。变化时脚本拒绝静默覆盖：

1. 比较新旧章界和受影响章节；
2. 能证明未变的旧事实继续复用；
3. 受影响批次标记 stale；
4. 显式使用 `--rebuild` 更新索引，再只处理 stale 或缺失范围；
5. 旧定位不可验证时不得冒用，也不得直接删除原成果。

## 完成状态

| 状态 | 条件 |
|---|---|
| `paused_after_stage1` | Stage 0/1 完整，等待用户决定是否继续 |
| `pending` | 至少一个用户要求的阶段仍未完成 |
| `completed` | 请求范围内的索引、语义批次、增强、聚合、报告和文风均通过验证 |
| `completed_with_errors` | 流程已走完，但报告明确列出失败批次、证据缺口或无法渲染的关系图 |

纯旧成果直接使用不改变原进度状态。缺少新增分析不能把旧成果标成失败，只限制依赖该分析的新功能。

## 剧情单元清单补建

用户明确要求补清单，或写作侧发现 `剧情/README.md` 缺清单时，可从现有 `剧情/*.md` 的标题、类型、桥段标签和章节范围机械补建。不得读原文、重跑 Stage、改剧情单元内容或动 `剧情/节奏.md`、`剧情/情绪模块.md`。没有字数证据时写“未知”。
