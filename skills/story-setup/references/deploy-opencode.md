# OpenCode 部署

`target_cli` 含 `opencode` 时，由 SKILL.md Phase 2 完整读取并依次执行本文件。路径检查、幂等重跑、残留清理、部署标记、模板占位符、项目指令合并和报告遵循 SKILL.md 的公共规则。

## 部署前置（先于下表任何 OpenCode 行执行）

只适配 OpenCode 2.x：1.x 的插件 loader 读不了 `story-hooks.ts`，只记一行日志后照常运行，写正文守卫整场缺席；1.x 也不认 agents 的 `permissions:` 规则，只读 agent（`consistency-checker`、`story-explorer`）会拿到写文件与 shell 权限。版本门 fail-closed。

1. 运行 `opencode --version`，取第一个 `主.次.修` 版本号：
   - 主版本 ≥ 2 → 继续
   - 主版本 < 2 → 停止 OpenCode 部署（其它 target 照常），告诉用户先升级到 2.x（先 `npm rm -g opencode-ai`，再 `npm i -g @opencode/cli` 或 `curl -fsSL https://opencode.ai/v2/install | bash`），装好后重跑 story-setup
   - 命令不可用或解析不出版本 → 同样停止 OpenCode 部署，请用户在自己的终端运行 `opencode --version`：用户在对话里确认显示 2.x 后才继续；是 1.x 按上一条处理
   - 停止 OpenCode 部署时：target 只有 opencode 则不写、不更新 `.story-deployed`（已有的原样保留，不抬 `agents_version`），也不写任何 OpenCode 文件；多 target 时其它端照常部署，写入的 `target_cli` 不含 opencode；安装报告「现在可以做什么」只写装上的端，「你还需要做的事」里用白话说 OpenCode 这次没装上及原因（如版本太旧），升级后重新部署时选把它加回来
2. 插件由 OpenCode 自动发现 `.opencode/plugins/*.ts` 加载，不写 `opencode.json`。项目根已有 `opencode.json` / `opencode.jsonc` 时，从其 `plugin`、`plugins` 数组删掉指向 `.opencode/plugins/story-hooks.ts` 的项（旧版部署留下；2.x 丢弃单文件路径并告警），数组删空就删掉该键，其余内容原样保留。

## 部署清单（机械可检查）

| Source path | Target path | Owner class | Merge mode | Validation check |
|-------------|-------------|-------------|------------|------------------|
| `skills/story-setup/references/opencode/AGENTS.md.tmpl` | `AGENTS.md` | user+managed | managed block merge | contains story skill routing sections |
| `skills/story-setup/references/opencode/agents/` | `.opencode/agents/` | story-setup managed | replace | 7 agent files exist（replace 前按下方「保留已有模型配置」缓存现有 `model:`，避免覆盖用户已配模型） |
| `skills/story-setup/references/opencode/plugin.ts` | `.opencode/plugins/story-hooks.ts` | story-setup managed | replace | TypeScript plugin file exists |
| `skills/story-setup/references/opencode/story_hook_core.js` | `.opencode/plugins/lib/story_hook_core.js` | story-setup managed | replace | Node syntax valid；与 ZCode 副本字节一致；被 story-hooks.ts import |
| `skills/story-setup/references/opencode/commands/` | `.opencode/commands/` | story-setup managed | replace | 14 command files exist |
| repository `skills/story-setup/references/agent-references/` | `skills/story-setup/references/agent-references/` | story-setup managed | replace | every reference resolves |
| `skills/story-setup/references/opencode/pre-commit.sh` | `.git/hooks/pre-commit` | user+managed | append or create | file exists and is executable；含 marker 块则替换块内容，不含则检测 exit 0 位置智能插入 |

## 部署步骤

