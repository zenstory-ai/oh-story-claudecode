# 作者记忆协议

> 谁读：长短篇主会话管理作者习惯，或规划、改稿时查作者记忆读；写正文时组装脚本代查，不读。

作者记忆由长短篇写作 skill 管理，保存作者明确说过、可跨会话复用的创作习惯。只记作者确认过的条目：不记待确认候选，也不记冲突候选。小说事实仍写进本书设定与追踪。

## 边界与优先级

加载优先级从高到低：

1. 安全、用户授权范围、明确的平台交付要求、字数与文件协议；句长、视角、修辞和标点偏好不属于不可覆盖的硬门禁；
2. 用户在当前请求中的明确要求；
3. 当前书的 `设定/文风.md`、题材定位、细纲和其他项目设定；
4. 作者记忆中的本书习惯；
5. 作者记忆中的题材、流程和全局习惯；
6. 对标素材、通用方法和默认值。

按句式、节奏与用词取最窄适用要求：低优先级只补缺项，不与高优先级要求并列执行。通用 references 自称“必须/禁用”不改变此顺序；审稿不因作者有意采用的表达本身扣分，真实可读性与因果问题仍照常评价。作者记忆不写本书事实，不降低审稿 rubric，也不让去 AI 味改动剧情意图。

## 存放与路由

记忆分两级：`{工作区}/.story/作者记忆/` 存 global / genre / workflow 条目，编号 `AP`；`{书}/.story/作者记忆/` 只存本书的 book 条目，编号 `BP`。每级的 `作者画像.md`（生效条目）和 `变更记录.md` 都从 state 生成，禁止手改；旧版留下的 `待确认.md` 下次写入时自动删掉。记忆不存在时照常创作，首次 `record` 自动创建。

- `--workspace` 必须显式传，指承载多本书、`.active-book`、`长篇/`、`短篇/` 或 `拆文库/` 的那一层；已有记忆时，是项目级 state 所在的最近祖先。`长篇/`、`短篇/` 下的书目录永远不当 `--workspace`，也不把用户主目录当默认工作区。
- `--book-root` 是当前书目录（长篇含 `设定/`、`正文/`，短篇含 `设定.md`、`正文.md`），写某本书时一律带上。书根就是工作区时，书级记忆住 `{工作区}/.story/作者记忆/书级/`，工具自动处理；工具说这个目录其实是某个工作区里的一本书时，按报错改传 `--workspace`。
- 编号前缀就是去向：`forget` 看 `item_id`，`remember` / `replace` 看 `scope.level`（`book` 书级，其余项目级）。`replace` 不跨级：本书例外直接 `remember` 为 book 条目，不算与全局冲突；要把全局规则改成本书规则，拆成 `forget` ＋ `remember`。

## 查询

只查生效（active）条目；老库里的待确认、冲突条目不进任何查询。长篇写正文由组装脚本代查；其他任务自己查一次，结果只把输出的 `lines` 交给执行者，完整画像、证据、变更记录不进上下文：

| 任务 | `--kind` | 交给谁 |
|---|---|---|
| 正文初稿 / 续写 | `prose_style` + `story_design` | 主会话与正文 agent |
| 去 AI 味 / 改写 | `prose_style` | 主会话与改写 agent |
| 设定 / 大纲 | `story_design` + `workflow` + `interaction` | 主会话，不传正文 agent |
| 审稿准备 | `delivery` + `interaction` + 必要的 `prose_style` | 主会话，不降低 rubric |

本书题材、写作流程有限定条目时带 `--genre`／`--workflow` 各查一次，合并去重。查询项作为低优先级倾向自然吸收，不为逐条命中牺牲连贯、节奏、字数或本书笔调。每次查询的 `lines` 不超过 2048 字节，按重要度 → 本书例外 → 最近更新装填；**`omitted_ids` 非空表示有习惯没带上**：照 `omitted_summaries` 用原话告诉作者，并建议说「整理作者记忆」。

## 记不记、记成什么

不装记录全部用户消息的 hook，不在作者没开口时观察他，只记作者明确说的习惯。

| 作者说了什么 | 处理 |
|---|---|
| “以后都这样”“我一直习惯……”等直接、稳定、范围清楚的原话 | 记，`source=explicit_user` |
| 作者明确接受助手提出的长期做法 | 记，`source=accepted_suggestion` |
| 像长期习惯但范围或稳定性含糊 | 先问一句「以后都这样吗？只管这本书还是都这样？」，作者确认了再记；没确认只照做、不记 |
| 与已有习惯相反 | 问作者是换掉旧的还是这次例外：换掉用 `replace`，例外只照做 |
| “这一章别……”“这次给我……”等一次性要求 | 只执行，不记录 |
| 同类修改反复出现、从成稿看出的模式 | 不记录、不推断 |
| 角色、时间线、伏笔、世界观、剧情走向 | 写项目设定/追踪，不写作者记忆 |

