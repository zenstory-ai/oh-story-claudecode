# Agent Note: README 面向读者而不是答案引擎

Status: implemented

## Problem

2026 年 9 月的 GEO 工作把 README.md / README_EN.md 改成了答案引擎的口味：顶部是站点链接条，接着是一段面向 LLM 的英文摘要、一张站外「实用指南」表和一张「直接回答」表，安装是第 8 个标题，第一条请求前还挂着「不是安装命令、输出仍需审阅、不会与托管工作台自动同步」这类边界句。读者是想开书、导入书稿或改一段正文的网文作者，他们要先翻四屏才能看到工作台截图和安装命令。GitHub 引荐数据显示 Google/Bing/Baidu 带来的访问约为 ChatGPT 类引擎的 7 倍，README 必须先服务人和经典搜索。

## Decision

两个 README 采用同一章节顺序：语言切换 → 标题 → 一句话粗体简介 → 一条项目主页链接 → `demo/story-dashboard.png` → 「这是什么 / What it is」（含核心思路与 v0.7.10 版本说明）→ 安装（`npx skills add` 命令在前，自然语言安装其次，排查与各宿主说明收进 `<details>`）→ 安装后的第一条请求 → 流程总览 → Skills / Agent 体系 / Hooks / 项目文件结构 / 知识体系 / 适用平台 → 常见问题 → 延伸阅读 → 贡献 / 交流 / 致谢 → ZenStory AI 项目 → 一行迁移说明。

删除了顶部 blockquote 链接条、中文 README 里的英文摘要段、「按写作任务开始」和「常见问题的直接回答」两张表（链接压缩为 FAQ 后的「延伸阅读」列表）、第一条请求前的边界段，以及 FAQ 里的「不承诺 / 不代表 / 不是工具实测 / makes no promise / do not promise / not a recorded tool run」句式。项目主页只留 `项目主页：https://zenstory.ai/zh/oh-story` 一条链接。「先跑 `/story-setup` 再新开会话」这条真实要求写在安装段一次，FAQ 的升级条目保留原文。

## Alternatives considered

- **保留答案引擎摘要段，只调整章节顺序**。最强理由：摘要段已被搜索引擎收录，删掉可能短期影响 AI 引擎的引用。被否：摘要段是中文 README 里的英文块，对中文读者是噪音，且 README_EN.md 已覆盖英文受众；AI 引擎引荐量只有经典搜索的约 1/7。
- **把指南表整体删除**。最强理由：六条站外指南都不是安装或使用步骤，删掉最省屏。被否：这些指南回答的正是作者的真实问题（导入续写、连续性、去 AI 味、文风），只是放错了位置；压成 FAQ 之后的一行一条列表既保留链接又不挡路。

## Consequences

- 收益：第一屏就是截图与一句话简介，安装命令从第 8 个标题提前到第 3 个；FAQ 不再夹带免责声明；两份 README 结构一致，站外链接集中在一处便于维护。
- 代价：答案引擎失去一段可直接引用的摘要；站内指南从表格降级为列表，「重点」列被压成一句尾注。

## Verification

手动检查两份 README：前两屏依次是简介、项目主页、`demo/story-dashboard.png`、「这是什么」与安装命令，第一条请求紧随安装之后；对 `不会自动同步 / 不是安装命令 / 输出仍需审阅 / 不承诺 / 不代表 / 独立产品 / 截至 / 当前版本的实际机制 / do not sync / separate product / does not promise / no promise / not a recorded` grep 为空。Skills 13 行、FAQ 11 条、Agent / Hooks / 文件结构 / 知识体系表与原文逐行相同。
