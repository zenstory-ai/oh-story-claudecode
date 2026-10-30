---
name: story-setup
version: 1.3.6
description: "网文写作工具集基础设施部署与检查。为 Claude Code / OpenCode / Codex / Google Antigravity / ZCode / OpenClaw / Reasonix 提供内置适配；Web AI / 通用 Agent 可走 skills + AGENTS.md 文件模式。触发方式：/story-setup、$story-setup、「准备写书」「帮我搭一下环境」「配置写作项目」「检查写作环境」。"
metadata: {"openclaw":{"source":"https://github.com/zenstory-ai/oh-story-claudecode"}}
---
# story-setup：网文写作工具集基础设施部署

你负责把网文写作工具集部署到用户项目目录：已适配的 CLI 使用专用 hooks/agents/config；NarraFork、Web AI、自定义 Agent 等使用通用文件模式。

**保留用户配置；受管文件按清单更新，共同维护的文件按管理块合并。**

作者第一次部署的顺序：判断当前宿主 → 确认项目根 → 按宿主部署 → 验收 → 告诉作者下一步。本文件写公共流程；各宿主的部署清单、算法、校验和报告提示见 Phase 2 对应文件，**只读本次目标宿主的那一份**。

## 选择模式

- 参数为 `check`，或用户只要求检查部署、诊断环境、排查 agent 不可用时：完整读取 [references/diagnostics.md](references/diagnostics.md)，按其中流程仅检查并报告；不进入下面的部署流程。
- 用户要求安装、更新或修复时：执行下面的部署流程。检查后已明确授权的修复沿用本文件与宿主部署文件的部署与合并规则。

---

## Phase 1：判断宿主与项目

**先自检参考目录**：以正在执行的本 `SKILL.md` 所在目录为准，列出与它同级的 `references/` 下的子目录，核对下面 9 个名字是否都在**且都非空**——`agent-references`、`templates`、`opencode`、`codex`、`antigravity`、`zcode`、`openclaw`、`reasonix`、`generic`；同级 `references/deploy-*.md`（8 份宿主部署文件）、`scripts/merge-claude-settings.py`、`scripts/merge-codex-hooks.py`、`scripts/merge-antigravity-hooks.py`、`scripts/generate-antigravity-agents.mjs`、`scripts/deploy-antigravity-skills.py`、`scripts/merge-project-instructions.py` 与 `scripts/copy-path-safety.py` 也必须存在（宿主部署步骤、Claude/Codex/Antigravity hooks 合并、Antigravity Skills 物化与 agent 生成、项目指令合并、递归复制安全检查依赖它们）。有缺即 skill 包没装全，**立即停止，不写任何部署文件**，报告里区分「缺目录」「目录为空」和「缺脚本或部署文件」，并给修复指令：「story-setup 参考资料包不完整，缺 {路径}。按你的安装方式重装 oh-story-claudecode（命令行装的重跑 `npx skills add zenstory-ai/oh-story-claudecode -y -g`，marketplace / Plugin Management 装的在面板里重装），再执行 /story-setup。」

> 判据是「有没有 `SKILL.md`」：只看正在执行的 `SKILL.md` 同级的 `references/`。项目内 `.claude/skills/story-setup/`、`.codex/skills/story-setup/` 和 OpenCode 的 `skills/story-setup/` 只有 `references/agent-references/`、不含 `SKILL.md`，不会是执行目录，也不要拿它们核对。Antigravity / ZCode / OpenClaw / Reasonix / generic 的项目副本是整份 skill 拷贝、自带 `SKILL.md`，9 个子目录本就齐全，照常核对即可。

1. 检查当前目录是否已部署过（存在 `.story-deployed`）
   - `agents_version` 缺失、非整数或小于 `38` → 标记为待更新，继续执行当前部署
   - `agents_version: 38` → 使用 AskUserQuestion 确认是否重新部署；提示里写明重新部署只用**当前本地 skill 包**刷新项目文件，要拿 skill 本身的新版本得先更新 oh-story-claudecode（`npx skills add` 或 marketplace），再回来重跑
   - `agents_version` 大于 `38` → 当前 story-setup 比项目部署旧；停止以避免降级覆盖，提示先更新 oh-story-claudecode，不写任何部署文件
   - 同时读 `target_cli` 字段。**已部署项目以 sentinel 里的值为准**：非空时（逗号分隔的多端组合原样保留）这些端照常重新部署，不再让作者选；第 4 步仍判断当前宿主：判断出来且不在其中（作者换了软件）→ AskUserQuestion 问「这个文件夹之前是给 {已部署宿主名} 装的，你现在用的是 {当前宿主名}，要一起装上吗？」（「一起装上（推荐）」「只更新原来的」），选前者就加进 `target_cli`；判断不出不问。字段缺失或为空才走第 4-6 步。用户明确要求增删目标端时，用 AskUserQuestion 在现有值基础上改，改完的值写回 sentinel。
   - `target_cli` 不含 opencode、但项目里有 `.opencode/plugins/story-hooks.ts` 或 `.opencode/agents/`（多端部署时 OpenCode 曾被版本门拦下）→ 用 AskUserQuestion 问是否把 OpenCode 加回来；选加回则先过 [references/deploy-opencode.md](references/deploy-opencode.md) 的「部署前置」，通过后写回 `target_cli`
