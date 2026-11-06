# story-review：审查收尾的追踪文件维护

追踪维护通过本 skill 的 `scripts/tracking_commit.py` 提交事务；[tracking-transaction.md](tracking-transaction.md) 只在报错或字段拿不准时读。**full / lean 模式只允许通过该工具修改 `追踪/`；solo 模式不修改任何 `追踪/` 文件。**不得直接 Edit/Write/追加 `伏笔.md`、角色快照、时间线视图、摘要或 `上下文.md`。

1. **先检查状态**：执行 `tracking_commit.py check --project {项目根}`，确认 `_tracking-state.json` 与全部自动生成的追踪文件一致。失败时按 tracking-transaction.md 的错误类型处理；提交后追踪文件不一致，用新的同章 revision 事务重建，不重跑已清理的旧输入，也不手改 Markdown。
2. **判定是否需要修订**：只有正文证据表明现有追踪事实错误或缺失时才维护。过期伏笔、漏登记开放钩子、角色当前状态、客观时间线、读者认知都归入其证据所在章的 `mode=revision` 事务。审查意见与未来写作建议不进事实追踪。
3. **构造完整同章事务**：先跑 `tracking_commit.py draft --project {项目根} --chapter {N}`，草稿已按该章现有记录预填；保留该章原记录中仍成立的内容，只修改有正文证据的变化；核心角色变化同时提交截至当前最后已写章的完整 `character_snapshots`。伏笔对同一 ID `upsert` 当前状态，不增加重复行；时间线同时提交客观事实、读者当前认知和实际揭示状态。
4. **提交并复检**：执行 `tracking_commit.py commit --project {项目根} --input {事务文件}`，再执行 `tracking_commit.py check --project {项目根}`。确认逐章记录规范且未超限、`上下文.md` 恰好固定 7 栏且 ≤12288 字节、作者/读者时间线及全部自动生成的追踪文件与 state 一致。
5. **正文改过时的出口**：正文改过的修订，commit 会按现正文重新计数。只有报「字数出了作者范围」时不重试、不改字数记录，那要作者定长度。把这章要修的追踪事实写进报告「需要你决定」，请作者在 `/story-long-write` 说「修改第N章」，并告诉它正文已经改过、要重新提交追踪。

例如审查 demo 第 10 章时，若正文明确显示周薄森说专业重拍版“缺了灵魂”、张耀祖拍板继续用江晨手机原版，修订事务可以把该结果写进客观事实和读者已知；钟嘉嘉“只猜对了一半”背后的培养安排如果正文尚未揭示，只能留在作者真相，不能写入读者视图。
