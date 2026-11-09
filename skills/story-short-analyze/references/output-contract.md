---
name: output-contract
description: story-short-analyze 输出契约。定义 Stage → 文件映射、_meta.json schema、写入顺序、Resume 与验收接入点；写作侧维护产出的读取方式。
---

# 输出契约：story-short-analyze ↔ story-short-write

`story-short-analyze` 将短篇拆文产出存入 `拆文库/{书名}/`。`story-short-write` 构思新篇时结合报告、节点、手法与原文建立对标，正文阶段从已落盘的对标摘要召回。

---

## 输出目录与文件树

```
拆文库/{书名}/
├── 原文/                  # 管道前置步骤产出，存放源文件备份
├── 拆文报告.md             # 人类可读综合报告（Stage 2-6 按阶段追加各段）
├── 情节节点.md             # Stage 2 情节节点清单（完整清单只存这一份）
├── 写作手法.md             # Stage 4 写作手法分析（独立成文）
└── _meta.json             # 管道元数据 + Stage 6 结构计数（resume + 验收数值依据）
```

**文件名约定**：`story-short-write` 按 `拆文报告.md / 情节节点.md / 写作手法.md` 定位产物，不可重命名。分析正文写入 Markdown，结构计数与反转枚举写入 `_meta.json.structure_counts`；具体读取范围与顺序按写作侧参考文件执行。

---

## Stage → 文件映射

| Stage | 名称 | 落地文件 | 主要内容 |
|-------|------|----------|---------|
| 2 | 结构+情节节点 | `拆文报告.md`（题材/故事核/结构/梗概/情节节点摘要段） + `情节节点.md` | 题材 / 故事核 / 结构划分（含开端/发展/高潮/结局） / 故事梗概 / 情节节点清单（每个节点带位置：节号 + 约第几字） |
| 3 | 情感线+爆点 | `拆文报告.md`（情感曲线段+钩子段+爆点段） | 情感曲线 / 钩子与付费断点 / 爆点 6 维度 / 期待感 |
| 4 | 反转+写作手法 | `拆文报告.md`（反转段） + `写作手法.md` | 前置反转检查 / 反转分析（铺垫线索逐条带位置） / 写作手法 ≥5 项维度 |
| 5 | 人物+开头结尾 | `拆文报告.md`（人物段+首尾段） | 人物分类+功能评估 / 开头分析 / 结尾分析 / 首尾呼应 |
| 6 | 综合评估 | `拆文报告.md`（综合段） + `_meta.json`（写 structure_counts） | 五维评分 / 爆点性 / 话题性 / 共鸣 ≥3 层 / 主结构 / 投稿层 / 可复用结构（含失败条件） / 节奏速报 |

---

## `_meta.json` schema

`_meta.json` 保存来源字数、题材、时间、阶段进度及结构计数，供续跑与验收使用；分析正文写入 `拆文报告.md`。

```jsonc
{
  "version": "2.0",
  "word_count": 5234,                   // 源文字数（Phase 1 Step 2 数出）
  "genre_detected": "追妻",             // Phase 1 Step 3 题材识别，取值见下方 Step 2 表
  "created_at": "{ISO8601 时间戳}",      // 拆文启动时间，写入时填当前 UTC
  "stages_completed": [2, 3, 4, 5],     // 已完成 Stage，按完成顺序 append
  "last_stage_in_progress": null,       // 当前正在执行的 Stage；空闲为 null

  "structure_counts": {                 // Stage 6 内容写完时一次性写入；计数照实填，可以为 0
    "beats": 5,                         // 结构段数（结构划分，含开端/发展/高潮/结局，Stage 2）
    "hooks": 4,                         // 钩子数（钩子标尺的功能类型，Stage 3）
    "setup_clues": 3,                   // 反转铺垫线索数（Stage 4）；无反转填 0
    "character_archetypes": 1,          // 有反差人物数（Stage 5）
    "reusable_structures": 2,           // 可复用结构条数（Stage 6）
    "reversal_type": "视角反转"          // 反转类型枚举（视角/身份/动机/时间线/信息/认知/无反转）；甜宠/喜剧/报应型填「无反转」；多层反转取对结局影响最大的一层
  }
}
```

