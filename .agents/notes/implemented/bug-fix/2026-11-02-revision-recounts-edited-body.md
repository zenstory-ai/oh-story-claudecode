# Agent Note: 正文改过的修订提交直接重新计数，不再要作者换工具

Status: implemented
Related: [其余 skill 按时刻读](../architecture/2026-10-17-other-skills-by-moment.md)

## Problem

章节提交后又去味或审稿改了正文，字数记录还钉着旧正文。之后按 story-review 的追踪修订流程跑 `tracking_commit.py commit`，脚本以「第N章正文已改」拒收，要作者转 `/story-long-write` 用 `storyctl.py chapter commit` 重交。2026-11-02 复现：已提交的第 1 章改一句后走审稿修订，exit 2；原先的决定（2026-10-17）是「不重试，请作者转 /story-long-write」。去味改句子是常规动作，每次都换一个工具重交，作者要理解一个与改稿无关的记账问题。

## Decision

- `tracking_commit.py` 的修订提交发现正文或字数目标改过时，按现文件重新计数并把新记录随同一事务写入。改后仍在作者范围内记 `within_user_band`；作者原先接受了带外长度、改后仍在带外，沿用 `accepted_current_length`。
- 只有原本在范围内、改后出了范围才拒收，报改了哪一项和「字数出了作者范围」，仍指向 `accept-current-length`，因为那是作者对长度的决定。
- story-review 的 review-tracking 第 5 步改成只在这种情况下停下。三份 `tracking_commit.py` 经 sync-shared-assets 同步。
- 回归：`test-tracking-commit.py` 的 `test_revision_recounts_a_body_edited_after_commit`。

## Alternatives considered

- **在 check 里加一条「正文已改」提醒**：最强理由是改动小、提醒得早。没采用：多一条要作者理解并照做的提示，后面照样要换工具重交，负担没减。
- **保持拒收，只把报错写得更清楚**：最强理由是修订仍经过 `storyctl` 的 blocking 检测再记账。没采用：审稿和去味本身就是改稿检查，拒收只换来一次换工具；长度这件需要作者拍板的事仍然拦着。

## Consequences

- 收益：去味、审稿后的修订一次提交完成，字数记录总是对着现正文。
- 代价：经 `tracking_commit.py` 直接提交的修订不再重跑 `storyctl` 的 blocking 质量检测；需要检测时仍走 `storyctl.py chapter commit`。
