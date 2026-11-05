# 正文布局转换

作者要求改正文存法、卷目录名或章节范围时读。这里的分卷是同一本书内部的目录，不是拆成多本书，也不自动重排剧情。只说“分卷发布”而含义不清时，一次确认是发布分组、正文分卷还是重排大纲；已明确的选择不重复问。

布局转换授权包含同步受影响的目录说明、链接和测试说明，不再另问“要顺手修改说明吗”。不改正文内容、大纲等固定目录位置；叙事上的第几卷和物理存储布局分开处理。

## 执行与验收

1. 读取 `.story/storage.json` 和正式章节；老书缺配置先执行 `show` 自动登记。把作者确认的目标布局写入 `.story/storage-proposal.json`，不猜分卷边界。作者只改存法，不重排卷纲或拆书。
2. 用下列命令冻结计划。核对章节总数、每章源/目标路径及待核对资料清单；已获得明确转换授权即可执行。计划后若正文或说明变了，重新生成计划。

```text
{PYTHON} <skill根>/scripts/storage_layout.py --project <书目录> plan-migration --config <书目录>/.story/storage-proposal.json --out <书目录>/.story/migration-plan.json
{PYTHON} <skill根>/scripts/storage_layout.py --project <书目录> migrate --plan <书目录>/.story/migration-plan.json
```

工具在 `.backup/正文迁移-时间-编号/` 保存完整正文、旧配置、关联资料原件与迁移回执，再移动正式章节。正文按字节哈希核对，章号与文件名不变。精确路径可自动替换，非文本格式和自由描述只列待核对；发生执行错误则撤回已移动文件并恢复配置及关联资料，备份保留。不要以删配置再 `init`、裸 `mv`、只修改卷纲代替转换。

3. 完整读取 `reference_review` 中每份资料，同轮修正目录树、步骤与当前结构描述。也检查项目根说明、测试说明、手写指南；活跃书目外层工作区资料标为 `@workspace/文件名`。备份、临时稿、对标原件、机器事件日志不做替换。固定目录不迁移，追踪的剧情卷信息不机械改成目录名；机器状态通过对应事务工具更新。
4. 修正后逐份登记核对，再复验。登记的是当前文件哈希，之后文件再变会重新进入待核对。精确旧路径残留不能靠登记跳过。

```text
{PYTHON} <skill根>/scripts/storage_layout.py --project <书目录> review-references --backup <本次备份目录> --files 测试说明.md README.md
{PYTHON} <skill根>/scripts/storage_layout.py --project <书目录> verify-migration --backup <本次备份目录>
```

`--files` 只列实际存在且已核对的相对路径。`needs_reference_review` 表示关联资料未完成；只有 `complete` 才能汇报整体完成。汇报给作者：改成什么结构、实际转换几章、正文内容是否一致、说明是否同步、备份位置。不能拿“卷纲已重排”或“配置已改”代替正文实际验收。

最后执行追踪检查；通过后再恢复写作。只做卷范围登记也走同一工具，避免覆盖配置或遗漏既有章。
