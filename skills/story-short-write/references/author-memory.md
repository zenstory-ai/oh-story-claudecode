# 作者记忆协议

作者记忆用于保存跨会话复用的创作偏好，不保存小说世界里的事实。它借鉴“原始证据 → 候选 → 已确认画像 → 变更记录”的记忆管道，但把决定权留给作者。

## 边界与优先级

加载优先级从高到低：

1. 安全、用户授权范围、明确的平台交付要求、字数与文件协议；句长、视角、修辞和标点偏好不属于不可覆盖的硬门禁；
2. 用户在当前请求中的明确要求；
3. 当前书的 `设定/文风.md`、题材定位、细纲和其他项目设定；
4. 作者记忆中的本书偏好；
5. 作者记忆中的题材、流程和全局偏好；
6. 对标素材、通用方法和默认值。

按表达维度取最窄适用要求：低优先级只补缺项，不与高优先级要求并列执行。通用 references 自称“必须/禁用”不改变此顺序；审稿不因作者有意采用的表达本身扣分，真实可读性与因果问题仍照常评价。

作者记忆不能把本书事实写进 `.story/作者记忆/`，不能覆盖当前请求，不能降低审稿 rubric，也不能让去 AI 味改动剧情意图。小说事实继续由各书的 `追踪/` 和 `设定/` 管理。

## 文件与所有权

作者记忆分两级存放，记忆随书走：

```text
{工作区}/.story/作者记忆/          # 项目级 store：global / genre / workflow 条目，编号 AP
├── _author-memory-state.json  # 唯一结构化权威
├── 作者画像.md               # 仅 active，供作者查看与管理
├── 待确认.md                 # pending / conflict，不参与约束
└── 变更记录.md               # 最近 100 次、最新在前的事务记录
{书}/.story/作者记忆/            # 书级 store：只存这本书的 book 条目，编号 BP，同样四个文件
```

三个 Markdown 文件都从 state 确定性生成，禁止手改；完整历史保留在 state，变更记录只展示最近 100 次。`作者画像.md` 是人类管理视图，普通写作 agent 不整份注入，而是调用 `query` 取得本次相关的紧凑上下文。作者记忆不存在时，普通写作、审稿和去味任务直接继续，不自动初始化空目录；首次 `record` 会随事务创建。

**定位规则**：`--workspace` 必须显式传给脚本——优先使用已经包含 `.story/作者记忆/` 的最近祖先；首次初始化时使用承载多本书、`.active-book`、`长篇/`、`短篇/` 或 `拆文库/` 的创作工作区根；不要把用户主目录当默认工作区。`--book-root` 是当前书的项目目录（`.active-book` 指向、或含 `设定/`、`正文/` 的那一层，如 `{工作区}/长篇/{书名}/`）；书名默认取书级 state 记录的名字，首次建立时取目录名，`--book` 可覆盖。

**路由规则**：ID 前缀就是 store——`decide` / `forget` 看 `item_id`（`AP` 进项目级，`BP` 进书级），`remember` / `replace` 看 `scope.level`（`book` 进书级，其余进项目级）。书级操作必须传 `--book-root`，没传直接报错，不会退而写进项目级。一份 `commit` 事务只能写一个 store；`replace` 与 `conflicts_with` 不能跨 store——本书例外按优先级覆盖全局规则，不算冲突，直接 `remember` 为 book 条目即可；要把全局规则改成本书规则，拆成 `forget` ＋ `remember` 两个事件。

**存量迁移，不做双读**：升级前写进项目级 store 的 book 条目不再参与查询与预算估算，也不再接受新的 book 写入；它们仍在 `作者画像.md` 里可见、可 `decide` / `forget`。对每本书运行一次 `migrate --book-root {书目录}` 即可整批搬回来：断言、证据、确认次数、重要度原样保留，换成 `BP` 编号，原 `AP` 条目标 `superseded` 并注明去向；与全局条目的冲突关系在迁移后不再成立，这类候选退回 `pending`。书级每个源条目一笔事务，重跑只补没做完的一半。「整理作者记忆」看到项目级画像里还有「本书：」条目时，把迁移列为默认提案项。

## 什么时候读取

