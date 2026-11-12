# Agent Note: 放开正文情绪直写与人物算账，校准去味误报并清理升级残留

Status: implemented

## Problem

Issue #540 反映生成的长篇正文里大量叙述句挂着手眼或道具小动作，人物正常的心理活动与利害盘算几乎消失，多轮局部修补后仍反复出现；附录同时指出 `README.md` 部分小节标题带有英文直译腔。

仓库此前虽已删除 `style-craft.md`，但写作参考、去味检测器和项目升级部署三处仍把人物的情绪与思考往手眼小动作上赶：

1. **写作热路径压制直写情绪与完整算账**：`writing-craft.md` 第 1 节用五步回退顺序把「直接点明情绪」压在最后一档，且限定只能用于「低强度或过场」，前几档则引导写物件变化和身体反应；第 7 节反注水规则笼统禁止「内心独白总结」；第 8 节限知视角规定念头只能写「半句的、被打断的……不写完整理性的内心独白」，把人物权衡得失和解释缘由的正当心理句一并掐断。对照 `38.207` 语料库中七猫 132 本完结长篇均匀抽样的 5,246 章（剥离引号对白后的纯叙述句），真人章节含肢体或手眼动作词的叙述句平均占 12.1%（P10–P90 为 3%–23%，其中指尖、袖口、摩挲、抿唇类纯微动作中位数为 0%、均值仅 1.5%），含盘算或因果词的叙述句平均占 15.1%（P10–P90 为 4%–28%），71.4% 的章节在旁白直写情绪词，且盘算因果句里 74.4% 是带逗号的完整复句；而旧规则写出的章节在同一口径下肢体动作句升至 24%–26%（按含广义动作动词的宽口径计可达 70% 以上），盘算因果句跌至 6%–8%。
2. **去味检测器漏掉慢速道具动作、误伤人物算账，且报错文案反向逼模型补动作**：
   - `check-ai-patterns.js` 的 `STOCK_REACTION_PATTERNS` 只覆盖「指尖微颤、指节泛白」等急促套话，漏掉模型为绕开黑名单改写的「指腹摩挲杯沿」「慢慢拢住药包」「视线落在某处停半秒」「手往袖里一缩」；
   - `findReasoningChainTic` 存在四处误伤根因：① 四个词桶各自独立扫描且不去重重叠区间，一句「可以通过呼吸判断」或「必须在规则惩罚前做出判断」会同时命中 `modal`、`mental`、`abstract` 被重复计 2–3 次；② 未要求出现推导连接词或情态链，单靠「知道/明白」加「任务/条件/风险/局面/结果」就能凑够两桶触发；③ 单处「在这种情况下」即可解锁整章计数，导致网游文的「任务」或玄幻文的「规则」高频出现时整章误报；④ `connector` 混入了传统叙事高频过渡词「想到这里」（5,280 章真人样本出现 376 次，而「按照这个逻辑」为 0 次、「真正的问题在于」仅 1 次）与「只有这样」，`modal` 混入了 #205 物业怪谈测试样本的剧情词「回家、进门」及日常表达「可以/能够 + 判断/理解」；
   - `not-is-comparison`、`quote-emphasis-tic`、`cliche-density-tic`、`metaphor-density-tic`、`reasoning-chain-tic`、`abstract-summary-tic` 六条规则的报错文案统一要求「改成可见的动作、物件」，每轮修稿都在把删掉的套话换成新的小动作；同时 `storyctl.py chapter check` 只统计段落碎度，看不见动作句与心理句失衡。
3. **老项目重跑 `/story-setup` 未清理已删参考文件**：除 Antigravity 先删后拷外，Claude Code、Codex、OpenCode 更新 `agent-references/`，以及 ZCode、OpenClaw、Reasonix、generic 更新 14 个已知 `skills/{name}/` 目录时只做覆盖复制，已从仓库移除的 `style-craft.md`、`emotion-on-page.md` 仍留在老项目磁盘上。

## Decision

1. **写作热路径放开情绪直写与完整算账，明确删改无后果微动作**：
   - `skills/story-long-write/references/writing-craft.md`（同步至写手子代理读取的 `agent-references/writing-craft.md`）第 1 节废除五步回退顺序，改为平级选用的四条通道：直接点明情绪（不限强度）、当下的利害算账与内心吐槽、台词与行动选择、真正改变局面的动作或物件后果；明确凡是不改变选择、关系或物理结果的手眼、姿态与道具微动作（含慢速摩挲、拢住、按住、视线停顿、手往袖里缩）一律删掉，或改写成判断、算账、直白情绪与台词。
   - 第 7、8 节拆开「作者替读者复读总结情绪」与「人物站在自身认知和口气里权衡利弊」，允许完整的利害权衡、自我说服与内心吐槽，保护 `因为/所以/既然/省得/免得/犯不着/横竖/索性` 等因果连接词；同步更新 `workflow-chapter.md` Step 6–7、`narrative-writer.md`（及 OpenCode、Codex、ZCode 生成产物）与短篇 `scene-craft.md`。
