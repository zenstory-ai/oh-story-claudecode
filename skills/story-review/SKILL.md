---
name: story-review
version: 1.1.1
description: "多视角对抗式审查。full/lean 模式在已部署 reviewer agents 时并行 spawn；缺失/异常 agents 或 spawn 失败时自动降级 solo，参考文件不可读时使用内置 rubric fallback。触发方式：/story-review、/审查、「审查一下」「帮我审一下」。"
metadata: {"openclaw":{"source":"https://github.com/zenstory-ai/oh-story-claudecode"}}
---
# story-review：多视角对抗式审查

> 版本：先读项目根 `.story-deployed` 的 `agents_version`。与本版 `agents_version: 46` 不一致时（缺失/非整数/小于或大于 46）**照常按当前宿主角色来源检查并 spawn**，只在「这次怎么审的」用一句白话提示更新（小于 46 提示跑 `/story-setup` 后新开会话，ZCode 先更新插件；大于 46 额外提示先更新 oh-story-claudecode，勿旧版降级覆盖）。版本提示不触发降级。

**执行铁律：审查只管挑毛病，不为原稿背书。**

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

按以下顺序取第一个命中层（前几层不存在属正常，不手工复制 `references/`）：
1. `{项目根}/.claude/skills/{规范路径}`
2. `{项目根}/.opencode/skills/{规范路径}`
3. `{项目根}/.codex/skills/{规范路径}`
4. `{项目根}/.zcode/skills/{规范路径}`
5. `{项目根}/skills/{规范路径}`（OpenClaw / Reasonix / generic 与本仓库）
6. `{项目根}/.agents/skills/{规范路径}`（Antigravity 真实 skill root）
7. 当前运行时加载本 skill 的目录或其全局搜索路径同名目录

规范路径（禁裸文件名、禁跨 skill 读他处 references）：

| 用途 | 规范路径 |
|---|---|
| 通用内容 rubric | `story-review/references/quality-rubric.md` |
| 三层去味与信号索引 | `story-review/references/deslop-guide.md` |
| 短篇卖点保护与覆盖 | `story-review/references/short-deslop.md` |
| 词句信号索引 | `story-review/references/banned-words.md` |
| 平台 rubric | `story-review/references/rubrics/{fanqie,qidian,zhihu,short-shuang}.md` |
| 标点 / AI 句式脚本 | `story-review/scripts/normalize-punctuation.js` · `story-review/scripts/check-ai-patterns.js` |

### 内置审查基准包（路径不可读时必用）

参考文件不可读时不得降级为无 rubric，必须用本节基准包并在「这次怎么审的」注明按内置标准审。

通用网文内容 rubric：
- 核心卖点：是否围绕明确卖点推进；看不出卖点至少 S2。
- 冲突推进：有无阻碍、选择、代价、信息或关系推进（日常/过渡章按章定位看关系、经营或铺垫）；只解释/闲聊/总结至少 S2。
- 任务卡点：办事受阻是否卡出信息、关系、代价、选择或伏笔变化；纯流程水戏删掉无损至少 S3。
- 情绪曲线：有无铺垫、升温、释放或反转；平直或突兀至少 S2/S3。
- 钩子与期待：开头或结尾是否制造后续问题；无悬念或未完成期待至少 S2。
- 开头新鲜度（仅开篇/前 3 章）：开局须用具体人物、处境与赌注抓人；商业爆款/品类经典开局范式（长短篇通用）有具体冲突与钩子即豁免，仅对空泛灌水或无赌注套壳判 S2/S3。
- 角色动机：行为是否符合目标、性格、处境和关系压力；为剧情失真判 S1/S2。
- 对话质量：有信息控制、角色差异与来回短打（长篇重潜台词；短篇允许直球摊牌、狠话与围观）；说明书腔或频繁 ≥60 字单人演讲至少 S2/S3。
- 设定一致性：不违背既有规则、时间线、角色属性与常识（悬疑物理与线索前置时机、现代都市离婚冷静期/担保责任等）；事实冲突或常识硬伤通常 S1/S2。
- 文字自然度：具体可感、物象接地气（短篇常见反应短语、旁白剧透与主观审判按 `short-deslop.md` 保留）；AI 腔、套话、跨章复读 `死寂/轰然/冷笑`、悬浮塑料豪门道具或微动作代偿定 S2/S3。
- 句长节奏：贴合本书文风与手机竖屏节奏（短篇允许一句一段与短句快切，长篇避免超百字大段墙）；机械碎句、动作清单或臃肿长句定 S3/S2。
- 标点节奏：叙述默认 `。`，`！`/`？` 服务真正峰拍（对话内 `——`、有节制 `……` 与旁白关键转折 `——` 可用）；通篇句号化、`！` 咆哮刷屏（>15/千字）、旁白 `——`/`……` 刷屏或畸形破折号定 S3/S2。
- 具体字数表达校验：正文用「这五个字/短短四字」等评价台词、题字、信件或弹幕时，须核对口径属实且有叙事必要；不符或难核对建议改「那几个字」类非数字表达。
- 格式可读性：段短适读、对话独立、无多余空行；阻碍阅读 S3，严重混乱 S2。
- 剧情循环：紧章目标→阻碍→行动→代价/反馈→新期待清晰；松章/过渡章交代目标、行动与状态变化，缺环通常至少 S2。
- 高潮构建：高潮章蓄能、落差与兑现有层次（强反转可用蓄能→假胜→崩解→反转/兑现），缺铺垫或兑现 S2/S3；细纲标无高潮的松章看功能落地。
- 关系进展：互动尺度匹配阶段，无触发跳变 S1/S2（短篇有明确触发即可快速心死/翻脸/结盟）。
- 伏笔状态：状态可追踪；密度只作结构风险提示，除非造成理解混乱否则不升 S2+。

