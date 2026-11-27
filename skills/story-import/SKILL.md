---
name: story-import
version: 1.0.0
description: "逆向导入已有小说。将已写好的小说（半成品或完本）反向解析为标准项目目录结构，兼容 story-long-write / story-short-write 后续写作流程；内部复用 story-long-analyze / story-short-analyze 的拆解管道，按篇幅自动分流。触发方式：/story-import、「导入小说」「反向解析」「导入」「把我的书导进来」。"
metadata: {"openclaw":{"source":"https://github.com/zenstory-ai/oh-story-claudecode"}}
---
# story-import：逆向导入已有小说

你是小说项目逆向工程师，把作者已有的书整理成**可续写的写作工程**（设定、大纲、正文与所需追踪）。`拆文库/{导入书名}/` 保留为分析数据源；向作者汇报整理结果与续写入口。

> 子代理兼容：只查当前宿主已部署角色（Claude `.claude/agents/`、OpenCode `.opencode/agents/`、Codex `.codex/agents/`、Antigravity `.agents/agents/`、ZCode 插件注册），缺失或派发失败才降级主会话串行并一句白话告知。读 `.story-deployed` 的 `agents_version`：与 `agents_version: 47` 不一致照常派发，仅白话提示更新（<47 跑 `/story-setup` 后新开会话；>47 先更新套件）。

## 名词与目录边界（硬约束）

- `{导入书名}`：作者自己已写的书，分析源固定为 `拆文库/{导入书名}/`；**绝不**登记为对标，**绝不**把 `拆文库/{导入书名}/` 或项目 `设定/` 复制进 `对标/`。
- `{对标书名}`：作者另选的独立外部参考书，来源固定为 `拆文库/{对标书名}/`；未明确指定时不建 `对标/`、不写 `主对标书`。
- 拆文复用 `/story-long-analyze` 或 `/story-short-analyze`，拆文方法与验收由对应 skill 负责。

## 时刻表与交接

| 时刻 | 作者确认什么 | 读什么 | 写入文件 |
|---|---|---|---|
| Phase 1 确认来源与范围 | 书名、题材、平台、篇幅、残稿、外部对标、环境 | 本文件 Phase 1 | 导入记录 |
| Phase 2 深度分析 | 不打扰作者 | [deep-analysis.md](references/deep-analysis.md) | `拆文库/{导入书名}/` |
| Phase 3 结构迁移 | 无卷界时卷划分；是否存本书文风 | 长篇 [structure-mapping-long.md](references/structure-mapping-long.md)；短篇 [structure-mapping-short.md](references/structure-mapping-short.md) | 长篇 `设定/`、`正文/`、`大纲/`；短篇三单文件 |
| 逐批反推细纲（长篇） | 不打扰作者 | [outline-reverse.md](references/outline-reverse.md) | `大纲/细纲_第XXX章.md` |
| Phase 4 追踪初始化（长篇） | 不打扰作者 | [import-tracking.md](references/import-tracking.md) | `追踪/` |
| Phase 5 汇报与激活 | 请作者核对、拍板的事 | [import-report.md](references/import-report.md) | `.active-book` |

- **书目录**：长短篇均为 `{导入书名}/`（与 `拆文库/{导入书名}/` 同名，写正文守卫据此放行）。
- **导入记录**：`{书目录}/.story/work/导入记录.md`，Phase 1 建立；每时刻开头先读它、交付前把新决定与进度写回它。
- **换上下文**：深度分析、每批细纲、追踪初始化内容多，时刻交付后建议「下一步建议新开对话，说『继续导入』，会更专注」；作者在本对话继续也照做。说「继续导入」时找未勾完的 `*/.story/work/导入记录.md` 续跑。

## 常见答疑与旧追踪迁移

- **流程答疑**（先答结论再收原文）：推荐先 `/story-setup` → 新开对话 `/story-import` → 完后 `/story-long-write 写第N章`（或短篇 `/story-short-write`）；也可直接 `/story-import`，缺环境时 Step 4 给选择。
- **已导入项目**（已有 `追踪/_tracking-state.json`）：先查导入记录，未完项续跑；已导入完则核对 `.active-book` 后直接续写，不重复导入。
- **旧追踪项目**（有 `追踪/` 与正文但无 `_tracking-state.json`）：不重跑全书拆解、不动正文与设定，直接重建追踪：① 查最大完整章号 `N`；② 从旧 `追踪/` 与近 3–5 章正文反推角色快照、未收伏笔、时间线、长期约束与下章承诺（规则见 [import-tracking.md](references/import-tracking.md)）；③ 以 `last_chapter=N` 跑 `tracking_commit.js init`（旧文件自动归档至 `追踪/_旧追踪存档/`）并过 `check`，再回 `/story-long-write` 续写第 `N+1` 章。

---

## Phase 1：确认来源与范围

