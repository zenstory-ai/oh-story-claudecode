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

工作区级目录：

```text
{工作区}/.story/作者记忆/
├── _author-memory-state.json  # 唯一结构化权威
├── 作者画像.md               # 仅 active，供作者查看与管理
├── 待确认.md                 # pending / conflict，不参与约束
└── 变更记录.md               # 最近 100 次、最新在前的事务记录
```

三个 Markdown 文件都从 state 确定性生成，禁止手改；完整历史保留在 state，变更记录只展示最近 100 次。`作者画像.md` 是人类管理视图，普通写作 agent 不整份注入，而是调用 `query` 取得本次相关的紧凑上下文。`query` 要显式传 `--book`、已知的 `--genre` / `--workflow`；只传 kind 不会返回本书或题材项。作者记忆不存在时，普通写作、审稿和去味任务直接继续，不自动初始化空目录；首次 `record` 会随事务创建。

工作区必须显式传给脚本。优先使用已经包含 `.story/作者记忆/` 的最近祖先；首次初始化时使用承载多本书、`.active-book`、`长篇/`、`短篇/` 或 `拆文库/` 的创作工作区根。不要把用户主目录当默认工作区。

## 什么时候读取

长篇、短篇、去 AI 味开始前，如果 state 已存在，用 `query` 按本书、题材、流程和类型筛选 active 条目。查询输出固定不超过 2048 字节。不要先查询全部再让 agent 自行筛选，按任务直接选择 kind：

| 任务 | query kinds | 注入位置 |
|---|---|---|
| 正文初稿 / 续写 | `prose_style` + `story_design` | 主会话与实际正文 agent |
| 去 AI 味 / 改写 | `prose_style` | 主会话与实际改写 agent |
| 设定 / 大纲 | `story_design` + `workflow` + `interaction` | 主会话，不传正文 agent |
| 审稿 | `delivery` + `interaction` + 必要的 `prose_style` | 主会话，不降低 rubric |

审稿匹配项只用于交付格式、协作方式和“作者有意采用的表达选择”说明；问题严重度和 PASS/FAIL 仍由 rubric 决定。

待确认项不进入 prompt 约束，也不应为了确认它们中断当前任务。只有用户主动查看作者画像、候选积累到适合回顾的节点，或新偏好与 active 条目冲突时，才集中呈现。

## 可靠性与负荷边界

- 明确“记住 / 确认 / 替换 / 忘掉”的请求走单事件 `record`，不要求 agent 手工读取修订号或拼多操作事务。成功响应会给出 `Author Memory Receipt: rN · APxxx`；没有回执就不得声称“已经记住”。
- 普通创作只做一次本地 `query`，没有 state 时返回空结果且不创建文件；有记忆时也只返回相关 active 条目，硬上限 2048 字节。完整画像、证据、候选和 journal 不进入正文 prompt。
- 查询项是低优先级倾向，不是逐条打卡清单。自然吸收即可，不复述画像、不刻意提高词面命中率，也不得为命中偏好牺牲正文连贯、节奏、字数或本书既定笔调。
- 不安装会记录全部用户消息的 prompt hook。自然语言是否属于长期习惯仍需 agent 判断；这样不能承诺隐式偏好 100% 捕获，但避免把一次性要求、私人对话和小说事实静默写入长期记忆。需要确定写入时，用户可明确说“记住：……”，并以回执验收。

## 捕获判定

| 输入证据 | 处理 |
|---|---|
| “以后都这样”“我一直习惯……”等直接、稳定、范围清楚的原话 | `active`，`source=explicit_user` |
| 用户明确接受助手提出的长期做法 | `active`，`source=accepted_suggestion` |
| 同类修改反复出现，但用户没说这是长期规则 | `pending`，`source=repeated_correction` |
| 从成稿或操作轨迹推断出的模式 | `pending`，`source=inferred_pattern` |
| “这一章别……”“这次给我……”等一次性要求 | 只执行，不记录 |
| 角色、时间线、伏笔、世界观、当前剧情走向 | 写项目设定/追踪，不写作者记忆 |
| 助手自己生成的文字、默认模板、工具告警、rubric 结论 | 不自我学习 |

保留用户的否定词、限定词和适用范围，`quote` 写原话，`assertion` 只做不改变语义的紧凑归纳。范围规则：

- “本书 / 这个角色 / 这次连载” → `book`；
- “都市文 / 这类题材” → `genre`；
- 交稿、检查、确认节奏等操作习惯 → `workflow`；
- “以后 / 一贯 / 我习惯”且无更窄限定 → `global`；
- 范围含糊但可能稳定 → 取当前最窄合理范围并置 `pending`。

类型可选：`prose_style`、`story_design`、`workflow`、`delivery`、`interaction`。置信度与重要度均为 `low | medium | high`。

## 冲突、撤回与强化

- 同一类型、范围、归纳文本再次出现时，脚本强化原条目，累加证据和确认次数，不重复建条目。
- 新偏好与 active 条目矛盾时，先以 `conflict` 记候选，并在 `conflicts_with` 列出冲突 ID；当前任务仍按本轮明确要求执行。
- 同一范围的规则改版用 `replace`，启用新条目并将旧条目标成 `superseded`。本书例外用 `remember` 新建 book 条目，保留 global 习惯；只有作者明确撤销或改变旧规则范围时才跨范围替换。
- pending 可以用 `decide=activate|reject`；冲突候选不能绕过旧规则直接 activate。
- 作者说“忘掉 / 这不再是我的习惯”时用 `forget`，保留历史证据但不再加载。
- active 条目的语义不可原地偷改；语义变化必须 replace，历史才可审计。

## 运行工具

先依次尝试 `python3`、`python`、`py -3` 找到 Python 3，再从当前 skill 根运行本地副本：

```text
{PYTHON} {当前 skill 根}/scripts/author_memory_commit.py init   --workspace {工作区}
{PYTHON} {当前 skill 根}/scripts/author_memory_commit.py record --workspace {工作区} --input {单事件.json}
{PYTHON} {当前 skill 根}/scripts/author_memory_commit.py query  --workspace {工作区} [--kind prose_style] [--book {书名}] [--genre {题材}] [--workflow {流程}]
{PYTHON} {当前 skill 根}/scripts/author_memory_commit.py commit --workspace {工作区} --input {事务.json}
{PYTHON} {当前 skill 根}/scripts/author_memory_commit.py check  --workspace {工作区}
```

- `record`：常用单事件入口，自动读取当前修订、首次自动初始化；`event_id` 相同且内容相同会幂等返回原回执，内容不同会失败。
- `query`：只读相关 active 条目；`--kind` 可重复，不存在 state 时返回空结果且零写入。返回的 `omitted > 0` 时收窄 kind / book / genre / workflow 后重查，不得改读完整画像规避预算。
- `commit`：高级批量入口；先在内存完成 schema、引用、容量和所有视图校验，最后原子替换 state。事务文件在成功前必须保留；过期修订会在任何写入前失败。
- `check`：从 state 重建并逐字核验所有派生视图。

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

把文件交给 `record`。待确认项的 `status` 用 `pending`；冲突候选用 `conflict` 并填写 active ID。确认或拒绝候选时，把下列对象作为新事件的 `operation`：

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
