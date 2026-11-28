---
name: story
description: "网络小说工具箱主入口。根据用户需求自动路由到对应 skill，并可启动本地 Dashboard。触发方式：/story、$story、/story dashboard、/网文、「我想写小说」「记住我的写作习惯」「打开工作台」「检查更新」。"
metadata: {"openclaw":{"source":"https://github.com/zenstory-ai/oh-story-claudecode"}}
---
# story：网文工具箱路由

识别用户的写作需求，并路由到对应 skill。

## 路由表

各宿主的调用写法：Claude Code、OpenCode 用 `/story-*`（Claude 插件安装时为 `/oh-story:story-*`），也可 `Skill("story-*")`；Codex、ZCode 用 `$story-*`（Codex 也可 `/skills`）；OpenClaw 用 `/skill story-*`；Antigravity、Reasonix 在 skill 入口选择或用自然语言点名。下表按 `/story-*` 写，其他宿主照此替换，本文件其余地方同理。

| 用户意图 | 关键词示例 | 路由到 |
|---|---|---|
| 长篇规划/写作 | 讨论长篇结构、规划剧情、开书、写大纲、补细纲、长篇、连载 | `/story-long-write` |
| 发布准备 | 发布资料、建书表单、平台书名简介标签、建书资料、上架准备 | `/story-publish` |
| 写短篇 | 短篇、盐言、七猫短篇、点众、一万字 | `/story-short-write` |
| 长篇拆文 | 拆文、分析这本书、黄金三章 | `/story-long-analyze` |
| 短篇拆文 | 拆短篇、分析这个故事 | `/story-short-analyze` |
| 长篇扫榜 | 长篇排行、什么火、新书在冒什么、起点/番茄/晋江/七猫长篇 | `/story-long-scan` |
| 短篇扫榜 | 短篇排行、知乎盐言排行 | `/story-short-scan` |
| 选题决策 | 写什么能爆、帮我选题、选题方向 | 长篇 `/story-long-scan`，短篇 `/story-short-scan`；没说篇幅先问一句 |
| 去 AI 味 | 去 AI 味、太 AI、去味 | `/story-deslop` |
| 审查稿件 | 审查、审稿、帮我审一下、一致性检查、看看有没有问题 | `/story-review` |
| 封面 | 封面、封面图、封面提示词 | `/story-cover` |
| 环境部署 | 准备写书、搭环境、初始化 | `/story-setup` |
| 浏览器操控 | 浏览器、抓取、登录态 | `/browser-cdp` |
| 导入小说 | 导入、反向解析、导入小说、把我的书导进来 | `/story-import` |
| 工作台 | dashboard、工作台、看拆文库、浏览项目文件、打开项目面板 | 见下方「工作台与版本更新」 |
| 检查/更新版本 | 检查更新、有新版本吗、升级、更新工具箱 | 见下方「工作台与版本更新」 |
| 切换/列出书目 | 切书、换书、列出我的书、我在写哪几本、切换项目 | 见下方「多书切换」 |
| 管理作者习惯 | 记住我的写作习惯、作者画像、整理作者记忆、忘掉这个偏好 | 见下方「作者习惯管理」 |
| 查故事资料 | 查角色、查伏笔、查进度、查设定、什么状态、写到哪了 | 见下方「查询」 |
| 查资料 | 查资料、帮我查资料、调研、搜索一下、搜一下 | 见下方「查询」 |

能明确匹配就直接调用对应 skill；匹配不上时只问缺的那一项。用户说"我想写小说"但没说长篇还是短篇，先问篇幅再路由。

### 裸调用与新手

只说 `/story`、看不出意图时，不贴路由表，给四个白话选项：「开一本长篇或接着写」→ `/story-long-write`；「写一篇短篇」→ `/story-short-write`；「把一章改得不那么 AI」→ `/story-deslop`；「更多（拆书、扫榜、导入旧稿、审稿、封面）」→ 再列进阶项。还没部署过（项目根没有 `.story-deployed`）时先建议 `/story-setup`，并说明部署完要新开一个会话再开始，写作助手才会生效。

作者明确要填平台建书资料（书名、简介、标签）时走 `/story-publish`，只说“开书”照常进长篇写作。ClawHub 单独安装的 `story` 不带 story-publish，找不到它时直接告诉作者，请其安装完整技能包，不凭记忆给平台标签。

### 导入续写顺序

用户问"导入续写先 setup 还是 import"时，直接回答：**推荐先 `/story-setup`，新开会话后 `/story-import`；导完长篇说 `/story-long-write 写第N章`（N 是导入后的下一章），短篇用 `/story-short-write` 先补完构思**。如果用户已经直接触发 `/story-import`，按 story-import 自带环境检测继续：未 setup 时让用户选择先去 setup 或继续串行导入。

## 书目录判定

本文件的"书目录""当前书"按此查找：

