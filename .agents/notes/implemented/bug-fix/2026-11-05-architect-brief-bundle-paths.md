# Agent Note: story-architect 任务包的包外读物走 agent 副本

Status: implemented

## Problem

`build_architect_brief.py` 给「按条件可读」写 `story-long-write/references` 的绝对路径，而 story-architect 的路径规则只允许读 `story-setup/references/agent-references`。`cross-book-recall.md` 又不在副本里，对标登记 ≥2 本的书出纲时 agent 只能停下（#522）。

## Decision

`cross-book-recall.md` 登记进 `shared-references.json`，副本与源字节相同。任务包写 `agent-references/{文件名}`，由各端 agent 按自己的路径规则解析。副本里不再点名 `benchmark-recall.md`：主对标取法写进文件；包外清单说明没列的参考不用找、对标资料缺了就停下，`gaps.*` 写进「要作者定的事」。

## Alternatives considered

- 在 agent 模板里开例外，允许读任务包点名的绝对路径：不用多一份副本，新增读物也自动可用。但全局安装时路径在项目外，会碰上宿主的权限确认，还要重新生成全部适配层。
- 同时给主会话留绝对路径：主会话自己做时不读任务包（走 SKILL.md 读取表），这条路径没有读者。

## Consequences

多一份要保持同步的副本，由 `check-shared-files.sh` 守卫；测试断言任务包点名的文件都在副本里。已部署项目要等发版抬 `agents_version` 并重新部署才拿到副本。