### 写入顺序（中断后可续）

1. **Stage N 开始前**：`last_stage_in_progress = N`，写盘。
2. **Stage N 文件写完后**：检查文件非空、新增内容长度合理（如 `拆文报告.md` 新增段 ≥ 200 字）。
3. **通过**：Stage 2–5 清空 `last_stage_in_progress`，将 `N` 追加到 `stages_completed[]`；Stage 6 须先通过下方验收。
4. **失败**：`stages_completed` 不动，`last_stage_in_progress` 保留为 `N`。
5. **Stage 6 内容写完后**：一次性算出 `structure_counts` 并写入 `_meta.json`，再进入验收。

### Resume 协议

- `last_stage_in_progress` 非空 → 该 Stage 上次中断，**从头**重跑，不复用半成品；Stage 6 内容已齐、仅验收未过时按下方例外处理。
- `last_stage_in_progress` 为空且 `stages_completed` 不含 `6` → 从 `max(stages_completed) + 1` 开始；尚无完成阶段时从 Stage 2 开始。
- `stages_completed` 含 6 → 已完成，只询问用户覆盖或取消。

**Stage 6 完成须同时满足内容写完与验收通过**。验收未过前，`last_stage_in_progress` 保持 `6`，`stages_completed` 不含 `6`。续跑时若综合段与 `structure_counts` 已完整落盘，只重跑验收；验收发现内容缺失则补足对应产出。

---

## 验收接入点

Stage 6 内容写完后、将 `6` 追加到 `stages_completed[]` 前，依次跑三道检查，通过后执行 Step 4：

### Step 1：拆文报告表达自检

按拆文流程本地加载的报告表达规则检查 `拆文报告.md`，跳过源文引用，只修报告本身的证据不足、空转套话与越界推测。发现问题时暂不将 `6` 追加到 `stages_completed[]`，修订后重扫。成稿去 AI 味由写作流程维护，不在此评判源文是否由 AI 写成。

### Step 2：`_meta.json.structure_counts` 校验

计数反映源文实际有多少，不设最低值：源文没有的写 0，并在报告对应段写明「源文没有」。阻断只看字段是否写齐、取值是否合法：

| 字段 | 要求 | 不达标 |
|------|------|--------|
| `structure_counts.beats` | ≥ 4（结构划分含开端/发展/高潮/结局）| 阻断 |
| `hooks` / `setup_clues` / `character_archetypes` / `reusable_structures` | 已写入非负整数，与报告对应段一致 | 阻断 |
| `structure_counts.reversal_type` | 在枚举内（含「无反转」）| 阻断 |
| `genre_detected` | 追妻、重生复仇、死人文学、小三、世情、豪门、宫斗宅斗、民俗、悬疑、甜宠、双男主、沙雕、仙侠之一，或「通用」 | 阻断 |

> 情节节点数不设阈值，按 `情节节点.md` 的语义变化边界提取，不在本表。`beats` 是结构段数，不是情节节点数。

### Step 3：`story-short-analyze` BLOCK 项扫描

扫拆文流程本地质量检查清单的全部 `[BLOCK]` 项，确认对应产出均已写出。
任一缺失 → 阻断。`[WARN]` 项 → 写入拆文报告末尾「待补」清单，不阻断。

### Step 4：通过

清空 `_meta.json.last_stage_in_progress`，将 `6` 追加到 `stages_completed[]`，按拆文流程 SKILL 的完成汇报告诉作者。

---

## 版本约定

`_meta.json.version` 跟本契约走：字段改名、类型或必填变更升 major，新增可选字段升 minor。
