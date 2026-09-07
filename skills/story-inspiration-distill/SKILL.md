---
name: story-inspiration-distill
version: 1.1.0
description: "小说灵感聚合与公共灵感库管理。机械渲染拆文阶段已随结构块生成的原子灵感字段，再用一次聚合完成单小说合并与有限的跨书候选；跨书卡写入可检索标签，供写作模块按需召回。不会二次逐块分析、回读原文或自动生成完整故事种子。"
metadata: {"openclaw":{"source":"https://github.com/zenstory-ai/oh-story-claudecode"}}
---
# story-inspiration-distill：三层灵感抽象

你负责把拆文阶段已经抽象好的结构块原子转成可复用机制资产，不负责重新拆文，也不负责写新故事。

## 输入边界

只读：

- `拆文库/{书名}/structure_blocks.csv`
- `拆文库/{书名}/全局分析/六维拆书.md`
- `拆文库/{书名}/全局分析/爆款机制.md`
- `拆文库/{书名}/全局分析/证据与边界.md`
- 现有 `灵感库/灵感索引.csv` 与对应三层卡

**禁止读取 `拆文库/{书名}/原文/`、`chapter_index.csv` 或非黄金章正文。** 证据不足时回到拆文模块补结构块，不能在本 skill 重新拆书。

执行前应用 `/story-runtime-guard` 的无历史分叉、单产物 owner、原子提交与断点规则。

## 公共目录

从当前工作区向上定位最近的现有 `灵感库/`；没有时在工作区根创建：

```text
灵感库/
├── 灵感索引.csv
├── 原子灵感/
│   └── {书名}/IA-001.md
├── 单小说灵感合并/
│   └── {书名}.md
├── 跨书灵感聚合/
│   └── CBA-001_{机制名}.md
└── _progress.json
```

三个中文层名是公共契约；英文术语只用于解释：

- 原子灵感 = Inspiration Atom，ID `IA-001`。
- 单小说灵感合并 = Single-Novel Inspiration Merge，簇 ID `NM-001`。
- 跨书灵感聚合 = Cross-Book Inspiration Aggregation，ID `CBA-001`。

## Stage 1：原子灵感（确定性机械渲染）

`structure_blocks.csv` 中每个 `status=ok` 的有效结构块生成且只生成一个 IA。IA 的标题、机制链、读者效果、迁移边界和风险已经由拆文 Stage 3 同次写入五个 `inspiration_*` 字段，本阶段不得调用模型重新概括。

运行：

```text
{PYTHON} scripts/inspiration_index.py render-atoms --root "{灵感库}" --blocks "{拆文目录}/structure_blocks.csv" --book "{书名}"
```

脚本机械生成紧凑 IA 卡，并把该书全部 IA 行对 `灵感索引.csv` **一次写入**。它会拒绝缺字段、结构块表头不匹配和抽象字段泄漏主要角色名；不读取原文或全局文件正文。

原子数必须等于有效结构块数。相同 `source_book + block_id` 重跑时覆盖同一 ID，不追加重复卡。

## Stage 2：单小说灵感合并

在一本书内部按机制因果链、读者需求和节奏形状聚类相似原子，写入 `单小说灵感合并/{书名}.md`。通常合并为 3–6 个 NM；语义确实不同可以超过，不得为凑数量硬并。

每个 NM 簇记录：

- `atom_count` 与 `source_atoms`。
- 共同机制、变化形态、成立条件、该书特有偏置、误用风险。
- 来源原子用相对链接列出；统计不是目录名，不另建“来源数目”层。

无法合并的原子保留单成员簇，不能为压缩数量硬并。

## Stage 3：跨书灵感聚合

把 NM 簇与现有 CBA 轻量索引比较，只读取可能匹配的 active CBA，不遍历全部 IA/NM。一本书内部的 NM 与 CBA 更新在同一次聚合上下文完成，不为每个簇分别调用模型。

只有一部书支持时，最多激活 3 张最有写作复用价值的 CBA，并必须标 `单书假设`；其余 NM 留在单小说层等待第二本书，不强行全部升格。两部及以上独立来源才标 `跨书重复验证`。

每张 CBA 必须记录：

- `novel_count`、`atom_count`、来源小说、来源 NM 与来源 IA。
- 共同机制链、可变参数、适用条件、反例、不可照搬边界和风险。
- “可能适用于”标签。标签契约见 [references/inspiration-contract.md](references/inspiration-contract.md)。

标签只表达适用性，不把观察写成市场定论。一本书来源不能标“普遍有效”。

## 标签与索引

`灵感索引.csv` 表头严格为：

```csv
item_id,layer,title,source_book,path,source_ids,novel_count,atom_count,tags,status
```

- 三层都入索引；`layer` 只取 `原子灵感/单小说灵感合并/跨书灵感聚合`。
- 写作模块只按 `layer=跨书灵感聚合` 且 `status=active` 检索。
- IA/NM 的 `tags` 留空，避免写作绕过聚合层；它们可在卡内保留“聚类键”，但不是公共召回标签。
- CBA 的标签按受控轴书写，不用自由散词。用 `scripts/inspiration_index.py validate` 验证，用 `query` 做确定性 Top-K。

## 原子提交与恢复

`_progress.json` 记录输入结构块校验和、机械渲染 IA、已合并小说、已更新 CBA、索引校验和与下一操作。每层都先写临时卡并验证链接，再原子替换；中断后从最近未提交层继续。结构块哈希不变时复用 IA，不再次调用语义模型。

## 禁止事项

- 不回读原文，不重新拆章。
- 禁止第二次语义读取：不读取结构块 locator 对应的原文片段，不把 IA 机械渲染变成第二次逐块分析。
- 不自动生成完整原创故事种子、角色组合、具体事件链或成稿桥段。
- 不复制原作专名、标志性台词、独有设定和原句。
- 不把原子海量塞进写作上下文；默认只由标签命中的 CBA 进入写作。
- 不为减少卡数强行合并语义不同的机制。

## 完成检查

1. 有效结构块数 = IA 数。
2. 每个 IA 恰好归属至少一个 NM。
3. 每个 CBA 能回链 NM 与 IA，统计一致。
4. CBA 标签轴合法；单书假设状态准确。
5. 全流程没有读取 `原文/` 或 `chapter_index.csv`。
6. `scripts/inspiration_index.py validate --root "{灵感库}"` 通过。
7. IA 由 `render-atoms` 机械生成且索引只写一次；单书 active CBA 不超过 3。
