# {项目名} — 网文写作工具集（通用 Agent / Web AI）

本项目按通用文件方式接入 oh-story skills。若当前平台没有 Claude Code / OpenCode / Codex / Antigravity / ZCode / OpenClaw 的 hooks 或 custom agents，仍可直接让 Agent 读取 `skills/*/SKILL.md` 和 `skills/*/references/` 执行；只是运行时硬拦截和多 agent 自动协作不会自动生效。

## Skill 路由表

优先用自然语言点名 skill；如果平台支持自定义命令，也可以把下表映射成命令。

| 意图 | Skill | 说明 |
|------|-------|------|
| 写长篇 / 开书 / 续写 | story-long-write | 长篇网文写作（逐章推进） |
| 写短篇 | story-short-write | 短篇网文写作（情绪驱动） |
| 长篇拆文 | story-long-analyze | 长篇小说深度拆解 |
| 短篇拆文 | story-short-analyze | 短篇小说拆文分析 |
| 长篇扫榜 | story-long-scan | 长篇小说榜单与市场趋势 |
| 短篇扫榜 | story-short-scan | 短篇小说榜单与情绪风口 |
| 去 AI 味 | story-deslop | 去除 AI 写作痕迹 |
| 封面 | story-cover | 生成封面图 |
| 审查 | story-review | 多视角审查；无 custom agents 时降级为单线程审查 |
| 导入 | story-import | 逆向导入已有小说到项目结构 |
| 网文工具箱 | story | 模糊意图自动分发 |
| 准备写书 / 部署 | story-setup | 通用项目结构与 skill 使用入口 |
| 浏览器登录态 / 抓取 | browser-cdp | 浏览器 CDP 工具；需平台允许本地脚本/浏览器控制 |

## 文件结构

- `skills/` — 项目本地 skills；Agent 应先读对应 `SKILL.md`，再按需读取 `references/`
- `拆文库/` — 拆文分析结果存放目录
- `{书名}/正文/` — 长篇小说正文章节
- `{书名}/正文.md` — 短篇小说正文
- `{书名}/设定/` — 角色设定、世界设定
- `{书名}/大纲/` — 卷纲、细纲
- `{书名}/追踪/` — `_tracking-state.json` 唯一结构化权威、固定 7 栏 `上下文.md` 续写状态卡、逐章紧凑记录、核心角色独立派生快照、伏笔当前视图、作者与读者双时间线；全部通过追踪工具生成
- `{书名}/对标/` — 对标作品分析

## 通用使用约定

- 写正文前先有大纲：长篇需要 `大纲/细纲_第N章*.md`，短篇需要 `小节大纲.md`。
- 无 hooks 的平台不会自动拦截越权写正文，Agent 必须在执行写作 skill 时自行检查大纲、上下文和追踪文件。
- 无 custom agents 的平台按 solo/direct 执行；遇到 skill 要求调用 story-architect、narrative-writer 等 agent 时，改由当前 Agent 直接完成，并在结果里说明降级。
- **去AI味自锁**（无 hook 平台此条是唯一防线）：每章正文落盘后，同一轮内立即按写作 skill 的「最毒句式速查 + 禁用词扫描」自检并清零（能运行 node 时跑 `check-ai-patterns.js --check --fail-on=blocking`）；写下一章前先复查上一章无欠账。唯一豁免＝用户显式说"本章不去味"，豁免章在标题行下加 `<!-- 去味:跳过 -->`。
- Compact / 新会话后优先读取 `{书名}/追踪/上下文.md` 恢复当前写作状态。

## Compact 后恢复上下文

写作中的关键上下文：
1. 当前写作项目名称和进度
2. 最近讨论的角色设定变更
3. 未完成的伏笔列表
4. 当前章节的情绪/节奏目标

如果存在 `{书名}/追踪/上下文.md`，compact 后首先读取该文件恢复上下文。