长篇、短篇、去 AI 味开始前，如果 state 已存在，用 `query` 按本书、题材、流程和类型筛选 active 条目：结果是项目级 store 与 `--book-root` 所指书级 store 的合并；不传 `--book-root` 就拿不到任何本书条目。查询输出固定不超过 2048 字节。`--kind` 必传——不传直接报错，不再默认返回全部类型；按任务直接选择 kind：

| 任务 | query kinds | 注入位置 |
|---|---|---|
| 正文初稿 / 续写 | `prose_style` + `story_design` | 主会话与实际正文 agent |
| 去 AI 味 / 改写 | `prose_style` | 主会话与实际改写 agent |
| 设定 / 大纲 | `story_design` + `workflow` + `interaction` | 主会话，不传正文 agent |
| 审稿 | `delivery` + `interaction` + 必要的 `prose_style` | 主会话，不降低 rubric |

审稿匹配项只用于交付格式、协作方式和“作者有意采用的表达选择”说明；问题严重度和 PASS/FAIL 仍由 rubric 决定。

待确认项不进入 prompt 约束，也不应为了确认它们中断当前任务。只有用户主动查看作者画像、候选积累到适合回顾的节点，或新偏好与 active 条目冲突时，才集中呈现。

## 可靠性与负荷边界

- 明确“记住 / 确认 / 替换 / 忘掉”的请求走单事件 `record`，不要求 agent 手工读取修订号或拼多操作事务。成功响应会给出 `Author Memory Receipt: rN · APxxx`；没有回执就不得声称“已经记住”。回执带 `warnings` 时把提醒原样转告作者。
- 普通创作只做一次本地 `query`，没有 state 时返回空结果且不创建文件；有记忆时也只返回相关 active 条目，硬上限 2048 字节。完整画像、证据、候选和 journal 不进入正文 prompt。
- **写入不因注入预算失败**：`record` / `commit` 照常成功、给回执；工具按上表四类任务组合估算最坏查询情形（全局条目＋各 scope 维度最重的单一切片，切片按大小写无关归并、轻重按写作时真正读到的字段算，与真实查询同一把尺），装不进 2048 字节的组合在返回的 `warnings` 里点名将被略过的条目及其断言首句。收到提醒就转告作者并建议「整理作者记忆」。写书级条目时「本书＋全局」按实际条目精确计算；写项目级条目时只看得到项目级 store，顺手传 `--book-root` 就把当前这本书也算进提醒。查询按 **重要度 → 本书例外 → 最近更新** 排序装填（跨 store 的「最近」按提交时刻比），先丢的恒是重要度较低的条目——`importance` 决定超编时谁留在 prompt 里，写入时按偏好的实际分量填，不要一律 `high`。
- 注入预算之外还有一道硬上限：`作者画像.md` 超过 12288 字节时写入会直接失败并要求先整理。active 条目攒到几十上百条才会碰到（远在注入预算之后），碰到就走「整理作者记忆」；`forget` 这类减量操作在满编时照常可用。
- 查询项是低优先级倾向，不是逐条打卡清单。自然吸收即可，不复述画像、不刻意提高词面命中率，也不得为命中偏好牺牲正文连贯、节奏、字数或本书既定笔调。
- 不安装会记录全部用户消息的 prompt hook，也不在作者没开口时观察他：不从反复修改、成稿或操作轨迹推断偏好写入。只记作者明确表达的偏好；自然语言是否属于长期习惯仍需 agent 判断，拿不准就只执行不记录。需要确定写入时，用户可明确说“记住：……”，并以回执验收。

## 捕获判定

| 输入证据 | 处理 |
|---|---|
| “以后都这样”“我一直习惯……”等直接、稳定、范围清楚的原话 | `active`，`source=explicit_user` |
| 用户明确接受助手提出的长期做法 | `active`，`source=accepted_suggestion` |
| 作者原话像长期偏好但范围或稳定性含糊 | `pending`，取当前最窄合理范围；待确认只来自作者自己的话 |
| 同类修改反复出现、从成稿或操作轨迹看出的模式 | 不记录、不推断；作者没开口的偏好不进记忆 |
| “这一章别……”“这次给我……”等一次性要求 | 只执行，不记录 |
| 角色、时间线、伏笔、世界观、当前剧情走向 | 写项目设定/追踪，不写作者记忆 |
| 助手自己生成的文字、默认模板、工具告警、rubric 结论 | 不自我学习 |

