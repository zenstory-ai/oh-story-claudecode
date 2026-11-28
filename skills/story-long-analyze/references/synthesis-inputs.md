# Stage 3–5：取料与事实保真

Stage 3、4、5 时刻均读本文件。

## 取料

用只读 `digest` 按需提取跨章观察与逐章字段（输出 Markdown），不重读全书缓存或原文：

```text
node "{story-long-analyze skill 根}/scripts/manage_analysis_run.js" digest --root "{拆文目录}" --part observations [--chapters 1-60]
node "{story-long-analyze skill 根}/scripts/manage_analysis_run.js" digest --root "{拆文目录}" --part chapters --chapters 1-60 --fields 三维节奏,涉及,状态变化 --points brief
```

- `observations`：按章汇总跨章观察（剧情点、披露候选、关系变化、峰谷、跨批状态），是 Stage 3–4 主语料。
- `chapters`：抽逐章字段（概要、关键事件、因果、局面结果、涉及、信息变化、状态变化、三维节奏、章尾钩子、证据）；`--points brief` 给标题/类型/基调，`full` 带白描。
- 上下文装不下时按 `--chapters` 分窗口合并，仅关键证据冲突才定点读取单章摘要；旧项目无缓存时直接复用现有资料，证据不足标未知/待核；Stage 3–5 绝不回读原文，Stage 6 仅按索引定点取 4–6 段锚点。

## 证据等级与阶段标记

底层文件推断按三级标：`A 明确`（资料直给）、`B 强推断`（多细节共同支持）、`C 暂定`（证据不足待核）；作者报告不写字母，按 author-facing 说人话。

Stage 3–5 产物落盘后再标完成（Stage 3 需 `节奏.md` 与 `情绪模块.md` 齐备；Stage 4 需至少 1 份角色档案与 1 份设定；Stage 5 需主报告）：

```text
node "{story-long-analyze skill 根}/scripts/manage_analysis_run.js" mark-stage --root "{拆文目录}" --stage stage3 --output "剧情/节奏.md"
```

## 事实保真

不凭常识补齐资料未给信息：力量等级、数值、距离、势力数、台词归属、出场章均须可回指批次证据或旧成果，查不到改写「原文未明确/旧资料未提供」或删除；相邻实体属性、等级、台词、统计数字不串用；落盘后抽查核对。