1. **先缓存已有模型配置**：执行下方「配置 Agent 模型」的「保留已有模型配置」，再做第 2 步的 replace。先覆盖会丢失用户已配模型。
2. 复制 `references/opencode/agents/` 到 `.opencode/agents/`。Agent 正文以 Claude Code Markdown 为真源，这里是仓库里预生成的产物，部署只做复制。
3. 复制 `plugin.ts` 到 `.opencode/plugins/story-hooks.ts`，`story_hook_core.js` 到 `.opencode/plugins/lib/`，`commands/` 到 `.opencode/commands/`，`pre-commit.sh` 按清单行合并进 `.git/hooks/pre-commit`。
4. 按 SKILL.md 先清理 `skills/story-setup/references/agent-references/` 内源端已退役的旧文件（`status: safe` 时），再复制当前 agent references。OpenCode 只使用当前规范前缀 `skills/`，不在运行时遍历历史备选路径。
5. 将 `references/opencode/AGENTS.md.tmpl` 按 SKILL.md「项目指令合并」写入根 `AGENTS.md`（`--host opencode`）。
6. 执行「配置 Agent 模型」其余步骤。
7. `.story-deployed` 的 `references_dir` 写 `skills/story-setup/references/agent-references`（多端时与其他端逗号拼接）。

## 配置 Agent 模型

> 子代理不指定模型时继承主模型，低成本 Agent 也耗主模型额度；此步骤自动检测用户模型并写入 `model:` 字段。

### 保留已有模型配置（必须在 `.opencode/agents/` 的 replace 之前执行）

OpenCode agents 部署是 `replace`，会覆盖上次写入的 `model:`。所以在执行该 replace **之前**先扫描现有 `.opencode/agents/*.md`，缓存每个 agent 的 `model:`（agent 名 → 模型 ID）。后续检测失败/超时、或用户跳过某一级时，用缓存值回填，避免把用户上次配好的低成本模型抹成主模型。若 replace 已先发生、缓存为空，则按全新部署处理，并在安装报告中提示"未能保留上次模型配置"。

### 获取模型列表

优先在项目根执行 `opencode api model.list -H "x-opencode-directory:<项目根绝对路径>"`，输出 JSON：`data[]` 每项的 `providerID/id` 即模型 ID，`cost[]` 为每百万 token 的 input/output 单价（空数组即无成本数据），`limit.context` 为上下文长度；不可用或解析失败时回退到 `opencode models` 纯文本（每行 `provider/model`）。两者都用 60000ms（60 秒）超时，因为首次运行需加载 models.dev 缓存。

- 成功 → 进入「模型分级」
- 超时 → 重试一次（缓存可能未预热）；仍然超时则按「保留已有模型配置」缓存回填已有 `model:`、跳过自动配置，在安装报告中输出手动配置指南
- 失败（命令不存在、输出为空等）→ 同上：回填「保留已有模型配置」缓存、跳过自动配置、输出手动配置指南

### 模型分级

**优先按成本分级（有 `model.list` 成本数据时）**：按每模型实际 cost 从低到高分档——低端取最便宜/免费档、中端取中价档、高端取最贵或上下文/能力最强档。免费模型按真实 cost=0 归低端，**不按名字里的营销词**（如 `nemotron-3-ultra-free` 名含 `ultra` 但 cost=0，应归低端）。无 cost 数据的模型也据此进入候选，不被丢弃。

**回退按关键词分级（只有 `opencode models` 或无 cost 时）**：按模型 ID 中最后一个 `/` 之后的模型名按 `-`、`.`、`_` 分割为段，逐段精确匹配关键词（不区分大小写）。例如 `minimax-m3` 拆为 `[minimax, m3]`，不匹配 `mini` 也不匹配 `max`；`claude-haiku-4.5` 拆为 `[claude, haiku, 4, 5]`，匹配 `haiku`。关键词分级是启发式，安装报告中标注 `分级依据：关键词（heuristic）`。

