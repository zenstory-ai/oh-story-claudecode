# 升级指南

## 当前版本

助手版本 38（v0.9.2）。已有项目更新技能包后，在项目根重跑 `/story-setup`（Codex 用 `$story-setup`，Antigravity 用 `/skills` 或直接点名），再新开会话。

- `setup_skill_version: 1.3.6`
- `agents_version: 38`

`.story-deployed` 字段不全，或 `agents_version` 不是整数、低于 38，都算待更新，重跑 story-setup 即可。项目里的 `agents_version` 大于 38，说明本机技能包比项目旧：先更新 oh-story-claudecode，不要用旧包覆盖。各版本改了什么见仓库根目录 `CHANGELOG.md`。

## 升级步骤

1. 更新技能包：命令行装的重跑 `npx skills add zenstory-ai/oh-story-claudecode -y -g`，插件市场或 Plugin Management 装的在面板里更新。
2. 在写作项目根重跑 `/story-setup`（Codex 用 `$story-setup`）。
3. 新开会话，让新的助手和 hook 生效；Codex 提示要信任 hook 时，在 `/hooks` 里信任一下。
4. 正在写的长篇：确认每本书有 `追踪/_tracking-state.json`。没有就按下方「追踪模型迁移」重建，否则写下一章会被拦。
5. 拆文成果或细纲不满足当前格式时，按检查提示定点补齐，不因单项缺口整本重拆。

## 本次更新必须重跑 story-setup（v0.9.2，助手版本 38）

- 新增发布资料技能 `story-publish`。重跑 story-setup 后，项目里才会有这个技能（OpenClaw、Reasonix、通用模式复制到项目 `skills/`）、项目指令里的「发布资料」入口，以及 OpenCode、ZCode 的 `/story-publish` 命令。
- 书稿、设定、追踪和作者记忆不用迁移。

## v0.9.1 升级说明（助手版本 37）

- 更新技能包后重跑 story-setup，并新开会话，让新版助手与 hook 生效。
- ZCode 用户须先更新并启用 `oh-story` 插件，再从**更新后的插件副本**运行 story-setup，覆盖项目 `.zcode/skills` 快照；不要用项目里的旧 story-setup 重部署。独立安装的 Skills 不会注册插件角色。
- ZCode 若仍命中项目旧快照，先把受管目录 `.zcode/skills/story-setup` 移出 `.zcode/skills` 留作备份，再从新版插件运行 story-setup；部署完成后该目录由新版重新生成。不必删除其他项目 Skills。
- Windows 用户重跑后会刷新项目 hook，避免继续使用旧版入口。

## v0.9.0 升级说明（助手版本 36）

- 写手、架构师、角色设计、一致性检查、查资料、资料研究这些助手的模板都改了。参考资料包里的排纲、开篇、人物、题材和情绪方法按使用环节重新整理，删掉了重复和过时的几份；写手读的技法与去 AI 味方法对齐。不重跑的话，项目里的旧助手会去找已经删掉的资料。
- 项目指令（`CLAUDE.md`、`AGENTS.md`）改成每个编程工具一个管理块，从 `<!-- oh-story:{工具} 开始` 到 `<!-- oh-story:{工具} 结束 -->`。第一次重跑会把旧版 oh-story 写进去的段落换成管理块，你自己写的段落留在块外；以后重跑只替换块里的内容。几个工具共用 `AGENTS.md` 时各占一块，互不覆盖。
- Claude Code 的 `.claude/rules/` 去掉了和写作流程打架的写死条目（章首、章尾钩子必须从固定类型里选、每章必须有情绪变化、固定段数和字数的警戒线），卷纲、细纲字段改以写作流程的模板为准，旧细纲缺字段照旧不拦。
- 一致性检查和查资料助手也能处理短篇项目（`设定.md`、`小节大纲.md`、`正文.md`）。资料研究助手发现浏览器调试端口没开时，把情况交回主会话，由主会话问你要不要启动浏览器。
- 书稿、设定、大纲、追踪和作者记忆的数据格式不变，不用迁移。
- 之前导入的长篇，卷纲里的剧情单元是一张表，写正文时无法按单元读取这些旧单元。续写新章不受影响：写第 N 章会先按单元卡写法补上新单元。要重写导入时的旧章，先让 `/story-long-write` 把那一卷的旧单元改写成单元卡。

