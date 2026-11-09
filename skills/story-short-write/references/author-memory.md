# 作者记忆协议

> 谁读：长短篇主会话管理作者习惯，或规划、改稿时查作者记忆读；写正文时组装脚本代查，不读。

作者记忆由长短篇写作 skill 管理，保存作者明确说过、可跨会话复用的创作习惯。只记作者确认过的条目：不记待确认候选，也不记冲突候选。小说事实仍写进本书设定与追踪。

## 边界与优先级

优先级从高到低：1. 安全、授权范围、平台交付、字数与文件协议（句长、视角、修辞、标点偏好不算硬门禁） → 2. 当前请求明确要求 → 3. 本书 `设定/文风.md`、题材定位、细纲与设定 → 4. 本书作者记忆 → 5. 题材、流程与全局作者记忆 → 6. 对标素材与通用方法。低优先级只补缺项，不与高优先级并列执行；作者记忆不写小说事实、不降低审稿 rubric、不改剧情意图。

## 存放与路由

分两级：`{工作区}/.story/作者记忆/` 存 global / genre / workflow 条目（编号 `AP`）；`{书}/.story/作者记忆/` 存本书 book 条目（编号 `BP`）。每级的 `作者画像.md` 和 `变更记录.md` 由 state 自动生成，禁止手改。

- `--workspace` 必传（承载多本书、`.active-book`、`长篇/`、`短篇/` 或 `拆文库/` 的目录，不得传书目录或用户主目录）；写某本书时必传 `--book-root`。
- `forget` 按 `item_id` 路由，`remember` / `replace` 按 `scope.level` 路由。`replace` 不跨级：本书例外直接 `remember` 为 book 条目；全局改本书拆成 `forget` + `remember`。

## 查询

只查 active 条目。长篇写正文由组装脚本代查；其他任务按需查一次，只把输出的 `lines`（上限 2048 字节，按重要度 → 本书例外 → 最近更新装填）交给执行者，`omitted_ids` 非空表示有习惯没带上，照 `omitted_summaries` 用原话告诉作者并建议「整理作者记忆」：

| 任务 | `--kind` | 交给谁 |
|---|---|---|
| 正文初稿 / 续写 | `prose_style` + `story_design` | 主会话与正文 agent |
| 去 AI 味 / 改写 | `prose_style` | 主会话与改写 agent |
| 设定 / 大纲 | `story_design` + `workflow` + `interaction` | 主会话 |
| 审稿准备 | `delivery` + `interaction` + 必要的 `prose_style` | 主会话 |

## 记不记、记成什么

只记作者明确说的习惯，不在作者未开口时推断：

| 作者说了什么 | 处理 |
|---|---|
| “以后都这样”“我一直习惯……”等稳定、范围清楚的原话 | 记，`source=explicit_user` |
| 明确接受助手提出的长期做法 | 记，`source=accepted_suggestion` |
| 像长期习惯但范围含糊 | 先问「以后都这样吗？只管这本书还是都这样？」，确认再记 |
| 与已有习惯相反 | 问换掉旧的（`replace`）还是本次例外（只照做） |
| 一次性要求、从成稿看出的模式、小说设定/剧情事实 | 不记入作者记忆 |

`quote` 写原话，`assertion` 限一句话（≤120 字节），例外和限定合在同一条记录里，背景写进 `reason`。范围：`book` / `genre` / `workflow` / `global`；类型：`prose_style` / `story_design` / `workflow` / `delivery` / `interaction`；置信度与重要度：`low | medium | high`；`source`：`explicit_user | accepted_suggestion | manual`。

## 改、忘与整理

- 同范围规则改版用 `replace`，撤回用 `forget`。
- **整理作者记忆**：作者要求整理、有习惯没带上、或 `作者画像.md` 超 12288 字节时，读项目级与本书 `作者画像.md`，向作者提议合并同义条（`replace`）、停用过时条（`forget`）、下调重要度或压短断言，同意后逐条 `record`；旧版项目级「本书：」条目跑 `migrate --book-root` 迁回书级。

## 回执怎么告诉作者

工具返回 `Author Memory Receipt` 才算记住（不念编号、不提字节/prompt/kind/scope），只回一句人话，如「记住了：《{书名}》的对话一律用「」，以后写这本书都照这个来；想改随时说。」`warnings` / `omitted_ids` 用白话提示：「你的习惯攒得有点多，写正文时这几条可能带不上：「……」」，建议「整理作者记忆」。

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
