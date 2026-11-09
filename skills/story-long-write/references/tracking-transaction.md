# 追踪状态协议

> 谁读：追踪提交报错、要查字段或体积上限时读，不预读。

`追踪/` 以结构化 state 为权威，由脚本生成各 Markdown 视图。模型只提交一份语义 JSON，不分别 `Write/Edit/echo >>` 多个追踪文件。

## 底账与自动生成的视图

| 层级 | 文件 | 语义 |
|---|---|---|
| 唯一底账 | `_tracking-state.json` | schema、最后提交章、导入截止章、状态修订号、上下文结构、角色/伏笔/时间线，以及已提交章节的字数记录 |
| 章节记录 | `逐章记录/第NNN章.md` | 本章对未来连续性有用的紧凑变化；目标 ≤1536 字节，硬上限 3072 字节；导入范围内修订写成覆盖记录 |
| 自动生成的视图 | `上下文.md`、`角色状态/{角色名}.md`、`伏笔.md`、`时间线/作者真相.md`、`时间线/读者已知.md` | 完全从 `_tracking-state.json` 自动生成；禁止手改，不作为程序输入 |

未来“第几章揭示”的计划写在卷纲/细纲，不写成时间线既成事实。完整当前语义以 `_tracking-state.json` 为准。

## 运行工具

先探测 Python 3 解释器（依次试 `python3`、`python`、`py -3`）：

```text
{PYTHON} {当前 skill 根}/scripts/tracking_commit.py init   --project {书项目根} --input {书项目根}/.story/work/init.json
{PYTHON} {当前 skill 根}/scripts/tracking_commit.py check  --project {书项目根}
{PYTHON} {当前 skill 根}/scripts/tracking_commit.py draft  --project {书项目根} --chapter {N}
{PYTHON} {story-long-write skill 根}/scripts/storyctl.py chapter check   --project {书项目根} --chapter {N} [--min-chars {下限} --max-chars {上限}]
{PYTHON} {story-long-write skill 根}/scripts/storyctl.py chapter commit  --project {书项目根} --chapter {N} --input {书项目根}/.story/work/第{NNN}章/tracking.json
{PYTHON} {story-long-write skill 根}/scripts/storyctl.py chapter accept-current-length --project {书项目根} --chapter {N} --input {书项目根}/.story/work/第{NNN}章/tracking.json
```

- `init`：仅在 `_tracking-state.json` 不存在时执行（旧追踪文件自动移入 `追踪/_旧追踪存档/`）；执行前读 [tracking-initialization.md](tracking-initialization.md)。
- `draft`：把逐章事务草稿预填到 `.story/work/第NNN章/tracking.json`，并输出字段上限与在场核心角色当前快照。新章（`append`）只填 `delta` 与变化角色快照；已提交章（`revision`）在预填记录上改成修订后的完整记录，不清空重写。
- **作者字数范围**：细纲可写 `字数范围：2000-2600`，本轮临时覆盖传 `--min-chars` / `--max-chars`（同时替代默认 ±12% 内部带与 ±15% 用户带）。
- `chapter check`：读取正文与细纲目标，返回 `ready`（可提交，exit 0）/ `needs_decision`（长度带外，交作者定夺，exit 0；`over` 额外返回 `compress-once` 删除字数）/ `blocked`（正文硬伤，exit 1）/ `invalid`（exit 1）/ `tool_unavailable`（exit 3）。加 `--plain` 输出白话结论（含短段占比与叙述句长中位数参考）。
- `chapter commit`：重跑计数与硬伤检查，将生效区间内的字数记录与逐章事务原子提交（成功后自动删除 `.story/work/第NNN章/`）。
- `chapter accept-current-length`：接受带外但质检通过的章节并原子提交；低于目标一半（`BELOW_ACCEPT_FLOOR`）或超长未压缩（`COMPRESSION_REQUIRED`）时拒绝，作者明确拍板加 `--force`。
- `check`：校验 state schema、逐章记录与自动生成视图的一致性。若报 `derived view differs from _tracking-state.json`，取当前 `state_revision` 重新提交该章 `mode=revision` 事务重建，禁止手改视图或删 `_tracking-state.json`；手写逐章记录导致 `chapter delta N already exists with different content` 时，删掉手写文件后重跑原事务。

## 逐章事务

