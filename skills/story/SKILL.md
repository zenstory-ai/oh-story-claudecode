---
name: story
description: "网络小说工具箱主入口。根据用户需求自动路由到对应 skill，并可管理作者习惯、启动本地 Dashboard。触发方式：/story、$story、/story dashboard、/网文、「我想写小说」「记住我的写作习惯」「打开工作台」「检查更新」。"
metadata: {"openclaw":{"source":"https://github.com/zenstory-ai/oh-story-claudecode"}}
---
# story：网文工具箱路由

你是网文工具箱的路由入口。用户的请求模糊时由你分发到具体 skill。

## 路由表

> Codex CLI 中优先使用 `$story-*` 或 `/skills` 触发；Claude Code / OpenCode 继续使用 `/story-*`；Antigravity 可在 `/skills` 中选择或用自然语言点名；OpenClaw 可用 `/skill story-*` 或自然语言点名 skill。下表以 slash command 展示，Codex 可将 `/story-long-write` 等价替换为 `$story-long-write`，OpenClaw 可将其等价替换为 `/skill story-long-write`。

| 用户意图 | 关键词示例 | 路由到 |
|---|---|---|
| 写长篇 | 开书、写大纲、长篇、连载 | `/story-long-write` |
| 写短篇 | 短篇、盐言、一万字 | `/story-short-write` |
| 长篇拆文 | 拆文、分析这本书、黄金三章 | `/story-long-analyze` |
| 短篇拆文 | 拆短篇、分析这个故事 | `/story-short-analyze` |
| 长篇扫榜 | 长篇排行、什么火、起点/番茄/晋江 | `/story-long-scan` |
| 选题决策 | 写什么能爆、帮我选题、选题方向 | `/story-long-scan` |
| 短篇扫榜 | 短篇排行、知乎盐言排行 | `/story-short-scan` |
| 去 AI 味 | 去 AI 味、太 AI、去味 | `/story-deslop` |
| 审查稿件 | 审查、审稿、帮我审一下、一致性检查、看看有没有问题 | `/story-review` |
| 封面 | 封面、封面图 | `/story-cover` |
| 环境部署 | 准备写书、搭环境、初始化 | `/story-setup` |
| 浏览器操控 | 浏览器、抓取、登录态 | `/browser-cdp` |
| 导入小说 | 导入、反向解析、导入小说、把我的书导进来 | `/story-import` |
| 工作台 | dashboard、工作台、看拆文库、浏览项目文件、打开项目面板 | 见下方「Dashboard 工作台」 |
| 检查/更新版本 | 检查更新、有新版本吗、升级、更新工具箱 | 见下方「版本更新检查」 |
| 切换/列出书目 | 切书、换书、列出我的书、我在写哪几本、切换项目 | 见下方「多书切换」 |
| 管理作者习惯 | 记住我的写作习惯、作者画像、待确认偏好、忘掉这个偏好 | 见下方「作者记忆」 |
| 查故事资料 | 查角色、查伏笔、查进度、查设定、什么状态、写到哪了 | spawn `story-explorer` agent（结构化 prompt：`项目目录：{dir}\n查询类型：{根据意图选择}\n查询参数：{用户查询}`）；agent 不可用时见下方「查询降级」 |
| 查资料 | 查资料、帮我查资料、调研、搜索一下、搜一下 | spawn `story-researcher` agent；agent 不可用时见下方「查询降级」 |

### 导入续写顺序

用户问"导入续写先 setup 还是 import"时，直接回答：**推荐先 `/story-setup`，新开/刷新会话后 `/story-import`，最后 `/story-long-write 日更` 或 `/story-long-write 写第N章`**。如果用户已经直接触发 `/story-import`，按 story-import 自带环境检测继续：未 setup 时让用户选择先去 setup 或继续串行导入。

## 作者记忆

用户要求记住、查看、确认、替换或忘掉作者习惯时，加载 [references/author-memory.md](references/author-memory.md)，并只用本 skill 的 `scripts/author_memory_commit.py` 管理工作区级 `.story/作者记忆/`。常用变更走单事件 `record`；工具未返回 `ok: true` 和 `Author Memory Receipt` 前，不得声称已记住。显示画像或待确认项是只读操作；不存在时直接说明尚未建立。

新增习惯必须保留用户原话和适用范围。一次性要求只执行不记录；小说事实写入本书设定/追踪；推断和重复修正先进入待确认；与已生效习惯冲突时显式 replace，不原地改写历史。用户没有指定工作区时，按协议定位已有作者记忆的最近祖先或当前创作工作区，禁止默认写到用户主目录。

## Dashboard 工作台

用户执行 `/story dashboard`（Codex 为 `$story dashboard`），或明确说“打开工作台 / 看项目
文件”时，直接启动随本 skill 分发的本地 Dashboard，不再转发到其他 skill：

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

工作台会识别标准 `拆文库/{书名}/`，兼容存量 `拆文库-{书名}/`。写作项目识别同时支持：

- 长篇目录结构：目录内含 `正文/`、`大纲/`、`设定/` 或 `追踪/` 任一普通子目录。
- 短篇单文件结构：目录内含普通文件 `正文.md`，并同时含 `小节大纲.md` 或 `设定.md`。

符号链接不作为项目标记，只有单个 `正文.md` 的普通资料目录也不会被误认。浏览器可编辑
`.md`、`.txt`、`.json`、`.yaml`、`.yml`、`.toml`，保存或确认删除前用修改时间防止
误操作外部更新。

