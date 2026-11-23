---
name: output-contract
description: story-short-analyze 输出契约。定义 Stage → 文件映射、_meta.json schema（v2.1）、量化网感体检表与 3 段原文语感切片交付、写入顺序、Resume 与验收接入点。
---

# 输出契约：story-short-analyze ↔ story-short-write

`story-short-analyze` 将网络短篇拆文产出存入 `拆文库/{书名}/`。`story-short-write` 构思与落稿时读取拆文报告、情节节点、写作手法（含量化网感体检表 + 3 段原文语感切片）、原文与 `_meta.json`，直接校准结构节奏与竖屏腔调。

---

## 输出目录与文件树

```
拆文库/{书名}/
├── 原文/                  # 管道前置步骤产出，存放源文件备份
├── 拆文报告.md             # 人类可读综合报告（Stage 2-6 按阶段追加各段）
├── 情节节点.md             # Stage 2 情节节点清单（完整清单只存这一份）
├── 写作手法.md             # Stage 4 产出（必含：量化网感体检表 + 3 段 150-250 字原文语感切片 + 核心手法）
└── _meta.json             # 管道元数据 + Stage 6 结构计数与网感摘要（v2.1）
```

**文件名约定**：`story-short-write` 按 `拆文报告.md / 情节节点.md / 写作手法.md / _meta.json` 定位产物，不可重命名。分析正文写入 Markdown，结构计数、题材枚举与网感关键指标写入 `_meta.json`。

---

## Stage → 文件映射

| Stage | 名称 | 落地文件 | 主要内容 |
|-------|------|----------|---------|
| 2 | 结构+情节节点 | `拆文报告.md`（题材/故事核/结构划分/梗概/情节节点摘要段） + `情节节点.md` | 题材（12 类枚举） / 故事核 / 网短篇五段结构划分（导语冷开场/免费建压/付费强卡点/连环反击反转/明账清算收尾） / 故事梗概 / 情节节点清单（每节点带位置） |
| 3 | 情感线+爆点 | `拆文报告.md`（情感曲线+钩子与付费断点+爆点+期待感） | 情感曲线 / 钩子与 30–40% 付费断点 / 爆点分析（含前40% vs 后60%分布） / 期待感 |
| 4 | 反转+写作手法 | `拆文报告.md`（反转分析段） + `写作手法.md` | 前置反转检查 / 反转或报应机制 / **`写作手法.md` 必含 `[BLOCK]`：量化网感体检表（9 项）+ 3 段 150–250 字原文语感切片（导语冷开场 / 对话交锋或压迫 / 高潮打脸或清算）+ 核心手法** |
| 5 | 人物+开头结尾 | `拆文报告.md`（人物分析+开头分析+结尾分析+钩子回收） | 人物分类与人设反差标签 / 反派压迫与功能评估 / 导语与首百字入局分析 / 清算收尾与钩子回收检查 |
| 6 | 综合评估 + `_meta.json` 写计数 | `拆文报告.md`（综合评估段） + `_meta.json` | 网短篇五维评分 / 爆点性 / 话题性 / 共鸣分析 / 主结构 / 投稿层 / 可复用结构（含失败条件） / 节奏速报 + **写入 `structure_counts` 与 `voice_metrics`** |

---

## `_meta.json` schema

`_meta.json` 保存来源字数、题材、时间、阶段进度、结构计数与网感摘要，供续跑、验收与下游对标召回使用；详细分析写入 Markdown。

```jsonc
{
  "version": "2.1",
  "word_count": 10240,                  // 源文字数（Phase 1 Step 2 数出）
  "genre_detected": "追妻火葬场",        // Phase 1 Step 3 题材识别，取值见下方 Step 2 表（12 类枚举）
  "created_at": "{ISO8601 时间戳}",      // 拆文启动时间，写入时填当前 UTC
  "stages_completed": [2, 3, 4, 5],     // 已完成 Stage，按完成顺序 append
  "last_stage_in_progress": null,       // 当前正在执行的 Stage；空闲为 null

  "structure_counts": {                 // Stage 6 内容写完时一次性写入；计数照实填，可以为 0
    "beats": 5,                         // 结构段数（网短篇五段划分，Stage 2）
    "hooks": 6,                         // 钩子数（钩子标尺的功能类型，Stage 3）
    "setup_clues": 3,                   // 反转铺垫线索数（Stage 4）；无反转填 0
    "character_archetypes": 2,          // 有反差人物数（Stage 5）
    "reusable_structures": 2,           // 可复用结构条数（Stage 6）
    "reversal_type": "视角反转"          // 反转类型枚举（视角/身份/动机/时间线/信息/认知/无反转）；多层取影响最大一层
  },

  "voice_metrics": {                    // Stage 6 同步写入，与 写作手法.md「量化网感体检表」一致
    "median_para_chars": 20,            // 段长中位（字）
    "single_sentence_para_rate": 0.85,  // 单句成段率（0~1）
    "dialogue_ratio": 0.36,             // 对话占比（0~1）
    "first_conflict_char": 65,          // 首冲突/首对白出现字位
    "hook_rate": 0.75,                  // 非末节节尾卡点率（0~1）
    "ending_type": "明账清算"            // 明账清算 / 火葬场追悔 / HE发糖 / 细思极恐留白 / 开放式
  }
}
```

