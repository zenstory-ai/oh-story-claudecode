# Agent Note: 静态守卫每条契约只留一个 owner

Status: implemented

## Problem

一轮只读测试审计发现静态文档/结构守卫里有三类冗余：同一条规则跑两遍（作者报告黑话规则在 `static-check.py` 与 `check-author-reports.py` 各扫一次）；已有更强 owner 的 grep（`check-story-setup-deployment.sh` TS10 重复 grep session-start 版本阈值、story-review 版本提示、frontmatter version、story-explorer legacy 分支，以及生成出来的 OpenCode/Codex narrative-writer 副本）；只钉措辞或拷贝数量、跑起来不会坏的断言（Reference Gate 逐字句子、demo 细纲数 21、references 子目录数 9、部署清单的非关键列名、已无内嵌 python 的 hook stdout 守卫）。改一个词或加一个目录就红，维护成本不换来行为保护。

## Decision

- 作者报告规则只由 `scripts/check-author-reports.py` 守卫；长篇四个 workflow 的模板在位与最少块数并入它的 `REQUIRED`（setup 1、chapter 4、daily 1、revision 1）。`static-check.py` 不再加载该规则，`test-static-check.py` 删两条重复用例。
- TS10 只留 owner 管不到的锚点：session-start 新旧版本分支由 TS5 真实执行覆盖；story-review 预检、setup frontmatter version、legacy 分支由 `check-current-skill-contracts.py` 覆盖；narrative-writer 字数规则只锚源模板，生成副本由 `check-opencode-adapter.sh` / `check-codex-adapter.sh` 的同步与确定性检查保证。
- references 子目录的「== 9」改为反向核对：Phase 1 自检名单里的每个目录都真实存在（正向「每个目录都在名单里」原本就有）。
- TS2 只保留 `Source path` / `Target path` 两个表头断言：自复制探测器靠它们认出部署清单表，表头改名会让清单行检查静默空转。其余列名断言删除。
- 契约检查删 `stage0-toc-block-removal`（目录块剔除由 `build_chapter_index.py` 执行，`test-long-analyze-runtime-refactor.py` 的带目录原文用例覆盖）、`chapter-boundary-table`（#438 后边界在 `chapter_index.csv`）、`expected_demo_outline_count` 与 `demo-outline-count`；`demo-outline-section` 在一份细纲都找不到时直接报错，防空转。`test_manifest_contract` 去掉与 CI 步骤重复的「manifest 与仓库一致」。
- `check-reference-gates.js` 只锚门禁首屏行位、reference 路由、Constraint Lock 与短篇交付预检的命令/参数/顺序（#418）。
- `check-python-invocation.sh` 删 hook 内嵌 python stdout 守卫（#243 起 hook 走 node 核）。

每条删除前都做过一次变异：改坏 owner，确认保留下来的守卫变红，再还原。

## Alternatives considered

- **保留两处作者报告扫描**——最强理由：`static-check.sh` 是本地最常跑的入口，顺带扫一遍能更早发现。否：两处用同一份规则，只是同一契约执行两遍；CI 两个都跑，本地清单也已列出 `check-author-reports.py`。
- **把 `stage0-chapter-table-validation` 一并删掉**——最强理由：它同样只是文字锚点。否：变异显示把 `validate_numbering` 改成空函数时运行时测试全绿，章号连续性校验没有运行时回归，删了就一点网都没有；等运行时车道补上断号/重号用例再删。
- **TS2 列名断言全删**——否：见上，`Source path` / `Target path` 是自复制探测器的定位锚，变异证实表头改名后含自复制行的清单也能通过。

## Consequences

- **收益**：改措辞、加 references 目录、改 demo 细纲数量不再让守卫红；每条行为只有一个失败点，失败信息指向真正的 owner。
- **代价**：`static-check.sh` 单独跑时不再报作者报告问题，要同时跑 `check-author-reports.py`；Reference Gate 里被删的句子（完整读取、repair 轮数等）不再有 CI 兜底，只靠真实写作评测与人审；章号连续性校验仍缺运行时回归（已记为后续）。

## Verification

`bash scripts/static-check.sh`；`python3 scripts/test-static-check.py`；`python3 scripts/check-author-reports.py --self-test && python3 scripts/check-author-reports.py`；`bash scripts/check-current-skill-contracts.sh`；`python3 scripts/test-current-skill-contracts.py`；`node scripts/check-reference-gates.js`；`bash scripts/check-python-invocation.sh`；`python3 scripts/test-plugin-packaging.py`；`bash scripts/check-story-setup-deployment.sh`。
