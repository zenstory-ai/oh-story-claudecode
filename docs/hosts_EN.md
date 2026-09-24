# Host deployment and install troubleshooting

[中文](hosts.md)

Oh Story supports 8 agent hosts. This page holds per-host deployment detail, known limits and install troubleshooting; day-to-day use only needs the [Installation](../README_EN.md#installation) section.

## Install troubleshooting: Windows errors, environment check, marketplace path
On Windows you may occasionally see an `ENOENT ... mkdir` error while the run still ends with `Done!`. That means a skill was only partially installed. If a whole subdirectory of story-setup's reference bundle is missing, `/story-setup` reports an incomplete reference bundle; other forms of partial install may go unreported. Either way, re-run the same install command to fix it.

To diagnose an installed environment, ask your agent to use story-setup to check your writing environment, or invoke the skill with the `check` argument. It checks the target CLI's deployment checklist and reports next steps without changing the project. Repairs use the existing setup workflow.

This standalone `npx skills` installation path does not use the Claude Code or ZCode marketplace, so the plugin identity change below does not affect it.

## Claude Code

The marketplace remains named `oh-story-skills`, but now contains one `oh-story` bundle. Claude Code discovers all 13 root Skills from that bundle:

```bash
claude plugin marketplace add https://github.com/zenstory-ai/oh-story-claudecode
claude plugin install oh-story@oh-story-skills
```

After installation, use `/oh-story:story-setup` or `/oh-story:story dashboard`. Existing plugin users should follow the [migration guide](../skills/story-setup/UPGRADING.md#插件打包身份迁移v079-同版本修复). This identity migration began with a same-version fix in v0.7.9; users still on the old plugin identities should refresh the marketplace and reinstall explicitly. See the [Claude Code plugin reference](https://code.claude.com/docs/en/plugins-reference) for commands.

## Antigravity

Run `story-setup` from `/skills` or by natural language and select `target_cli=antigravity`. Inside the current writing project it updates only 13 known `.agents/skills/` directories, 7 known `.agents/agents/agent-name/agent.md` definitions (`agent-name` stands for the actual name), `.agents/rules/oh-story.md`, two `.agents/hooks/` runtime files, and the managed `oh-story` group in `.agents/hooks.json`. Other user Skills, Agents, Rules, Hooks, and hook groups are preserved; the deployer itself never writes `~/.gemini/`. Skills are real project-local directories. If `.agents/skills` is already a symlink, setup explains the git-diff impact and requires explicit migration approval; without approval it never writes through the link. Hooks require `node` on PATH. Open a fresh conversation after deployment, then smoke-test both the IDE and interactive `agy`. **`agy 1.1.22 -p` is currently outside the supported surface:** each headless process may scan the workspace before silent authentication finishes, then fail to reload custom agents and hooks. The result can be a skill fallback, `subagent not found`, or ordinary model output under `~/.gemini/antigravity-cli/scratch/`. For CLI writing, start interactive `agy` from the project and confirm `/skills`, `/agents`, and `/hooks` have discovered oh-story before sending the task; check the scratch directory for accidental story output after testing.

## Codex

Use it in-place: Codex scans `$REPO_ROOT/.agents/skills` (a symlink to `skills/`) and discovers all 13 skills; invoke via `$story`, `$story-setup`, or `/skills`. On Windows, enable git `core.symlinks=true` or the symlink breaks — then use the `$story-setup` deployment below.

After `$story-setup` deploys into a writing project, it creates `.codex/agents/*.toml`, `.codex/hooks.json`, `.codex/hooks/{story_codex_hook.py,run-story-hook.sh,run-story-hook.cmd}`, and `.codex/skills/story-setup/references/agent-references/`. Trust the project `.codex/` layer, review/trust hooks in `/hooks`, and open a fresh Codex session so custom agents load.

## ZCode

Add this repository in Plugin Management and install `oh-story` to access all 13 Skills/Commands. The marketplace may appear as `oh-story-zcode` (root catalog) or `oh-story-skills` (Claude catalog); choose one, since both contain the same bundle. For older installs with multiple entries, follow the [migration guide](../skills/story-setup/UPGRADING.md#插件打包身份迁移v079-同版本修复). With `target_cli=zcode`, `$story-setup` deploys `.zcode/skills/`, `.zcode/commands/`, and `.zcode/hooks/story_zcode_hook.js`, then safely merges `.zcode/config.json` and the root `AGENTS.md`. Hooks require `node` on PATH. ZCode 3.3.4 does not execute project/plugin custom agents and has no `PreCompact` or `SessionEnd`; affected workflows report a solo/direct fallback, while `SessionStart` restores context after compaction. See the [official ZCode plugin documentation](https://zcode.z.ai/en/docs/plugin).

## OpenCode

Requires **OpenCode 2.x** (`curl -fsSL https://opencode.ai/v2/install | bash` or `npm i -g @opencode/cli`). 1.x cannot load the prose-guard plugin, so story-setup stops and asks you to upgrade; projects deployed under 1.x should re-run story-setup after upgrading. After global install, opencode auto-discovers skills from `~/.claude/skills/`; trigger story-setup with natural language on first use (e.g., "use story-setup to deploy the web novel environment"). Slash commands load automatically after deployment; if they don't appear, run `opencode reload`. Some hook behaviors differ from Claude Code (session-start / session-end / compact, etc.) — see the OpenCode section in [CONTRIBUTING.md](../CONTRIBUTING.md).

## OpenClaw

Current support is skills-only. OpenClaw can discover the 13 story skills from workspace `skills/`, `.agents/skills`, `~/.agents/skills`, `~/.openclaw/skills`, or configured extra skill roots. `SKILL.md` files use OpenClaw-compatible single-line `name` / `description` plus single-line JSON `metadata.openclaw`. When `story-setup` targets OpenClaw, it copies the skills into project `skills/` and writes an OpenClaw `AGENTS.md`; agents/hooks are intentionally deferred, so outline-before-prose guards are soft skill checks rather than runtime enforcement. If new skills do not appear immediately, open a fresh OpenClaw session or wait for the skills watcher to refresh.

## Reasonix

Current support is Skills + a native plugin manifest. Reasonix natively scans project skill roots (`.agents/skills` etc., a symlink to `skills/`) and discovers all 13 skills — verify with `reasonix doctor capabilities`; you can also `reasonix plugin install` via the root `reasonix-plugin.json`. When `story-setup` targets `target_cli=reasonix`, it copies the skills into project `skills/` and writes a Reasonix `AGENTS.md`; hooks/custom agents are intentionally deferred, so skills needing specialist agents fall back to solo/direct. If Windows symlinks are disabled, use the native plugin instead.

## Generic Web AI / agent

If your platform can read a GitHub repo or project files, have the agent read `skills/*/SKILL.md` plus the relevant `references/`. For local project copies, run `story-setup` with `target_cli=generic`; it only writes a generic `AGENTS.md` and `skills/`. Without this project's hooks/custom agents, checks run as skill-level soft constraints or solo/direct fallbacks.

**OpenClaw / Reasonix / generic paths need manual cleanup of nested directories:** these three keep their skill copy inside the project's `skills/`, so re-running `/story-setup` executes that project-local copy and the automatic cleanup never reaches them. If the project contains `skills/story-setup/references/agent-references/agent-references/` (possibly nested several levels deep) or `skills/story-setup/skills/`, delete them by hand. To update the skill text itself, reinstall this project and overwrite the 13 skill directories under the project's `skills/` from the new package.

After updating, if a project has already run `/story-setup`, re-run `/story-setup` from the project root to sync hooks / agents / references. Per-version changes are in [CHANGELOG.md](../CHANGELOG.md) and [Releases](https://github.com/zenstory-ai/oh-story-claudecode/releases).

**Multi-agent collaboration needs setup + a fresh session:** the 7 specialist agents (story-architect, narrative-writer, consistency-checker, etc.) are written into `.claude/agents/` by `/story-setup`, `.codex/agents/*.toml` by `$story-setup`, or generated into `.agents/agents/agent-name/agent.md` (`agent-name` stands for the actual name) by Antigravity `story-setup`. Antigravity calls them with `invoke_subagent` and the matching `TypeName`; if custom subagents are unavailable, each skill reports a solo/direct fallback. Run `/story-review` in the fresh session — `Effective Mode: full/lean` means agents registered, while `Fallback: ... -> solo` means they are unavailable.

**Import and continuation order:** run `/story-setup` from the writing-project root first to deploy hooks, agents, and `AGENTS.md`; start or refresh the session, then run `/story-import` for the existing novel and continue with `/story-long-write 日更` or `/story-long-write 写第N章`. You can also run `/story-import` directly; if setup is missing, it offers to run setup first or continue with a serial import.

**Author preferences persist across sessions:** tell `/story` to remember a writing habit; the write counts as successful only when it returns an `Author Memory Receipt`. Normal writing queries only relevant confirmed items with a hard 2 KB output cap, rather than injecting the full profile, candidates, and history into the prose prompt. This memory stays separate from per-book continuity tracking, and current instructions, book settings, and hard gates always take priority.