| 等级 | 匹配关键词 | 对应 Agent |
|------|-----------|-----------|
| 低端 | `haiku`, `flash`, `mini`, `nano`, `lite` | chapter-extractor, consistency-checker, story-explorer |
| 中端 | `sonnet`, `plus` | story-researcher, character-designer |
| 高端 | `opus`, `pro`, `ultra`, `max` | story-architect, narrative-writer |

- 一个模型可能匹配多个等级的关键词，取最高等级
- 关键词回退下未匹配任何关键词的模型仍列入候选附加建议（按成本分级则一律纳入），并在安装报告列出，提示"可通过自定义输入使用"
- 同一等级内，如果包含多个模型供应商，优先列出知名供应商（anthropic、openai、google、deepseek）的模型

### 逐级交互选择

按 低端 → 中端 → 高端 顺序，每级用 AskUserQuestion 让用户选择。问题只用作者能懂的角色名；括号里的内部 agent 名只写在技术备注里，不放进问题。

| 等级 | 问作者的话 | 技术备注：对应 agent |
|------|-----------|---------------------|
| 低端 | 「拆书助手、资料检索员和校对员做的是翻找和核对，给它们选哪个模型？便宜的就够用。」 | chapter-extractor（拆书助手）、story-explorer（资料检索员）、consistency-checker（校对员） |
| 中端 | 「人物设计师和资料研究员整理设定与资料，给它们选哪个模型？」 | character-designer（人物设计师）、story-researcher（资料研究员） |
| 高端 | 「写正文的写手和排大纲、统筹全书的总指挥直接决定正文质量，给它们选哪个模型？」 | narrative-writer（写手）、story-architect（总指挥） |

每级选项结构：

```
选项：
  - provider/model-id
  - provider/model-id
  - 自定义输入（手动输入完整模型 ID，ID 拼写错误要到运行时才会暴露；高端提示请勿使用低端模型，会影响正文质量）
  - 保留现有模型（有缓存时才显示）
  - 跳过，用主模型（低端/高端说明「成本可能较高」；中端说明「主模型质量通常足够」）
```

规则：
- 候选最多显示 5 个，超过则截断并提示"更多模型请使用自定义输入"。**每一级无论候选数是否为 0 都用 AskUserQuestion 弹出**，选项至少含：候选模型（如有）、`自定义输入`、`保留现有模型`（「保留已有模型配置」缓存到该 agent 的 model，无则不显示此项）、`跳过，用主模型`。候选为 0 时仍弹窗，并在问题说明里给出对应警告 + 列出未分级/未入档模型供参考——不再静默跳过交互（否则用户够不到自定义输入）。
- `自定义输入`：用户输入 `provider/model-id` 完整 ID；写入前校验为单行、无控制字符、匹配 `^[A-Za-z0-9._-]+/[A-Za-z0-9._:+-]+$`，不符则提示重输或改选跳过。
- `保留现有模型`：写回「保留已有模型配置」缓存的该 agent model（重新部署时保住用户上次配置），不算"跳过"。写手的缓存模型按本次分级落在低端或中端时（旧版把写手按中端配），高端这级的问题说明加一句「写手上次配的是中档模型，写正文建议换高端的」，推荐重选。
- `跳过，用主模型`：显式清除——不写该 agent 的 `model:`，agent 继承主模型。想保留上次配置请选 `保留现有模型`。
- 各级候选为 0 时在问题说明里给出提示：
  - 低端："没找到便宜的模型，拆书助手、资料检索员和校对员会用主模型，花费可能较高"
  - 中端："没找到合适的中档模型，人物设计师和资料研究员会用主模型。主模型质量够的话这样没问题；想省钱可以自定义输入一个不比主模型差的中档模型，或从下面未分级的模型里选。"
  - 高端："没找到高端模型，写手和总指挥会用主模型"

### 写入 model 字段

