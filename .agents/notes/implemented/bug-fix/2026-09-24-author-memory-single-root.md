# Agent Note: 作者记忆单书布局：书级 store 移进子目录，写后读另一级失败不再报错

Status: implemented
Date: 2026-09-24
Related: [2026-09-18-author-memory-two-level-store](../architecture/2026-09-18-author-memory-two-level-store.md)、[2026-09-18-author-memory-query-budget](2026-09-18-author-memory-query-budget.md)

## Problem

两级 store（#435）默认项目级在 `{工作区}/.story/作者记忆/`、书级在 `{书}/.story/作者记忆/`。
单书布局（`正文/`、`大纲/`、`追踪/` 直接在工作区根，story-setup 诊断与 hooks 的书根发现都支持）
下书根就是工作区，两级落到同一个 `_author-memory-state.json`：

1. 带 v0.7.10 数据时，`--book-root` 等于工作区的 `query` / `migrate` / 书级 `record` 都把
   项目级 state 当书级校验，报 `state.book must be a string`，连全局偏好也读不到。
2. 全新工作区里第一次书级 `record` 把书级 state 写进这个文件；此后所有 `query` 与项目级写入
   都报 `project-level state must not carry state.book`，工具没有任何恢复路径。真实会话里模型
   自行改了已安装脚本来绕过。

同一代码路径还有一个高危问题：`record` / `commit` 先落盘，再调 `visible_states` 读另一级 store
做预算估算；读失败（`--book-root` 不存在、`--book` 与书级记录不符、state 损坏）时整条命令
返回 `ok:false`、退出码 2，但写入已持久化。agent 据此告诉作者「没记住」，换个 `event_id`
重试就派生重复条目。

## Decision

1. **书根就是工作区时，书级 store 住子目录** `{工作区}/.story/作者记忆/书级/`（常量
   `SINGLE_ROOT_BOOK_DIR`）。判定按路径：`--book-root` 与 `--workspace` resolve 后相同。两级仍是
   两份 state、两套派生视图、两条修订线，`AP` / `BP` 路由、校验、查询合并、`migrate` 全部复用，
   只改 `book_memory_root` 这一处落点。
2. **书名默认值**：单书布局下书级 state 还不存在且没传 `--book` 时，若项目级存量 book 条目只
   指向一本书，取它的书名，否则取目录名。单书工作区的目录名常常不是书名，不这样做 `migrate`
   会按目录名找不到存量、静默迁移零条。
3. **写坏的工作区自愈**：每个命令入口 `prepare_workspace` 在单书布局下检查项目级位置上的 state
   是否带 `state.book`；是就按书级规则整份校验，`os.replace` 原子移进 `书级/`，重渲染书级视图，
   再在项目级位置写一份空 state 覆盖陈旧视图。state 内容与修订不变。`query` 也会触发这一步，
   否则读路径永远自愈不了。两处都是书级 state 时不猜，报错点名两份文件。没带 `--book-root`
   时项目级报错信息指明「带 `--book-root {工作区}` 重跑即自动归位」。
4. **写后读另一级失败降级为提醒**：`visible_states` 捕获 `AuthorMemoryError`，返回的 `warnings`
   首条注明「已写入某级 store；另一级读取失败，本次预算提醒没算上它」，命令照常 `ok:true`、
   给回执。文档要求有回执即已记住，不换 `event_id` 重试。
5. `author-memory.md` 删掉与代码不符的「跨 store 的『最近』按提交时刻比」，改为同一范围必在同一
   store、按该 store 修订号比；补单书布局与写后读失败两段说明。脚本与文档五份副本经同步脚本同步。

## Alternatives considered

**单书布局下只保留一个 state，AP / BP 条目同住、按 scope 或前缀区分。** 最强的理由：物理上
真的只有一个 store，不多一层目录，作者只看一份画像。不采用是因为 state 的 `book` 字段、
`next_item_number`、修订号、journal、`validate_state` 的前缀与 scope 归属校验、视图标题、
`migrate` 的两步提交全按「一个 state 一个 store」设计，混住要在十几处加分支；`migrate` 在同一
state 里搬条目还要重写失败窗口的幂等语义。子目录方案零改动复用这些不变式。

**照搬真实会话里模型的补丁：路径重合时按 state 有没有 `book` 字段决定它是项目级还是书级。**
最强的理由：改动最小，两行。不采用是因为它仍是一个文件：谁先写谁占位，书级占了之后项目级
条目无处可写（反之亦然），只是把报错换成了静默丢失。

**只校验、不降级：写入前先加载另一级 store，失败则整条命令零写入报错。** 最强的理由：不会
出现「写了但报错」，语义干净。不采用是因为另一级只用于预算估算，与本次写入无关；`--book-root`
写错就拒绝记下一条全局偏好，是用无关错误挡住作者的明确请求。

**自愈只放在写命令或 `migrate` 里，`query` 保持零写入。** 最强的理由：`query` 的「只读」承诺
不打折。不采用是因为日常流程里最先、最常跑的是 `query`；它不自愈，写坏的工作区就一直读不到
全局偏好，直到作者碰巧说一句「记住」。归位不改任何 state 内容，只是一次性挪位置。

## Consequences

- 单书布局可正常使用两级 store；v0.7.10 单根存量库照常 `query`、书级 `record`，`migrate`
  把存量本书条目搬进 `书级/`，书名取存量条目里的名字。
- 已被旧版写坏的工作区在下一次带 `--book-root {工作区}` 的任意命令里自愈，不丢条目。
- 代价：判定按路径，若同一目录先当单书工作区用、后来又改成多书工作区的一本书（或反过来），
  书级 store 位置会随之不同，需要作者手工挪目录；两处都有书级 state 时要人工处理。
- 代价：`query` 在写坏的单书工作区里会有一次写盘（归位），文档已注明。
- 写后读另一级失败时预算提醒可能漏算那一级，`warnings` 首条已说明；读失败本身不再让 agent
  误报「没记住」。
- 测试新增单书全新库、v0.7.10 单根库迁移、写坏库自愈、写后读另一级失败四组用例（两个测试函数），
  两个函数在旧脚本上都失败。
