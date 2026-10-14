# Agent Note: 发布平台书籍资料与写作产物交接

Status: implemented

## Problem

`story-publish-details` 已能按番茄的带版本资料核对建书字段，但还没有进入本仓库的路由。作者完成长篇或短篇规划后，书名、平台、题材、主角和剧情事实已落盘；若发布资料流程忽略这些文件，会重复询问或凭空补写。`story-cover` 已能构建平台封面提示词，但现有流程会继续生图，无法只把提示词交给作者审阅。

## Decision

- 把 `story-publish-details` 作为独立 skill 接入仓库和 `story` 路由，明确其交付物是发布平台的书籍资料，不触发长篇规划或正文写作。
- 只读复用长篇的 `设定/题材定位.md`、角色卡、大纲/细纲，短篇的 `设定.md`、`小节大纲.md`，以及作者已确认的现有资料。作品事实可支持候选书名、简介和标签；平台候选值与限制仍只由本 skill 的带版本参考文件决定。
- 给 `story-cover` 增加“仅提示词”模式：有已确认的书名、笔名、平台和题材时复用其提示词构建，不调用生图工具、不要求输出目录。实际封面生成仍走原流程。
- 新 skill 依照仓库格式保留独立参考文件，不直接引用兄弟 skill 的 reference；按需调用兄弟 skill 的公开入口。
- 发布资料定稿后写入书目录的 `发布资料-<平台>.md`；长篇对应 `正文/` 上一级，短篇对应 `正文.md` 所在目录。必填项与本轮要求的可选项未解决前不落盘，更新旧文件前核对手工修改。
- 更新 14-skill 发现、ZCode 命令、文档预算与适配器校验；在 ClawHub 清单中将 fork 本地新增 skill 标为暂不发布，等待单独的发行审查。

## Alternatives considered

- **把平台字段直接加进 `story-long-write`**：能接上既有规划产物。否：短篇和导入作品也需要建书资料，且平台表单版本与写作工作流的更新节奏不同。
- **复制 `story-cover` 的风格库到新 skill**：无需改现有封面流程。否：复制后会产生两套题材与平台风格规则，后续更容易漂移。
- **每次由 `story-publish-details` 直接生图**：一次拿到完整封面。否：作者可能只需要提示词或尚未确认笔名；封面又不是番茄建书必填项。

## Consequences

- 收益：已有写作工程可以作为发布资料的事实来源，封面提示词可以单独审阅，平台字段仍可追溯到带版本的选项清单。
- 收益：已确认的发布资料留在本书工程中，后续建书或跨会话核对不依赖聊天记录。
- 代价：新增 skill 会影响仓库的 skill 计数、路由和分发校验；`story-cover` 要维护两种输出模式。新模式不保证平台实际审核通过，最终以当前后台表单为准。

## Verification

- `scripts/static-check.sh`、`scripts/check-doc-budget.sh`、`scripts/check-shared-files.sh`、`scripts/check-zcode-adapter.sh`、`scripts/check-reasonix-adapter.sh`、`scripts/check-openclaw-skills.sh` 和 `scripts/check-plugin-packaging.py` 通过。
- Codex adapter 检查通过 Python/Hook 阶段，但本机 checkout 的 `.agents/skills` 不是符号链接，在仓库既有的符号链接门禁处停止；需在支持 Git symlink 的环境复验。
