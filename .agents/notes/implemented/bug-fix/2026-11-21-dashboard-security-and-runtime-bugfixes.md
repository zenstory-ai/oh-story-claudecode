# Agent Note: 修复 Dashboard 目录边界、Hook 书目发现、运行时并发与守卫契约缺陷

Status: implemented

## Problem

在完成三轮代码与契约审计后，确认了一批跨模块真实缺陷，直接影响工作区安全边界、状态落盘一致性、错误可观测性与仓库守卫有效性：

1. **Dashboard 路径边界漏放隐藏目录**：`skills/story/scripts/dashboard-server.mjs` 虽在目录树遍历时跳过隐藏目录，但 `resolveWorkspacePath` 与 `resolveWorkspaceDirectory` 未拦截 `.claude/`、`.codex/`、`.omc/`、`.git/` 或经符号链接指向隐藏父目录的直接读写请求，且 `withSerializedFileMutation` 以未规范化路径作为并发锁键；前端 `app.js` 亦存在行内代码被斜体/粗体正则破坏、删除竞态及换行符显示未随文件更新等问题。
2. **五端 Hook 书目发现误扫参考目录**：`story_hook_core.js` 的 `discoverActiveBook` 与 `discoverAllBooks` 会把 `拆文库/`、`对标/` 中的项目结构误判为作者正在写的书，干扰会话状态提醒与自动追踪。
3. **跨进程状态写入与异常退出静默吞错**：
   - `author_memory_commit.js`（长短篇共用）并发写入缺少跨进程文件锁，并行 `init`/`commit`/`record`/`migrate` 存在覆写竞态。
   - `storyctl.js` 调用 `check-outline-copy.js` 时把所有非零退出码一律按抄纲告警处理，工具自身崩溃（退出码 2 或异常中断）被误判为内容告警而非 `tool_unavailable`。
   - `tracking_commit.js` 草稿事务写 `tracking.json` 未走原子写入，且未匹配补零细纲文件名；`manage_analysis_run.js` 扫描补零章节摘要失败；`normalize-punctuation.js` 在引号模式误伤 HTML 注释与白名单片段且 `curly` 模式未跨行保持引号栈；`aggregate-rank.js` `--sample` 遗漏 `section` 字段；`generate-antigravity-agents.mjs` 存在失效替换且漂移时静默跳过；`scripts/bench/metrics.py` 的 `check_status` 未兼容 `--plain` 文本输出。
4. **`shared-references.py` 未校验 `derived_groups`**：`scripts/shared-references.json` 中的派生组缺少模式校验与磁盘成员存在性检查，漂移或配置错误不会被 CI 拦截。
5. **ClawHub 清单依赖缺项**：`story-short-scan` 与 `story-long-scan` 同样可选依赖 `browser-cdp`，但 `.clawhub/publish.json` 中缺失 `"optional-skill:browser-cdp"`。

## Decision

- **Dashboard 隐藏目录与并发边界收口**：在 `dashboard-server.mjs` 的 `resolveWorkspacePath` 与 `resolveWorkspaceDirectory` 中，对候选路径与 `realpath` 双向调用 `hasIgnoredDirectorySegment(realRoot, targetDir)`（过滤空段与 `"."`，放行 `./book` 与 `.story`，以 `403 directory_hidden` 拒绝隐藏目录及其符号链接目标）；`withSerializedFileMutation` 统一使用规范化后的 `resolvedFile` 作为锁键。前端 `app.js` 在 `inlineMarkdown()` 中先行暂存行内代码片段，在删除期间阻止 `openFile()` 竞态并用当前文件判定保护清理，同时依据 `file.eol` 同步更新编码与换行符标签。
- **Hook 书目发现排除参考库**：在 `story_hook_core.js` 的 `findFirst`（`discoverActiveBook`）与 `discoverAllBooks` 中显式跳过 `拆文库` 与 `对标`，并经 `sync-shared-assets.py sync` 同步至全部 5 端副本。
- **运行时容错与并发保护**：
  - `author_memory_commit.js` 引入基于 `O_CREAT|O_EXCL` 锁文件与 `Atomics.wait` 轮询的 `withStoreWriteLock`，覆盖 `init`/`commit`/`record`/`migrate` 写路径，并保证无变更或未初始化报错路径不会误建目录；同步至 `story-short-write`。
  - `storyctl.js` 仅把 `check-outline-copy.js` 的 `status === 1` 映射为 `OUTLINE_COPY_REVIEW`，其余非零或 `null` 退出码记入 `toolErrors`（`TOOL_ERROR`）并触发 `tool_unavailable`（退出码 3）。
  - 补齐 `manage_analysis_run.js` 补零章节摘要读取、`tracking_commit.js` 原子写入与 `^细纲_第0*${chapter}章` 匹配、`build_writer_prompt.js` 补零重名排除、`build_architect_brief.js` 卷纲正则统一、`normalize-punctuation.js` HTML 注释/白名单屏蔽与 `curly` 跨行栈、`aggregate-rank.js` `section` 字段回填、`metrics.py` `--plain` 文本回退解析及 `generate-antigravity-agents.mjs` `replaceRequired()` fail-loud 守卫。
- **守卫脚本与文档/清单同步**：`scripts/shared-references.py` 对 `derived_groups` 校验结构、`reason` 非空、成员数 >= 2 且在仓库根内、Markdown/runtime 域约束、与 `groups`/`tree_groups` 互斥及磁盘文件存在。同步修正 `story-setup` 升级指引、七端适配模板与文档预算倒挂项，并更新 `.clawhub/publish.json` 中 `story-short-scan` 依赖与本次改动技能的 patch 版本、伴随版本钉住及 `packageDigest`。

## Alternatives considered

- **Dashboard 仅在路由层做字符串前缀黑名单**：改动更小，但无法拦截 `..` 折叠或符号链接指向隐藏目录的绕过路径，也容易误伤 `./book` 相对路径，因此改在解析层对候选路径与 `realpath` 双向校验目录段。
- **`author_memory_commit.js` 引入第三方文件锁依赖（如 `proper-lockfile`）**：接口现成，但违背套件运行时零第三方依赖原则，跨端安装复杂度高；改用 Node.js 原生 `fs.openSync(..., 'wx')` + `Atomics.wait` 实现零依赖互斥锁。
- **`storyctl.js` 将所有 `check-outline-copy.js` 非零退出统一按 `TOOL_ERROR` 处理**：无法区分正常的抄纲命中（退出码 1）与脚本崩溃（退出码 2），会阻断正常修订流程；因此精确按退出码分流。
- **在 `story_hook_core.js` 靠配置白名单指定书目目录**：避免硬编码排除名，但用户工作区书目名自由变化，维护白名单反而破坏零配置体验；排除固定的 `拆文库` 与 `对标` 目录即可准确覆盖仓库约定。

## Consequences

- **收益**：Dashboard API 杜绝通过直接路径或符号链接越权读写隐藏配置目录；五端 Hook 不再被拆文/对标目录干扰；`author_memory_commit.js` 与 `tracking_commit.js` 降低并发与中断损坏风险；`storyctl.js`、`generate-antigravity-agents.mjs` 与 `shared-references.py` 均改为显式暴露故障，避免静默漂移；全部修复均附带独立回归测试。
- **代价**：Dashboard 对工作区内自定义点号前缀目录（`.story` 除外）均返回 `403 directory_hidden`；`author_memory_commit.js` 高并发写入时可能触发短暂锁等待；`shared-references.json` 新增或修改 `derived_groups` 时须提供完整 `reason` 与存在的成员文件。
