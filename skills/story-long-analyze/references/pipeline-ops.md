# 全局拆书管道运维

## 状态文件

JSON checkpoint schema v4 使用两个状态文件，不再把章节边界、批次与断点混写进 Markdown。当前固定为 `schema_version: 4`，分析契约还必须同时满足 `contract_version: 5.0`。

### `_progress.json`

```json
{
  "schema_version": 4,
  "contract_version": "5.0",
  "source_sha256": "<64 hex>",
  "boundary_sha256": "<64 hex>",
  "current_stage": "stage_3_structure_blocks",
  "final_status": "pending",
  "last_committed_batch": "SB-004",
  "completed_ranges": ["1-3", "4-9"],
  "pending_ranges": ["10-17"],
  "artifact_checksums": {
    "chapter_index.csv": "<sha256>",
    "structure_blocks.csv": "<sha256>"
  },
  "failed_ranges": [],
  "retry_reasons": [],
  "next_action": "analyze candidate block 10-17"
}
```

### `_state_snapshot.json`

```json
{
  "schema_version": 4,
  "source_sha256": "<64 hex>",
  "chapter_boundaries": [],
  "aliases": {},
  "block_progress": {},
  "unresolved_information": [],
  "evidence_locators": []
}
```

状态快照只保存恢复所需的紧凑事实，不保存对话历史、完整原文、逐章摘要或机械摘句。

## 原子提交

每个批次固定执行：

1. 写同目录临时文件。
2. 校验 schema、章号/范围、定位、数值范围与 UTF-8。
3. 计算产物 SHA-256。
4. 用原子替换提交正式产物。
5. 最后原子更新 `_progress.json`。

第 5 步失败时，下一次先按 `artifact_checksums` 对账；校验通过则补提交进度，不重复读取原文。禁止直接 append 半个 CSV 批次。

## schema 版本

| 版本 | 含义 | 恢复规则 |
|---:|---|---|
| 1/缺失 | 旧逐章拆解，无统一章节边界 | 不续跑；从 Stage 0 重建 |
| 2 | A 旧管道：章节摘要、剧情/角色/设定、报告、文风 | 可保留原文与黄金三章；重建 v4 |
| 3 | A+B 初版：二十列逐章语义索引 + 六个拆分全局文件 | 可保留原文和黄金三章作只读参考；五列索引与结构块必须重建 |
| 4 + contract 4.0 | 前一候选：五列机械索引 + 旧结构块 + 六个拆分全局文件 | 原文、黄金三章和机械索引可保留；重建 enriched `structure_blocks.csv` 与三个全局文件 |
| 4 + contract 5.0 | 当前管道：黄金三章 + 五列机械索引 + enriched 结构块 + 三个全局文件 | 按哈希、contract version 和最近原子提交恢复 |

旧文件不静默删除。用户明确要求整理时才移动到 `_legacy/`。

## 恢复步骤

1. 读取 `_progress.json` 和 `_state_snapshot.json`。
2. 检查 `contract_version`；不是 `5.0` 时不得按当前断点直接续跑旧结构块契约。
3. 已有产物保留为只读 legacy；经用户明确启动重建后，可复用同源五列机械索引，重建 enriched 结构块与三个全局文件。
4. 重新计算备份原文的 `source_sha256`；不一致则停止，报告 `source_changed`，等待显式重建。
5. 重算边界哈希；不一致则停止，报告 `boundary_changed`。
6. 校验 `artifact_checksums`。已提交产物有效时直接复用；无效产物回滚到最近一个校验通过的批次。
7. `paused_after_stage1` 从 Stage 2 开始，不重跑 Stage 0/1。
8. Stage 2 已有同哈希五列索引时不写入；进入 Stage 3。
9. Stage 3 从 `pending_ranges` 的首个范围开始；`completed_ranges` 禁止再读。
10. Stage 4–6 缺哪个当前全局文件就从对应阶段整份重做，不拼接半份结论，不回扫所有成功结构块。

同一范围只有记录了明确 `retry_reasons` 才能重读；原因必须属于执行失败、定位失败、schema 失败或证据冲突，不能写“为了更准确”。

## 错误处理

| 场景 | 处理 |
|---|---|
| 章节识别失败 | 提示确认格式；支持自定义正则；不进入 Stage 1 |
| 目录块误识别 | 剔除开头密集标题块，重跑连续性校验 |
| 多卷重复章号 | 保留卷名消歧，全局连续重编号 |
| CSV 部分写入 | 丢弃临时文件，保留上一个正式文件 |
| 源或边界哈希变化 | 停止续跑；显式 `--rebuild` 后整体重建 Stage 2–6 |
| 结构块证据不足 | 合并相邻块或标 failed；不使用首尾句/标题补写 |
| 别名冲突 | 分开实体，记录待确认 |
| 双时间线矛盾 | 两种解释并列写入边界，不补写原作 |
| 全局文件缺失 | 阻断 completed；从对应 Stage 整份重做 |

## 完成状态

- `completed`：五列索引、enriched 结构块和三个全局文件通过质量门。
- `completed_with_errors`：存在 failed 结构块或输入缺口，但影响边界已传播到 `证据与边界.md`。
- `paused_after_stage1`：只完成 Stage 0/1。
- `pending`：其他进行中状态。

完成前确认本轮没有生成非黄金章逐章摘要、逐章语义 CSV、剧情/角色/设定拆分目录、拆文报告或文风文件。