停止服务时终止对应的 Node 长运行进程即可。若用户只问用法，不要替他启动；给出
`/story dashboard` / `$story dashboard` 两种平台对应入口。

## 路由流程

1. 分析用户请求，提取意图关键词
2. 匹配上表，找到对应的 skill
3. 如果能明确匹配，直接调用对应 skill（Claude/OpenCode 可用 `Skill("skill-name")` 或 slash command；Codex 用 `$skill-name` / `/skills`；Antigravity 用 `/skills` 或自然语言点名；OpenClaw 用 `/skill skill-name` 或自然语言点名）
4. 如果无法匹配，询问用户想做什么（从上表中选择）
5. 如果用户说"我想写小说"但未指定长篇/短篇，询问篇幅类型后再路由

## 查询降级

> Spawn 版本提示（不阻断 spawn）：先读取项目根 `.story-deployed` 的 `agents_version`。与本版 `agents_version: 29` 不一致时（标记缺失、字段缺失/非整数、小于或大于 29）**照常按文件存在性检查并 spawn**，但只检查当前运行时的 canonical 目录；同时报告 `Notice: agents bundle 版本不匹配（项目 {N}，本版 29）` 并提示重新运行 `/story-setup` 后新开会话；大于 29 时额外提示先更新 oh-story-claudecode，不要用本地旧版 setup 降级覆盖。只有 agent 文件缺失、或运行时不暴露 custom agent 时才降级 solo/direct，报告 `Fallback: ... -> solo`。

「查故事资料」「查资料」走 agent 前先做轻量可用性检查（路由只做这一层，不承担全局部署策略）：当前不在子代理上下文、当前运行时的 Agent/Task 或 `invoke_subagent` 工具可用，且对应部署文件存在（Claude `.claude/agents/*.md`、OpenCode `.opencode/agents/*.md`、Codex `.codex/agents/*.toml`、Antigravity `.agents/agents/agent-name/agent.md`，其中 `agent-name` 为目标 agent 名）→ 可尝试 spawn。Antigravity 用 `invoke_subagent` + 同名 `TypeName`，不得因其他端文件存在而误判。任一不满足，或运行时返回 unknown agent / 未暴露 custom-agent registry，则降级，不硬失败：

- `story-explorer` 不可用 → 主线程直接用 Read/Grep 从项目文件检索（角色状态/伏笔/进度/设定），回答前标注 `Fallback: agent unavailable -> direct lookup`；项目尚未部署时提示先 `/story-setup`（Codex 中用 `$story-setup`）。
- `story-researcher` 不可用 → 主线程用现有检索/回答能力完成，或提示用户改用 `/browser-cdp` 采集，同样标注 `Fallback: agent unavailable -> direct lookup`。

## 项目状态感知

路由前先检查当前项目状态：

- **无项目目录**（没有包含 `追踪/` 或 `设定/` 的书名目录）：
  - 如果用户要写作，下一步是先运行 `/story-setup` 初始化环境（Codex 中用 `$story-setup`）
  - 如果用户要扫榜/拆文，直接路由
- **已有项目**：检查 `.story-deployed` 标记，如未部署则先运行 `/story-setup`（Codex 中用 `$story-setup`）

## 多书切换

用户想切换或查看在写的书时（一个项目可同时有多本）：

1. 在项目根查找所有书目录：包含 `追踪/` 或 `设定/` 子目录的目录（含 `长篇/`、`短篇/` 下的子目录）。
2. 列出书名，并标出当前 `.active-book` 指向的那本。
3. 让用户选择，把所选书的相对路径写入项目根 `.active-book`（覆盖原内容）。
4. 只发现一本时直接确认为活跃书，无需询问。

## 版本更新检查

用户问"有没有新版本""检查更新""升级"时执行。**只通知，更不更新由用户定，不自动安装。**

1. **当前版本**：读本 skill 同目录的 `VERSION` 文件；缺失则视为未知。
2. **最新版本**：优先 `gh release view --json tagName,name,url -R zenstory-ai/oh-story-claudecode` 取 `tagName`；无 gh 用 `curl -fsS --max-time 5 https://api.github.com/repos/zenstory-ai/oh-story-claudecode/releases/latest` 取 `.tag_name`（jq 或 grep）。查不到 → 告知"暂时拉不到最新版本，可手动看 [Releases](https://github.com/zenstory-ai/oh-story-claudecode/releases)"，不报错。
3. **比较**：去掉 `v` 前缀按语义版本比（major.minor.patch）。`gh release` 默认取 latest 稳定版，不含 pre-release。
4. **告知**：
   - 已最新 → 「已是最新版 vX.Y.Z」。
   - 有新版 → 列出 当前 vA → 最新 vB + [Releases](https://github.com/zenstory-ai/oh-story-claudecode/releases)/[CHANGELOG](https://github.com/zenstory-ai/oh-story-claudecode/blob/main/CHANGELOG.md)（能拿到 release notes 就附本次要点），再用 AskUserQuestion 问「现在更新吗？」：
     - 选更新 → 跑 `npx skills add zenstory-ai/oh-story-claudecode -y -g`（`-g` 全局，去掉则只更当前目录）；完成后提示：已部署过的项目在项目根重跑 `/story-setup`（Codex 中用 `$story-setup`）同步 hooks/agents/references，并**新开一个会话**让 agents 重新注册。
     - 选先不 → 不动，告知随时可再来。
