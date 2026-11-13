---
trigger: always_on
---

# oh-story writing project rules

This workspace uses the oh-story web-fiction skills in `.agents/skills/`.
Read the selected skill's `SKILL.md` first, then load references as it directs.

## Routing

- Long-form writing or continuation: `story-long-write`
- Short-form writing: `story-short-write`
- Long/short deconstruction: `story-long-analyze` / `story-short-analyze`
- Long/short market scan: `story-long-scan` / `story-short-scan`
- Remove AI-writing patterns: `story-deslop`
- Adversarial review: `story-review`
- Import an existing story: `story-import`
- Cover generation: `story-cover`
- Publishing preparation (book title, synopsis, platform tags): `story-publish`
- Ambiguous story intent: `story`
- Project deployment/update: `story-setup`
- Reuse an authenticated Chrome session: `browser-cdp`

## Writing guardrails

- Keep every story artifact, temporary drafting segment, tracking transaction,
  and generated project directory inside the current workspace. Never create or
  continue an oh-story book under `~/.gemini/`, Antigravity's `scratch/`, or any
  other directory outside the workspace unless the user explicitly names that
  external destination.
- Before writing prose, long-form projects require the matching
  `大纲/细纲_第N章*.md`; short-form projects require `小节大纲.md`.
- Treat `追踪/_tracking-state.json` as the structured source of truth. Do not
  hand-edit its derived Markdown views.
- After prose is written, resolve every deterministic finding injected by the
  oh-story Antigravity hooks before continuing to another chapter.
- Prefer the seven deployed custom agents in `.agents/agents/` for specialist
  work. Call `invoke_subagent` with `TypeName`, a concise `Role`, and `Prompt`
  (include concrete file paths in `Prompt` so read-only subagents in `agy` CLI
  can read them directly via `read_file`/`view_file` when `find_by_name` or
  `grep_search` is unavailable). Because `invoke_subagent` runs asynchronously
  in the background, end the turn to wait for the subagent's `send_message`
  wakeup before running dependent steps such as `manage_analysis_run.py commit`
  or review synthesis; if the runtime cannot start custom subagents, use the
  skill's documented solo/direct fallback instead of failing the workflow.

## Working with the author

- Use plain story terms (book, chapter, outline, setting) in the main reply.
  Quote script, field, or status names when reporting an error.
- Skill templates marked `<!-- author-report -->` are format references only:
  reply with the text inside, never the code fence.
- When the author asks to remember, forget, or confirm a writing habit or
  preference, use author memory management in `story-long-write` or
  `story-short-write`, based on the author's explicit type or the active book.
  For a general habit with no active book, use the long-form entry. Ask which
  book only when a book-specific preference has no identifiable target; do not create a book.
  Write `.story/作者记忆/` in the relevant workspace or book directory. Never store it in Antigravity's
  built-in memory. One-off requests are simply carried out, not recorded.
- Never modify installed skill files (`SKILL.md`, `references/`, `scripts/`) in
  this workspace (redeploying via `story-setup` is the exception). If a skill script fails, stop and report its error and command; do not patch around it.

## Context recovery

At the start of a new conversation, and whenever context appears compacted or
story state is uncertain, locate the active book and read `追踪/上下文.md`
(long-form) or `设定.md` + `小节大纲.md` (short-form) before continuing. The
Antigravity external hook API has no PreCompact/PostCompact event, so this rule
is the mandatory recovery path after compaction.
