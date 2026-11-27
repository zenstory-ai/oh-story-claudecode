# 作者记忆协议

> 谁读：长短篇主会话管理作者习惯，或规划、改稿时查作者记忆读；写正文时组装脚本代查，不读。

保存作者明确说过、可跨会话复用的创作习惯。只记已确认条目，不记待确认/冲突候选；小说事实仍写进设定与追踪。

## 边界与优先级

从高到低：1. 安全、授权、平台交付、字数与文件协议（句长/视角/修辞/标点偏好不算硬门禁） → 2. 当前请求明确要求 → 3. 本书 `设定/文风.md`、题材定位、细纲与设定 → 4. 本书作者记忆 → 5. 题材/流程/全局作者记忆 → 6. 对标与通用方法。低优先级只补缺项，不改小说事实、审稿标准或剧情意图。

## 存放与路由

两级：`{工作区}/.story/作者记忆/` 存 global / genre / workflow（编号 `AP`）；`{书}/.story/作者记忆/` 存 book（编号 `BP`）。`作者画像.md` 与 `变更记录.md` 由 state 自动生成，勿手改（手改 `check` 报 `drift_warnings`）。

- `--workspace` 必传（多书根/`.active-book`/`长篇/`/`短篇/`/`拆文库/`所在目录，禁传用户主目录；独立单篇短篇未套工作区时传短篇目录）；涉及本书必传 `--book-root`。
- `forget` 按 `item_id` 路由，`remember`/`replace` 按 `scope.level` 路由。`replace` 不跨级：本书例外直接 `remember` 为 book；全局改本书拆 `forget` + `remember`。

## 查询

只查 active 条目。长篇写正文由组装脚本代查；其余按需查一次，只把输出 `lines`（上限 2048B，按重要度→本书例外→最近更新装填）交给执行者；`omitted_ids` 非空时按 `omitted_summaries` 原话告知作者并建议「整理作者记忆」：

| 任务 | `--kind` | 交给谁 |
|---|---|---|
| 正文初稿 / 续写 | `prose_style` + `story_design` | 主会话与正文 agent |
| 去 AI 味 / 改写 | `prose_style` | 主会话与改写 agent |
| 设定 / 大纲 | `story_design` + `workflow` + `interaction` | 主会话 |
| 审稿准备 | `delivery` + `interaction` + 必要的 `prose_style` | 主会话 |

## 记不记、记成什么

只记作者明确说的习惯，不擅自推断：

| 作者说了什么 | 处理 |
|---|---|
| “以后都这样”“我一直习惯……”等稳定、范围清楚的原话 | 记，`source=explicit_user` |
| 明确接受助手提出的长期做法 | 记，`source=accepted_suggestion` |
| 像长期习惯但范围含糊 | 先问「以后都这样吗？只管这本书还是都这样？」，确认再记 |
| 与已有习惯相反 | 问换掉旧的（`replace`）还是本次例外（只照做） |
| 一次性要求、成稿推测模式、小说设定/剧情事实 | 不记入 |

`quote` 写原话，`assertion` 一句话（≤120B，超长仅 `warnings`），例外合在同一条，背景写 `reason`。`scope.level`：`book | genre | workflow | global`；`kind`：`prose_style | story_design | workflow | delivery | interaction`；`confidence`/`importance`：`low | medium | high`；`source`：`explicit_user | accepted_suggestion | manual`。

## 改、忘与整理

- 同范围改版用 `replace`，撤回用 `forget`。
- **整理**：作者要求、有习惯漏带、或 `作者画像.md` >12288B / `变更记录.md` >24576B（均为软 `warnings`；单视图硬上限 65536B、state JSON 硬上限 2MB）时，读两级 `作者画像.md`，提议合并同义条（`replace`）、停用过时条（`forget`）、降重要度或压短断言，同意后逐条 `record`；旧版项目级「本书：」条目跑 `migrate --book-root` 迁回书级。

## 回执怎么告诉作者

返回 `Author Memory Receipt` 才算记住（不念编号、不提字节/prompt/kind/scope），只回一句白话，如「记住了：《{书名}》的对话一律用「」，以后写这本书都照这个来；想改随时说。」`warnings`/`omitted_ids` 用白话提醒漏带条目并建议「整理作者记忆」。

## 运行工具

从当前写作 skill 根运行本地副本：

```text
node {当前 skill 根}/scripts/author_memory_commit.js record  --workspace {工作区} [--book-root {书目录}] --input {工作区}/.story/work/作者记忆-事件.json
node {当前 skill 根}/scripts/author_memory_commit.js query   --workspace {工作区} --book-root {书目录} --kind {类型}（必传，可重复） [--genre {题材}] [--workflow {流程}]
node {当前 skill 根}/scripts/author_memory_commit.js migrate --workspace {工作区} --book-root {书目录}
node {当前 skill 根}/scripts/author_memory_commit.js check   --workspace {工作区} [--book-root {书目录}] [--strict]
```

- 每次记/改/忘为单事件 `record`（自动读修订、首次自动初始化）；事件 JSON 写 `{工作区}/.story/work/`，成功后删。同 `event_id` 同内容幂等，不同内容报错；`warnings` 不阻断写入，有回执勿换 `event_id` 重试。
- `migrate` 迁旧项目级本书条目（可重跑）；`check` 核派生视图，漂移默认 exit 0 报 `drift_warnings`（严格拦加 `--strict`）。

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

book 条目 `scope.value` 填书名（首次取目录名）。改、忘替换 `operation`（`BP` 编号传 `--book-root`）：

```json
{"action":"replace","old_ids":["AP001"],"preference":{"kind":"prose_style","scope":{"level":"global","value":null},"assertion":"以后对话允许更长的试探，但避免解释设定","quote":"……","source_ref":"conversation:2026-08-25","source":"explicit_user","confidence":"high","importance":"high","reason":"作者明确替换原有全局规则"}}
{"action":"forget","item_id":"AP003","quote":"忘掉这个偏好。","reason":"作者明确撤回"}
```
