# demo — real output samples

[中文](README.md)

Real output from the skills, browsable as files.

> **Provenance**: *曾将爱意私藏* and *让你管账号，你高燃混剪炸全网* are this project author's own
> published works, so both the source text and the deconstruction are included here.
> *Coiling Dragon* (《盘龙》) is a Qidian classic used only as **input** for deconstruction —
> this directory holds our generated analysis, not the original prose.
>
> In every case the skills' **output** is the deconstruction report, plot-node list, technique notes,
> character/plot/setting files and tracking state.

## Cover generation example
![Cover example — Sword Dao Supreme](封面-剑道独尊.png)


## Deconstruction demo — Coiling Dragon
Full output from `/story-long-analyze` deep mode on the first 23 chapters of *Coiling Dragon*:

```
demo/拆文库/盘龙/
├── 概要.md              # Novel overview + chapter index
├── 拆文报告.md           # 5-dimension scoring + pacing analysis + takeaways
├── 文风.md              # Benchmark voice: sentence rhythm, punctuation, dialogue subtext, emotion pacing
├── 章节/
│   ├── 第1章_深度拆解.md … 第3章_深度拆解.md  # One deep analysis per Golden-3 chapter
│   └── 第1章_摘要.md … 第23章_摘要.md          # One summary file per chapter
├── 角色/
│   ├── 林雷.md           # Protagonist full profile
│   ├── 霍格.md           # Core supporting
│   ├── 希尔曼.md         # Core supporting
│   ├── 希里.md           # Functional character
│   ├── 德林柯沃特.md      # Core supporting
│   ├── 沃顿.md           # Functional character
│   └── 角色关系.md        # Relationship network
├── 剧情/
│   ├── 故事线.md          # Framework + 4 plotlines + 2 storylines
│   ├── 强者过境与魔法启蒙.md etc.  # Five scene-level plot units
│   ├── 节奏.md            # Pacing + key-info progression + emotional trigger eruption rhythm
│   └── 情绪模块.md        # Reader needs + emotional engine + reusable writing modules
└── 设定/
    ├── 世界观/
    │   ├── 背景设定.md    # Core rules + special settings
    │   ├── 力量体系.md    # Battle qi + magic + ranks
    │   ├── 地理.md        # Andaluxia + Yulan Continent
    │   └── 金手指.md      # Panlong Ring + Delin Cowort
    └── 势力/
        └── 巴鲁克家族.md  # Baluk family (dragon-blood lineage)
```

Long-form deconstruction also produces `文风.md`, plus `剧情/节奏.md` (pacing, key-info progression, emotional trigger eruption rhythm) and `剧情/情绪模块.md` (reader needs, emotional engine, reusable writing modules); daily writing consumes these through `对标/{书名}/剧情/` to keep voice, pacing, and emotion modules close to the benchmark.


## Deconstruction demo — Once I Hid My Love (曾将爱意私藏, short-form)
`/story-short-analyze` deconstructing the short story 《曾将爱意私藏》 (~8,500 chars, win-back / "faked-death" genre):

```
demo/拆文库/曾将爱意私藏/
├── 原文/原文.txt        # Source backup
├── 拆文报告.md          # Story core + 5-dim scores + 6-facet payoff + cognitive reversal + 9-layer resonance
├── 情节节点.md          # 54 plot points (source quotes + emotion markers −9~+9)
├── 写作手法.md          # POV / dialogue / info-gap / object-hook — 11 techniques
└── _meta.json           # structure_counts (Phase 7 gate basis)
```

Short-form deconstruction outputs `拆文报告 / 情节节点 / 写作手法`; downstream `/story-short-write` writes a new same-genre story from them.


## Import demo — 让你管账号，你高燃混剪炸全网 (long-form continuation project)
Run `/story-setup` first, then use `/story-import` to reverse-build the author's already-published first 20 chapters (~37k Chinese chars) into a continuation-ready writing project. Continue with `/story-long-write 日更` or `/story-long-write 写第21章`:

```
demo/长篇/让你管账号，你高燃混剪炸全网/
├── 正文/        Chapters 001–020 (published source text)
├── 大纲/        大纲.md · 卷纲_第1卷.md · 细纲_第001–020章.md (one file per chapter)
├── 设定/        角色/ (6 character files) · 世界观/{background · cheat-system}
│                关系.md · 题材定位.md · 文风.md
└── 追踪/        _tracking-state.json · 上下文.md · 伏笔.md · 逐章记录/
                 角色状态/{角色名}.md · 时间线/{作者真相.md · 读者已知.md}
```

Per-chapter extraction (events / characters / settings / foreshadowing / timeline) is reverse-engineered into a continuation bible, so the author seamlessly continues from chapter 21.

## Added in this batch

| Path | What it is |
|---|---|
| [`长篇/…/正文/第021章_离别怎么会开花.md`](长篇/让你管账号，你高燃混剪炸全网/正文/第021章_离别怎么会开花.md) | Chapter 21, continued by `/story-long-write` in one real session (2,068 chars, chapter check green; the README video is this session) |
| [`长篇/…/大纲/细纲_第021章.md`](长篇/让你管账号，你高燃混剪炸全网/大纲/细纲_第021章.md) · [`设定/角色/谭守义.md`](长篇/让你管账号，你高燃混剪炸全网/设定/角色/谭守义.md) | The blueprint the skill wrote first (0 blocking structural findings) and the new character card |
| [`长篇/…/.deslop-whitelist`](长篇/让你管账号，你高燃混剪炸全网/.deslop-whitelist) · [`追踪/逐章记录/第021章.md`](长篇/让你管账号，你高燃混剪炸全网/追踪/逐章记录/第021章.md) | The book-local style whitelist the skill created itself; the chapter-21 tracking record (with its retirement log) |
| [`设定/角色/陆振国.md`](长篇/让你管账号，你高燃混剪炸全网/设定/角色/陆振国.md) · [`大纲/卷纲_第1卷.md`](长篇/让你管账号，你高燃混剪炸全网/大纲/卷纲_第1卷.md) · [`设定/关系.md`](长篇/让你管账号，你高燃混剪炸全网/设定/关系.md) | What the author's one-line ruling at the end of the video ("the sceptic is a military-affairs influencer") turned into: a new character card, plus the volume outline and relationship table updated to match (second session, 6½ minutes) |
| [`去AI味对照/`](去AI味对照/README_EN.md) | Real scan output from the `/story-deslop` checker: 8 findings on an AI-flavored sample vs zero on the clean rewrite |

> `追踪/` was advanced to chapter 21 by the skill itself, in the same real session, through `storyctl.py chapter commit`
> (`state_revision` 0 → 1); every derived view is re-rendered from `_tracking-state.json`. `.deslop-whitelist` was also
> registered by the skill after reading `设定/文风.md`.