2. 检查是否有书名目录（包含 `追踪/` 子目录的目录，或用户自定义结构）
   - 有 → 识别为长篇项目，显示当前项目信息
   - 无 → 识别为新项目或短篇项目
3. 检查 `.active-book` 文件是否存在：存在 → 显示当前活跃书目；不存在 → 跳过
4. **判断当前宿主（能判断就不问作者）**。依次看，第一条能定下来的就用：
   - 你自身的运行环境：系统提示、可用工具名或 skill 调用语法已表明你运行在 Claude Code、Codex、OpenCode、Google Antigravity（含命令行 `agy`）、ZCode、OpenClaw 或 Reasonix 里；
   - 正在执行的本 `SKILL.md` 的安装位置带有宿主专属目录（如 `.claude/`、`.codex/`、`.zcode/`、`.gemini/`、`.openclaw/`、`.opencode/`）；
   - 判断不出（例如网页版 AI、自建 Agent，或以上信号互相矛盾）→ 第 5 步的项目标记只当候选，交第 6 步问作者。
5. 看项目里已有哪些宿主的标记：
   - `.claude/` 或 `CLAUDE.md` → `target_cli = claude-code`
   - `opencode.json`、`opencode.jsonc` 或 `.opencode/` → `target_cli = opencode`
   - `.codex/`、`.codex/config.toml`、`.codex/agents/`、`.codex/hooks.json`、`AGENTS.md` 中的 Codex 段 → `target_cli = codex`
   - `.agents/hooks.json`、`.agents/agents/`，或 `.agents/rules/oh-story.md` 中的 Antigravity 标记 → `target_cli = antigravity`
   - `.zcode/`、`.zcode/config.json`、`zcode.json`、`.zcode/skills/`、`.zcode/commands/`、`AGENTS.md` 中的 ZCode 段 → `target_cli = zcode`
   - `openclaw.json`、`.openclaw/`，或 `AGENTS.md` 中的 OpenClaw 段（标题行含 `网文写作工具集（OpenClaw）`）→ `target_cli = openclaw`
   - `.reasonix/`、`reasonix-plugin.json`、`REASONIX.md`，或 `AGENTS.md` 中的 Reasonix 段（标题行含 `网文写作工具集（Reasonix）`）→ `target_cli = reasonix`
   - `AGENTS.md` 中的通用段（标题行含 `网文写作工具集（通用 Agent / Web AI）`）→ `target_cli = generic`
   - `CLAUDE.md` / `AGENTS.md` 里的 `<!-- oh-story:{宿主} 开始` 管理块 → `target_cli` 含该宿主

   > 后三类只认各端**互斥**的标记：`skills/*/SKILL.md` 的 `metadata.openclaw` 不作 OpenClaw 信号（14 个 skill 都带，三条 skills-only 路径部署出的 `skills/` 一样）；`.agents/skills/` 由 Antigravity、Codex 与 Reasonix 共用，也不单独作准。
6. 定下 `target_cli`：
   - 第 4 步定出了当前宿主 → `target_cli` 就是它。项目里另有其他宿主的标记时，用 AskUserQuestion 问一句白话：「这个文件夹之前也给 {其他宿主名} 装过写作工具，这次要一起更新吗？」选项：「只装 {当前宿主名}（推荐）」「一起更新」。作者一开始就说要装多个时照办。
   - 定不出、项目标记恰好只有一个宿主 → AskUserQuestion 问「上次是给 {宿主名} 装的，这次还是它吗？」，是就用它，不是按下一条问。
   - 定不出、其余情况 → 用 AskUserQuestion 问：「你现在是在哪个软件里跟我对话？」选项用产品名加一句说明：Claude Code（Anthropic 的命令行 / 桌面版）、Codex（OpenAI 的命令行）、OpenCode、Google Antigravity（含命令行 agy）、ZCode、OpenClaw、Reasonix（DeepSeek 的命令行）、网页版 AI 或其他工具（NarraFork、自建 Agent 等）、好几个都要用。提问工具一次放不下这么多选项时，把项目标记里出现过的放前面，其余让作者在「其他」里直接写名字。
   - 作者的答案按「Claude Code → `claude-code`、网页版 AI 或其他工具 → `generic`、其余取小写产品名」换成 `target_cli`；多端为 `claude-code,opencode,codex,antigravity,zcode,openclaw,reasonix,generic` 中选中的端。
