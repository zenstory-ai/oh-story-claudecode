# Agent Note: 精简 README 重复与非核心章节

Status: implemented
Related: [2026-09-16-readme-for-readers-not-engines](../process/2026-09-16-readme-for-readers-not-engines.md)、[2026-09-16-readme-masthead](../process/2026-09-16-readme-masthead.md)

## Problem

居中 masthead 上线后，`README.md` 与 `README_EN.md` 仍保留约 440 行篇幅，存在三处明显重复与堆积：
1. 「这是什么」「工作原理」「适用平台」三节反复复述同一组事实（文件系统当记忆、写前守卫与写后检查、7 款编程 Agent、目标网文平台）；
2. 底部挂着 17 条链接的「延伸阅读」，以及与 masthead 社区按钮、仓库标准入口重复的「贡献」「交流」「贡献者」小节；
3. 「常见问题」累积到 11 条，其中能否在 Codex 使用、是否需要显卡、长短篇入口差异等已在前文回答，冲淡了真正需要排查的导入续写、连贯性、Windows 安装报错与升级步骤；部分段落和英文首条请求示例还残留「宿主」等生硬工程措辞。

## Decision

1. **合并重复概览**：将「工作原理」中唯一的增量信息（`_tracking-state.json` 底账、7 个专职角色分工、`docs/architecture.md` 与 `docs/knowledge-base.md` 入口）及「适用平台」完整平台列表并入「这是什么」，删除独立的「工作原理」与「适用平台」两节；同步更新 `docs/architecture.md` 与 `docs/architecture_EN.md` 回指锚点。
2. **裁撤尾部冗余小节**：删除「延伸阅读」「贡献」「交流」「贡献者」四节；将「致谢」紧接在「常见问题」之后、置于「ZenStory AI 项目」之前，并简化为三条纯链接（`linux.do`、`FanqieRankTracker`、`zhuque`）。
3. **收敛 FAQ 与行文润色**：将「常见问题」从 11 条压至 5 条高频实操与排障问答（旧稿导入续写、长篇防崩机制、外部 AI 检测器差异、Windows `ENOENT` 修复、升级与切换工具），关键站内文档与实操指南随对应回答就近挂出；保留全部 6 个真实运行/对照代码块与表格原文不变，收紧外围说明，把面向作者正文里的「宿主 / host」改为「编程 Agent / 工具」，并将 `README_EN.md` 首条请求改为自然的作者口吻，保持中英文结构逐节对齐。

## Alternatives considered

- **保留「延伸阅读」但折叠进 `<details>`**。最强理由：不丢任何仓库内 SEO 文章入口。被否：折叠块仍需双语同步维护 17 条链接，且高频指南已就近挂入对应 FAQ 回答，其余专题文章留在 `docs/` 由搜索引擎和文档目录自然索引即可。
- **保留全部 11 条 FAQ，只缩短每条字数**。最强理由：读者直接按标题检索时命中面更广。被否：前两条和末条与「这是什么」「安装」「Skills」完全重复，保留只会拉长首尾阅读路径。

## Consequences

- **收益**：`README.md` 与 `README_EN.md` 各缩减约三分之一篇幅，核心信息集中在「这是什么 → 安装 → 实际效果 → 第一条请求 → 流程与 Skills → 5 条 FAQ」，中英文标题、代码块、表格与尾部结构 1:1 对齐，阅读更顺畅。
- **代价**：部分 `docs/` 专题写作文章不再从根 README 直接出链；`docs/architecture*.md` 原先指向 `#工作原理` / `#how-it-works` 的锚点改指 `#这是什么` / `#what-it-is`。
