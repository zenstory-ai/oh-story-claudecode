# Agent Note: 正文动作代偿与心理盘算失衡收口

Status: implemented

## Problem

Issue #540 报告正文中大量叙述句带手眼或道具动作、角色心理与利害盘算几乎消失，且多轮修订后仍在复现；附录同时指出 `README.md` 部分小节标题有英文直译腔。

根因不在已删除的 `style-craft.md` 单点，而在写作热路径、去 AI 味检测器与重部署清理三条链路仍朝着「把情绪与判断压成可见小动作」同向施力：

1. **写作热路径把直写情绪压在末档、限制完整心理句**：`writing-craft.md` 第 1 节用五级回退顺序把「直接点明情绪」标成仅限「低强度或过场」的兜底，第 3、4 档引导「操作物件或环境」「身体反应」；第 7 节反注水规则一刀切禁「内心独白总结」；第 8 节限知视角要求「用半句的、被打断的……不写完整理性的内心独白」，把角色正常的利害算账与因果判断一并掐掉；`workflow-chapter.md` 自检与 `narrative-writer.md` 也缺少反道具/手眼小动作代偿判据。实测 90 章七猫人类网文样本中，去引语叙述句里肢体动作句与心理因果句均值同为 19%（P10–P90 分别为 8%–32% 与 8%–28%），而旧写作链路实测跑出动作句 24%–26%、心理因果句仅 6%–8%。
2. **检测器漏放慢速道具代偿、误伤角色判断，且修复提示反向诱导补动作**：`check-ai-patterns.js` 的 `STOCK_REACTION_PATTERNS` 只抓急促套话，漏掉「慢慢拢住药包」「指腹摩挲」「视线落在……停了半秒」「手往袖里一缩」等慢速道具代偿；`REASONING_CHAIN_PATTERNS` 在没有任何论文连接词或判断情态词时，仅凭单段出现心理词加抽象词（如「知道」「条件」）就会触发 `reasoning-chain-tic`；`cliche-density-tic`、`metaphor-density-tic`、`reasoning-chain-tic`、`abstract-summary-tic` 四条修复提示统一要求改成「可见的动作、物件」，形成去味越改动作越密的负反馈。同时 `storyctl.py chapter check` 只看碎句率，看不见动作句与心理因果句失衡。
3. **重部署未清理受管目录里的退役文件**：`style-craft.md`、`emotion-on-page.md` 已从仓库删除，但除 Antigravity 先删后拷外，Claude Code、Codex、OpenCode 部署 `agent-references/` 以及 ZCode、OpenClaw、Reasonix、generic 部署 14 个已知 `skills/{name}/` 时只做覆盖复制，不清理源端已删除的旧 `.md` 文件，老项目重跑 `/story-setup` 后退役参考文件仍留在磁盘。

## Decision

1. **热路径对齐四条并列通道与反动作代偿判据**：
   - `skills/story-long-write/references/writing-craft.md`（同步至 `agent-references/writing-craft.md`）第 1 节改用按场景任选的四条并列通道（直写情绪且不限强度、角色当下的判断/利害算账/内心吐槽、台词与行动选择、改变局面的动作或物件后果），并设「反动作代偿」硬判据（不改变选择、关系或物理结果的手眼/姿态/道具小动作一律删，或改写为判断、算账、直白情绪或台词）；第 7、8 节区分「叙述者替读者复读情绪」与「角色自己的利害算账、因果判断与吐槽」，放行完整的角色盘算与 `因为/所以/既然/省得/犯不着` 因果句。
   - 同步更新 `skills/story-long-write/references/workflow-chapter.md` Step 6–7、`skills/story-setup/references/templates/agents/narrative-writer.md`（并重生成 OpenCode、Codex、ZCode 适配产物）与 `skills/story-short-write/references/scene-craft.md`。
2. **校准 `check-ai-patterns.js` 并为 `storyctl.py` 补充动作/心理参考观测**：
   - `STOCK_REACTION_PATTERNS` 纳入慢速与道具代偿分支（`指腹`、`慢慢`、`捻/拢住/按住/压住/扣住`、`落在……停/顿`、`手/指尖/手指往袖/怀/兜里缩/揣/收/藏`），同步至四份共享检测器副本；
   - `findReasoningChainTic` 要求同段至少命中 `connector` 或 `modal` 才报论文式推导，不再单凭 `mental + abstract` 误伤角色正常利害盘算；
   - 四条把改写方向单一导向「可见的动作、物件」的提示改为并列指向直白情绪、角色利害判断、对话与具体后果；
   - `skills/story-long-write/scripts/storyctl.py` 的 `chapter check` 新增与 `fragmentation()` 同口径（七猫 90 章去引语叙述句标定）的非阻断指标 `prose_balance(body)` 及 `--plain` 白话参考提示。
