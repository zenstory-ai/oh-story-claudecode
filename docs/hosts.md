# 各编程 Agent 的部署与安装排查

[English](hosts_EN.md)

Oh Story 支持 8 款编程 Agent。本页是各 Agent 的部署细节、已知限制和安装排查；
日常使用只需 README 的[安装](../README.md#安装)一节。

## 安装排查：Windows 报错、环境检查、marketplace 路径

Windows 上偶尔会看到 `ENOENT ... mkdir` 报错但末尾仍显示 `Done!`，这是有技能没装全。story-setup 的参考资料目录整个缺了一块时，跑 `/story-setup` 会提示参考资料包不完整；其它形式的残缺不一定有提示。无论有没有报错，重跑同一条安装命令即可修复。

排查已安装环境时，向 Agent 说「用 story-setup 检查写作环境」，或给 story-setup 传入 `check` 参数。它按目标 CLI 的部署清单检查并给出处理建议；仅检查不会改动项目，需要修复时仍走原来的 setup 流程。

这条 `npx skills` 独立安装路径不经过 Claude Code 或 ZCode marketplace，不受下方插件打包身份调整影响。

## Claude Code

marketplace 名保持 `oh-story-skills`，其中现在只有一个 `oh-story` bundle，由 Claude Code 从仓库根自动发现全部 13 个 Skills：

```bash
claude plugin marketplace add https://github.com/zenstory-ai/oh-story-claudecode
claude plugin install oh-story@oh-story-skills
```

安装后使用 `/oh-story:story-setup`、`/oh-story:story dashboard` 等命令。旧插件用户按[升级指南](../skills/story-setup/UPGRADING.md#插件打包身份迁移v079-同版本修复)迁移；该身份迁移始于 v0.7.9 的同版本修复；仍使用旧插件身份的用户需主动刷新市场并重装。命令详见 [Claude Code 插件参考](https://code.claude.com/docs/en/plugins-reference)。

## Antigravity

先用 `/skills` 或自然语言运行 `story-setup`，选择 `target_cli=antigravity`。它只在当前写作项目创建/更新 13 个 `.agents/skills/` 已知目录、7 个 `.agents/agents/agent-name/agent.md` 已知定义（`agent-name` 替换为实际名称）、`.agents/rules/oh-story.md`、两个 `.agents/hooks/` runtime 文件与 `.agents/hooks.json` 的 `oh-story` 管理组；其他用户 Skills、Agents、Rules、Hooks 和 hook groups 都保留，部署器本身不会写 `~/.gemini/`。项目内 Skills 使用真实目录；若 `.agents/skills` 已是 symlink，会先解释 git diff 并征求明确迁移同意，未同意绝不沿链接写入。Hook 依赖 PATH 中的 `node`；部署后新开 conversation，再分别在 IDE 与交互式 `agy` 中 smoke test。命令行写作可从项目目录启动交互式 `agy`，确认 `/skills`、`/agents`、`/hooks` 已发现 oh-story 后再发任务。**print 模式（`agy -p`）必须带 `--add-dir "$PWD"`**：实测 agy 1.2.10 带上它会加载工作区 `.agents/`（13 个 skills、7 个 agents 与 hooks），不带则一个都不加载，skill 回退、甚至把普通模型输出写到 `~/.gemini/antigravity-cli/scratch/`。测试后检查 scratch 没有意外小说产物。

## Codex

repo 内直接使用：Codex 会扫描 `$REPO_ROOT/.agents/skills`（指向 `skills/` 的 symlink）发现 13 个 skill；用 `$story`、`$story-setup` 或 `/skills` 调用。Windows 上 git 需开 `core.symlinks=true`，否则 symlink 失效，改走下方 `$story-setup` 部署。

跑 `$story-setup` 部署到写作项目后，会写入 `.codex/agents/*.toml`、`.codex/hooks.json`、`.codex/hooks/{story_codex_hook.py,run-story-hook.sh,run-story-hook.cmd}` 和 `.codex/skills/story-setup/references/agent-references/`；请信任项目 `.codex/` 配置层并在 `/hooks` review/trust hooks、新开 Codex 会话，让 custom agents 生效。**在 `/hooks` 信任之前，Codex 会静默跳过这些 hooks，包括写正文前的大纲守卫**，不报错也不提示；自动化里的 `codex exec` 可加 `--dangerously-bypass-hook-trust`。

## ZCode

在 Plugin Management 中添加本仓库，安装 `oh-story`，即可调用全部 13 个 Skills/Commands。市场名可能显示 `oh-story-zcode`（根 catalog）或 `oh-story-skills`（Claude catalog）；选择其中一个即可，内容相同。旧版多条目安装按[升级指南](../skills/story-setup/UPGRADING.md#插件打包身份迁移v079-同版本修复)迁移。`$story-setup` 选择 `target_cli=zcode` 会部署 `.zcode/skills/`、`.zcode/commands/`、`.zcode/hooks/story_zcode_hook.js`，安全合并 `.zcode/config.json` 与根 `AGENTS.md`；Hook 依赖 PATH 中的 `node`。ZCode 3.3.4 不执行项目/plugin custom agents，也没有 `PreCompact` / `SessionEnd`，相关流程会明确降级 solo/direct，compact 后由 `SessionStart` 恢复上下文。插件格式见 [ZCode 官方文档](https://zcode.z.ai/en/docs/plugin)。

## OpenCode

需要 **OpenCode 2.x**（`curl -fsSL https://opencode.ai/v2/install | bash` 或 `npm i -g @opencode/cli`）；1.x 加载不了写正文守卫插件，story-setup 会拦下并提示升级，已按 1.x 部署过的项目升级后重跑 story-setup。全局安装后 opencode 自动从 `~/.claude/skills/` 发现 skills；首次用自然语言触发 story-setup（如「用 story-setup 部署网文写作环境」），部署后 slash command 自动加载，没出现就运行 `opencode reload`。部分 hook 行为与 Claude Code 有差异（session-start / session-end / compact 等），详见 [CONTRIBUTING.md](../CONTRIBUTING.md) 的 OpenCode 章节。

## OpenClaw

当前支持 skills-only：OpenClaw 可从 workspace `skills/`、`.agents/skills`、`~/.agents/skills`、`~/.openclaw/skills` 等 skill root 发现本项目 13 个 skill；`SKILL.md` 已按 OpenClaw 要求使用单行 `name` / `description` 与单行 JSON `metadata.openclaw`。`story-setup` 选择 `target_cli=openclaw` 时会把 skills 复制到项目 `skills/` 并写入 OpenClaw 版 `AGENTS.md`；agents/hooks 暂不部署，写正文前大纲守卫在 OpenClaw 下是 skill 内软约束。部署后如未显示新 skills，请新开 OpenClaw session 或等待 watcher 刷新。

## Reasonix

当前支持 skills + 原生 plugin manifest：Reasonix 原生扫描项目 skill root（`.agents/skills` 等，指向 `skills/` 的 symlink）发现 13 个 skill，用 `reasonix doctor capabilities` 校验；也可用根 `reasonix-plugin.json` 走 `reasonix plugin install`。`story-setup` 选择 `target_cli=reasonix` 时会把 skills 复制到项目 `skills/` 并写入 Reasonix 版 `AGENTS.md`；hooks/custom agents 暂不部署，涉及专业 Agent 的 skill 走 solo/direct fallback。Windows 未启用 symlink 时改走原生 plugin。

## Web AI / 通用 Agent

平台能读取 GitHub 仓库或项目文件时，可让 Agent 读取 `skills/*/SKILL.md` 与对应 `references/`；需要本地副本时，`story-setup` 可选 `target_cli=generic`，只写通用 `AGENTS.md` 和 `skills/`。无本项目 hooks/custom agents 的环境按 skill 内软约束或 solo/direct fallback 执行。

**OpenClaw / Reasonix / 通用路径的目录残留要手动清：** 这三条路径的 skill 副本在项目 `skills/` 里，重跑 `/story-setup` 执行的就是项目里那份，自动清理到不了。项目里若出现 `skills/story-setup/references/agent-references/agent-references/`（可能嵌了多层）或 `skills/story-setup/skills/`，手动删掉。要让项目里的 skill 文本本身更新，还需要重新安装本项目后，用新包覆盖项目 `skills/` 下这 13 个目录。

升级后如果项目里已经跑过 `/story-setup`，建议在项目根重跑一次 `/story-setup`，同步 hooks / agents / references。每版变更见 [CHANGELOG.md](../CHANGELOG.md) 与 [Releases](https://github.com/zenstory-ai/oh-story-claudecode/releases)。

**多 agent 协作要先部署再新开会话：** 7 个专业 agent（story-architect、narrative-writer、consistency-checker 等）由 `/story-setup` 写入项目 `.claude/agents/`，由 `$story-setup` 写入 `.codex/agents/*.toml`，或由 Antigravity `story-setup` 生成 `.agents/agents/agent-name/agent.md`（`agent-name` 替换为实际名称）。Antigravity 使用 `invoke_subagent` + 同名 `TypeName`；运行时未暴露 custom subagent 时按 skill 明确降级 solo/direct。判断是否生效：新会话里跑 `/story-review`，报告开头「这次怎么审的」写着几个视角（完整审或精简审）即注册成功；写着「我一个人审」说明还在旧会话，或当前运行时未暴露该 agent。

**导入续写顺序：** 推荐先在写作项目根运行 `/story-setup`（部署 hooks/agents/AGENTS），新开/刷新会话后运行 `/story-import` 导入已有小说，再用 `/story-long-write 日更` 或 `/story-long-write 写第N章` 续写。也可以直接运行 `/story-import`；它会先检测是否已 setup，未部署时让你选择先去 setup 或继续串行导入。

**作者习惯会跨会话延续：** 对 `/story` 说“记住我的写作习惯”（部署后的项目里直接说「记住：……」也会走这里，不进编程工具自带的记忆）。作者记忆分两级：全局、题材、流程类偏好进工作区 `.story/作者记忆/`（编号 `AP`），只属于某本书的偏好进该书目录下的 `.story/作者记忆/`（编号 `BP`），随书归档、迁移；看到 `Author Memory Receipt` 才算写入成功。普通写作只查询本次相关的已确认条目，输出硬上限 2KB，不把完整画像、候选和历史塞进正文 prompt。它与每本书的剧情追踪分开，当前要求、本书设定和硬性门禁始终优先。
