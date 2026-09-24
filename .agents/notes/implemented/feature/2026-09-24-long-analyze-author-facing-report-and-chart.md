# Agent Note: 拆文对作者说人话——报告、回复模板与中文关系图

Status: implemented
Date: 2026-09-24
Issue: 发版前复审（真实 Claude Code 运行）
Related: [2026-09-24-long-analyze-legacy-prologue-alignment](../bug-fix/2026-09-24-long-analyze-legacy-prologue-alignment.md)、[2026-09-22-long-analyze-single-state-runtime](../architecture/2026-09-22-long-analyze-single-state-runtime.md)

## Problem

真实运行里作者看到的拆文汇报夹着 `classification: current_complete`、`final_state: completed`、
`recommended_path: direct_use`、`stage_repairs: []`、「plan --intent continue 返回 batches: []」、
「披露引用与三维解释完整 100%」「B 级推断」「REL-001/004」。根源在文档：Stage 5 报告模板要求写
「质量评估：置信度 / 覆盖率 / 重叠率」「B/C 级推断」、引用 `EV-*`/`RV-*`/`AX-*`，而对话里的进度、停下提问、
完成汇报和出错说明没有任何模板，模型只能把脚本 JSON 转述出来。

同一次运行的 `人物关系图/*.png` 人名全是拼音首字母：环境没有中文字体，模型临时写的 matplotlib 脚本
就退回了拼音。关系图没有固定生成方式，SKILL 只写了「无法可靠渲染时记录原因」。

## Decision

- **新增 `references/author-facing.md`**：作者看到的一切都按它写——总规则 7 条（说书不说系统；不出现脚本名、
  命令、字段名、状态值、批次编号、内部文件、质量指标名、证据分级字母和「三维」；编号只和名称一起出现；证据
  强弱说人话；需要作者拿主意时一个问题 + 推荐 + 默认；工程细节最多末尾一行技术备注；脚本 `author_message`
  转述不贴 JSON），加上对话模板（开头三章拆完停下问、进度、全部拆完、停下/出错的常见说法）和两份文件模板。
- **拆文完成汇报**固定为：拆了哪本、拆到哪；最值得学的三点；可借用的套路；不建议学的；按用途列出的文件去处
  （「看节奏去 剧情/节奏.md」）；需要作者定的事（问题 + 推荐）。
- **`快速预览.md` 与 `拆文报告.md` 模板搬到 author-facing.md 并重写**：删掉质量评估小节和 A/B/C 分级，
  「证据边界与待核事项」改为「还不确定的地方」，时间线/节奏小节改写成「读者知道的和角色知道的」「节奏」的人话
  说明，可借鉴套路以「模块名（EM-编号）」带名引用；导入、写作、选题回填读取的小节名（基本信息、核心发现、
  黄金三章评分、爽点密度、核心机制、可借鉴套路、写法技巧、不建议模仿等）保留。`output-templates.md` 的
  对应小节改为指针，机械可追溯信息留在节奏、情绪模块、剧情单元和关系文件里。
- **静态守卫**：`check-current-skill-contracts.py` 把 author-facing.md 里每个代码块视为作者原样读到的文字，
  拦截字段/状态名、snake_case、批次号、脚本名与命令参数、Stage/Phase 编号、置信度/覆盖率/重叠率/三维、证据
  分级字母、不带名称的 EM/REL/EV/RV/AX 编号、内部文件与 hash/JSON；并要求 SKILL.md 路由到该文件。回归测试
  用真实运行里出现过的原句逐条验证会被拦下。
- **关系图脚本 `scripts/render_relation_chart.py`**：只从 `角色/角色关系.md` 生成。主产物是
  `人物关系图/人物关系图.md`（Mermaid 图 + 文字清单 + 关键关系演变），任何 Markdown 查看器都显示中文，且在尝试
  画 PNG 之前就写好，画图出错也不丢。关系列认 `→`/`->` 等单向箭头、`↔`/`<->`（拆成两条）和「甲 → 乙 → 丙」链式
  （逐段拆），单元格里转义的 `\|` 不拆列；认不出的行计数返回并告诉作者。Mermaid 标签去掉 `%%`，清洗后为空时换成
  「未命名」「关系」，避免 mermaid 解析失败。`--png` 时先按常见中文字体名（PingFang SC、Hiragino Sans GB、Microsoft
  YaHei、SimHei、Noto Sans CJK、WenQuanYi、Source Han Sans 等）和 `fc-list :lang=zh` 找字体，排除 LastResort、
  Adobe Blank 这类对任何字都返回方框字形的兜底字体，并用 FT2Font 逐字检查要画的每个字都有字形（macOS 的
  PingFang.ttc 首个字面是繁体 HK 版，缺简体字，只看字体名会画出方块）；表情和其他符号不画进图片，其余文字全部有
  字形才画两张 PNG。没有中文字体、中文字体缺某几个字（说出是哪几个字）或没有 matplotlib 时不出图，返回一句
  大白话 `author_message`，绝不退回拼音或首字母。
- 检查器和建索引脚本的停下说明、原文变化说明也改成作者语言（见 Related 的 bug-fix 篇）。

## Alternatives considered

- **只在 SKILL.md 加一条「用大白话」规则**：改动最小；但报告模板本身要求写覆盖率和 B/C 级，规则和模板打架时
  模型跟模板走，真实运行已经证明如此。
- **报告里完全去掉 EM 编号**：作者读起来最干净；但灵感库和写作侧要按编号回查情绪模块卡，带名编号两边都能用。
- **PNG 继续做主产物，缺字体时自动下载字体**：图片最直观；但运行时联网下载字体既慢又可能被拦，也不该替作者
  往系统里装东西。Mermaid Markdown 在常用编辑器里直接渲染中文，零依赖。
- **缺字体时用拼音或英文名兜底画图**：至少有图；但作者看不懂的图比没有图更糟，正是这次要修的问题。

## Consequences

收益：作者看到的汇报、报告和关系图都能直接读；工程词回流会被守卫拦下；关系图在任何环境都有中文可读版本，
有中文字体时还有图片。

代价：拆文报告小节结构变了，旧报告不会自动改写（Stage 5 重跑才生效）；demo 盘龙的旧报告仍是旧格式；守卫只
覆盖 author-facing.md 的代码块，对话里模型是否照做仍靠模板约束；PNG 需要 matplotlib，默认 CI 不真画图，只测无字体回退
路径，选字体逻辑用假字体对象测；图片版不画表情等符号（Markdown 版保留原样）；story-import 的长篇导入管道仍按旧写法描述关系图，未同步。
