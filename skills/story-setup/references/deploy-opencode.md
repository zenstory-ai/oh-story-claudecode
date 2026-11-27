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
| `skills/story-setup/references/opencode/story_hook_core.js` | `.opencode/plugins/lib/story_hook_core.js` | story-setup managed | replace | Node syntax valid；与 Claude/Codex/ZCode/Antigravity 副本字节一致；被 story-hooks.ts import |
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

> 子代理不指定 `model:` 时继承主模型，低成本助手也会耗主模型额度；按下面 4 步保留/配置各档模型。

1. **先缓存已有模型配置（必须在 `.opencode/agents/` replace 前）**：扫描现有 `.opencode/agents/*.md`，记录每个 agent 当前顶层 `model:`。后续拉取失败、超时或用户选「保留现有模型」时用此缓存回填；若 replace 已先发生致缓存为空，按全新部署处理并在报告注明「未能保留上次模型配置」。
2. **获取并分级可用模型（60s 超时，超时重试一次）**：优先在项目根执行 `opencode api model.list -H "x-opencode-directory:<项目根绝对路径>"`（取 `data[]` 的 `providerID/id`、`cost[]`、`limit.context`），不可用时回退 `opencode models`（每行 `provider/model`）。仍失败则用第 1 步缓存回填 `model:`、跳过交互并在报告给手动指引。
   - **优先按成本分级**：有 `cost[]` 时按单价从低到高分低/中/高三档（`cost=0` 免费模型归低端，不看名字营销词如 `ultra-free`），无成本项照常纳入候选。
   - **回退按关键词分级**（报告标 `分级依据：关键词（heuristic）`）：取 ID 末 `/` 后按 `-`、`.`、`_` 切段精确匹配（不区分大小写，多命中取最高档，同档优先 anthropic/openai/google/deepseek，未匹配项列为附加建议）：
     - 低端（`haiku`/`flash`/`mini`/`nano`/`lite`）→ `chapter-extractor`、`consistency-checker`、`story-explorer`
     - 中端（`sonnet`/`plus`）→ `story-researcher`、`character-designer`
     - 高端（`opus`/`pro`/`ultra`/`max`）→ `story-architect`、`narrative-writer`
3. **逐级交互（低端 → 中端 → 高端）**：每级无论候选是否为 0 均用 AskUserQuestion 弹窗（候选最多列 5 个，超限提示自定义输入；问题中只用作者懂的角色名，禁出现内部 agent 名）：
   - 低端：「拆书助手、资料检索员和校对员做的是翻找和核对，给它们选哪个模型？便宜的就够用。」（0 候选提示将用主模型、花费偏高）
   - 中端：「人物设计师和资料研究员整理设定与资料，给它们选哪个模型？」（0 候选提示可用主模型或自定义/从未分级项选）
   - 高端：「写正文的写手和排大纲、统筹全书的总指挥直接决定正文质量，给它们选哪个模型？」（写手缓存落在低/中档时提醒换高端；0 候选提示将用主模型）
   - 每级选项：候选 `provider/model-id`、`自定义输入`（单行无控制字符，须匹配 `^[A-Za-z0-9._-]+/[A-Za-z0-9._:+-]+$`；高端提示勿用低端模型）、`保留现有模型`（仅缓存非空时显示，写回原值）、`跳过，用主模型`（显式清除，不写 `model:`）。
4. **写入 `model:` 字段**：在对应 `.opencode/agents/*.md` frontmatter 闭合 `---` 前以**零缩进顶层字段**插入或替换 `model: provider/model-id`（禁插进 `permissions:` 缩进块内；含 YAML 特殊字符加引号）。未走到交互的失败等级用缓存回填；若回填的写手模型属低/中档，在「你还需要做的事」提醒换高端模型。

## 验证

- 检查 `.opencode/agents/` 下的 7 个 agent 定义文件是否存在，且 frontmatter 包含 `mode: subagent` 和 `permissions` 规则列表
- 检查 `.opencode/plugins/story-hooks.ts` 是否存在
- 检查 `.opencode/plugins/lib/story_hook_core.js` 存在且 `node --check` 通过（story-hooks.ts import 之，与 Claude/Codex/ZCode/Antigravity 副本字节一致的共享写正文守卫核；置于 `lib/` 子目录以避开 OpenCode 对 `.opencode/plugins/*.js` 的插件自动发现，`lib/` 里不得放 `index.*` / `server.*`）
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
