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
| 发布准备 | 发布资料、建书表单、平台书名简介标签、建书资料 | `/story-publish` |
| 写短篇 | 短篇、盐言、一万字 | `/story-short-write` |
| 长篇拆文 | 拆文、分析这本书、黄金三章、灵感库、跨书灵感聚合 | `/story-long-analyze` |
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
| 工作台 | dashboard、工作台、看拆文库、浏览项目文件、打开项目面板 | 见下方「Dashboard 工作台」 |
| 检查/更新版本 | 检查更新、有新版本吗、升级、更新工具箱 | 见下方「版本更新检查」 |
| 切换/列出书目 | 切书、换书、列出我的书、我在写哪几本、切换项目 | 见下方「多书切换」 |
| 管理作者习惯 | 记住我的写作习惯、作者画像、待确认偏好、忘掉这个偏好 | 见下方「作者习惯管理」 |
| 查故事资料 | 查角色、查伏笔、查进度、查设定、什么状态、写到哪了 | 见下方「查询」 |
| 查资料 | 查资料、帮我查资料、调研、搜索一下、搜一下 | 见下方「查询」 |

能明确匹配就直接调用对应 skill；匹配不上时只问缺的那一项。用户说"我想写小说"但没说长篇还是短篇，先问篇幅再路由。

### 裸调用与新手

只说 `/story`、看不出意图时，不贴路由表，给四个白话选项：「开一本长篇或接着写」→ `/story-long-write`；「写一篇短篇」→ `/story-short-write`；「把一章改得不那么 AI」→ `/story-deslop`；「更多（拆书、扫榜、导入旧稿、审稿、封面）」→ 再列进阶项。还没部署过（项目根没有 `.story-deployed`）时先建议 `/story-setup`，并说明部署完要新开一个会话再开始，写作助手才会生效。

作者明确要填平台建书资料（书名、简介、标签）时走 `/story-publish`，只说“开书”照常进长篇写作。ClawHub 单独安装的 `story` 不带 story-publish，找不到它时直接告诉作者，请其安装完整技能包，不凭记忆给平台标签。

### 导入续写顺序

用户问"导入续写先 setup 还是 import"时，直接回答：**推荐先 `/story-setup`，新开会话后 `/story-import`；导完长篇说 `/story-long-write 写第N章`（N 是导入后的下一章），短篇用 `/story-short-write` 先补完构思**。如果用户已经直接触发 `/story-import`，按 story-import 自带环境检测继续：未 setup 时让用户选择先去 setup 或继续串行导入。

## 书目录判定

本文件的"书目录""当前书"均按此查找：

1. 项目根有 `.active-book` 且指向项目内一个存在的目录 → 就是它。
2. 否则在项目根往下最多 4 层找，跳过以 `.` 开头的目录、`node_modules`、`拆文库/`、`对标/`：
   - 含 `追踪/`、`正文/` 子目录或 `正文.md` 文件的目录（与写作 hook 同一口径）；
   - 刚定完方向、还没有正文的长篇：含 `设定/题材定位.md` 的目录；
   - 构思中、还没有正文的短篇：同时有 `设定.md` 与 `小节大纲.md` 的目录。
   找到多本又没有 `.active-book` 时，需要"当前书"就问作者是哪本（做法同「多书切换」）。
3. 篇幅：有 `正文/` 或 `设定/` 子目录的是长篇，有 `正文.md` 或 `设定.md` 文件的是短篇。