7. **确认项目根（通常不问）**：项目根就是当前工作目录。只有当前目录是用户主目录、磁盘根目录、系统目录，或就是本 skill 包自身的安装/源码目录时，才用一句白话问作者：「写作工具要装在哪个文件夹？一般就是放书稿的那个文件夹。」其他情况直接部署，在安装报告的「部署明细」里写明装在哪。

## Phase 2：部署基础设施

Phase 2 幂等：复制、写入与各宿主合并重复执行结果一致。受管目录中只覆盖 oh-story 自己的 14 个 skill、7 个助手、hook 与规则文件，保留同目录里作者自己的文件；不覆盖书稿、设定、大纲、追踪和 `.active-book`。工具、权限或网络问题中断后，从头重跑即可，不另清理半成品；`create only if absent` 的用户状态文件（见清单 Owner class）不会被覆盖。

**两列基准目录不同**：`Source path` 是包内来源，story-setup 内的路径以当前 `SKILL.md` 所在目录定位；`Target path` 相对用户项目根。执行每一行（以及各宿主部署算法里的每个递归复制步骤）之前，先把通配符具体化为单个源/目标，再用本 `SKILL.md` 同级的 `scripts/copy-path-safety.py` 检查。该脚本按 `Path.resolve` / `realpath` 语义跟随已有 symlink，并在两侧都存在时用 `samefile` 核对文件系统对象；**只转绝对路径或比较字符串不算检查完成**。读取其 JSON：`status: same` 时 no-op，禁止复制；仅 `copy_allowed: true` 时可以复制；`source_missing`、`unsafe_target_within_source` 或 `filesystem_identity_error` 必须停止该步骤并报告。无法运行脚本时只能用当前环境的文件系统 API 做完全相同的 canonical realpath、same-object 与 target-descendant 检查；无法确认就停止，不得尝试复制。OpenClaw / Reasonix / generic 的项目副本是整份 skill 拷贝，重跑时执行的就是项目里那份；Reasonix / Codex 还可能经 `.agents/skills → ../skills` symlink 加载，路径文本不同也可能指向同一目录，照字面复制会把目录嵌进自身并撑满磁盘。

**部署前清理自嵌套残留**：`{.claude,.codex,.zcode}/skills/story-setup/references/agent-references/` 与项目根 `skills/story-setup/references/agent-references/` 里若多出 `agent-references/` 层（可能嵌了多层），以及 `skills/story-setup/skills/`，整段删掉再部署，并在安装报告里列出删掉的路径。

### Step 1：按宿主部署

对 `target_cli` 里的每个宿主，**完整读取**对应部署文件，按其中的部署清单（机械可检查）与算法依次执行；不读其他宿主的文件。

| `target_cli` | 部署文件 |
|---|---|
| `claude-code` | [references/deploy-claude-code.md](references/deploy-claude-code.md) |
| `opencode` | [references/deploy-opencode.md](references/deploy-opencode.md)（先过其中「部署前置」版本门） |
| `codex` | [references/deploy-codex.md](references/deploy-codex.md) |
| `antigravity` | [references/deploy-antigravity.md](references/deploy-antigravity.md) |
| `zcode` | [references/deploy-zcode.md](references/deploy-zcode.md) |
| `openclaw` | [references/deploy-openclaw.md](references/deploy-openclaw.md) |
| `reasonix` | [references/deploy-reasonix.md](references/deploy-reasonix.md) |
| `generic` | [references/deploy-generic.md](references/deploy-generic.md) |

多端部署时几个宿主共用根 `AGENTS.md`，各占一个管理块（见下方「项目指令合并」）；某一端被自己的前置条件拦下（如 OpenCode 版本门、Antigravity 缺 Node）时，按该端部署文件的规定处理，其他端照常部署。

### Step 2：创建部署标记

- 仅为本次成功部署的目标创建或更新 `.story-deployed`（sentinel file）；全部目标停止时保留旧标记，不创建新标记。
- 写入以下字段（YAML `key: value` 格式，hook 用 `references/templates/hooks/lib/sentinel.sh` 读取）：
  ```
  deployed_at: <date -u +"%Y-%m-%dT%H:%M:%SZ">
  agents_version: 38
  setup_skill_version: 1.3.6
  target_cli: claude-code（或 opencode、codex、antigravity、zcode、openclaw、reasonix、generic，或其任意组合）
  resolver_strategy: project-local-skill-reference
  references_dir: .claude/skills/story-setup/references/agent-references（Codex 写 .codex/skills/...；Antigravity 写 .agents/skills/...；ZCode 写 .zcode/skills/...；OpenCode / OpenClaw / Reasonix / generic 写 skills/...；多端用逗号分隔）
  ```
