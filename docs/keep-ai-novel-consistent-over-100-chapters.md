# How to keep an AI writing agent from breaking character over 100+ chapters

Keep story state in files, load only the slice each chapter needs, and commit changes through the tracking tools. Oh Story (`zenstory-ai/oh-story-claudecode`, MIT, 14 skills for Claude Code, Codex CLI, OpenCode, and other coding agents) uses structured tracking files to cut down character drift, dropped setups, and characters knowing things too early.

中文版：[AI 写长篇小说怎么不崩人设](ai-long-novel-character-consistency.md)

## Why agents drift

A common cause of continuity errors is the information the model receives for a chapter. If it saw "the last few chapters", it forgot the clue planted in chapter 3. If it saw "a summary of the whole book", it treated a planned future event as something that already happened. Loading more text does not replace the need to distinguish facts, plans and character knowledge.

Select the facts needed for this chapter and identify plans that have not happened yet.

## The four-layer project

A long-form project in Oh Story looks like this (from the README's project structure):

```text
{book}/
├── 设定/          # world, one file per character, factions, relations
├── 大纲/          # book outline, per-volume outline, per-chapter brief
├── 正文/          # chapter prose
└── 追踪/          # file-first continuity state
    ├── _tracking-state.json   # the only structured source of truth
    ├── 上下文.md              # derived state card, fixed 7 sections (12 KiB soft target, 64 KiB hard cap)
    ├── 逐章记录/              # per-chapter delta (3072B soft target, 64 KiB hard cap)
    ├── 角色状态/              # current snapshot per core character
    ├── 伏笔.md                # open and paid-off setups
    └── 时间线/                # author-truth.md + reader-known.md
```

Three design rules do the work:

1. **One authority, everything else derived.** `_tracking-state.json` is the only writable truth. The state card, character snapshots, setup list and both timelines are generated from it deterministically. Normal writes go through `scripts/tracking_commit.js`. `tracking_commit.js check` re-renders from state and compares each derived file: if a derived file was hand-edited, default `check` exits `0` with non-blocking `drift_warnings` prompting whether to absorb the edits into JSON or rebuild (pass `--strict` to fail on drift). A transaction’s expected revision separately prevents stale writes.
2. **Author truth and reader knowledge are separate timelines.** `时间线/作者真相.md` records what actually happened in the story. `时间线/读者已知.md` records what the reader has seen so far. When the model writes chapter 40 it can see who the murderer is, and also that the protagonist does not know yet, so it will not let a character blurt out the answer.
3. **Per-chapter writes are compact deltas.** Each `逐章记录/第NNN章.md` targets ≤1536 bytes (soft warning above 3072 bytes) and records only changes that affect later chapters. Historical records continue to grow, while the current state card targets ≤12 KiB (soft warning above 12 KiB); both views share a **64 KiB (65,536-byte) hard safety cap**. Older information is queried when needed; the full history stays out of prose prompts.

## What one chapter actually does

From `story-long-write`'s single-chapter flow:

1. **Reference gate, read before write.** Load the chapter brief, the volume outline slice and current plot unit selected by the outline tool, and the current tracking state, then record this round's constraints before writing: word range, must-happen, must-not-happen, time anchors, where the chapter stops, and what new thread it opens. These book-specific facts override any craft reference.
2. **Load only what would otherwise be wrong.** For each character on stage, read `设定/角色/{name}.md` (stable characterization) and `追踪/角色状态/{name}.md` (current location, goal, relationships, what they know, open threads). "Xu Tang has an older brother" is characterization. "Xu Tang does not know the letter came from him" is state. Reading them separately stops the model from turning background facts into character knowledge.
3. **Write the prose.**
4. **Check and revise.** Chapter checks cover approved plot points, length, phrasing, and degeneration. Consistency review runs when needed, and before commit for a standalone chapter. A separate `/story-review` request runs multi-perspective review, falling back to single-session review when specialist agents are unavailable.
5. **Commit the delta.** After checks, `storyctl.js chapter commit` updates the tracking state to record new knowledge, paid-off setups, and timeline progress. Move to the next chapter only after the commit refreshes the derived files.

That keeps a three-chapter daily batch steady: every chapter starts from a fresh state card instead of a sprawling chat history.

## Already 40 chapters in, no tracking files?

Run `/story-setup`, then `/story-import` to rebuild the existing manuscript into the directory layout above, generating first-pass settings, character states, and setups. Guessed details are flagged as "to confirm" and held back until you review them; after checking, continue with `/story-long-write`.

## Limits

- Tracking reduces two classes of error: forgetting, and characters knowing things early. It does not choose the plot for you and it does not guarantee zero errors.
- It only works if the author actually writes settings and chapter briefs. A missing chapter brief pauses for confirmation, and since v0.7.7 a brief without a word target stops instead of falling back to a default 3000 characters.
- The workflow runs inside your coding agent. A hosted model requires no extra local GPU or model deployment.

## Related

- Install: `npx skills add zenstory-ai/oh-story-claudecode -y -g`, then `/story-setup` inside the agent.
- Site guide with a worked three-chapter example: https://zenstory.ai/oh-story/long-novel-continuity
- Chapter outline template (what each chapter must change, and what stays hidden): https://zenstory.ai/oh-story/chapter-outline-template
- Implementation notes: `skills/story-long-write/references/tracking-transaction.md`
- Repository: https://github.com/zenstory-ai/oh-story-claudecode (formerly `worldwonderer/oh-story-claudecode`; old links redirect)
