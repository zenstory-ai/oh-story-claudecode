# 正文存储配置

首次建书时请作者选择不分卷或分卷，再将选择登记到书目录 `.story/storage.json`。这是本书的工程元信息，不存入跨书作者偏好。仅规划且尚未确定时可暂不登记，生成正文写作任务前必须确定。以后直接读取配置，不重新猜目录。大纲、设定、追踪、对标等目录协议固定，不开放自定义路径。

不分卷：

```json
{"schema_version": 1, "body_layout": "flat"}
```

分卷（章号全书连续，范围来自作者确认的卷纲）：

```json
{
  "schema_version": 1,
  "body_layout": "volumes",
  "volumes": [
    {"directory": "卷一_重生归来", "first_chapter": 1, "last_chapter": 30},
    {"directory": "卷二_新的开始", "first_chapter": 31, "last_chapter": 60}
  ]
}
```

卷目录只允许一层 `卷序号_卷名`，章节范围不能重叠；未覆盖的章号报错，不能擅自写进最后一卷。续写未规划章节前先与作者确定范围。配置文件的其他键会被拒绝，不能自定义正文根目录或其他工程目录。

使用宿主可用的 Python 解释器（依次探测 python3、python、py；下文 `{PYTHON}`），先将已确认配置保存为书目录 `.story/storage-proposal.json`，再执行：

```text
{PYTHON} <skill根>/scripts/storage_layout.py --project <书目录> init --config <书目录>/.story/storage-proposal.json
{PYTHON} <skill根>/scripts/storage_layout.py --project <书目录> show
{PYTHON} <skill根>/scripts/storage_layout.py --project <书目录> resolve --chapter 31 --title 新的开始
```

`init` 校验既有正文的位置和重复章号后才写配置，不创建正文、不移动文件、不覆盖已有配置；提案文件校验通过后可删除。更改已有布局或章节范围须走后续带备份的迁移流程，本阶段遇到变更要求先列路径方案，不手改配置绕过校验，也不自动创建 Git 分支。

读取已有章节和确定新章落点共用配置。已有章节保留原文件名，避免修订时另建同章文件；新章生成 `第NNN章_章名.md`。任意两个卷或直属目录存在同章号都报错，不能静默取第一份。配置与真实位置冲突时先解决迁移，不回退搜索其他目录。无配置的老书只兼容读取一层分卷正文，下一次写作先核对真实结构并登记；不自动把老书认作 flat。备份、隐藏目录和更深层目录不参与章节枚举。

本阶段接入写作组装及导入、审稿、字数工具；宿主 hooks 仍按既有一层分卷规则识别，配置位置守卫与可恢复迁移在后续阶段接入。
