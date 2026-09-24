---
trigger: always_on
---

# oh-story writing project rules

This workspace uses the oh-story web-fiction skill pack. Discover skills from
`.agents/skills/`; read the selected skill's `SKILL.md` before executing it and
load its references only when that skill instructs you to do so.

## Routing

- Long-form writing or continuation: `story-long-write`
- Short-form writing: `story-short-write`
- Long/short deconstruction: `story-long-analyze` / `story-short-analyze`
- Long/short market scan: `story-long-scan` / `story-short-scan`
- Remove AI-writing patterns: `story-deslop`
- Adversarial review: `story-review`
- Import an existing story: `story-import`
- Cover generation: `story-cover`
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
  work. Call `invoke_subagent` with the agent's `TypeName`; if the runtime cannot
  start them, use the skill's documented solo/direct fallback instead of
  failing the workflow.

## Working with the author

- Talk to the author in plain story terms (book, chapter, outline, setting). Do
  not surface script, field, or status names, except when quoting an error.
- Skill templates marked `<!-- author-report -->` are format references only:
  reply with the text inside, never the code fence.
- When the author asks to remember, forget, or confirm a writing habit or
  preference (e.g. 「记住：这本书对话用直角引号」), use the `story` skill's author
  memory; its script writes `.story/作者记忆/`. Never store it in Antigravity's
  built-in memory. One-off requests are simply carried out, not recorded.
- Never modify installed skill files (`SKILL.md`, `references/`, `scripts/`) in
  this workspace (redeploying via `story-setup` is the exception). If a skill script errors, stop and report the error and the
  command to the author instead of patching around it.

## Context recovery

At the start of a new conversation, and whenever context appears compacted or
story state is uncertain, locate the active book and read `追踪/上下文.md` before
continuing. The Antigravity external hook API has no PreCompact/PostCompact
event, so this rule is the mandatory recovery path after compaction.
