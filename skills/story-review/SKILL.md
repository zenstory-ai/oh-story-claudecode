---
name: story-review
version: 1.1.1
description: "多视角对抗式审查。full/lean 模式在已部署 reviewer agents 时并行 spawn；缺失/异常 agents 或 spawn 失败时自动降级 solo，参考文件不可读时使用内置 rubric fallback。触发方式：/story-review、/审查、「审查一下」「帮我审一下」。"
metadata: {"openclaw":{"source":"https://github.com/zenstory-ai/oh-story-claudecode"}}
---
# story-review：多视角对抗式审查

> 版本：先读项目根 `.story-deployed` 的 `agents_version`。与本版 `agents_version: 47` 不一致时（缺失/非整数/小于或大于 47）**照常按当前宿主角色来源检查并 spawn**，只在「这次怎么审的」用一句白话提示更新（小于 47 提示跑 `/story-setup` 后新开会话，ZCode 先更新插件；大于 47 额外提示先更新 oh-story-claudecode，勿旧版降级覆盖）。版本提示不触发降级。

**执行铁律：审查只管挑毛病，不为原稿背书；确定性预检通过不代替内容与文笔审查。**

**文风裁决**：先读 [references/style-resolution.md](references/style-resolution.md)，加载本书文风，复用调用方 `style_resolution` 与作者偏好；单独调用时按当前请求与本书文风裁决并交给后续执行者。只接收调用方已有偏好，独立调用不查不记作者记忆；偏好不能降级严重度或放过事实冲突。

## Phase 0：预检与降级（必须先执行）

1. **定请求模式**：`full`（默认，4 个 Agent：`story-architect`、`character-designer`、`narrative-writer`、`consistency-checker`）、`lean`（`story-architect` + `consistency-checker`）、`solo`（当前会话直审）。已在子代理内执行时禁止递归 spawn，直接降级 `solo`。
2. **查当前宿主角色与工具**（仅查当前宿主来源，不跨端扫描，不因其他端文件或部署标记降级）：

| 宿主 | 角色来源与合法判定 | 派发工具 |
|---|---|---|
| Claude Code | `.claude/agents/{agent}.md`，frontmatter `name:` 匹配目标 | `subagent_type` |
| OpenCode | `.opencode/agents/{agent}.md`，frontmatter 含 `mode: subagent` 与复数 `permissions:` 规则列表（单数 `permission:` 视为待重部署） | `subagent`（`agent`） |
| Codex | `.codex/agents/{agent}.toml`，可解析 TOML 且含 `name`、`description`、`developer_instructions` | `agent_type` |
| Antigravity | `.agents/agents/agent-name/agent.md`，frontmatter 含匹配 `name`、`mainAgent: false`、`subagent: true`、非空 `tools` | `invoke_subagent`（`TypeName`） |
| ZCode | 已启用插件注册的同名角色（不要求 `.zcode/agents/`）；定义不可直读时以运行时注册为准 | `Agent`（按当前 schema） |

3. **降级规则**：任一必需角色缺失/损坏、当前宿主派发工具不可用，或运行时任一 spawn 失败，立刻停止继续派发并改用 `solo` 重审（不拿部分结果当 full/lean 结论）。实际方式与降级原因只在报告开头「这次怎么审的」用白话说清，不加技术备注行。

## 审查基准与参考资料规则

### 报告面向作者（必须遵守）

写给作者：审了什么、哪里要改、为什么（用读者感受和故事后果，附原文引用）、要作者拍板的事、下一步。reviewer 名、S1–S4、Gate、检测器类别名、脚本名、PASS/FAIL、内部字段名不进正文；位置写「第 N 章/第 N 节「引文」」或「第 N 章/第 N 节第 M 段」。优先级换白话：S1/S2 → **必须改**，S3 → **建议改**，S4 → **可以不改**。

### 参考资料解析顺序

依次取第一个命中层（不手工复制 `references/`）：`{项目根}/{.claude,.opencode,.codex,.zcode}/skills/{规范路径}` → `{项目根}/skills/{规范路径}`（OpenClaw/Reasonix/generic）→ `{项目根}/.agents/skills/{规范路径}`（Antigravity）→ 当前加载本 skill 的目录或全局同名目录。

规范路径（禁裸文件名、禁跨 skill 读他处 references）：

| 用途 | 规范路径 |
|---|---|
| 通用内容 rubric | `story-review/references/quality-rubric.md` |
| 三层去味与信号索引 | `story-review/references/deslop-guide.md` |
| 短篇卖点保护与覆盖 | `story-review/references/short-deslop.md` |
| 词句信号索引 | `story-review/references/banned-words.md` |
| 平台 rubric | `story-review/references/rubrics/{fanqie,qidian,female,zhihu,short-shuang}.md` |
| 标点 / AI 句式脚本 | `story-review/scripts/normalize-punctuation.js` · `story-review/scripts/check-ai-patterns.js` |

