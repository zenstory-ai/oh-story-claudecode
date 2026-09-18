# 文风档案生成与单独重建

> **何时加载**：story-long-analyze Stage 6。Stage 6 可以在完整管道末尾运行，也可以在已有拆文只缺 `文风.md` 时单独运行；单独运行不得触发 Stage 1–5。

## 原则

1. 文风档案描述作者实际写法，不评价作者水平。
2. 情绪和节奏意图以 `剧情/情绪模块.md`、`剧情/节奏.md` 为准，文风只管表达层。
3. 已有完整 `文风.md` 时原样保留；用户明确要求增强时才更新。
4. Stage 6 不重扫全书。允许使用索引行号定点回读 4–6 段原文，以补齐可验证锚点。
5. 摘要措辞不能冒充作者原句；缺少原文和有效样本时明确报错。

## 来源顺序

1. 既有 `文风.md`；
2. 项目内非空且含连续原文的 `_style-sample.txt`；
3. `章节/第1-3章_深度拆解.md` 中带定位的短引和写法证据；
4. `_analysis_cache/批次-*.md`、`章节/*_摘要.md` 与 `拆文报告.md` 的结构层观察；
5. 仍缺锚点时，读取 `chapter_index.csv`，按旧版“覆盖主要基调”的方式选择 4–6 章，再按 `start_line/end_line` 定点读取原文片段。

第 5 项只读取被选章节的局部行段，不允许从头到尾扫描原文。没有索引的旧项目可以仅运行机械索引脚本；这一步不写 `_progress.md`，也不启动其他分析阶段。

## 单独重建文风

当 story-long-write 或用户发现 `文风.md` 缺失时：

1. 运行检查器，确认其他拆文成果可用且 `stage_repairs` 包含 `stage6_style`；
2. 若 `_style-sample.txt` 有效，直接用它；
3. 否则确认 `chapter_index.csv` 与原文存在。缺索引时只运行：

   ```text
   "{PYTHON}" "{story-long-analyze skill 根}/scripts/build_chapter_index.py" --source "{拆文目录}/原文/原文.txt" --output "{拆文目录}/chapter_index.csv" --locator-path "原文/原文.txt"
   ```

4. 从索引中选择 4–6 章，优先覆盖紧张、轻松、冲突、关系回收、高潮与收束等已有资料能确认的不同基调；按行号只取每章一段 300–500 字连续原句，写入或更新 `_style-sample.txt`；
5. 按 [style-profile-protocol.md](style-profile-protocol.md) 生成 `文风.md`；
6. 文件成功落盘后运行：

   ```text
   "{PYTHON}" "{story-long-analyze skill 根}/scripts/manage_analysis_run.py" mark-stage --root "{拆文目录}" --stage stage6 --output "文风.md"
   ```

索引、原文和有效样本都不存在时停止，返回“无法取得可验证文风锚点”，不得生成锚点全空的可用文风。

## 档案内容

- 叙述视角、段落推进、对白比例、动作与心理安排；
- 句长、标点、口吻和角色语气，只从原文锚点归纳；
- 情绪转场引用三维节奏和篇幅安排，不把剧情强度当文风；
- 每项标 `high / med / low` 置信度及来源路径；
- 原文锚点 4–6 段，每段标章节、行号、基调和示范点。

## 质量检查

- 每条高置信结论都有资料路径或可核原文锚点；
- 4–6 段锚点覆盖不同基调，且来自索引指定的局部行段；
- 摘要没有被当成作者原句；
- `文风.md` 保持现有下游字段，未获增强请求时不覆盖旧文件；
- Stage 6 失败只报告本阶段缺口，不回头重跑 Stage 1–5。
