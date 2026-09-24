# Agent Note: 作者记忆 store 分家：项目级与书级分置，记忆随书走

Status: implemented
Date: 2026-09-18
Issue: #435（出自 #429 评审讨论的扩展 A）
Related: [2026-09-18-author-memory-query-budget](../bug-fix/2026-09-18-author-memory-query-budget.md)、[2026-09-18-author-memory-explicit-only](../simplification/2026-09-18-author-memory-explicit-only.md)、[2026-09-24-author-memory-single-root](../bug-fix/2026-09-24-author-memory-single-root.md)（书根就是工作区时书级 store 改住 `书级/` 子目录）

## Problem

作者记忆此前是「一个工作区一份」：甲书、乙书的 book 条目和全局条目混在
`{工作区}/.story/作者记忆/` 一个 state 里。两个后果：

1. 书归档、迁移、拷去别的工作区时，这本书的偏好留在原工作区变成孤儿——单一
   工作区盒子解决不了。
2. 写入端预算提醒只能「挑最重的一本书」做最坏估算（#429 的第 5 点已把两把尺
   子对齐），写书级条目时「本书＋全局」仍是估算而不是精确计算。

书级数据住书目录是仓库既有惯例（`追踪/`、`设定/`），作者记忆是唯一例外。

## Decision

1. **两级 store**：项目级 `{工作区}/.story/作者记忆/` 只存 global / genre /
   workflow 条目，ID 前缀 `AP`；书级 `{书}/.story/作者记忆/` 只存该书 book 条目，
   ID 前缀 `BP`，state 多一个 `book` 字段记书名。两级目录结构、派生视图、事务
   格式完全相同，`validate_state` 按 store 校验前缀与 scope 归属。
2. **ID 前缀即路由键**：`decide` / `forget` 看 `item_id` 前缀，`remember` /
   `replace` 看 `scope.level`。书级操作必须传 `--book-root {书目录}`，没传直接
   报错，不会退而写进项目级——否则存量永远清不完。一份 `commit` 只写一个 store；
   `replace` 与 `conflicts_with` 不跨 store（本书例外按优先级覆盖全局，不算冲突；
   跨 store 改版拆成 `forget` ＋ `remember`）。
3. **书名以 state 为准**：首次建立取 `--book` 或目录名，之后目录改名不影响；
   `--book` 与 state 记录不一致时报错。
4. **查询＝项目级＋书级合并**：`query --book-root` 读两级，按 重要度 → 本书例外 →
   最近更新 合并装填。两个 store 的修订号互不可比，但 book 条目只来自书级、其余
   只来自项目级，同 scope 必同 store，所以「最近更新」仍按修订号比即可。不传
   `--book-root` 拿不到任何本书条目。
5. **预算提醒**：book 维度就是当前可见的书级 store，不再需要「挑最重的一本书」。
   写书级条目时「本书＋全局」因此是精确计算；写项目级条目时看不到任何书级 store，
   顺手传 `--book-root` 就把当前这本书算进去。估算与真实查询共用 `build_query_result`
   构造信封（`book_revision` 也计入）——评审复现过估算端少算附加字段导致的假阴性。`assert_no_false_negatives` 的 oracle 改为
   直接调用 `merged_query`（`command_query` 走的纯函数），不再在测试里重写一遍查询，
   否则 oracle 与估算同源、信封漂移测不出来；变异验证：估算端去掉 extra 时该测试失败。
6. **存量只迁不双读**：项目级里升级前写入的 book 条目不再参与查询与估算，也不再
   接受新的 book 写入；仍在画像里可见、可 `decide` / `forget`。`migrate --book-root`
   一次性整批搬家：断言、证据、确认次数、重要度原样保留，换 `BP` 编号，原 `AP` 标
   `superseded` 并注明去向。
   书级**每个源条目一笔事务** `migrate:APxxx`，摘要只看不可变字段（编号、类型、
   范围、断言）：评审指出若整批一个事务号且摘要含 status / evidence，中途失败后
   作者对存量条目做过 `decide` / `forget` 就会永久锁死（同号不同摘要）或重复建条
   （批次变了换号）。先写书级再写项目级，重跑时书级已有记录的复用编号只补项目级；
   失败窗口里作者对源条目的 `decide` / `forget` 不会同步到副本，由作者对副本重做。
   重跑也重写书级快照修复派生视图。与全局条目的冲突关系迁移后不再成立，这类候选退回
   `pending`。「整理作者记忆」把迁移列为默认提案项。
