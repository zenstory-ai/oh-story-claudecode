# How it works: agents, hooks and project structure

[中文](architecture.md)

Oh Story splits long-form writing into three layers: the file system as memory, specialist agents, and automated gates. The overview is in [What it is](../README_EN.md#what-it-is).

## Agent System

Writing skills call seven specialist agents as needed, falling back to the current session when your coding agent has not registered them. The models below are Claude Code defaults; other coding agents use their adapter settings:

| Agent | Model | Role |
|:------|:------|:-----|
| **story-architect** | Opus | Story architecture — genre positioning, outline structure, hook/twist design, emotion arcs |
| **character-designer** | Sonnet | Character design — profiles, voice, motivation chains, dialogue writing |
| **narrative-writer** | Opus | Narrative writer — prose writing, de-AI-ify, format compliance |
| **consistency-checker** | Haiku | Consistency check — fact conflict scanning, foreshadowing tracking, S1-S4 grading reports |
| **story-researcher** | Sonnet | Research — CDP search + full-text extraction, multi-source cross-verification, structured reference files |
| **story-explorer** | Haiku | Story query — read-only character/foreshadowing/setting/progress lookup, quick context loading |
| **chapter-extractor** | Haiku | Chapter extraction and legacy-asset cleanup — chapter facts, per-chapter plot points, and cross-chapter plot arcs |

Agents read relevant character, dialogue and twist references as needed. Unread files do not enter the context.

## Automation Hooks

`/story-setup` deploys a unified Node.js 18+ hook runtime for Claude Code (`run-story-hook.sh` + `story_hook_cli.js` + `story_hook_core.js`, shared across Codex, OpenCode, ZCode, and Antigravity), covering 8 events:

| Event | Trigger | Function |
|:------|:--------|:---------|
| `session-start` | Session start | Display branch, progress snapshot, deconstruction status, and deployment checks |
| `detect-story-gaps` | Session start | Detect setting gaps, missing outlines, foreshadowing breaks, and continuity drift |
| `session-end` | Session end | Optionally log session end to `追踪/session-log.txt` (when `STORY_SESSION_LOG=1`) |
| `pre-compact` | Before context compaction | Save progress snapshot path and line-count summary |
| `post-compact` | After context compaction | Prompt to read progress snapshot for context recovery |
| `pre-tool-commit-advisory` | git commit | Check hardcoded attributes and setting required fields (warning only, non-blocking) |
| `pre-tool-prose-guard` | Before writing prose (Bash/Write/Edit) | Hard-blocks prose writes on unexpanded shell variables, missing/empty (<30-char) chapter outline, missing `小节大纲.md`, or missing/corrupt `_tracking-state.json`; prior-chapter toxic phrasing, uncommitted chapter gaps, and manual `上下文.md` status edits emit non-blocking pre-write advisories |
| `post-tool-prose-check` | After writing prose (Write/Edit) | Lightly scan for truncation, leaked workflow terms, and deterministic AI phrasing (advisory; word count is measured by the writing workflow before delivery) |

## Project File Structure

The project keeps settings, outlines, prose, and tracking in separate files. Each chapter loads only the records it needs and commits the changes that actually happened, so continuity does not depend on an ever-growing chat history.

Only `story-long-write` and `story-short-write` manage and query author memory. `story` routes related requests; de-AI-ifying and review use the style requirements passed by the writing workflow.

Author memory stays separate from any one book's continuity tracking and lives in two stores so preferences travel with the book: the workspace `.story/作者记忆/` holds global, genre, and workflow preferences (`AP` ids), and each book directory's `.story/作者记忆/` holds only that book's preferences (`BP` ids). Both share the same layout:

```text
.story/作者记忆/
├── _author-memory-state.json  # Single source of truth
├── 作者画像.md               # Confirmed preferences used in creation
├── 待确认.md                 # Candidates whose scope the author left vague, and conflict candidates
└── 变更记录.md               # Auditable replacement and withdrawal history
```

Only preferences the author states explicitly are recorded; nothing is inferred from repeated edits or finished drafts.

**Long-form:** the English directory labels below explain their roles. Actual project paths use the Chinese names shown in the [Chinese structure](architecture.md#项目文件结构).

```
{Book Title}/
├── Settings/
│   ├── World/              # Background, power systems, etc. — one file per topic
│   ├── Characters/         # One file per character (Shen_Zhi.md, Lu_Yanzhi.md)
│   ├── Factions/           # One file per faction/organization (Tianji_Pavilion.md)
│   ├── Relationships.md    # Character relationship map
│   └── Genre_Positioning.md # Core trope + benchmark analysis
├── Outline/
│   ├── Outline.md          # Full-book volume-level structure
│   ├── Volume_1.md         # One per volume: payoff pacing + emotion arc + character arc + foreshadowing + twists
│   ├── Chapter_001.md      # One per chapter: summary + multi-line plot + relationships/order + hooks
│   └── ...
├── Prose/
│   ├── Chapter_001_Title.md
│   └── ...
├── Benchmark/                # Benchmark reference (structured subdirs synced from deconstruction)
│   └── {Benchmark Book}/
│       ├── Source/              # Benchmark book original chapters
│       ├── Characters/         # Structured character profiles (synced from analyze)
│       ├── Plotlines/          # Structured plot lines/pacing/emotion modules (synced from analyze)
│       ├── Settings/           # Structured world settings (synced from analyze)
│       ├── 文风.md              # Benchmark voice used before daily writing
│       └── Report.md            # Analyze skill output
├── Tracking/                # File-first continuity state
│   ├── _tracking-state.json # Master tracking data (not loaded into prose prompts)
│   ├── Context.md           # Auto-generated continuity card
│   ├── Chapter_Records/     # Per-chapter continuity changes
│   ├── Character_Status/    # Auto-generated snapshot per core character
│   ├── Foreshadowing.md     # Auto-generated current foreshadowing list
│   └── Timeline/            # Auto-generated author-truth and reader-known timelines
├── References/              # story-researcher output
│   └── {topic}.md           # Split by research topic
```

**Short-form file structure:**

```
短篇/{Title}/
├── 设定.md                  # Story core, characters, platform tone, and twist design
├── 小节大纲.md              # 8-section structure + emotion curve
├── 正文.md                  # Final draft
└── 拆文库/                  # If a reference novel exists (analyze output)
    └── {Book}/
        ├── 拆文报告.md
        ├── 情节节点.md
        └── 写作手法.md
```

The eight-section short-form outline is just an example; the actual section count follows the confirmed design and length target.

**Deconstruction Library:** Deconstruction skills save structured outputs (characters, plotlines, settings, chapters) under `拆文库/{Book Title}/` at project root; long-form plot output includes `节奏.md` and `情绪模块.md`. Writing skills read these files from `对标/{书名}/剧情/` and related benchmark subdirectories, falling back to `拆文库/` at project root when book-local copies are absent. The book’s own style always takes priority; benchmark style only fills in unspecified dimensions.

**`.active-book`:** a text file at project root containing the active book's relative path (for example, `长篇/My Novel`). Hooks and writing skills use it to locate the current project.
