# Agent Note: 三层灵感库改为拆书技能内管道，复用 EM 机制卡

Status: implemented
Date: 2026-09-22
Issue: PR #387（依赖 PR #386）
Related: [2026-09-22-long-analyze-single-state-runtime](../architecture/2026-09-22-long-analyze-single-state-runtime.md)
Related（接手收口）：[2026-09-23-inspiration-library-takeover](../simplification/2026-09-23-inspiration-library-takeover.md)——逐章挂点与子串近义判定已在该篇撤回

## Problem

三层灵感库最初的设计（PR #387 首版）基于六维拆书的 `structure_blocks.csv`：每个结构
块的五个 `inspiration_*` 字段机械渲染一个原子灵感（IA）文件。评审后的 #386 移除了
结构块产物，该底座不复存在。首版的实际试运行还暴露了两个结构性问题：

1. **逐块原子化导致重复维护**——单书 IA 多达 60–148 个，机制内容在 EM 卡、IA 卡、
   NM 卡、CBA 卡四层重复出现；评审意见明确要求「尽量复用已有的案例和机制分析，再做
   跨书比较与检索，减少同一内容在多层卡片中重复维护」。
2. **来源路径墙**——一张 CBA 卡的来源节列出 62 条 IA 相对路径链接，写作每次召回都
   要读这面墙；评审要求「杜绝 CBA 及原子卡片中的大量重复引用路径，改为需要时可查」。

另外，独立第 14 个 skill 带来打包、部署、命令、七端清单的全套配线，而灵感库本质是
拆文产物的组织层。

## Decision

1. **并入 story-long-analyze 作可选后置管道**，不新增 skill：文档为
   `references/inspiration-library.md`，脚本为 `scripts/inspiration_index.py`（与三个
   状态脚本并列）。触发词「灵感库/提炼灵感/跨书灵感聚合/更新灵感库」；**单书拆文不
   自动入库**。skill 计数保持 13，打包/部署/命令零改动。
2. **IA 源改挂 Stage 3 的 EM 机制卡**（#386 的「三层灵感库最小消费契约」已为此预留
   `EM-*` 权威 ID）：五字段 1:1 映射（读者想看什么/情绪链＋戏剧单元/可替换项/不可照
   搬）。**IA 降为索引登记行，不生成文件**——机制全文只在 `剧情/情绪模块.md` 一处维
   护；每书 IA 数量从逐块的几十上百个降为 EM 卡数（完整卡 `grade=full`＋索引条目
   `grade=index`）。
3. **卡内禁路径引用**：NM/CBA 来源只写 `书名/EM-xxx` 式裸 ID 一行；`validate` 机械
   拒绝卡内出现 `](`、`.md)`、层目录名或 `拆文库/`。路径解析统一走 `灵感索引.csv`
   （新增 `resolve` 子命令按需回查）。CBA 引用 NM 时成员 EM 自动并入闭包，不再展开
   列出；`novel_count`/`atom_count` 由闭包自动核算。
4. **NM 只在同书 ≥2 卡同构时创建**，内容为合并增量（理由/差异/反例），不复述机制；
   取消首版「每个 IA 必须归属一个 NM」的覆盖率要求。
5. **消费面全阶段挂点**：写前召回新增可选轴 (a0)（Top 3 active CBA →
   `selected_inspiration_aggregates`，无库/零命中记 gap 不阻塞，降档照常执行）；
   写手 prompt 组装脚本新增「跨书灵感」槽（脚本探测 `灵感库/灵感索引.csv`，无库直接
   封槽、有库留空槽归主会话按 (a0) 填）；开书（适用阶段=设定）、卷纲（=卷纲）、细纲
   （=细纲）各加一条可选召回旁注；cross-book-recall 增「公共灵感标签召回」节（八轴
   标签、核心轴门槛、Top 3–8 预算），并明确该通道**独立于多对标 ≥2 本触发条件**；
   story-explorer `benchmark_style_load` 附带同一召回；project-files 权威读取顺序第 6
   条钉死预算与冲突裁决。专名泄漏登记时按 `角色/` 目录
   机械扫描（「不可照搬」字段除外——点名专名是其职责）。
6. **缺料走 #386 的按需增强**：无 `剧情/情绪模块.md` 时返回 `repair_action` 指向
   `--intent enhance`（原文读取可为 0），灵感层不代拆、不补写。版本号与发布安排留给
   维护者，本次不动 `agents_version` / `setup_skill_version`。

## Alternatives considered

- **保留独立 skill**：边界最清晰、可单独安装；但灵感库输入输出全部长在拆文产物上，
  独立 skill 的代价是 14 技能全套打包与部署配线，且评审方向是收敛，放弃。
- **保留逐块 IA 文件（沿用首版）**：IA 文件可独立阅读；但这正是重复维护与路径墙的
  根源，且结构块底座已被 #386 移除，放弃。
- **IA 完全不登记、CBA 直接引用 EM**：层级最少；但失去「每书机制清单」这一跨书比较
  的工作面与 EM↔IA 集合一致性校验的抓手，索引行成本极低，保留登记层。

## Consequences

收益：机制全文单点维护，索引从试运行库的 493 行量级降到每书数行；CBA 卡体积随路径
墙移除大幅缩小，写作召回上下文只含自包含抽象；重跑登记逐字节幂等；EM 变化由
`ia_em_set_mismatch` 机械发现。

代价：CBA 溯源需要经索引二跳（`resolve` 缓解）；机制覆盖密度从逐结构块降为 EM 卡
粒度（最强 3 张完整＋其余索引条目），弱机制只有 ID 级登记；旧格式试运行库不做迁移
（main 从未发布过灵感库，无兼容负担）。