3. **补齐 `story-setup` 独占受管目录的退役文件清理**：
   - `skills/story-setup/scripts/copy-path-safety.py` 增加可选 `--prune-orphans`：仅在 `classify_copy` 判定 `status == "safe"`（`copy_allowed: true`）且目标本身非符号链接时，删除目标受管目录中源目录已不存在的文件与空子目录，返回排序后的 `pruned` 列表；`status == "same"` 或目标本身是符号链接时零删除；
   - `skills/story-setup/SKILL.md` 及对应 `deploy-*.md` 规定对独占受管目录（各端 `agent-references/`、`.claude/hooks/` 以及 ZCode / OpenClaw / Reasonix / generic 的 14 个已知 `skills/{skill-name}/` 目录）覆盖前清理源端已退役文件，不触碰共享父目录里的用户自有条目。
4. **重写 `README.md` 翻译腔小节标题与单向动作化措辞**：保留既有外链锚点（`#安装`、`#常见问题`），将直译标题与延伸阅读链接文字改为自然中文，并修正去 AI 味说明中「全部交给可见动作和物件」的单向表述。
5. **同步 ClawHub 发布清单**：递增本次涉及字节变更的 `story-deslop`、`story-long-write`、`story-review`、`story-setup`、`story-short-write` 及主路由 `story` 的包版本，使用固定的中央控制脚本重新生成 `packageDigest`。

## Alternatives considered

- **把 `prose_balance` 设成 `storyctl.py` 或写后 hook 的阻断门禁**：硬门禁能强制每章指标落进区间，但不同题材与章节类型（如纯打斗章或纯密谋章）单章动作句、心理句占比天然会有合理偏离，设成阻断会逼模型机械凑「觉得/因为」词频，重演反向指标游戏，因此保持只作参考、不阻断。
- **在 `story-setup` 对 `.claude/agents/`、`.opencode/agents/`、`.zcode/commands/` 等共享父目录一并按源目录删未知文件**：实现最统一，但这些目录允许用户放自定义 agent 和 command，全目录清理会误删用户资产；退役的写作参考文件实际只存在于 `agent-references/` 和 14 个已知 skill 子目录内，只清理独占受管目录即可覆盖问题且不伤用户文件。
- **在 `check-ai-patterns.js` 新增独立的慢速道具代偿检测类别名**：拆分新类别名在报表里更细，但 `expression.md` 与 `test-handoff-contracts.py` 锁死了 22 个检测类别双向索引且 `expression.md` 热路径字数预算只剩 34 字，并入同属反应套话的 `stock-reaction-tic` 无需膨胀热路径文档即可在同一修稿环节拦截。

## Consequences

- **收益**：写作端、去味检测端与章节体检口径一致，直写情绪、角色利害盘算与因果说明回到正常网文比例，慢速道具小动作代偿被精准识别；老项目升级部署时自动清掉 `style-craft.md`、`emotion-on-page.md` 等历史残留；`README.md` 章节标题更符合中文母语阅读习惯。
- **代价**：`writing-craft.md`、`narrative-writer.md`、`storyctl.py`、`check-ai-patterns.js` 与多端适配产物同批改动，需同步维护共享资产与多端适配守卫；`prose_balance` 采用轻量词面正则做叙述句抽样参考，仅供单章偏科提示，不替代审稿对具体句意的判断。

## Verification

- 真人语料校准：`STOCK_REACTION_PATTERNS` 扩展后在七猫 90 章长篇（0/90）、16 篇短篇（0/16）与 20 章 demo 人类样本（0/20）上零误报；`prose_balance` 在同一批七猫 90 章上标定动作句与心理因果句均值同为 19%（P10–P90 分别为 8%–32% 与 8%–28%）。
- 回归与守卫：`bash scripts/test-ai-patterns.sh`、`python3 scripts/test-storyctl.py`（23 项）、`bash scripts/check-story-setup-deployment.sh`（含 `--prune-orphans` 退役文件清理、`same` 零改动与符号链接拒绝穿透断言）、`bash scripts/static-check.sh`、`python3 scripts/skill-numbering.py check`、`bash scripts/check-doc-budget.sh`、`bash scripts/check-shared-files.sh`、`python3 scripts/check-agent-notes.py` 及七端适配检查全部通过。
