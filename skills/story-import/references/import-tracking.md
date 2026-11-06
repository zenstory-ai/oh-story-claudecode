# 追踪初始化时刻（仅长篇）

Phase 4 完整读取本文件、[tracking-initialization.md](tracking-initialization.md) 的事务骨架与 [character-state-reverse.md](character-state-reverse.md) 的快照规则。截止章、残稿决定与卷划分取自导入记录；证据取自已落盘的拆文库和项目 `大纲/`，不重读原文。

导入项目必须通过本 skill 自带的 `scripts/tracking_commit.py init` 一次性生成追踪状态，禁止模型分别写最终文件。

## 语义准备顺序

1. **导入截止章**：将最后完整章 N 写入 `last_chapter`，工具在 `_tracking-state.json` 写入 `imported_through_chapter=N`。第 1..N 章不伪造日更事务，也不另写一份重复当前状态的叙事基线。
2. **核心角色当前快照**：从拆书产物反推主角、反派、核心配角的截至 N 章状态，按角色写入 `character_snapshots`，工具生成 `追踪/角色状态/{角色名}.md`；算法见 character-state-reverse.md。
3. **伏笔当前行**：从有正文证据的铺垫/回收事件生成 `foreshadow`（识别方法见下）。每个 ID 只保留当前状态一行；尚未实际埋设的未来设计留在大纲，不写 `伏笔.md`。
4. **事实与读者认知**：把关键事件生成到 `timeline_events`（提取方法见下）。同一事件同时写客观事实、读者截至 N 章已知内容和实际揭示状态；未来计划揭示章不得伪装成已发生事实。
5. **续写状态卡输入**：准备当前位置、长期约束、活跃核心角色、近三章速记、下一章承诺和连贯性风险。`上下文.md` 由工具生成固定 7 栏，不把文风、文件索引、普通待办或质检计数塞进续写状态卡。
6. **执行初始化**：事务写到 `{书目录}/.story/work/init.json`（成功前保留，不写系统 `/tmp`、书根、`大纲/` 或 `正文/`）。按当前平台探测 Python 3（`python3` → `python` → `py -3`），执行：

   > 项目 `追踪/` 里已有不属于当前协议的早期文件时不必手工清理：`init` 会先把它们按原样整体移入 `追踪/_旧追踪存档/`，再在原地建当前协议。旧内容保留供作者查阅，不参与解析，当前状态完全由本次导入输入决定；校验失败的 `init` 不移动任何文件。`init` 只在 `_tracking-state.json` 不存在时执行，绝不覆盖已初始化项目。

   ```text
   {PYTHON} {story-import skill 根}/scripts/tracking_commit.py init --project {书目录} --input {书目录}/.story/work/init.json
   {PYTHON} {story-import skill 根}/scripts/tracking_commit.py check --project {书目录}
   ```

半成品最后一章为残稿时，`last_chapter`、角色快照和其他当前语义检查点一律截至最后完整章；残稿处理策略（导入记录里作者的决定）写入 `continuity_risks`，不把未完成动作登记成既成事实。

以 demo《让你管账号，你高燃混剪炸全网》导入至第 10 章为例：续写状态卡要写清江晨的手机原版《诸君，且听龙吟》被专业团队高清重拍，但高层看片后认为新版“缺了灵魂”，最终继续采用原版；江晨快照应体现其军宣创作价值已获周薄森、张耀祖确认；读者时间线只写读者已经看到的看片会结论，钟嘉嘉“只猜对了一半”背后的培养安排若尚未揭示，只能出现在作者真相，不能泄露到读者视图。

## 条目形状与容量

在 tracking-initialization.md 的事务骨架上填条目，`last_chapter` 写 N；下面只展示伏笔、时间线与近章速记，不能替代完整初始化事务：