1. 项目根 `.active-book` 指向项目内现有目录即当前书。
2. 否则从项目根往下最多 4 层找（跳过 `.` 开头目录、`node_modules`、`拆文库/`、`对标/`），含 `追踪/`、`正文/` 子目录、`正文.md` 文件、`设定/题材定位.md`，或同时含 `设定.md` 与 `小节大纲.md` 的是书目录；找到多本又无 `.active-book` 时问作者选（同「多书切换」）。
3. 篇幅：有 `正文/` 或 `设定/` 子目录为长篇，有 `正文.md` 或 `设定.md` 为短篇。

没找到书目录时：创建写作项目先跑 `/story-setup`；只讨论结构、选题、扫榜或拆文时直接路由。找到书目录后按目标 skill 的环境检查继续，需初始化或补部署时跑 `/story-setup`。

## 作者习惯管理

按用户明确指定的长篇/短篇选写作 skill；没指定时按当前书的篇幅。没有当前书的通用习惯交 `/story-long-write` 管理；只针对某本书却定位不到时问是哪本，不要求先建书。路由层只转交，不读写作者记忆文件。

## 查询

### 交给哪个助手、传什么

「查故事资料」交 `story-explorer`，prompt 三行：

```text
项目目录：{书目录的绝对路径}
查询类型：{按下表选}
查询参数：{用户问到的角色名、伏笔、设定关键词或章节范围}
```

| 用户在问 | 查询类型 |
|---|---|
| 某角色现在什么状态 | `character_status` |
| 某角色在哪几章出场 | `character_appearances` |
| 某条伏笔的情况 | `foreshadow_status` |
| 还有哪些伏笔、哪些没收 | `foreshadow_list` |
| 某个设定怎么定的 | `setting_detail` |
| 某个设定在哪些章出现过 | `setting_appearances` |
| 第 X 到 Y 章发生了什么 | `timeline`（查询参数默认带 `perspective: reader`；作者明确问幕后真相时用 `author`） |
| 写到哪了 | `progress` |
| 两个角色现在什么关系 | `relationship` |

一句话含多类查询时，分次调用或只选最主要的一类；问的是创作建议而不是查已有内容时，不交给它，主会话直接答。

「查资料」交 `story-researcher`，prompt 按下面写，没有的可选项整行省略：

```text
query：{要查的主题}
type：{可选：历史考证、地理/环境、职业知识、文化习俗、器物/服饰、诗词典故、视觉参考、真实案例}
context：{可选：为什么要查，如正在写哪一段}
project_dir：{书目录的绝对路径；没有书目录时用项目根}
cdp_port：{可选：Chrome 调试端口不是 9222 时写}
```

### 能不能用助手

> 版本：先读取项目根 `.story-deployed` 的 `agents_version`。与本版 `agents_version: 47` 不一致时（标记缺失、字段缺失/非整数、小于或大于 47）**照常按当前宿主角色来源检查并 spawn**，只用一句白话提示作者「查资料助手是旧版，运行 /story-setup（ZCode 先更新插件）后新开会话」；大于 47 时额外提示先更新 oh-story-claudecode，不要用本地旧版 setup 降级覆盖。只有当前宿主角色缺失或不暴露调用能力时才降级 solo/direct，按下方一句白话告知作者，不另加技术备注行。

走助手前只做本端可用性检查：当前不在子代理内、有本端调用工具，且对应角色可用（Claude `.claude/agents/*.md`、OpenCode `.opencode/agents/*.md`、Codex `.codex/agents/*.toml`、Antigravity `.agents/agents/agent-name/agent.md`；ZCode 查插件注册的同名角色，不要求 `.zcode/agents`）→ 可尝试 spawn。Antigravity 用 `invoke_subagent` + 同名 `TypeName`，ZCode 用 `Agent` 按实际 schema 派发，不跨端误判。任一不满足或返回 unknown agent，则降级处理：

- `story-explorer` 不可用 → 主会话直接用文件读取与检索工具从书目录检索（角色状态、伏笔、进度、设定），回答前说一句「查资料助手没启用，这次我直接翻项目文件」；项目尚未部署时提示先 `/story-setup`。
- `story-researcher` 不可用 → 主会话用当前可用的搜索能力回答，回答前说一句「查资料助手没启用，这次我直接搜」；搜不到就如实说明。

### 怎么回答作者

讲故事里的事（谁、在哪章、发生了什么）；文件字段名、伏笔/事件编号不单独出现，编号必须跟着故事描述。助手返回的英文字段和缺口说明由主会话翻成白话再说。

## 多书切换

用户想切换或查看在写的书时（一个项目可同时有多本）：

1. 按「书目录判定」第 2 条列出所有书目录，标出当前 `.active-book` 指向的那本。
2. 让用户选择，把所选书的相对路径写入项目根 `.active-book`（覆盖原内容）。
3. 只发现一本时直接确认为活跃书，无需询问。

## 工作台与版本更新

- 启动或停止本地 Dashboard 工作台，以及检查/升级工具箱版本时，按需读取 [references/dashboard-and-update.md](references/dashboard-and-update.md) 执行。
- Dashboard 默认只监听 `127.0.0.1`（不开启局域网监听）；版本更新须先报告版本，经用户同意后再安装。