### 内置审查基准包（路径不可读时必用）

参考文件不可读时必须用本节并在「这次怎么审的」注明按内置标准审。

通用网文内容 rubric：
- 核心卖点：围绕明确卖点推进，缺卖点至少 S2。
- 冲突推进：有真实阻碍、私心反咬、代价或信息推进；纯闲聊或零阻力走过场/反派降智送人头至少 S2。
- 任务卡点：受阻卡出意外变数、代价或伏笔；可删水戏或送头走过场至少 S3。
- 情绪曲线：有铺垫、升温、释放或反转；平直/突兀 S2/S3。
- 钩子与期待：章首/章尾留后续问题；无期待至少 S2。
- 开头新鲜度（仅开篇/前 3 章）：具体人物、处境与赌注抓人（经典爆款切口有冲突即豁免）；空泛灌水 S2/S3。
- 角色动机：行为合私心与处境压力（女频禁恋爱脑/雌竞/爹味）；失真或纸片反派降智送人头 S1/S2。
- 对话质量：有信息差与说话语气差异（短篇许直球交锋）；说明书腔或长篇大论单人演讲 S2/S3。
- 设定一致性：合规则、时间线、线索前置、细节数值与时代/行业常识；冲突 S1/S2。
- 文字自然度：关键道具与盘算自然（短篇留反应词，女频留 `轻笑/低笑`）；AI 腔、油腻氛围词或无功能材质穿搭空镜摆设过载 S2。
- 句长节奏：短对话快推，叙述留口语因果与盘算；抽干内心的纯动作碎句或大段文字墙 S2。
- 标点节奏：叙述默认 `。`，`！` 只留给情绪高潮；旁白动辄刷感叹号、非热血题材满篇咆哮、旁白 `——`/`……` 刷屏或畸形破折号 S3/S2。
- 格式可读性：段短、对话独立、无多余空行；影响顺读 S3/S2。
- 剧情循环：紧章目标→真实阻滞→反咬博弈→代价→新期待；松章交代状态变化，零阻力走过场或缺环至少 S2。
- 高潮构建：高潮章蓄能、落差、兑现有层次；缺铺垫/兑现 S2/S3。
- 关系进展：尺度匹配阶段，无触发跳变 S1/S2（短篇有触发可快翻脸；女频禁真出轨/暴力洗白 HE 与下药强绑）。
- 伏笔状态：状态可追踪；密度仅提示，致混乱才升 S2+。

三层去味 fallback：表达清公文/翻译腔、套词复述、没用的环境摆设与纯动作碎句；用笔展交锋、压水戏；故事核依据与场后变化（短篇留偷听/打脸等常见桥段）。只报不改。

平台 fallback：番茄/七猫长篇（首章开头快见对话落简介场景、禁大脑寄存处/境界表、尽快立矛盾）；起点长篇（设定融冲突、升级清晰、长线钩）；女频长篇/晋江（CP 去油苏感、男主去爹味、女主主体反雌竞、禁真出轨洗白与预期诈骗、关键物件情绪悬崖）；知乎盐言（150–300 字导语直接续接、第一人称吐槽、32–44% 折页、吐槽/悬疑可偏内心独白）；商业短篇（开篇直入冲突、32–44% 付费卡点、按题材推进与首尾呼应收尾）。

## Phase 1：收集待审查内容

1. **定范围与分批**：用户指定文件/章节则只审指定项；未指定时 git 仓审 `git diff --name-only` 里的正文/设定/大纲，否则长篇审 `正文/` 最近修改章、短篇审 `正文.md`。传给 reviewer 用路径/章名/行号（单文件或短片段可附 300–1200 字摘录），不整本贴进 prompt。多章/整卷/整本先读 [references/batch-review.md](references/batch-review.md) 分批执行。
2. **读支撑材料**：solo 与分批由你读正文、相关设定、大纲、`追踪/上下文.md` 与伏笔；full/lean 只读定范围、定平台和开放项所需文件，其余由 reviewer 按路径自读。缺材料标证据不足。
3. **判篇幅与平台，加载 rubric**：有 `正文/` 或 `设定/` 为长篇，有 `正文.md` 或 `设定.md` 为短篇。平台优先本次指定，其次长篇读 `设定/题材定位.md`、短篇读 `设定.md`「目标平台」（`.active-book` 仅定书目录）。每次必加载通用 rubric，按下表叠加平台表（不可读用内置摘要）：