保留用户的否定词、限定词和适用范围，`quote` 写原话，`assertion` 只做不改变语义的紧凑归纳，**新建条目限一句话（≤120 字节，约 40 个字）**；需要解释的背景写进 `reason`（不进 prompt 载荷），不另开字段。

**一条偏好就是一条记录，例外和限定不许拆出去单列。** 「以后少用破折号，对话里也别用，除非表示打断」是一条带例外的偏好，必须整条写成一个 `assertion`（「破折号少用、对话里也不用，只在表示打断时保留」）。超编时条目是逐条被丢的，把「除非表示打断」拆成独立一条，就可能只丢掉例外、把作者明说过的限定变成送进正文的绝对禁令。只有原话确实塞了**几条互不依赖**的偏好（如「多用短句」＋「章末留钩子」）才拆成几条。整句写不进 120 字节时压缩措辞，不要切掉限定词。

升级前写下的长断言不受新上限约束：原样重申它会**强化**原条目（确认次数 +1），不会因超长被拒；只有真正新建条目才校验 120 字节。

范围规则：

- “本书 / 这个角色 / 这次连载” → `book`；
- “都市文 / 这类题材” → `genre`；
- 交稿、检查、确认节奏等操作习惯 → `workflow`；
- “以后 / 一贯 / 我习惯”且无更窄限定 → `global`；
- 范围含糊但可能稳定 → 取当前最窄合理范围并置 `pending`。

类型可选：`prose_style`、`story_design`、`workflow`、`delivery`、`interaction`。置信度与重要度均为 `low | medium | high`。`source` 只接受 `explicit_user`、`accepted_suggestion`、`manual`；工具会拒绝推断类来源，存量 state 里的旧来源条目照常可读、可确认、可退役。

## 冲突、撤回与强化

- 同一类型、范围、归纳文本再次出现时，脚本强化原条目，累加证据和确认次数，不重复建条目。
- 新偏好与同一 store 里的 active 条目矛盾时，先以 `conflict` 记候选，并在 `conflicts_with` 列出冲突 ID；当前任务仍按本轮明确要求执行。本书例外与全局规则不算冲突。
- 同一范围的规则改版用 `replace`，启用新条目并将旧条目标成 `superseded`。本书例外用 `remember` 新建 book 条目（传 `--book-root`），保留 global 习惯；只有作者明确撤销或改变旧规则范围时才跨范围替换，跨 store 时拆成 `forget` ＋ `remember`。
- pending 可以用 `decide=activate|reject`；冲突候选不能绕过旧规则直接 activate。
- 作者说“忘掉 / 这不再是我的习惯”时用 `forget`，保留历史证据但不再加载。
- active 条目的语义不可原地偷改；语义变化必须 replace，历史才可审计。

## 整理作者记忆

作者说「整理作者记忆」，或回执 `warnings`／查询 `omitted_ids` 提示超编时：读项目级与当前书的 `作者画像.md`（每条都标了范围、重要度、把握和确认次数，重要度就是超编时的去留依据），提出合并同义条（`replace` 多合一）、退役过时条（`forget`）、给错标成 `high` 的条目下调重要度、把超长断言压缩成一句话的提案；项目级画像里还有「本书：」条目时，「对该书运行 `migrate --book-root`」列为默认提案项。清单让作者逐条确认，确认后按 store 各汇成一份 `commit` 事务提交（一份事务只写一个 store）。合并时保住每条的否定词、限定词和适用范围——合不动就退役其中一条，不要靠删限定词把两条凑成一条。整理只由作者发起或确认，不自动执行。

## 运行工具

先依次尝试 `python3`、`python`、`py -3` 找到 Python 3，再从当前 skill 根运行本地副本：

```text
{PYTHON} {当前 skill 根}/scripts/author_memory_commit.py init    --workspace {工作区} [--book-root {书目录}]
{PYTHON} {当前 skill 根}/scripts/author_memory_commit.py record  --workspace {工作区} [--book-root {书目录}] --input {单事件.json}
{PYTHON} {当前 skill 根}/scripts/author_memory_commit.py query   --workspace {工作区} --book-root {书目录} --kind {类型}（必传，可重复） [--genre {题材}] [--workflow {流程}]
{PYTHON} {当前 skill 根}/scripts/author_memory_commit.py commit  --workspace {工作区} [--book-root {书目录}] --input {事务.json}
{PYTHON} {当前 skill 根}/scripts/author_memory_commit.py migrate --workspace {工作区} --book-root {书目录}
{PYTHON} {当前 skill 根}/scripts/author_memory_commit.py check   --workspace {工作区} [--book-root {书目录}]
```

