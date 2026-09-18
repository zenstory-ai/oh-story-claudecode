# Agent Note: README 顶部的演示是真实录屏，仓库 demo 跟着视频走

Status: implemented

## Problem

README 瘦身前是 543 行说明文字，没有一处让读者看到 skill 真正跑起来的样子。第一版演示视频用 Remotion 动效「模拟」了一个终端，维护者一眼判定为假；第二版真录了，但审阅发现片中的第 21 章与仓库 `demo/长篇` 里的第 21 章不是同一次运行（文件名、字数、伏笔都对不上），读者看完视频点进 demo 会发现对不上。此外视频文件不能进仓库（`npx skills add` 会整库克隆）。

## Decision

- README 顶部（中英）嵌入一段**真实录屏**：tmux 100×24 里的 Claude Code 会话，asciinema 录 cast，在 cast 层做分段倍速与跳切（`retime`），agg 渲染，Remotion 只加片头片尾与底部角标。删掉 ≥ 1 分钟处角标写「跳过 · 实际 mm:ss」，倍速处写「×N · 实际 mm:ss」，静帧写「定格」。
- **仓库 demo 跟视频走，不反过来**：`demo/长篇/让你管账号，你高燃混剪炸全网` 的第 21 章、细纲、追踪状态、`.deslop-whitelist`、新角色卡，全部原样同步自录制那次会话的产物（`sync_run_to_demo.py` 只复制 `大纲/ 设定/ 正文/ 追踪/`），README 里引用的数字（2068 / 2300、F057/F058）与回写 diff 也取自同一次运行。补录会话改动的文件同样同步。
- 视频托管在 GitHub user-attachments（PR 评论里发布一次即可匿名可达），仓库不含任何视频文件；README 用 `<video src=…>`，`poster` / `width` 在 GitHub 上会被 sanitizer 剥掉，不写。
- 录制环境固定：项目层 `.claude/settings.json` 钉死简体回复、停用无关 plugin、清空 statusLine、免提示权限；录前把上一次录影的副本目录移出书稿父目录。
- 视频只回答网文作者的四个顾虑（这是给我的 / 不难 / 它读过我的书 / 写出来能看 / 我说了算），不演门禁术语；教学交给 README 正文「看看它的输出」。

来源：#434

## Alternatives considered

- **Remotion 动效模拟终端**——最强理由：可控、每一帧都好看、不用等一小时真跑。否：观众一眼看出是假的，对「AI 写的网文能不能看」这个成见零说服力。
- **视频跟仓库 demo 走（按仓库里已有的第 21 章重录一遍）**——最强理由：不动仓库。否：真跑每次产出都不同，永远追不上；反过来让 demo 同步自录制产物，只需一个同步脚本，且 demo 因此获得「一次真实会话的完整产物」这个更强的身份。
- **视频文件入库 / 走 Git LFS**——最强理由：不依赖 user-attachments 这种非正式托管。否：`npx skills add` 整库克隆，2 MB 起步且每次重剪都累加；LFS 对 skill 安装器不透明。
- **同时出竖版**——最强理由：短视频平台可用。否：只有一个维护者，README 才是目标位置，先不做。

## Consequences

- **收益**：README 首屏 40 秒内回答「装了会怎样」；视频、README 数字、demo 文件三者互证；重剪只改 `spec.json` 与 Remotion，不碰母带。
- **代价与已知上限**：每次重录都要同步 demo 并重跑 `chapter check` / `tracking_commit.py check`；user-attachments 的链接由 GitHub 托管，无法自建 CDN 或加封面图；母带里的路径（`/Users/<user>/写作/…`）会入镜，下次录制换目录。

## Verification

`python3 skills/story-long-write/scripts/tracking_commit.py check --project demo/长篇/让你管账号，你高燃混剪炸全网` → `last_committed_chapter 21, state_revision 1`；`storyctl.py chapter check --chapter 21` → 2068/2300 internal_pass；GitHub 渲染的 README 含 `<video src="https://github.com/user-attachments/assets/…">`，匿名 HEAD 302。