三层去味 fallback 速查：表达查翻译腔、比喻/套词堆砌、空泛升华与重复车轱辘（短篇保留竖屏一句一段、口语吐槽、常见反应短语与旁白 `——`）；用笔查关键交锋被概括与无功能水戏（短篇保留冷开场与快进节奏）；故事查行动来由、成立依据与场后变化（短篇保留偷听、自爆、围观打脸等引擎，除悬疑不按办案标准抠取证）。有原文证据才出 finding，只报告不落改。

平台 fallback 摘要（叠加在通用 rubric 上）：
- 番茄 / 七猫长篇：首章 ≤300 字见对话、≤400 字入冲突并亮核心卖点/金手指，手机短段（P50 约 22–26 字），高频爽点与章尾钩子。
- 起点长篇：设定融进冲突不堆百科、升级路径清晰、金手指有用、长线期待与追读钩子、手机可读性。
- 知乎盐言短篇：150–300 字高密度导语、第一人称吐槽/信息差、30–40% 付费折页张力、竖屏短段、反转或痛快落点。
- 商业短篇（番茄/七猫/黑岩/小程序/点众）：冷开场百字入冲突、竖屏一句一段与高对话占比、30–40% 付费强卡点、40%+ 连环反击、明账清算收尾。

## Phase 1：收集待审查内容

1. **定范围与分批**：用户指定文件/章节则只审指定项；未指定时 git 仓审 `git diff --name-only` 里的正文/设定/大纲，否则长篇审 `正文/` 最近修改章、短篇审 `正文.md`。传给 reviewer 用路径/章名/行号（单文件或短片段可附 300–1200 字摘录），不整本贴进 prompt。多章/整卷/整本先读 [references/batch-review.md](references/batch-review.md) 分批执行。
2. **读支撑材料**：solo 与分批由你读正文、相关设定、大纲、`追踪/上下文.md` 与伏笔；full/lean 只读定范围、定平台和开放项所需文件，其余由 reviewer 按路径自读。缺材料标证据不足。
3. **判篇幅与平台，加载 rubric**：有 `正文/` 或 `设定/` 为长篇，有 `正文.md` 或 `设定.md` 为短篇。平台优先本次指定，其次长篇读 `设定/题材定位.md`、短篇读 `设定.md`「目标平台」（`.active-book` 仅定书目录）。每次必加载通用 rubric，按下表叠加平台表（不可读用内置摘要）：

| 篇幅 | 目标平台 | 叠加的平台表 |
|---|---|---|
| 长篇 | 起点 | `story-review/references/rubrics/qidian.md` |
| 长篇 | 番茄、七猫 | `story-review/references/rubrics/fanqie.md` |
| 长篇 | 晋江、其他、未定、没写 | 不叠加 |
| 短篇 | 知乎盐言（也写作盐选） | `story-review/references/rubrics/zhihu.md` |
| 短篇 | 番茄、七猫、黑岩、小程序、点众、未定、没写 | `story-review/references/rubrics/short-shuang.md` |

   短篇同时必读 `story-review/references/short-deslop.md`（覆盖通用去味默认值），并按 `设定.md`「平台基调」核格式、引号与导语。将已加载标准压成 5–12 条审查基准包摘要供 solo/子 Agent 共用。
4. **确定性预检（只报告不改稿）**：含本地正文路径时运行本 skill 脚本（`--mode=auto` 对 `正文.md` 自动走 short 模式，非 `正文.md` 短篇传 `--mode=short`）：
   ```bash
   node scripts/normalize-punctuation.js --check --mode=auto <正文文件...>
   node scripts/check-ai-patterns.js --check --fail-on=review_required --mode=auto <正文文件...>
   node scripts/check-degeneration.js --check <正文文件...>
   ```
   - `normalize-punctuation.js` 的 `ellipsis`、`em-dash`（仅报畸形/粘连破折号，标准 `——` 不报）、`double-hyphen`、`markdown-divider` 归 `format`；`check-ai-patterns.js` 的 `em-dash` 独立归 `prose` 密度复核（二者不再去重），默认 `--quote-mode keep`。
   - `check-ai-patterns.js` 的 `review_required` / `advisory` 作 `prose` 候选，按 `style_resolution` 与 `deslop-guide.md`（短篇叠 `short-deslop.md`）复核后定级。
   - `check-degeneration.js` 的 blocking（复读/截断/tier1 工程词）归 S1/S2 `prose`（建议重写该段），advisory 归 S3。
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