对应用户选择的 agent 文件（`.opencode/agents/*.md`，由部署步骤第 2 步在此之前已部署），在 frontmatter 末尾、closing `---` 之前，以**零缩进的顶层字段**插入 `model:`（不要插进 `permissions:` 规则列表等多行块的缩进内部）。值含 YAML 特殊字符时加引号，确保不破坏 frontmatter：

```yaml
---
description: ...
mode: subagent
permissions:
  - action: "*"
    resource: "*"
    effect: deny
  - action: read
    resource: "*"
    effect: allow
steps: 12
model: provider/model-id
---
```

- 如果 agent 文件已有 `model:` 字段（重新部署场景），替换该顶层 `model:` 的值，不新增重复键
- `保留现有模型`：写回「保留已有模型配置」缓存的该 agent model
- `跳过，用主模型`：不写入 `model:` 字段
- 检测失败/超时、没走到本步骤的等级：用「保留已有模型配置」缓存回填 `model:`，避免 replace 抹掉用户上次配置；回填的写手模型按关键词落在低端或中端时，在「你还需要做的事」里提醒作者给写手换高端模型

## 验证

- 检查 `.opencode/agents/` 下的 7 个 agent 定义文件是否存在，且 frontmatter 包含 `mode: subagent` 和 `permissions` 规则列表
- 检查 `.opencode/plugins/story-hooks.ts` 是否存在
- 检查 `.opencode/plugins/lib/story_hook_core.js` 存在且 `node --check` 通过（story-hooks.ts import 之，与 `.zcode` 副本字节一致的共享写正文守卫核；置于 `lib/` 子目录以避开 OpenCode 对 `.opencode/plugins/*.js` 的插件自动发现，`lib/` 里不得放 `index.*` / `server.*`）
- 检查 `.opencode/commands/` 下的 14 个 command 文件是否存在
- 按源目录相对路径核对 `skills/story-setup/references/agent-references/`，含子目录
- 检查 `opencode.json` / `opencode.jsonc`（如有）的 `plugin`、`plugins` 数组不再含指向 story-hooks.ts 的项
- `opencode` 可用时在项目根执行 `opencode api plugin.list -H "x-opencode-directory:<项目根绝对路径>"`，确认 `id` 为 `oh-story.story-hooks` 的条目 `state.status` 为 `active`（首次请求可能返回空列表，隔几秒重试）
- 检查 `.git/hooks/pre-commit` 是否存在且有执行权限（Windows 上跳过执行权限检查）
- 检查 `.opencode/agents/` 下 agent 文件 frontmatter 可被 YAML 解析、`model:`（如有配置）是合法顶层标量，而非仅 grep 到 `model:` 子串

## 安装报告必须提示

- 部署后新开 OpenCode 会话，让 agents、commands 与插件生效。
- 执行了「配置 Agent 模型」时，在「部署明细」里输出模型配置摘要（角色名在前，内部名放括号里）：
  ```
  Agent 模型配置：
    总指挥（story-architect）         → <高端模型>（provider/model-id）
    写手（narrative-writer）          → <高端模型>（provider/model-id）
    人物设计师（character-designer）  → <中端模型>（provider/model-id）
    资料研究员（story-researcher）    → <中端模型>（provider/model-id）
    拆书助手（chapter-extractor）     → <低端模型>（provider/model-id）
    校对员（consistency-checker）     → <低端模型>（provider/model-id）
    资料检索员（story-explorer）      → <低端模型>（provider/model-id）
  ```
- 自动检测失败（读不到模型列表）时，在「你还需要做的事」里用白话写：
  <!-- author-report -->
  ```md
  这次没能读到可用模型列表。已配过的助手沿用原模型，未配过的先用主模型，花费可能偏高。想省钱就告诉我一个便宜的模型名，我帮它们换上；写手和总指挥建议用你最好的模型。
  ```
  「部署明细」只留一行：模型写在 `.opencode/agents/{agent名}.md` frontmatter 的 `model:`，可用模型见 `opencode models`，定价见 https://models.dev/。