保留否定词、限定词和适用范围：`quote` 写原话，`assertion` 只做不改变语义的紧凑归纳，**新建条目限一句话（≤120 字节，约 40 个字）**，背景写进 `reason`（不进 prompt）。**一条习惯就是一条记录，例外和限定不许拆出去单列**：「以后少用破折号，对话里也别用，除非表示打断」整条写成「破折号少用、对话里也不用，只在表示打断时保留」；只有原话塞了几条互不依赖的习惯才拆。

范围：“本书 / 这个角色” → `book`；“都市文 / 这类题材” → `genre`；交稿、检查、确认节奏等操作习惯 → `workflow`；“以后 / 一贯”且无更窄限定 → `global`。类型：`prose_style`、`story_design`、`workflow`、`delivery`、`interaction`。置信度与重要度均为 `low | medium | high`，按实际分量填，不要一律 `high`（超编时先丢重要度低的）。`source` 只接受 `explicit_user`、`accepted_suggestion`、`manual`。

## 改、忘与整理

- 同一类型、范围、归纳文本再出现，脚本强化原条目，不重复建条；老库里的待确认条目被作者原话再说一次就生效。
- 同一范围的规则改版用 `replace`（新条目生效、旧条目停用）；作者说“忘掉 / 这不再是我的习惯”用 `forget`。生效条目的意思不可原地偷改。
- **整理作者记忆**：作者说要整理，或有习惯没带上、`作者画像.md` 超过 12288 字节写不进时，读项目级与当前书的 `作者画像.md`，提出合并同义条（`replace` 多合一）、停用过时条（`forget`）、下调错标成 `high` 的重要度、把超长断言压成一句话；用原话逐条列给作者，作者同意后逐条 `record`。合并时保住否定词、限定词和范围，合不动就停用其中一条。项目级画像里还有「本书：」旧条目时，对那本书跑一次 `migrate --book-root` 把它们搬回书里。

## 回执怎么告诉作者

只回一句人话，说记住了什么、管哪本书或哪类场合，如「记住了：《{书名}》的对话一律用「」，以后写这本书都照这个来；想改随时说。」改、忘同理：「换成了：……，原来的「……」不再用」「忘掉了：……」。工具返回 `Author Memory Receipt` 才算记住，没有回执不得说“已经记住”；回执编号不念给作者。`warnings` / `omitted_ids` 不原样贴：说「你的习惯攒得有点多，写正文时这几条可能带不上：「……」」，建议说「整理作者记忆」。不提字节、prompt、kind、scope。

## 运行工具

依次尝试 `python3`、`python`、`py -3` 找到 Python 3，从当前写作 skill 根运行本地副本：

```text
{PYTHON} {当前 skill 根}/scripts/author_memory_commit.py record  --workspace {工作区} [--book-root {书目录}] --input {工作区}/.story/work/作者记忆-事件.json
{PYTHON} {当前 skill 根}/scripts/author_memory_commit.py query   --workspace {工作区} --book-root {书目录} --kind {类型}（必传，可重复） [--genre {题材}] [--workflow {流程}]
{PYTHON} {当前 skill 根}/scripts/author_memory_commit.py migrate --workspace {工作区} --book-root {书目录}
{PYTHON} {当前 skill 根}/scripts/author_memory_commit.py check   --workspace {工作区} [--book-root {书目录}]
```

- 每次记、改、忘都是一份单事件 `record`：自动读当前修订、首次自动初始化。事件 JSON 写在 `{工作区}/.story/work/`，成功后删掉；同一 `event_id` 内容相同不重复写，内容不同则失败。写入不因加载上限失败，`warnings` 只是提醒，有回执就是记住了，不要换 `event_id` 重试。
- `migrate` 把旧版写在项目级的本书条目搬进书级（可重复跑，失败直接重跑）；`check` 核对自动生成的视图，出错时才用。

## 事件格式

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
      "reason": "用户以“以后”明确声明长期偏好"
    }
  }
}
```

book 条目的 `scope.value` 填书名（书级已记的名字，首次取目录名）。改、忘时把下列对象换进 `operation`（`BP` 编号传 `--book-root`）：

```json
{"action":"replace","old_ids":["AP001"],"preference":{"kind":"prose_style","scope":{"level":"global","value":null},"assertion":"以后对话允许更长的试探，但避免解释设定","quote":"……","source_ref":"conversation:2026-08-25","source":"explicit_user","confidence":"high","importance":"high","reason":"作者明确替换原有全局规则"}}
{"action":"forget","item_id":"AP003","quote":"忘掉这个偏好。","reason":"作者明确撤回"}
```