```json
{
  "schema_version": 1,
  "mode": "append",
  "chapter": 10,
  "chapter_title": "专业团队拍得还不如他拍的好？",
  "expected_state_revision": 9,
  "delta": {
    "result": "专业团队重拍的高清版在高层看片会上被判定缺了灵魂，张耀祖拍板继续采用江晨的手机原版。",
    "character_changes": [
      {"name": "江晨", "change": "作品价值获军内高层确认，从爆款新人升为不可替代的军宣创作者"}
    ],
    "foreshadow_changes": [
      {
        "action": "upsert",
        "id": "F027",
        "summary": "专业团队仍拍不出江晨原版的灵魂，继续验证其创作能力不可复制",
        "planted_chapter": 10,
        "planned_resolution_chapter": null,
        "status": "已埋",
        "importance": "中"
      }
    ],
    "timeline_events": [
      {
        "action": "upsert",
        "id": "E005",
        "story_time": "实弹训练两天后",
        "objective_fact": "文工团高层否决专业重拍版，决定沿用江晨手机拍摄的原版视频",
        "reader_knowledge": "读者已看到周薄森指出专业版缺了灵魂，张耀祖当场拍板用回原版",
        "reveal_status": "已揭示",
        "reveal_chapter": 10,
        "characters": ["江晨", "周薄森", "张耀祖"]
      }
    ],
    "constraints": ["后续继续用作品落地效果和围观反应放大江晨的高光，不能只写系统奖励数字"],
    "next_chapter_commitments": ["结算五天百万粉任务，并承接老兵主题的新任务"]
  },
  "context": {
    "position": {
      "volume": "第一卷·军宣整顿",
      "volume_start_chapter": 1,
      "story_time": "实弹训练两天后",
      "scene": "火箭军文工团高层看片会"
    },
    "long_term_constraints": ["军宣爽点要用作品效果和围观反应链兑现，不能只靠系统播报"],
    "active_character_names": ["江晨"],
    "continuity_risks": ["钟嘉嘉说江晨只猜对一半，未公开的培养安排不能被当成读者已知事实"]
  },
  "character_snapshots": {
    "江晨": {
      "identity": "火箭军文工团宣传兵；军宣爆款创作者",
      "location": "火箭军文工团高层看片会",
      "goal": "完成五天百万粉任务，持续做出真正能打的军宣内容",
      "state": "专业团队反向验证原版价值，军内认可继续抬升",
      "abilities_resources": ["前世MCN爆款运营经验", "《中国军魂》伴奏", "天王级唱功", "大师级导演能力"],
      "relationships": ["钟嘉嘉持续提供军报资源", "周薄森和张耀祖已明确认可其创作能力"],
      "knowledge": ["《军报》采访稿已经过审", "原版视频将继续作为正式军宣内容"],
      "open_threads": ["五天百万粉任务尚未结算", "钟嘉嘉所谓只猜对一半仍未解释"]
    }
  }
}
```

约束：

- `expected_state_revision` 取当前 `state_revision`（`draft` 自动预填）；逐章 JSON 不写 `wordcount`。
- `context` 字段：`init` 收 `position`、`long_term_constraints`、`active_character_names`、`continuity_risks`、`recent_chapters`、`next_chapter_commitments` 六项；`commit` 只收前四项（后两项由工具自动算出，手填报错 exit 2）。
- `character_snapshots` 中的核心复用角色须同时出现在 `character_changes`；已建快照的核心角色再次变化时须提交新快照（单文件目标 ≤4096 字节，硬上限 8192 字节）。无快照的临时角色只写 `character_changes`。
- `context.active_character_names`：仅列下一章出场或被直接牵动的核心角色（最多 20 人，须已有快照）。
- `context.long_term_constraints`（最多 6 条，超限先合并或请作者取舍）与 `context.continuity_risks` 整份提交当前值；凡上一版有、本次移除的条目须列进 `delta.retired_context_items`（仅 `mode=append` 允许）。
- 不再复用的核心角色写进 `delta.retired_characters`（仅 `mode=append` 允许；同事务不交快照、不列在 `active_character_names`，阵亡/退场变化照写进 `character_changes`）。
- `伏笔.md` 只呈现已埋设状态；`timeline_events.action` 为 `upsert/delete`，`未揭示` 的 `reveal_chapter` 必须为 `null`。
- `mode=revision`：在 `draft` 预填草稿上修改该章完整连续性记录（不可提交退役项），角色、伏笔、时间线和上下文提交截至最新已写章的当前值。

## 续写状态卡固定格式

`上下文.md` ≤12288 字节（活跃角色 ≤20 人、活跃伏笔 ≤8 条、近章 3 章），由 state 自动生成 7 个顶层区块：`## 当前位置`、`## 长期约束`、`## 核心角色状态`、`## 活跃伏笔`、`## 近三章速记`、`## 下一章承诺`、`## 连贯性风险`。超字节上限时先压短状态行，再减人数。
