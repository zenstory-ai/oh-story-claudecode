# Claude Code skills that are not for coding: a fiction-writing skill pack as the worked example

**Short answer:** yes, agent skills work for non-developers, and the largest example is a novel-writing pack. Oh Story (`zenstory-ai/oh-story-claudecode`) is an MIT-licensed set of 13 skills that turns Claude Code, Codex CLI, OpenCode, Google Antigravity, OpenClaw, ZCode and Reasonix into a full workflow for writing serialized fiction: scan bestseller charts, deconstruct top-ranked books, draft chapters with file-based continuity tracking, strip AI-flavored prose, generate covers. About 6.8k GitHub stars. No code is written by the user; the agent reads and writes Markdown files in a book project.

This page explains what an agent skill is in plain terms, what a mature non-coding skill pack looks like on disk, and how a writer installs and uses one.

## What a skill is, in one paragraph

A skill is a folder with a `SKILL.md` file and optional `references/` and `scripts/`. `SKILL.md` tells the agent when the skill applies and what to do. The agent loads it only when the task matches, so a project can carry dozens of skills without stuffing the context window. Skills are different from prompts (a skill is on disk and re-used across sessions), from plugins (a plugin is a distribution wrapper that may bundle skills, agents and hooks), and from MCP servers (MCP exposes tools over a protocol; skills are instructions and files the agent reads directly). See Anthropic's docs for the formal definition; this page is about what one looks like when it is built for writers.

## What a non-coding pack looks like

The 13 skills in Oh Story, grouped by writing task:

| Task | Skill | What it does |
|---|---|---|
| Set up | `story-setup` | Deploys per-agent config, 7 specialist sub-agents and hooks into a book project |
| Route | `story` | Natural-language entry ("I want to start a book"), author-preference memory, local dashboard |
| Research | `story-long-scan`, `story-short-scan` | Scan 起点/番茄/晋江 and short-fiction charts for repeated patterns, not single rankings |
| Deconstruct | `story-long-analyze`, `story-short-analyze` | Six-stage pipeline: golden first three chapters, per-chapter summaries, rhythm and emotion-module indexes, settings, style profile |
| Draft | `story-long-write`, `story-short-write` | Outline to prose with a file-first tracking state (`_tracking-state.json`, per-chapter deltas ≤3072 bytes) |
| Revise | `story-deslop` | Writing lint for AI-flavored prose: deterministic pattern check, 7 gates, capped deletion ratios |
| Review | `story-review` | Multi-perspective review with parallel reviewer agents, falls back to single-thread |
| Import | `story-import` | Reverse-parse an existing manuscript into the project structure |
| Cover | `story-cover` | Cover generation from title and genre |
| Browser | `browser-cdp` | Reuse a logged-in Chrome session to fetch chart data |

The parts that make it more than a prompt collection:

- **Deterministic checks.** `story-deslop` runs `node scripts/check-ai-patterns.js` before any rewrite; `story-long-write` refuses to write a chapter whose brief lacks a word target instead of guessing.
- **Blocking reference gates.** A chapter is written only after the agent has read the brief, the volume outline and the current tracking state and recorded a Constraint Lock (word range, must-happen, must-not-happen, time anchors).
- **Layered state on disk.** Settings, outlines, prose and tracking live in separate directories. The tracking state card is a fixed 7-section file capped at 12KB, so chapter 300 loads about as much context as chapter 30.
- **Per-runtime deployers.** One `/story-setup` writes the right files for whichever agent you use (`.claude/`, `.codex/`, `.opencode/`, `.agents/` and so on).
- **Cross-runtime packaging.** The repo ships `marketplace.json`, `.claude-plugin`, `.zcode-plugin` and `reasonix-plugin.json`, which is what a multi-host skill pack needs today.

## How a writer uses it

```bash
npx skills add zenstory-ai/oh-story-claudecode -y -g
```

Then, inside the agent, in an empty folder for the book:

```text
/story-setup
```

Open a new session and say what you want in plain language. "帮我开书" starts a new book (settings, outline, first chapters). "把我的书导进来" imports an existing manuscript. "这篇太 AI 了" runs the de-AI pass. "沈栀现在什么状态" asks a sub-agent to report a character's current state from the tracking files. No terminal commands beyond the two above.

The pack is built for Chinese web fiction (起点, 番茄, 晋江, 七猫, 知乎盐言), and the skills, references and file names are in Chinese. The mechanism is language-independent.

## Why this matters for "skills beyond code"

Most articles about agent skills illustrate them with developer tooling: frontend design, test generation, database queries. Fiction is a harder case for the same machinery. The state is large, it changes every chapter, the author must stay in control of plot decisions, and "correct" is a matter of reader feel rather than a passing test. A pack that handles that with files, gates and scripts is a useful reference for anyone building skills for non-coding work: research, editing, documentation, production pipelines.

## Related

- Repository: https://github.com/zenstory-ai/oh-story-claudecode (formerly `worldwonderer/oh-story-claudecode`; old links redirect)
- English README: [README_EN.md](../README_EN.md)
- Site guide for first-time users: https://zenstory.ai/oh-story/agent-skills-for-writers
- Sibling packs by the same org: short drama (`drama-skills`), novel to game (`novel-to-game`), video recap (`video-recap-skills`), DeepSeek harness plugin (`oh-story-dsh`)
- Continuity mechanism in detail: [keep-ai-novel-consistent-over-100-chapters.md](keep-ai-novel-consistent-over-100-chapters.md)
