# Agent Note: 全题材四层剧情库改造、拆文到写作自动召回与十轮全仓去过拟合清理

Status: implemented

## Problem

在实测长短篇开篇、设定、大纲、细纲、正文与「扫榜 → 拆文 → 写作」端到端链路时，发现三类影响成稿质量与长期可维护性的系统性问题：

1. **题材包深度与结构不足**：原有 36 份题材包（22 长篇 + 14 短篇）对开局切入、中期高潮与节奏调剂的写法偏概括，且缺少覆盖核心节点的分流派剧情类型库，正文写手容易退回模板化打脸或流水账。
2. **拆文成果向写作的自动召回存在断点**：`build_writer_prompt.js` 在未手动填写旧版提示卡或对标拆文已完备时，未能自动抽取并注入主对标的 `剧情/情绪模块.md`、`剧情/节奏.md` 与命中流派包正文技巧，且 `isDeployedPack` 仅检查旧路径而漏检各宿主 `.claude/skills/story-setup/references/agent-references/...` 与 `.zcode/...` 真实部署路径。
3. **多轮实验沉淀引发过拟合、套话膨大与跨文件漂移**：在多轮对照试验过程中，部分单案微观补丁、Section 5 原文切片专名/道具向 Sections 1–4 反向泄漏、跨包重复粘贴通用规则、自造黑话（如 `延迟信息差`、`考点标签`、`20 字节拍器`、`蓄压轨`、`工时物理`）、伪精确微计数、已退役字段/列以及少量跨宿主工具名与文档口径漂移混入 Skill 与运行时脚本。

## Decision

1. **全题材包四层重构与去过拟合定型**：
   - 将 22 份长篇与 14 份短篇题材包统一为「1. 故事线设计 / 2. 常见剧情设计（黄金三章/五段节奏 + 分阶段剧情类型库 + 高频断章钩子 + 常见毒点）/ 3. 人物设计 / 4. 正文技巧 / 5. 案例片段」结构；所有通用写作原则与防 AI 味底线集中收敛到 `flow-opening-plan.md`、`flow-outline.md`、`flow-drafting.md` 与 `story-short-write/SKILL.md`，题材包只留题材专属差异与反差切口。
   - 经 10 轮专项去过拟合与全仓巡检，彻底清除单案微观补丁、Section 5 原文切片向 Sections 1–4 的反向泄漏、跨包错贴与重复长套话、病句与嵌套 HTML 注释截断，严格保留 `## 5. 案例片段` 原文引用不变。
2. **拆文 → 写作自动召回与运行时一致化**：
   - 升级 `skills/story-long-write/scripts/build_writer_prompt.js` 自动匹配并注入主对标情绪模块/节奏与命中流派包正文技巧，修复 `isDeployedPack` 对 5 端真实部署路径的探测，并将提示词硬底线中的黑话与单案词改为白话通用表达。
   - 修复 `story_hook_core.js` 漏白名单 `设定/全书梗概.md` 导致的提交假警告（同步 5 端副本）；对齐 `check-delivery-contract.js` 短篇旁白破折号提醒阈值与 `check-ai-patterns.js` 短篇口径；移除 `story-short-analyze` 中恒为 `null` 的死字段 `first_conflict_char` 及无下游消费的冗余小节；为 `scripts/sync-opencode.py` 补齐 `Agent(subagent_type: ...)` 到 OpenCode 子代理语法的转换。
3. **跨 Skill 与文档口径统一、锁紧热路径预算**：
   - 清理全部 14 个 Skill、7 端宿主模板（含 `story-consistency.md`、`story-explorer.md` 中残留的 demo 测试书人名）及 `README.md` / `README_EN.md` / `CONTRIBUTING.md` / `docs/*.md` / `scripts/README.md` 中的无用列、自造黑话、伪精确计数与过时口径，并重新生成 OpenCode / Codex / ZCode 适配层。
   - 更新 `scripts/doc-budget.json`：将全部长篇路径的最重题材包钉住项由 `豪门虐恋追妻.md` 切换为当前最重的 `悬疑灵异.md`，并按精简后的实际字数收紧文件与路径预算。

## Alternatives considered

- **保留实验中的单案微观补丁作为「避坑明细」**：最强理由是能避免某几个具体测试案例再次踩坑。不用：单案数值与道具（如特定物理参数、特定行业单据、单本书角色桥段）既污染上下文预算，又会在跨题材写作时诱导模型生搬硬套，泛化为通用因果与常识自洽规则即可覆盖整类问题。
- **在 CI 中为自造黑话或套话新增正则禁词守卫**：最强理由是可以机械阻止黑话回流。不用：仓库 `AGENTS.md` 明确规定面向作者的白话风格不设禁词守卫、靠评审守住，且没有破坏运行时的确定性失效模式；机械禁词反而容易误伤合法讨论与正反对照样例。
- **不收紧 `doc-budget.json`，保留高余量便于后续加字**：最强理由是减少后续改动调整预算的摩擦。不用：放任数百字的闲置预算会让跨包套话重新膨胀，`check-doc-budget.mjs` 也会持续打印降预算提醒；在保留合理余量的前提下收紧预算才能锁住本次瘦身收益。

## Consequences

- **收益**：
  - 34/34 专类题材包全部通过多轮 `noveldb` 对照与盲评检验（10 轮盲评 44 场 43 胜 1 负），同时全套 36 份题材包和核心 Skill 实现显著瘦身，热路径上下文开销明显下降。
  - 拆文 → 写作自动召回链路与运行时检测/Hook/文档口径保持一致，消除了 `全书梗概.md` 提交误报、已部署题材包路径漏检、短篇破折号阈值冲突和 OpenCode 生成代理工具名泄漏等真实缺陷。
  - 经过 10 轮递进巡检（含最终 2 路独立零偏见终检），全仓达到 0 P0 / 0 P1。
- **代价与注意事项**：
  - 预算收紧后，后续若向任一题材包或核心手册新增通用规则，必须先删等量旧文或显式调整 `scripts/doc-budget.json` 并说明理由；若其他长篇题材包字数超过 `悬疑灵异.md`，需同步更新 `doc-budget.json` 里的最重题材包钉住项以通过 `test-doc-budget.py`。

## Verification

- 本地运行 `.github/workflows/cross-platform.yml` 全部检查项：`lint-repo.py`、`check-doc-budget.mjs`、7 项仓库守卫与契约回归、`check-story-setup-deployment.sh`、7 端宿主适配层校验、`check-plugin-packaging.py` / `test-plugin-packaging.py`、全部 Node 契约与检测器测试、全部 Python 运行时与流水线回归、全部 6 端 Hook 回归及采集脚本语法/CDP dry-run 检查均通过。