所有子命令都可加 `--book {书名}` 覆盖书名；正在写某本书时一律带上 `--book-root`，书级操作没有它会直接报错。

- `record`：常用单事件入口，按路由规则落到项目级或书级 store，自动读取该 store 的当前修订、首次自动初始化；`event_id` 相同且内容相同会幂等返回原回执，内容不同会失败。原样重申已有条目的 `assertion` 会强化该条（不受 120 字节新建上限约束）。返回里的 `store` / `book` 说明写到了哪一级，`warnings` 是预算提醒，要原样转告作者。
- `query`：只读相关 active 条目，项目级与书级合并返回；`--kind` 必传、可重复，两级 state 都不存在时返回空结果且零写入。输出按 重要度 → 本书例外 → 最近更新 排序装填；装不下的条目跳过而不中断（一条长的不挡后面的短条），漏下的 ID 按同一优先级报进 `omitted_ids`（最多列 20 条，`omitted` 是真实总数）。**`omitted_ids` 非空＝记忆超编**——转告作者并建议「整理作者记忆」，它不是「没有更多了」，也不得改读完整画像规避预算。
- `commit`：高级批量入口；一份事务只写一个 store，先在内存完成 schema、引用、容量和所有视图校验，最后原子替换 state。事务文件在成功前必须保留；过期修订会在任何写入前失败。
- `migrate`：把项目级 store 里某本书的存量 book 条目整批搬进 `--book-root` 的书级 store，幂等，中途失败直接重跑；返回 `migrated`（源→新编号），没有存量时为空。
- `check`：从 state 重建并逐字核验所有派生视图；传 `--book-root` 时两级一起核验。

## 事务格式

常用单事件新增或强化：

```json
{
  "schema_version": 1,
  "event_id": "conversation-2026-08-25-message-42",
  "operation": {
    "action": "remember",
    "preference": {
      "kind": "prose_style",
      "scope": {"level": "global", "value": null},
      "assertion": "对话尽量短，用动作承接情绪，不用大段解释",
        "quote": "以后对话都短一点，情绪放动作里，别让角色长篇解释。",
        "source_ref": "conversation:2026-08-25",
        "source": "explicit_user",
        "confidence": "high",
        "importance": "high",
      "status": "active",
      "reason": "用户以“以后”明确声明长期偏好",
      "conflicts_with": []
    }
  }
}
```

把文件交给 `record`（book 范围的事件同时传 `--book-root`）。待确认项的 `status` 用 `pending`；冲突候选用 `conflict` 并填写同一 store 里的 active ID。确认或拒绝候选时，把下列对象作为新事件的 `operation`（`BP` 编号的事件传 `--book-root`）：

```json
{"action":"decide","item_id":"AP002","decision":"activate","quote":"对，这就是我的长期习惯。","reason":"作者明确确认"}
```

用新规则替代一个或多个旧条目时，`replace.preference` 与上例字段相同，但不传 `status`、`conflicts_with`，新条目直接 active；下列对象同样作为 `operation`：

```json
{
  "action": "replace",
  "old_ids": ["AP001"],
  "preference": {
    "kind": "prose_style",
    "scope": {"level": "global", "value": null},
    "assertion": "以后对话允许更长的试探，但避免解释设定",
    "quote": "把以前对话都要短的习惯替换掉：以后可以让对话慢一点，多试探，但还是别拿台词讲设定。",
    "source_ref": "conversation:2026-08-25",
    "source": "explicit_user",
    "confidence": "high",
    "importance": "high",
    "reason": "作者明确替换原有全局规则，不是新增本书例外"
  }
}
```

撤回条目的 `operation`：

```json
{"action":"forget","item_id":"AP003","quote":"忘掉这个偏好。","reason":"作者明确撤回"}
```

需要把多个动作绑定成一次原子提交时才用高级 `commit`：顶层传 `schema_version`、唯一 `transaction_id`、当前 `expected_state_revision` 和含 1–32 项的 `operations`。操作按数组顺序应用，任一步失败则整份事务零写入。成功后删除临时输入文件；显式记忆请求还要把工具返回的回执原样告诉用户。