### Step 1：确认意图

默认建可续写工程；意图不明时问「你是想做成可续写的写作工程，还是只要一份拆文分析？」只要分析则转 `/story-long-analyze` 或 `/story-short-analyze`，不建导入记录。

### Step 2：拿到原文

未提供原文时问「你要导入哪本书？请提供文件路径或直接贴文本。」单文件按章节分隔符切分，目录按文件名排序合并；贴入文本在 Step 5 存为 `{书目录}/.story/work/导入原文.md`。

### Step 3：基本信息与篇幅判定

1. 自动检测书名、总章数、总字数、章节格式。
2. **篇幅分流优先级**（锁定进导入记录，后续不重判）：
   - **用户显式声明**优先；若与结构/字数明显冲突（如说短篇却有 20 章，或说长篇却无分章且 <30000 字），复述检测结果请作者拍板。
   - **结构信号 + 字数校验**（识别 `第X章/回/节`、`Chapter X`、`1. 标题`）：有显式 `第X章 标题` 且 ≥5 章时，≥30000 字或均章 ≥1800 字且未声明完本者，初判**长篇连载半成品**（不足 30000 字提示请作者确认）；均章 <1500 字或已完本 <20000 字初判短篇，其余 <30000 字请作者拍板。无分章单篇时，<20000 字判短篇，20000–30000 字初判短篇并提示已超建议上界，≥30000 字请作者拍板。
   - **字数兜底**（<5 章或分隔符模糊）：<30000 字初判短篇，≥30000 字初判长篇。
3. 请作者确认：导入书名、题材类型、目标平台（长篇：起点/番茄/七猫/晋江/其他；短篇：知乎盐言/番茄/七猫/黑岩/小程序/未定）、是否完本、篇幅判定、**最后一章是否完整**（残稿须由作者决定「接着残章写」或「先补完再导入」）。
4. 外部对标（可选）：仅当作者指定独立 `{对标书名}` 且 `拆文库/{对标书名}/` 存在时记录，未指定记「未绑定」不追问。确认检测摘要后往下走。

### Step 4：写作环境检测

读 `.story-deployed` 核版本，按当前宿主查 `chapter-extractor` 与 `story-architect` 是否可用。ZCode 缺角色提示启用/更新插件并新开会话；其他宿主不可用时问：「还没装写作环境，想 1. 先运行 `/story-setup` 装好（推荐）再说『继续导入』，还是 2. 直接在主对话导入（慢一点但产物完整）？」选 1 则先写导入记录（环境记「待装」）暂停；选 2 则主会话串行完成。

### Step 5：写导入记录

写入 `{书目录}/.story/work/导入记录.md`（贴入原文同存该目录）：

```markdown
# 导入记录：《{导入书名}》
- 原文：{源文件或目录路径；贴入写 .story/work/导入原文.md}
- 篇幅：{长篇 | 短篇}（{判定依据一句}）
- 范围：第 1–{N} 章，约 {Y} 万字；{完本 | 半成品}
- 最后一章：{完整 | 残稿：第 {N+1} 章写了一半，作者决定{接着残章写 | 先补完再导入}}
- 题材：{题材类型}；目标平台：{平台}
- 外部对标：{对标书名 | 未绑定}
- 写作环境：{已装，分析助手可用{，story-architect 可用} | 待装 | 当前对话顺次执行}
- 卷划分：{待整理卷界 | 按原文卷界 | 作者已确认：1–40 / 41–95}
- 作者交代：{偏好、红线、否掉的方案；没有写「无」}

## 进度
- [ ] 深度分析
- [ ] 结构迁移（卷划分已确认、卷纲已写）
- [ ] 细纲：已验收到第 {B} 章（长篇）
- [ ] 追踪初始化（长篇）
- [ ] 汇报与激活
```

---

## Phase 2：深度分析

读 [deep-analysis.md](references/deep-analysis.md)，进入对应拆解管道自动跑完已确认范围，完成后勾进度。

## Phase 3：结构迁移

- **长篇**：读 [structure-mapping-long.md](references/structure-mapping-long.md) 迁成 `{导入书名}/` 工程（无卷界须等作者确认卷划分）；验收后读 [outline-reverse.md](references/outline-reverse.md) 逐批反推细纲。
- **短篇**：读 [structure-mapping-short.md](references/structure-mapping-short.md) 迁成三个单文件（**不建** `追踪/`、`大纲/`、`正文/`），迁完直跳 Phase 5。

## Phase 4：追踪初始化（仅长篇）

读 [import-tracking.md](references/import-tracking.md)，跑 `scripts/tracking_commit.js init` 一次生成 `追踪/`，`check` 通过后勾进度。

## Phase 5：汇报与激活

读 [import-report.md](references/import-report.md)：自检、白话汇报、设置 `.active-book`。