## 从 v0.8.5 及更早升上来

重跑一次 story-setup 就会装上当前版本，中间版本不用逐个补。下面是写书时会碰到的变化：

- 长篇写后检查需要 Node.js 18+：缺 Node 时这一章不能提交，装好后重跑检查。长篇拆文需要 Python 3。
- 改已经提交过的章，写作流程会先生成这一章的修订草稿再提交，不直接改追踪文件。
- 细纲可以加一行「字数范围：2000-2600」，填入你给的范围；没写就按默认上下浮动。老细纲、老卷纲照常可用，排纲时才按新格式补。
- 写正文前细纲不能是空壳（去掉 `#` 号和空白不到 30 字会被拦）；标了 `<!-- 去味:跳过 -->` 的章不会因为这行标记被判有问题。
- 扫榜每次写进 `扫榜/{日期}/` 新目录，旧目录不用动。
- 换了编程工具后重跑 story-setup，会问你要不要把当前工具一起装上。
- 项目里旧的 `.claude/agent-memory/` 不再使用，可以删掉。

## OpenCode 只支持 2.x（v0.7.11）

OpenCode 2.0 起发布在 npm 包 `@opencode/cli`（`opencode-ai` 停在 1.x）。本适配只支持 2.x：1.x 的插件 loader 读不了新版 `story-hooks.ts`，在 1.x 上会没有写正文守卫与写后兜底；1.x 也不认 agents 的 `permissions:` 规则，只读 agent 会失去权限限制。story-setup 在版本是 1.x 或无法确定时停止部署。

1. 升级 OpenCode：先卸载旧包 `npm rm -g opencode-ai`，再 `npm i -g @opencode/cli`（或 `curl -fsSL https://opencode.ai/v2/install | bash`），确认 `opencode --version` 为 2.x。两个包都提供 `opencode` 命令，不先卸载旧包时 PATH 上可能仍是 1.x。
2. 更新技能包后，在写作项目根重跑 story-setup：替换 `.opencode/plugins/story-hooks.ts` 与 `.opencode/agents/`（改为 2.x 原生 `permissions:` 规则列表，已配的 `model:` 会保留），并从 `opencode.json` / `opencode.jsonc` 删除旧的 story-hooks 插件注册。

## 插件打包身份迁移（v0.7.9 同版本修复）

Claude Code / ZCode 市场改为单一 `oh-story` 插件，仍包含全部 13 个 Skills。该迁移始于 v0.7.9 的同版本修复，仍使用旧插件身份的用户需手动迁移；`npx skills` 安装无需迁移。卸载前备份要保留的插件数据，以下操作仅针对旧插件记录，保留写作项目及 story-setup 部署文件。

### Claude Code

1. 先在受影响的写作项目目录中列出已安装插件，按记录中的 `id` 与 `scope` 核对实际旧身份；`project` / `local` 记录属于各自项目，多个项目须分别核对：

   ```bash
   claude plugin list --json
   ```

   只处理列表中确实存在、marketplace 为 `oh-story-skills` 的以下旧 ID：

   ```text
   browser-cdp@oh-story-skills
   story@oh-story-skills
   story-cover@oh-story-skills
   story-deslop@oh-story-skills
   story-import@oh-story-skills
   story-long-analyze@oh-story-skills
   story-long-scan@oh-story-skills
   story-long-write@oh-story-skills
   story-review@oh-story-skills
   story-setup@oh-story-skills
   story-short-analyze@oh-story-skills
   story-short-scan@oh-story-skills
   story-short-write@oh-story-skills
   ```