### 写入顺序（中断后可续）

1. **Stage N 开始前**：`last_stage_in_progress = N`，写盘。
2. **Stage N 文件写完后**：检查文件非空、新增内容长度合理（如 `拆文报告.md` 新增段 ≥ 200 字；Stage 4 确认 `写作手法.md` 已含体检表与 3 段切片）。
3. **通过**：Stage 2–5 清空 `last_stage_in_progress`，将 `N` 追加到 `stages_completed[]`；Stage 6 须先通过下方验收。
4. **失败**：`stages_completed` 不动，`last_stage_in_progress` 保留为 `N`。
5. **Stage 6 内容写完后**：一次性写入 `structure_counts` 与 `voice_metrics` 到 `_meta.json`，再进入验收。

### Resume 协议

- `last_stage_in_progress` 非空 → 该 Stage 上次中断，**从头**重跑，不复用半成品（若 `拆文报告.md` 已追加该 Stage 半截小节，先截断/替换该小节再重写，避免重复段）；Stage 6 内容已齐、仅验收未过时只重跑验收。
- `last_stage_in_progress` 为空且 `stages_completed` 不含 `6` → 从 `max(stages_completed) + 1` 开始；尚无完成阶段时从 Stage 2 开始。
- `stages_completed` 含 6 → 已完成，只询问用户覆盖或取消。

**Stage 6 完成须同时满足内容写完与验收通过**。验收未过前，`last_stage_in_progress` 保持 `6`，`stages_completed` 不含 `6`。

---

## 验收接入点

Stage 6 内容写完后、将 `6` 追加到 `stages_completed[]` 前，依次跑三道检查，通过后执行 Step 4：

### Step 1：拆文报告表达自检

按拆文流程本地加载的报告表达规则检查 `拆文报告.md`，跳过源文引用与语感切片，只修报告本身的证据不足、空转套话与越界推测。发现问题时暂不将 `6` 追加到 `stages_completed[]`，修订后重扫。

### Step 2：`_meta.json` 字段与枚举校验

计数反映源文实际有多少，不设最低值：源文没有的写 0，并在报告对应段写明「源文没有」。阻断只看字段是否写齐、取值是否合法：

| 字段 | 要求 | 不达标 |
|------|------|--------|
| `structure_counts.beats` | ≥ 1（完本通常 4–5 段；半成品或极短片段按实际已有功能段计） | 阻断 |
| `hooks` / `setup_clues` / `character_archetypes` / `reusable_structures` | 已写入非负整数，与报告对应段一致 | 阻断 |
| `structure_counts.reversal_type` | 在枚举内（含「无反转」） | 阻断 |
| `genre_detected` | 12 类枚举之一：`追妻火葬场`、`总裁豪门`、`世情打脸`、`宅斗宫斗`、`年代重生打脸`、`脑洞设定流`、`复仇打脸`、`甜宠`、`男频都市反杀`、`双男主`、`悬疑`、`通用短篇` | 阻断 |
| `voice_metrics` | 6 项指标与 `写作手法.md`「量化网感体检表」口径一致 | 阻断 |

> 情节节点数不设阈值，按 `情节节点.md` 的语义变化边界提取，不在本表。`beats` 是结构段数，不是情节节点数。

### Step 3：`story-short-analyze` BLOCK 项扫描

扫拆文流程本地质量检查清单的全部 `[BLOCK]` 项（重点确认 `写作手法.md` 已含**量化网感体检表**与**3 段 150–250 字原文语感切片**）。任一缺失 → 阻断。`[WARN]` 项 → 写入拆文报告末尾「待补」清单，不阻断。

### Step 4：通过

清空 `_meta.json.last_stage_in_progress`，将 `6` 追加到 `stages_completed[]`，按拆文流程 SKILL 的完成汇报告诉作者。

---

## 版本约定

`_meta.json.version` 现行 `"2.1"`：字段改名、类型或历史必填变更升 major；新增字段 `voice_metrics` 在新版 `2.1` 拆文中为必填阻断项，下游读取旧 `2.0` 产出时视为可选并保持向后兼容，故升 minor。