```json
{
  "foreshadow": [
    {"id": "F027", "summary": "专业团队仍拍不出江晨原版的灵魂", "planted_chapter": 10,
     "planned_resolution_chapter": null, "status": "已埋", "importance": "中"}
  ],
  "timeline_events": [
    {"id": "E010", "story_time": "实弹训练两天后",
     "objective_fact": "文工团高层否决专业重拍版，决定沿用江晨手机拍摄的原版视频",
     "reader_knowledge": "读者已看到周薄森指出专业版缺了灵魂，张耀祖当场拍板用回原版",
     "reveal_status": "已揭示", "reveal_chapter": 10, "characters": ["江晨", "周薄森", "张耀祖"]}
  ],
  "context": {
    "recent_chapters": [{"chapter": 10, "summary": "专业重拍版被判缺了灵魂，高层拍板用回手机原版"}]
  }
}
```

- 伏笔 `id` 形如 `F001`，`status` 取 已埋/已回收/已过期/放弃，`importance` 取 高/中/低；`planted_chapter` 不晚于 N。事件 `id` 形如 `E001`，`reveal_status` 取 未揭示/部分揭示/已揭示：`未揭示` 的 `reveal_chapter` 必须为 `null`，部分/完全揭示只能填已经发生的实际章节。
- `context` 在 init 时收六项：`position`、`long_term_constraints`、`active_character_names`、`continuity_risks`、`recent_chapters`（最多 3 章，按章号升序）、`next_chapter_commitments`。
- `character_snapshots` 里的角色就是核心角色；四个列表不限条数，单角色文件目标 ≤4096 字节，硬上限 8192 字节，超过在任何写入前拒绝。`active_character_names` 是导入截止章之后下一章的活跃角色，不是核心角色总数：最多 20 人且必须已有快照；`long_term_constraints` 最多 6 条。
- `上下文.md` ≤12288 字节，只含 7 个顶层区块：当前位置、长期约束、核心角色状态、活跃伏笔（最多 8 条）、近三章速记、下一章承诺、连贯性风险。
- 报错按提示改事务本身再跑，字段形状以 tracking-initialization.md 的骨架和本节为准。

## 伏笔提取

| 情节点类型 | 伏笔可能性 | 提取方式 |
|-----------|-----------|---------|
| 铺垫 | 高 | 直接提取为伏笔 |
| 信息揭示（部分） | 中 | 检查后续是否有呼应 |
| 物品首次出现 | 中 | 检查后续是否有使用 |
| 角色秘密 | 高 | 标记为角色伏笔 |
| 未解决的悬念 | 高 | 从章尾标记提取 |

状态推断：后续情节点实际回应了同一伏笔 → 已回收；尚未回应 → 已埋。不能只凭节点叫“揭示”或“解决”就判回收；半成品末尾尚未回应的铺垫可注明“接近断点”。

## 时间线提取

从情节点和时间标记提取：明确日期直接记录；相对时间有可靠参照点时推算，季节只能确定到季节。按章节、章内情节点序号整理；缺少参照时写“时间未明”，有依据的推断标 `[推断]`。

## 验收

初始化成功后应得到：

```text
追踪/
├── _tracking-state.json
├── 上下文.md
├── 逐章记录/                 # 导入旧章不补造文件，续写从第 N+1 章开始
├── 角色状态/{角色名}.md
├── 伏笔.md
├── 时间线/
│   ├── 作者真相.md
│   └── 读者已知.md
```

- [ ] `tracking_commit.py check` 通过，`_tracking-state.json` 与全部自动生成的追踪文件一致
- [ ] `_tracking-state.json.imported_through_chapter` 等于最后完整导入章
- [ ] `追踪/伏笔.md` 每个 ID 至多一行，未来尚未埋设的设计没有混入
- [ ] `_tracking-state.json.timeline` 已登记关键事实与读者认知，`读者已知.md` 无真相泄露
- [ ] `追踪/角色状态/{角色名}.md` 已覆盖全部核心角色并对齐 character-state-reverse.md
- [ ] `追踪/逐章记录/` 空目录已创建，且没有为导入章伪造日更记录
- [ ] `追踪/上下文.md` 顶层恰好固定 7 栏且 ≤12288 字节

通过后在导入记录勾「追踪初始化」，`init.json` 可删除；汇报末尾按 [SKILL.md 的换上下文规则](../SKILL.md#时刻表与交接) 建议新开对话。
