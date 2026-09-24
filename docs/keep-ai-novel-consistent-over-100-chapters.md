# How to keep an AI writing agent from breaking character over 100+ chapters

**Short answer:** stop asking the model to remember the book. Put the story state in files, load only the slice a chapter needs, and write the changes back with a script. That is how Oh Story (`zenstory-ai/oh-story-claudecode`, MIT, 6.8k stars, 13 agent skills for Claude Code, Codex CLI, OpenCode and other coding agents) runs "daily update" batches of three chapters at a time without the cast drifting.

This page describes the mechanism as shipped in v0.7.10. It is not a claim that nothing ever goes wrong across 300 chapters.

中文版：[AI 写长篇小说怎么不崩人设](ai-long-novel-character-consistency.md)

## Why agents drift

Every drift bug reduces to one question: what did the model see when it wrote this chapter? If it saw "the last few chapters", it forgot the clue planted in chapter 3. If it saw "a summary of the whole book", it treated a planned future event as something that already happened. A bigger context window does not fix this. A novel is longer than any window, and the more you stuff in, the less attention any single fact gets.

So the fix is not memory. It is selection.

## The four-layer project

A long-form project in Oh Story looks like this (from the README's project structure):

```text
{book}/
├── 设定/          # world, one file per character, factions, relations
├── 大纲/          # book outline, per-volume outline, per-chapter brief
├── 正文/          # chapter prose
└── 追踪/          # file-first continuity state
    ├── _tracking-state.json   # the only structured source of truth
    ├── 上下文.md              # derived state card, fixed 7 sections, ≤12KB
    ├── 逐章记录/              # per-chapter delta, ≤3072 bytes each
    ├── 角色状态/              # current snapshot per core character
    ├── 伏笔.md                # open and paid-off setups
    └── 时间线/                # author-truth.md + reader-known.md
```

Three design rules do the work:

1. **One authority, everything else derived.** `_tracking-state.json` is the only writable truth. The state card, character snapshots, setup list and both timelines are generated from it deterministically. All writes go through `scripts/tracking_commit.py`; hand-editing derived files is forbidden. Two files can never disagree about where a character is.
2. **Author truth and reader knowledge are separate timelines.** `时间线/作者真相.md` records what actually happened in the story. `时间线/读者已知.md` records what the reader has seen so far. When the model writes chapter 40 it can see who the murderer is, and also that the protagonist does not know yet, so it will not let a character blurt out the answer.
3. **Per-chapter writes are capped deltas.** Each `逐章记录/第NNN章.md` targets ≤1536 bytes with a hard cap of 3072, and records only changes that affect later chapters. State does not grow linearly with chapter count. The context for chapter 300 is about the same size as for chapter 30.

## What one chapter actually does

From `story-long-write`'s single-chapter flow:

1. **Reference gate, read before write.** Load the chapter brief, the volume outline and the current tracking state, then build a Constraint Lock: word range, must-happen, must-not-happen, time anchors, where the chapter stops, what new debt it opens. These project facts override any craft reference.
2. **Load only what would otherwise be wrong.** For each character on stage, read `设定/角色/{name}.md` (stable characterization) and `追踪/角色状态/{name}.md` (current location, goal, relationships, what they know, open threads). "Xu Tang has an older brother" is characterization. "Xu Tang does not know the letter came from him" is state. Reading them separately is what stops the model from turning a fact into character knowledge.
3. **Write the prose.**
4. **Commit the delta.** `tracking_commit.py` records who learned what, which setup paid off, how far time moved. Derived files refresh.
5. **Review.** `story-review` can spawn parallel reviewer agents, including a consistency checker, against the settings and tracking files. If the agents are not deployed it degrades to a single-thread review instead of skipping.

This is why a three-chapter batch keeps working: each chapter starts from a fresh state card, not from an ever-growing chat transcript.

## Already 40 chapters in, no tracking files?

Run `/story-setup`, then `/story-import` to reverse-parse the existing manuscript into the structure above. It produces first-pass settings, character states and setups. Inferred facts are listed as "to confirm" rather than written as truth; review them, then continue with `/story-long-write`.

## Limits

- Tracking reduces two classes of error: forgetting, and characters knowing things early. It does not choose the plot for you and it does not guarantee zero errors.
- It only works if the author actually writes settings and chapter briefs. A missing chapter brief pauses for confirmation, and since v0.7.7 a brief without a word target stops instead of falling back to a default 3000 characters.
- Everything runs inside the coding agent you already use. No GPU, no self-hosted model.

## Related

- Install: `npx skills add zenstory-ai/oh-story-claudecode -y -g`, then `/story-setup` inside the agent.
- Site guide with a worked three-chapter example: https://zenstory.ai/oh-story/long-novel-continuity
- Chapter outline template (what each chapter must change, and what stays hidden): https://zenstory.ai/oh-story/chapter-outline-template
- Implementation notes: `skills/story-long-write/references/state-tracking.md`, `tracking-transaction.md`
- Repository: https://github.com/zenstory-ai/oh-story-claudecode (formerly `worldwonderer/oh-story-claudecode`; old links redirect)
