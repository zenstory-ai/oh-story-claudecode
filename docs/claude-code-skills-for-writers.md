# Claude Code skills that are not for coding: a fiction-writing skill pack as the worked example

Agent skills can organize non-coding work. Oh Story (`zenstory-ai/oh-story-claudecode`) is an MIT-licensed set of 14 skills that turns Claude Code, Codex CLI, OpenCode, Google Antigravity, OpenClaw, ZCode and Reasonix into a full workflow for writing serialized fiction: scan bestseller charts, deconstruct top-ranked books, draft chapters with file-based continuity tracking, strip AI-flavored prose, prepare platform book-entry details, generate covers. No code is written by the user; the agent reads and writes Markdown files in a book project.

## What a skill is, in one paragraph

A skill is a folder with a `SKILL.md` file and optional `references/` and `scripts/`. `SKILL.md` tells the agent when the skill applies and what to do. The agent loads it only when the task matches, so a project can carry dozens of skills without stuffing the context window. Skills are different from prompts (a skill is on disk and re-used across sessions), from plugins (a plugin is a distribution wrapper that may bundle skills, agents and hooks), and from MCP servers (MCP exposes tools over a protocol; skills are instructions and files the agent reads directly). See Anthropic's docs for the formal definition; this page is about what one looks like when it is built for writers.

## What a non-coding pack looks like

The 14 skills in Oh Story, grouped by writing task:

| Task | Skill | What it does |
|---|---|---|
| Set up | `story-setup` | Deploys host-specific files; specialist agents and hooks depend on the host |
| Route | `story` | Routes natural-language requests and preference management to the relevant writing skill; starts the local dashboard |
| Research | `story-long-scan`, `story-short-scan` | Scan 起点/番茄/晋江 and short-fiction charts for repeated patterns, not single rankings |
| Deconstruct | `story-long-analyze`, `story-short-analyze` | Long-form Stages 0–6 cover chapter indexing, golden opening, block extraction, rhythm, settings, report and style; short-form Stages 2–6 produce its own analysis assets |
| Draft | `story-long-write`, `story-short-write` | Outline to prose; long-form uses file-first tracking (`_tracking-state.json`, per-chapter deltas ≤3072 bytes), while short-form uses its own setting, outline and story files |
| Revise | `story-deslop` | Diagnoses expression, narrative emphasis and story causality, then revises within the author's scope and authorization |
| Review | `story-review` | Multi-perspective review with parallel reviewer agents, falls back to single-thread |
| Import | `story-import` | Reverse-parse an existing manuscript into the project structure |
| Publish prep | `story-publish` | Turns confirmed settings and outlines into a platform's book-entry details (title, synopsis, tags), checked against that platform's rules; Fanqie for now |
| Cover | `story-cover` | Cover prompts or images from title and genre |
| Browser | `browser-cdp` | Reuse a logged-in Chrome session to fetch chart data |

The parts that make it more than a prompt collection:

- **Deterministic checks.** `story-deslop` uses `node scripts/check-ai-patterns.js` to locate patterns in local files, alongside contextual review; `story-long-write` refuses to write a chapter whose brief lacks a word target instead of guessing.
- **Blocking reference gates.** A chapter is written only after the agent has read the brief, the volume outline and the current tracking state and written down this round's constraints (word range, must-happen, must-not-happen, time anchors).
- **Layered state on disk.** Settings, outlines, prose and tracking live in separate directories. The tracking state card is a fixed 7-section file capped at 12KB, with older records queried as needed instead of loading the full history.
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

Open a new session and say what you want in plain language. "帮我开书" (help me plan a book) starts settings and outline work; prose is written when requested. "把我的书导进来" imports an existing manuscript. "这篇太 AI 了" runs the de-AI pass. "沈栀现在什么状态" asks a sub-agent to report a character's current state from the tracking files. No terminal commands beyond the two above.

The pack is built for Chinese web fiction (起点, 番茄, 晋江, 七猫, 知乎盐言), and the skills, references and file names are in Chinese. The mechanism is language-independent.

## Why this matters for "skills beyond code"

Fiction uses the same machinery for a different kind of state. The state is large, it changes every chapter, the author must stay in control of plot decisions, and "correct" is a matter of reader feel rather than a passing test. Files preserve state, gates check required inputs, and scripts handle mechanical validation. The same division can support research, editing, documentation and production workflows.

## Related

- Repository: https://github.com/zenstory-ai/oh-story-claudecode (formerly `worldwonderer/oh-story-claudecode`; old links redirect)
- English README: [README_EN.md](../README_EN.md)
- Site guide for first-time users: https://zenstory.ai/oh-story/agent-skills-for-writers
- Install to first chapter in Claude Code or Codex, step by step: https://zenstory.ai/oh-story/claude-code-novel-writing
- Sibling packs by the same org: short drama (`drama-skills`), novel to game (`novel-to-game`), video recap (`video-recap-skills`), DeepSeek harness plugin (`oh-story-dsh`)
- Continuity mechanism in detail: [keep-ai-novel-consistent-over-100-chapters.md](keep-ai-novel-consistent-over-100-chapters.md)