7. `fingerprint` 的 `scope.value` 改按 casefold 比，与 `same_scope_value`、切片归并
   同口径——书名如今来自 `--book`、目录名、state 三处，大小写不一致时不该派生第二条。
8. 调用点：story-review / story-deslop / story-short-write 的 `query` 显式传
   `--book-root`；story-long-write 入口注明带 `--book-root`。五份脚本与文档副本
   经 `sync-shared-assets.py` / `shared-references.py` 同步。

## Alternatives considered

**永久双读，不设日落。** 最强的理由：零迁移成本，老用户什么都不用做。不采用是
因为 #429 评审明确指出这条路径「最容易挂很久没人清」——只要静默兼容，迁移就永远
不会发生，孤儿问题也就永远不解决。

**兼容读＋每次点名的日落提醒（本次第一版，已撤回）。** 存量条目照常返回，`query`
在 `legacy_book_ids` 点名、每次写入 `warnings` 按书统计，直到迁完。它让升级不丢
偏好，但代价是：估算要把存量切片与书级 store 并成一片、跨 store 排序要按提交时刻
比、`migrate` 要处理失败窗口里源条目被退役的复活问题，光相容路径就多出约 150 行。
用户判断复杂度过高后撤回，改为只迁不读：升级后本书偏好要跑一次 `migrate` 才回来，
UPGRADING 明说；全局、题材、流程偏好不受影响。

**书级 store 不存 `scope.value`，靠目录定位。** 少一个冗余字段。不采用是因为
`compact_item` 是注入契约（写手要看到「本书」这个范围），且书目录改名后没有任何
地方记书名；state 多一个 `book` 字段比改契约便宜。

**跨 store 的 `replace` / `conflicts_with`。** 允许「用本书规则替换全局规则」一步
到位。不采用是因为两个 store 各自原子提交，跨 store 的引用没有一致性保证；而按
既有优先级设计，本书例外本来就不该 supersede 全局规则。

**`--book-root` 缺省时自动按 `--book` 在 `长篇/`、`短篇/` 下猜目录。** 少传一个
参数。不采用是因为书目录布局由各 skill 决定（`.active-book` 可指向任意相对路径），
脚本猜错会把记忆写进错误的目录且无声；映射由调用方传入，猜测留给 agent。

## Consequences

- 书归档、迁移、拷贝时偏好跟着书走；写书级条目时预算提醒从最坏估算变成精确计算。
- 破坏性变更：book 级 `record` / `commit` 没传 `--book-root` 直接报错；老 skill
  副本的调用点要重跑 `/story-setup` 更新。记进 CHANGELOG `Changed`。
- 存量工作区升级后本书偏好从 prompt 里消失，直到对每本书跑过 `migrate`；UPGRADING
  与 CHANGELOG 都点明了这一步。
- 写项目级条目而没传 `--book-root` 时，提醒看不到任何书级 store，可能漏报某本书
  的超编；写书级条目时会补报。文档要求正在写某本书时一律带 `--book-root`。
- `query` 载荷在带书目录时多出 `book_revision`，计入 2048 字节信封，估算端同样计入。
- `migrate` 中途失败的窗口里，作者对源条目的 `decide` / `forget` 不会同步到已建的
  副本；重跑不会锁死也不会重复建条，但副本状态要作者自己再处理一次。
- 迁移一本书会在书级 journal 留下每条一笔的事务记录；变更记录只展示最近 100 次，
  存量上百条的书会把更早的记录挤出视图（state 里仍完整）。