没找到任何书目录：创建写作项目时先运行 `/story-setup`；只讨论结构、选题，或要扫榜、拆文时直接路由。找到了：按目标 skill 自己的环境检查继续，需要初始化或补部署时运行 `/story-setup`。

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
type：{可选：历史考证、地理/环境、职业知识、文化习俗、器物/服饰、描写参考、命名参考、体系构建、诗词典故、视觉参考、真实案例、读者偏好}
context：{可选：为什么要查，如正在写哪一段}
project_dir：{书目录的绝对路径；没有书目录时用项目根}
cdp_port：{可选：Chrome 调试端口不是 9222 时写}
```

### 能不能用助手

> Spawn 版本提示（不阻断 spawn）：先读取项目根 `.story-deployed` 的 `agents_version`。与本版 `agents_version: 38` 不一致时（标记缺失、字段缺失/非整数、小于或大于 38）**照常按当前宿主角色来源检查并 spawn**；同时用一句白话提示作者「查资料助手是旧版，运行 /story-setup（ZCode 先更新插件）后新开会话」，`Notice: agents bundle 版本不匹配（项目 {N}，本版 38）` 原文写进回答最末一行「技术备注：」；大于 38 时额外提示先更新 oh-story-claudecode，不要用本地旧版 setup 降级覆盖。只有当前宿主角色缺失或不暴露调用能力时才降级 solo/direct，`Fallback: ... -> solo` 同样只进技术备注行。

走助手前只做本端可用性检查：当前不在子代理内、有本端调用工具，且对应角色可用（Claude `.claude/agents/*.md`、OpenCode `.opencode/agents/*.md`、Codex `.codex/agents/*.toml`、Antigravity `.agents/agents/agent-name/agent.md`；ZCode 查插件注册的同名角色，不要求 `.zcode/agents`）→ 可尝试 spawn。Antigravity 用 `invoke_subagent` + 同名 `TypeName`，ZCode 用 `Agent` 按实际 schema 派发，不跨端误判。任一不满足或返回 unknown agent，则降级处理：

- `story-explorer` 不可用 → 主会话直接用 Read/Grep 从书目录检索（角色状态、伏笔、进度、设定），回答前说一句「查资料助手没启用，这次我直接翻项目文件」；项目尚未部署时提示先 `/story-setup`。
- `story-researcher` 不可用 → 主会话用当前可用的搜索能力回答，回答前说一句「查资料助手没启用，这次我直接搜」；搜不到就如实说明。

### 怎么回答作者

讲故事里的事（谁、在哪章、发生了什么）；文件字段名、伏笔/事件编号不单独出现，编号必须跟着故事描述。助手返回的英文字段和缺口说明由主会话翻成白话再说。

## 多书切换

用户想切换或查看在写的书时（一个项目可同时有多本）：

1. 按「书目录判定」第 2 条列出所有书目录，标出当前 `.active-book` 指向的那本。
2. 让用户选择，把所选书的相对路径写入项目根 `.active-book`（覆盖原内容）。
3. 只发现一本时直接确认为活跃书，无需询问。

## Dashboard 工作台

用户执行 `/story dashboard`，或明确要求打开工作台、查看项目文件时，启动本 skill 的本地 Dashboard：

1. 把**当前工作目录**作为默认工作区；用户明确给出目录时改用该目录。目录必须存在。
2. 从当前已加载的 `story` skill 目录定位 `scripts/dashboard-server.mjs`，不要硬编码仓库路径、
   全局 skill 路径或用户主目录。
3. 检查 `node` 可用后，以长运行进程执行：

   ```bash
   node "<story-skill-dir>/scripts/dashboard-server.mjs" --root "<workspace>" --open
   ```

4. 等待输出出现“本机地址”，把完整 URL 回给用户。工具支持后台进程/PTY 时让服务保持运行；
   无法自动拉起浏览器不算失败，仍返回可点击 URL。
5. Dashboard 默认只监听 `127.0.0.1`。不要主动增加 `--allow-network`，不要把工作区暴露到
   局域网或公网。

工作台按自己的规则识别目录，与上方「书目录判定」不同：识别标准 `拆文库/{书名}/`，兼容存量 `拆文库-{书名}/`；写作项目识别同时支持：

- 长篇目录结构：目录内含 `正文/`、`大纲/`、`设定/` 或 `追踪/` 任一普通子目录。
- 短篇单文件结构：目录内含普通文件 `正文.md`，并同时含 `小节大纲.md` 或 `设定.md`。

符号链接不作为项目标记，只有单个 `正文.md` 的资料目录不识别为写作项目。浏览器可编辑 `.md`、`.txt`、`.json`、`.yaml`、`.yml`、`.toml`；保存或确认删除时核对文件内容版本，避免覆盖外部修改。

停止服务时终止对应的 Node 长运行进程即可。若用户只问用法，不要替他启动；告诉用户用 `/story dashboard`（按上方宿主写法替换）。

## 版本更新检查

用户问“有没有新版本”“检查更新”“升级”时执行。**先报告版本，是否安装由用户决定。**

1. **当前版本**：读本 skill 同目录的 `VERSION` 文件；缺失则视为未知。本 skill 在写作项目里（如项目下的 `skills/`、`.agents/skills/`、`.zcode/skills/`）时，读到的是项目副本的版本。
2. **最新版本**：优先 `gh release view --json tagName,name,url -R zenstory-ai/oh-story-claudecode` 取 `tagName`；无 gh 用 `curl -fsS --max-time 5 https://api.github.com/repos/zenstory-ai/oh-story-claudecode/releases/latest` 取 `.tag_name`（jq 或 grep）。查不到 → 告知"暂时拉不到最新版本，可手动看 [Releases](https://github.com/zenstory-ai/oh-story-claudecode/releases)"，不报错。
3. **比较**：当前版本已知时，去掉 `v` 前缀按语义版本比较（major.minor.patch）；未知时只展示最新稳定版，不判定是否已最新。`gh release` 默认取 latest 稳定版，不含 pre-release。
4. **告知**：
   - 已最新 → 「已是最新版 vX.Y.Z」。
   - 有新版或当前版本未知 → 展示已知版本与 [Releases](https://github.com/zenstory-ai/oh-story-claudecode/releases)/[CHANGELOG](https://github.com/zenstory-ai/oh-story-claudecode/blob/main/CHANGELOG.md)，有 release notes 时附更新要点，再用宿主可用的提问方式问「现在更新吗？」。选先不 → 不动，告知随时可再来。
5. **更新**（用户同意后）：按本 skill 目录的位置判断安装方式。
   - 在插件目录里（路径含 `plugins/`）：Claude Code 跑 `claude plugin marketplace update oh-story-skills` 再跑 `claude plugin update oh-story@oh-story-skills`，重启后生效；ZCode 在 Plugin Management 里刷新市场后更新 `oh-story`。
   - 用 `npx skills` 装在全局或当前目录：重跑 `npx skills add zenstory-ai/oh-story-claudecode -y -g`（原来装在当前目录的去掉 `-g`）。
   - 其他安装方式（如 ClawHub）：按原来的方式重装最新版。
   - 本 skill 在写作项目里：先用上面对应的方式更新安装包，再用新装的包在项目根运行 `/story-setup`，项目里的副本才会换成新版；OpenClaw、Reasonix 和通用文件模式下项目里跑的就是这份旧副本，要用新包手动覆盖项目 `skills/` 下的 14 个 skill 目录。

   更新完提示：已部署过的项目在项目根重跑 `/story-setup` 同步 hooks、agents 和参考资料，然后**新开一个会话**，写作助手才会重新加载。