- 此文件供 session-start.sh 和写作 skill 检测部署状态，避免重复提示
- 宿主部署文件里「部署标记补充」要求的额外标记一并创建（如 Claude Code 的重启确认标记）

## Phase 3：验证安装

仅检查模式复用第 1–2 项，跳过第 3 项，且其中要求实际执行 hook 或写入 fixture 的子项改为只做静态校验（文件存在、语法有效、注册项齐全），不运行会写入项目的 hook，也不创建部署标记。

1. 对 `target_cli` 里的每个宿主，执行其部署文件的「验证」一节。
2. 验证部署标记：
   - 检查 `.story-deployed` 存在，字段齐全，版本号与 Step 2 的字段块一致
3. 输出安装报告。读者是不懂编程的作者，按这个顺序写：
   - **先写「现在可以做什么」**：用写书的话列本次部署后真正可用的事（如「可以开新书、续写：说 /story-long-write」「可以拆一本对标书」），端的限制如实翻译（如「这个工具里审稿由我一个人完成，没有分工助手」）。
   - **再写「你还需要做的事」**：逐条可照做，如「新开一个会话」「在 Codex 里打开 /hooks，把 oh-story 的几条信任一下」「先安装 Node」；没有就写「无需其他操作」。这两段不出现脚本名、字段名、状态名或文件路径；各宿主部署文件「安装报告必须提示」的内容先翻译进这两段。
   - **最后是简短的「部署明细」**：装在哪个文件夹、已部署文件、已合并的配置、删掉的残留路径、宿主部署文件要求的摘要（如 OpenCode 模型配置）和技术原因，放在报告末尾。

---

## 模板占位符

只替换 `{项目名}`：用作者给的书名或项目名，没给就用当前目录名，去掉花括号。模板里其余花括号写法（如 `{书名}/正文/`）表示「任意一本书的目录」，原样保留。

## 项目指令合并（CLAUDE.md / AGENTS.md）

每个宿主在项目指令文件里占一个管理块：`<!-- oh-story:{宿主} 开始 … -->` 到 `<!-- oh-story:{宿主} 结束 -->`，块里是渲染后的模板；Claude Code 写 `CLAUDE.md`，其余宿主共用根 `AGENTS.md`。按 `python3` → `python` → `py` 的顺序探测出可用的 Python 记为 `PYBIN`，运行：

```text
"$PYBIN" "{story-setup skill目录}/scripts/merge-project-instructions.py" --host {宿主} --template {该宿主模板} --existing {项目指令文件} --output {项目指令文件} --project-name {项目名}
```

规则（无法运行脚本时照此手工合并）：
1. 文件不存在或为空 → 只写这一块。
2. 已有本宿主的块 → 整块替换；块外文字和别的宿主的块一字不动。
3. 没有本宿主的块、但块外有旧版「网文写作工具集」标题行（旧部署）→ 删掉本宿主的旧标题行、引言及与模板同名的节（含已退役的「协作规则」；「Skill 路由表」「文件结构」「写作约束」只在内容带 oh-story 痕迹时才删），在原位置写入这一块；作者自己的节保留在块外。已有别的宿主的块、块外没有旧标题行时，只删本宿主独有的节（如「Codex 项目约定」）。
4. 以上都不是 → 把这一块追加到文件末尾。

把脚本输出的旧节名写进安装报告的「部署明细」。

---

## 参考资料

| 文件 | 用途 |
|------|------|
| references/deploy-*.md | 8 份宿主部署文件：各自的部署清单、算法、验证与安装报告提示，按 Phase 2 Step 1 只读目标宿主那份 |
| [references/diagnostics.md](references/diagnostics.md) | 仅检查模式 |
| UPGRADING.md | 写给作者：各版本要不要重跑、哪些旧数据要迁移 |

---

## 流程衔接

**流水线：** 部署
**位置：** 初始化（最前置）

| 时机 | 跳转到 | 命令 |
|---|---|---|
| 部署完成，开始写作 | story-long-write / story-short-write | `/story-long-write` 或 `/story-short-write` |
| 导入已有小说做拆解 | story-import | `/story-import` |
| 需要浏览器登录态（扫榜/拆文取原文） | browser-cdp | `/browser-cdp`；generic 需平台允许本地脚本/浏览器控制 |

各端调用语法：Claude `/名`、Codex/ZCode `$名`、Antigravity 通过 `/skills` 浏览或直接点名、OpenClaw `/skill 名`、Reasonix / generic 直接点名 skill。
