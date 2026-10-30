# 开源 AI 写小说工具怎么选：10 个项目按使用方式对比（2026）

选开源 AI 写小说工具，先按使用方式分三类：装进 Claude Code、Codex、Cursor 等编程 Agent 里的命令或 skill 包；自带界面、填自己 API Key 就能用的命令行或桌面应用；需要在本机部署的网页应用。分好类，再看三件事：长篇的前后一致靠什么维持，模型从哪里来，项目是否还在维护。

> 利益相关：本文由 Oh Story 的维护者编写，Oh Story 和 ZenStory 工作台也在对比之列。所有项目按同一组标准列出，数据取自各项目仓库与 README，截至 2026-10-30；星标数和最近提交日期会变，引用前请回仓库核对。

## 一、总表

| 项目 | 使用方式 | 许可证 | 星标 / 默认分支最近提交 | 模型从哪来 | 长篇一致性靠什么 |
|---|---|---|---|---|---|
| [InkOS](https://github.com/Narcooo/inkos) | 命令行 + 终端界面 + 本地网页 | AGPL-3.0 | 10,915 / 2026-10-24 | 自配 API：OpenAI、Anthropic 及兼容接口，列表含 Ollama | `story/state/*.json` 状态文件、伏笔状态（打开/推进/延后/回收）、连续性审计 Agent |
| [ainovel-cli](https://github.com/voocel/ainovel-cli) | 命令行 / 终端界面 / 无头模式（Go） | Apache-2.0 | 2,256 / 2026-10-15 | 自配 `base_url`：OpenRouter、Anthropic、Gemini、OpenAI 等 | 多 Agent（架构、写手、编辑、仲裁），滚动分卷规划，按伏笔和人物出场推荐相关章节，七维审稿，断点续写 |
| [show-me-the-story](https://github.com/Nigh/show-me-the-story) | 单个可执行文件 + 浏览器界面（Go） | MIT | 631 / 2026-10-04 | OpenAI 兼容接口 | 人物、世界观、组织与关系图；带出处的事实抽取；设定变更提案；伏笔追踪 |
| [Pagekin（AI-Novel-Writer）](https://github.com/EthanYoQ/AI-Novel-Writer) | 桌面应用（Windows / macOS） | GPL-3.0 | 2,053 / 2026-10-29 | 自填 OpenAI 兼容 Key，或本地 Ollama | 设定、架构、章节蓝图，逐章写、审、改、定稿；人物关系图 |
| [goink](https://github.com/sigpanic/goink) | 桌面应用（Go + Wails） | AGPL-3.0 | 488 / 2026-10-13 | 未核实 | 人物、关系历史与伏笔回收期限的结构化追踪；本地中文语义检索 |
| [AI_NovelGenerator](https://github.com/YILING0013/AI_NovelGenerator) | 本地网页应用（Next.js + FastAPI + MongoDB） | AGPL-3.0 | 6,364 / 2026-10-16 | OpenAI 兼容、DeepSeek、Gemini、Claude | 卷—弧—场景—章节分层规划，人物与势力关系图，可编辑的节点式工作流 |
| [Long-Novel-GPT](https://github.com/MaoXiaoYuZ/Long-Novel-GPT) | 网页应用（Gradio，Docker） | 未检测到许可证 | 1,251 / 2025-11-05 | `.env` 配 Key，支持 OpenAI 格式的本地接口 | 大纲→章节→正文逐层展开，可导入旧作拆书再改写 |
| [NovelKit](https://github.com/t59688/novel-kit) | 编程 Agent 斜杠命令（README 写明目前只支持 Cursor） | 未检测到许可证（README 徽章写 MIT） | 162 / 2025-12-22 | 用宿主的模型 | “小说宪法”一致性检查，章节生命周期，伏笔追踪 |
| [novel-writer-skills](https://github.com/wordflowlab/novel-writer-skills) / [novelws](https://github.com/binlee1990/novel-writer-skills) | Claude Code 斜杠命令 | MIT | 270 / 2025-10-20；分支版 novelws 6 / 2026-02-26 | 用 Claude Code 的模型 | `/track`、`/plot-check`、`/timeline` 等追踪命令；novelws 另有 JSON 追踪文件和本地看板 |
| [Oh Story](https://github.com/zenstory-ai/oh-story-claudecode)（我们） | 编程 Agent skill 包，适配 Claude Code、Codex、OpenCode 等 7 个宿主 | MIT | 8,153 / 2026-10-30 | 用宿主 Agent 的模型，不另配 | 设定、大纲、正文、追踪分文件存；写正文前检查本章细纲；追踪文件由工具重建，手改会被检查拒绝 |

另一个相关项目是 [denova](https://github.com/alfredxw/denova)（Apache-2.0，981 星，Beta）：写作加互动游戏的工作台，内置网文 skill，也能接入 Claude Code、Codex。

## 二、按你的情况选

**想让 AI 尽量自动写完长篇。** 看 ainovel-cli 和 InkOS。ainovel-cli 的 README 写明可写到 500 章以上，支持断点恢复，也能逐章人工审批；InkOS 把状态、伏笔和章节摘要都落成文件，还有连续性审计。两者都需要自己配模型 API。

**不用编程 Agent，想要一个打开就能写的应用。** 看 show-me-the-story（一个不到 10MB 的可执行文件，浏览器里操作）、Pagekin（桌面应用，可接本地 Ollama）和 goink。它们都由作者自己填 API Key，费用按自己用的模型计算。

**已经在用编程 Agent。** 看 Oh Story、novel-writer-skills / novelws 和 NovelKit。这类工具不带模型，写作用的就是 Agent 当前的模型。区别在宿主范围和题材：novel-writer-skills 只支持 Claude Code，NovelKit 只支持 Cursor；Oh Story 适配 7 个宿主，流程按网文写（起点、番茄、晋江等平台的扫榜和拆文）。

**想在本机部署一套网页工作台。** AI_NovelGenerator 功能最全，但需要 MongoDB 副本集，README 说明只适合本地使用、没有登录鉴权。Long-Novel-GPT 用 Docker 启动最简单，不过最近一次提交已是一年前。不想部署也可以用托管版的 ZenStory 工作台（我们的项目，免费版每天 3 条 AI 消息）。

## 三、选之前再核对三件事

1. **许可证。** AGPL（InkOS、AI_NovelGenerator、goink）要求以网络服务形式提供修改版时公开源码；MIT、Apache 更宽松；GitHub 未检测到许可证的项目（NovelKit、Long-Novel-GPT）在复用代码前要先问清作者。只是自己写书用，许可证影响不大。
2. **维护状态。** 默认分支一年内没有提交的项目，接口或模型变动后可能跑不起来。AI_NovelGenerator 的 `main` 分支是重写版，和旧版数据结构不同，星标大多积累在旧版。
3. **是否面向网文。** README 明确面向中文网文的有 Oh Story（列出起点、番茄、晋江、七猫、刺猬猫等平台）和 Pagekin（写明为网文连载设计）；Long-Novel-GPT 附带网文风格的提示词。其余项目写的是通用小说创作，网文的黄金三章、断章、追读这些要靠自己的提示和细纲补上。

## 常见问题

**开源 AI 写小说工具需要显卡吗？**
大多数不需要。它们调用云端模型 API，或者使用编程 Agent 自带的模型；只有接本地模型（如 Ollama）时，才需要本机算力。

**用自己的 API Key 写一本书大概花多少钱？**
取决于模型单价、章节数和每章的审稿轮数，各项目都没有给出统一数字。先用几章试跑，按实际用量估算；ainovel-cli 和 Long-Novel-GPT 都能在运行中看到消耗。

**商业工具和这些开源项目怎么取舍？**
商业工具如 Sudowrite（每月 10 美元起）、NovelCrafter（每月 4 美元起）、笔灵 AI 都是在线服务，开箱即用，数据存在服务方。开源项目把设定、大纲和正文留在自己电脑上，能改流程，代价是要自己配模型和环境。

## 相关

- Oh Story 安装：[README 安装说明](../README.md#安装)
- 长篇怎么不崩人设：[AI 写长篇小说怎么不崩人设](ai-long-novel-character-consistency.md)
- 仓库地址：https://github.com/zenstory-ai/oh-story-claudecode