2. **刷新 catalog 前**，逐个卸载实际存在的旧 ID，并使用列表中原有的 `user`、`project` 或 `local` scope。以下以 user-scope 的 `story` 插件为例：

   ```bash
   claude plugin uninstall story@oh-story-skills --scope user --keep-data
   ```

   `--keep-data` 保留该旧插件身份的数据，但不会把它迁移到新的 `oh-story` 身份。同一旧 ID 若出现在多个 scope，每个 scope 分别执行。

3. 所有实际旧身份卸载完后，刷新已有 catalog；若本机尚未添加该 catalog，则添加仓库：

   ```bash
   claude plugin marketplace update oh-story-skills
   # 仅在 catalog 尚不存在时：
   claude plugin marketplace add https://github.com/zenstory-ai/oh-story-claudecode
   ```

4. 在原 scope 安装统一 bundle；多个 scope 分别安装：

   ```bash
   claude plugin install oh-story@oh-story-skills --scope user
   ```

5. 新开 Claude Code 会话，使用 `/oh-story:story-setup` 或 `/oh-story:story dashboard`。命令与 manifest 格式见 [Claude Code 插件参考](https://code.claude.com/docs/en/plugins-reference)。

### ZCode

在 Plugin Management 中卸载受影响的旧条目，刷新市场；必要时重新添加本仓库，再安装一个 `oh-story`。沿用界面中的市场名（`oh-story-skills` 或 `oh-story-zcode`），避免重复安装。若无法卸载，保留数据备份，附 ZCode 版本与界面现象联系官方支持，不要清空全部缓存或手改缓存 JSON。操作说明见 [ZCode 插件文档](https://zcode.z.ai/en/docs/plugin)。

## 项目里多出的嵌套目录

旧版部署可能在项目里留下嵌套目录：`agent-references/agent-references/`（可能多层）或 `skills/story-setup/skills/`，严重时会撑满磁盘。新版部署会拒绝这种复制并自动删掉残留。

OpenClaw、Reasonix 和通用模式把 skill 放在项目 `skills/` 里，重跑时执行的是项目里那份旧 skill，无法自动清理：先手动删掉上面两类目录，再用更新后的技能包覆盖项目 `skills/` 下的 14 个目录。

## 追踪模型迁移（v0.7.2 及更早的长篇项目必读）

长篇追踪以 `追踪/_tracking-state.json` 为准，由写作流程的提交工具统一写入；续写状态卡、逐章记录、角色快照、伏笔表和两份时间线都由工具整份生成，不手改。

判断与后果：

| 情况 | 表现 |
|------|------|
| `追踪/_tracking-state.json` 存在且 `check` 通过 | 正常，无需处理 |
| 缺 `_tracking-state.json` 但已有正文 | 日更停止；Claude Code、Codex、OpenCode、ZCode、Antigravity 上写正文会被 hook 直接拦下，其他工具由写作流程自己停下 |
| 存在但派生视图被手改 | `check` 报 `derived view differs from _tracking-state.json` |

迁移**不需要重跑全书拆解**：正文、`设定/`、`大纲/`、`拆文库/` 都不受影响，只重建 `追踪/`。执行 `/story-import` 的「旧追踪项目迁移」——数出最后完整章号 `N`，从旧追踪文件与最近几章正文重建当前状态，构造 `last_chapter=N` 的初始化事务跑 `tracking_commit.py init`。旧追踪结构会被按原样整体移入 `追踪/_旧追踪存档/`，不删除、不参与解析。

退役结构：`_tracking-meta.json`、`时间线/事件库.json` 及更早追踪文件不再被解析，`commit` 与 `check` 遇到会直接拒绝。

之后写作时，追踪只通过写作流程提交；生成文件被手改后，用该章的修订提交整份重建。

## 作者记忆两级存储迁移（v0.7.11 之前的项目）

作者记忆从「一个工作区一份」改成两级：工作区 `.story/作者记忆/` 只存全局、题材、流程条目（编号 `AP`），每本书目录下的 `.story/作者记忆/` 存这本书的条目（编号 `BP`），记忆随书归档、迁移。同时不再从反复修改或成稿推断偏好：`record` 拒绝 `repeated_correction` / `inferred_pattern` 来源，存量条目照常可读、可确认、可退役。

下方命令中的 `{所用写作 skill 根}` 指 `story-long-write` 或 `story-short-write` 的安装目录。

迁移时按以下三点处理：

1. 新的本书偏好必须传 `--book-root {书目录}` 才能写入；旧 skill 副本没带这个参数会报错，重跑 `/story-setup` 让脚本与文档同版。
2. 升级前写进工作区的本书条目**不再被 `query` 返回**（全局、题材、流程条目不受影响），直到搬进书目录；它们仍在工作区 `作者画像.md` 里可见。
3. 对每本书运行一次即可整批搬家，幂等、中途失败直接重跑：

   ```text
   {PYTHON} {所用写作 skill 根}/scripts/author_memory_commit.py migrate --workspace {工作区} --book-root {工作区}/长篇/{书名}
   ```

   断言、原话证据、确认次数、重要度原样保留；与全局条目的冲突候选在迁移后退回待确认。也可以对 agent 说「整理作者记忆」，迁移会列为默认提案项。

**单书布局**（`正文/`、`追踪/` 直接在工作区根）：书级数据存储在 `{工作区}/.story/作者记忆/书级/`，迁移时 `--book-root` 就传工作区本身：

   ```text
   {PYTHON} {所用写作 skill 根}/scripts/author_memory_commit.py migrate --workspace {工作区} --book-root {工作区}
   ```

书名默认取存量本书条目里的书名；存量里有多本书的条目时用 `--book {书名}` 指定。用过 main 上预发布版本、查询时报 `project-level state must not carry state.book` 的工作区，带 `--book-root {工作区}` 运行任一命令即自动修复，不丢条目。

## 长篇拆文旧成果（v0.7.10 及更早拆的书）

- v0.7.10 及更早的拆文库如果原文以楔子/序章开头，续拆会先停下询问（旧版不认楔子，直接续跑会错一章）。只拆到黄金三章的库选「楔子单独成章重拆」代价最小；已有逐章摘要的库推荐「楔子并入第一章，按旧章号继续」。
- `拆文报告.md` 小节结构变了（去掉「质量评估」，「证据边界与待核事项」改为「还不确定的地方」），旧报告不会自动改写，重跑 Stage 5 才生效。
- 人物关系图改为 `人物关系图/人物关系图.md`（文字清单保留中文，支持 Mermaid 的查看器可显示关系图），有中文字体时另出 PNG；以前生成的拼音版 PNG 不会自动删除，可手动删掉。
- 拆文进度文件 `_progress.md` 只认 `schema_version: 2`；更早格式的进度文件不能续拆，按提示从头拆。

## 导入项目的自对标清理

旧版 `story-import` 可能把作者自己的导入书误建成 `对标/{当前书名}/`，甚至把本书设定登记成“主对标”。升级不会自动删除用户文件，按以下边界人工核对：

1. 保留 `拆文库/{导入书名}/`；它是本书导入分析和重建工程的数据源，不是错误目录。
2. 以项目根 `设定/` 为本书正式设定。若 `对标/{当前书名}/` 的内容确认只是从本书 `设定/` 或 `拆文库/{导入书名}/` 复制而来，且没有人工补充，再删除这个误建目录。
3. 清理 `设定/题材定位.md` 中把当前书登记为主/副对标的字段；真实外部对标登记不动。
4. 若某个 `对标/{外部书名}/` 目录名看似外部作品，但内容实际来自当前书，删除这份错误视图，再从真正的 `拆文库/{对标书名}/` 重新同步；不要改名冒充修复。
5. 重新运行 `/story-setup`（Codex 用 `$story-setup`）并新开会话，让当前助手模板生效。