| 篇幅 | 目标平台 | 叠加的平台表 |
|---|---|---|
| 长篇 | 起点 | `story-review/references/rubrics/qidian.md` |
| 长篇 | 晋江 | `story-review/references/rubrics/female.md` |
| 长篇 | 番茄、七猫 | `story-review/references/rubrics/fanqie.md`（若 `设定/题材定位.md` 属女频或命中女频流派包，同时叠加 `story-review/references/rubrics/female.md`） |
| 长篇 | 其他、未定、没写 | 女频叠加 `story-review/references/rubrics/female.md`，其余不叠加 |
| 短篇 | 知乎盐言（也写作盐选） | `story-review/references/rubrics/zhihu.md`（女频按需并叠 `story-review/references/rubrics/female.md`） |
| 短篇 | 番茄、七猫、黑岩、小程序、点众、未定、没写 | `story-review/references/rubrics/short-shuang.md`（女频按需并叠 `story-review/references/rubrics/female.md`） |

   短篇同时必读 `story-review/references/short-deslop.md`（覆盖通用去味默认值），并按 `设定.md`「平台基调」核格式、引号与导语。将已加载标准压成 5–12 条审查基准包摘要供 solo/子 Agent 共用。
4. **确定性预检（只报告不改稿）**：含本地正文路径时运行本 skill 脚本（`--mode=auto` 对 `正文.md` 自动走 short 模式，非 `正文.md` 短篇传 `--mode=short`）：
   ```bash
   node scripts/normalize-punctuation.js --check --mode=auto <正文文件...>
   node scripts/check-ai-patterns.js --check --fail-on=review_required --mode=auto <正文文件...>
   node scripts/check-degeneration.js --check --fail-on=review_required <正文文件...>
   ```
   - `normalize-punctuation.js` 的 `ellipsis`、`em-dash`（仅报畸形/粘连破折号，标准 `——` 不报）、`double-hyphen`、`markdown-divider` 归 `format`；`check-ai-patterns.js` 的 `em-dash` 独立归 `prose` 密度复核（二者不再去重），默认 `--quote-mode keep`。
   - `check-ai-patterns.js` 的 `review_required` / `advisory` 作 `prose` 候选，按 `style_resolution` 与 `deslop-guide.md`（短篇叠 `short-deslop.md`）复核后定级。
   - `check-degeneration.js` 的 blocking（复读/截断/占位符/粗体残留/tier1 工程词）归 S1/S2 `prose`（建议重写该段），review_required（屏蔽拼音/作者元信息行）归 S2，advisory 归 S3。
   - `story-review` 不改正文、设定或大纲（改稿转 `/story-deslop`）；仅 full/lean 追踪维护可动 `追踪/`，分批可写 **.story-review/state.md**。

## 统一 Findings Schema

所有 reviewer 先按此结构整理，再转写为面向作者的白话报告；`location` 用工具读取显示的原始行号。`consistency`/`factual`/`causal`/`rule_boundary` 的 `fix` 只写事实统一方向，不写文学创作建议。

```yaml
- severity: S1 | S2 | S3 | S4
  category: structure | character | prose | consistency | platform | factual | format | causal | rule_boundary
  location: 文件路径:行号 或 章节/段落描述
  evidence: "引用原文或具体证据"
  issue: "问题描述"
  fix: "可执行修改建议"
```

严重度：S1（破主线/动机/世界规则/读者信任，必改）、S2（明显损留存/节奏/效果/可信度，必改）、S3（局部措辞/格式/节奏，建议改）、S4（风格微调，可不改）。

## Phase 2–4：执行、裁决与输出

- **Phase 2（并行 Spawn）**：实际模式为 full/lean 时读 [references/agent-prompts.md](references/agent-prompts.md) 并行派发；不派缺失 Agent，每个 prompt 自包含路径、范围与 Schema。
- **Phase 3（综合裁决）**：收齐结果按 `agent-prompts.md`「综合裁决」合并、去重、呈现分歧。
- **Phase 4（输出报告）**：full/lean 用 `agent-prompts.md` 报告模板；降级或指定 solo 时读 [references/solo.md](references/solo.md) 执行并输出。
- **追踪文件维护**：有 `追踪/_tracking-state.json` 的长篇且实际模式为 full/lean 时，收尾读 [references/review-tracking.md](references/review-tracking.md) 修订追踪；solo 不改 `追踪/`。

## 流程衔接

改审出问题转 `/story-long-write` 或 `/story-short-write`；清 AI 味转 `/story-deslop`。
