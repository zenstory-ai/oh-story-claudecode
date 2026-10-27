# 逐批反推细纲（长篇导入）

卷纲写定后，从章节摘要反推每章细纲，一批一个任务包。进度记在导入记录（`{书目录}/.story/work/导入记录.md`）的「细纲：已验收到第 B 章」；续跑从第 B+1 章起整批重做，这一批里已经存在但没验收的细纲文件按新任务包重写覆盖。

## Step 1：生成本批任务包

按当前平台探测 Python 3（`python3` → `python` → `py -3`），请求第 B+1 章起的 20 章（剩下不足 20 章就到最后一章）：

```text
{PYTHON} {story-import skill 根}/scripts/build_outline_brief.py --project {书目录} --chapters {A-B}
```

脚本把规则模板（[outline-reverse-rules.md](outline-reverse-rules.md) 全文）、实测历史长度、摘要要点与本批单元卡写成 `{书目录}/.story/work/排纲/导入细纲_第AAA-BBB章.md`。每章须唯一归属单元，历史长度按 `visible_chars_v1`。读取量含包与补读正文：缺失或不完整摘要按全章计补读上限，超过约 25K 时少排几章（可少于 10 章）。以 stdout JSON 的 `chapters` 为实际范围、`next` 为下批起点，`null` 表示末章。

长度必须由脚本测，不得用模型估算或静默跳过。找不到 Python 3 或脚本报错时停下，用一句话告诉作者卡在哪（如「第 12 章正文读不到，先把正文迁完」），原文报错放技术备注；卷纲缺失、单元缺覆盖或重叠时，先回结构迁移补卷纲。

## Step 2：写本批细纲

- **有 story-architect**（导入记录写着可用，按 SKILL.md 顶部的当前宿主角色来源检查，ZCode 查插件注册角色）：主会话只取任务包路径，不读包的内容。Prompt：`项目目录：{dir}\n任务包：{任务包路径}\n先完整读取任务包，按包里的规则与模板完成；作者已定的事在 .story/work/导入记录.md，对话内容不会传给你\n交付后只回任务包开头要求的几项`。Antigravity 用 `invoke_subagent` + `TypeName: "story-architect"`。
- **没有**：主会话完整读取任务包，按包内规则写本批；不另读包外写作技法，也不整读拆文库摘要。

## Step 3：验收与交接

每批写完由主会话运行 `node {story-import skill 根}/scripts/check-outline-contract.js --json <本批细纲路径...>`：exit 1 时只按报告补缺的字段或小节（有 story-architect 时把报错原样交回同一 agent 修一次）。通过后把导入记录的细纲进度改成「已验收到第 B 章」。还有下一批时，向作者一句话说到第几章了，末尾按 [SKILL.md 的换上下文规则](../SKILL.md#时刻表与交接) 建议新开对话说「继续导入」；没有子代理时每批都这样建议。全部章节细纲写完再进 Phase 4。