2. **按 17.5 万篇真人语料校准 `check-ai-patterns.js` 与 `storyctl.py`**：
   - `STOCK_REACTION_PATTERNS` 补入 `指腹`、`慢慢`、`拢住/按住/压住/扣住/捻`、`落在……停/顿`、`手/指尖/手指往袖/怀/兜里缩/揣/收/藏`；
   - `findReasoningChainTic` 按 `connector → modal → mental → abstract` 顺序在同一行内去重重叠区间，从 `connector` 移除「想到这里、只有这样」，从 `modal` 移除「回家、进门、理解」与「可以、能够」，并要求全篇至少命中 3 处 `connector` 或 `modal` 推导链才报；
   - 将上述六条规则及 `trailer-ending`、`trailer-summary` 的修稿提示改为并列指向直白情绪、人物利害判断、决定、对话与具体后果，同步全部四份检测器副本及 `demo/去AI味对照/README.md` 示例输出；
   - `skills/story-long-write/scripts/storyctl.py` 的 `chapter check` 新增与 `fragmentation()` 同口径的非阻断参考指标 `prose_balance(body)` 及 `--plain` 白话提示，参照值按七猫 5,246 章标定为肢体动作句均值 12%（3%–23%）、盘算因果句均值 15%（4%–28%）。
3. **升级部署清理受管目录内的源端已删文件**：
   - `skills/story-setup/scripts/copy-path-safety.py` 增加可选参数 `--prune-orphans`：仅在 `status == "safe"` 且目标本身非符号链接时，删除目标目录中源目录已不存在的文件与空子目录，返回排序后的 `pruned` 列表；`status == "same"` 或目标为符号链接时不删任何文件。
   - `skills/story-setup/SKILL.md` 与各端 `deploy-*.md` 对独占受管目录（`agent-references/`、`.claude/hooks/` 及 ZCode / OpenClaw / Reasonix / generic 的 14 个已知 `skills/{skill-name}/` 子目录）在覆盖前执行清理，不动共享父目录里的用户自定义文件。
4. **收敛润色 `README.md` 并更新 ClawHub 清单**：保留 `## 这是什么`、`## 安装后的第一条请求` 等原有自然标题及站外文章原名链接，仅将内部术语标题 `从门禁到回写，一条链走完` 改为 `从补细纲、写正文到追踪回写`，修正 `看看它的输出`、`可复用的模块`、`判定为 AI` 三处直译表达及去味说明里只提「可见动作和物件」的单向措辞；递增本次改动的 6 个 skill 包版本并重算 `packageDigest`。

## Alternatives considered

- **把 `prose_balance` 设为 `storyctl.py` 或写后 hook 的阻断条件**：硬阻断能强行压低单章动作句比例，但纯打斗章或纯密谋章天然会偏离全书均值，一旦阻断提交又会逼模型按词表凑「觉得、因为」，重演指标对抗，因此保持只作参考提示。
- **在 `story-setup` 对 `.claude/agents/`、`.opencode/agents/`、`.zcode/commands/` 等父目录一并按源目录删未知文件**：逻辑最简单，但这些父目录允许用户存放自定义 agent 与命令，整目录对齐会误删用户资产；已删除的参考文档只落在 `agent-references/` 和 14 个已知 skill 子目录内，只清理独占子目录即可解决问题且不伤用户文件。
- **在 `check-ai-patterns.js` 为慢速道具动作单立新的 finding 类型名**：单独命名在统计上更细，但 `expression.md` 与 `test-handoff-contracts.py` 绑定了 22 个检测类别双向索引且 `expression.md` 字数预算只剩 34 字；这类写法本质仍是套式反应，并入 `stock-reaction-tic` 即可在同一修稿环节处理。

## Consequences

- **收益**：写作规则、去味检测与章节检查三处口径打通，直写情绪、完整利害盘算与口语因果句恢复正常空间，慢速手眼与道具小动作被纳入套式反应提示，`reasoning-chain-tic` 在七猫 151,844 章长篇与 24,012 篇短篇上降至零误报；老项目重跑 `/story-setup` 自动清掉历史遗留旧文档。
- **代价**：涉及共享参考、共享检测器脚本与多端 agent 模板，后续修改同类规则需继续通过 `shared-references.py`、`sync-shared-assets.py` 和各端适配生成脚本同步；`prose_balance` 基于词面正则抽样，仅用于单章偏科提示，不替代具体句意审读。

## Verification

- `38.207` 真实语料全量核验（七猫 132 本完结长篇共 151,844 章 + 全部 24,012 篇完结短篇）：
  - `reasoning-chain-tic` 在全量 151,844 章长篇与 24,012 篇短篇上误报由旧版 3 章（网游「任务」高频章、对话占 82% 叠加「可以通过…判断」重复计分章、玄幻 15 处「规则」配单处「在这种情况下」章）降至 **0 章 / 0 篇（0.000%）**，原有公文推导正例 `FIXTURE18` 仍稳定检出（31 处命中、13 处推导链、70.3/千字）；
  - 扩充后的 `STOCK_REACTION_PATTERNS` 在抽样长篇章节误报率仅由 `0.43%` 微增至 `0.45%`（+1 章），2,000 篇短篇由 `0.20%` 微增至 `0.25%`（+1 篇）。
- 本地回归与守卫：`bash scripts/test-ai-patterns.sh`、`python3 scripts/test-storyctl.py`（23 项）、`bash scripts/check-story-setup-deployment.sh`、`bash scripts/static-check.sh`、`python3 scripts/skill-numbering.py check`、`bash scripts/check-doc-budget.sh`、`bash scripts/check-shared-files.sh`、`python3 scripts/check-agent-notes.py`、七端适配守卫及 `clawhub_release.py validate` 全部通过。
