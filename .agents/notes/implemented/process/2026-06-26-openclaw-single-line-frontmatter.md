# Agent Note: SKILL.md frontmatter 保持单行键值以兼容 OpenClaw

Status: implemented

## Problem

13 个 skill 要被 Claude Code、Codex、OpenCode、OpenClaw、ZCode、Reasonix 从同一份 `skills/` 发现。OpenClaw / AgentSkills 的 frontmatter 解析只接受单行顶层键：`description: |` 块标量与缩进的多行 `metadata` 会让 skill 在 OpenClaw 下直接不可见。而每个 skill 的触发词很长（十几个中文触发短语加英文别名），直觉写法就是块标量。

## Decision

- 每个 `SKILL.md` 的 frontmatter 顶层键 must 单行：`name`、`description`（引号字符串，不用 `|` / `>` 块）、`metadata` 为单行 JSON 对象且含 `metadata.openclaw`（至少 `source`；可选 `requires.bins/env/config/anyBins` 做 OpenClaw load-time gating，例如 `story-cover` 用 `GPT_IMAGE_API_KEY` 控制可见性）。
- 触发词全部保留在 `description` 里，只做格式单行化，never 因为要单行而删触发词；更长的触发说明放正文。
- canonical source 只有仓库根 `skills/` 一份；never 为 OpenClaw 维护第二份 skill 或镜像包。OpenClaw 原生扫 workspace `skills/`，不依赖 `.agents/skills` symlink；`story-setup target_cli=openclaw` 只部署项目 `skills/` 与 `references/openclaw/AGENTS.md.tmpl`，不部署 agents / hooks / plugin。
- 守卫：`scripts/check-openclaw-skills.sh`（CI 强制）拒绝缩进行、块标量与非 JSON 的 `metadata`，并要求恰好 13 个 skill；`OPENCLAW_REAL_CHECK=1` 时用临时 profile + 临时 workspace 创建隔离 agent，确认真实 CLI 能发现 13 个 skill，结束后清理。
- 例外：OpenClaw 在 session 启动时 snapshot eligible skills，改动后需新 session 或等 skills watcher 刷新——这是运行时行为，不是仓库可控项。

来源：8d08e23 (#186)、398795d (#189)

## Alternatives considered

- **为 OpenClaw 单独生成兼容副本或发布 plugin 包**——最强理由：主 `SKILL.md` 可保留可读的多行 description，OpenClaw 特有字段不污染其他端。否：8d08e23 明确「不引入 plugin 实体包 / 镜像」「canonical skill 仍是仓库根 skills/ 单份」；第二份必然漂移，仓库已经在为 reference 副本同步付 `check-shared-files` 的成本，见 [跨 skill 副本笔记](../architecture/2026-05-07-cross-skill-copies-not-symlinks.md)。
- **单行化时顺手精简触发词**——最强理由：一行几百字难读。否：触发词决定各端的命中率，8d08e23 写明「保留每个 skill 的全部触发词，仅格式单行化」。
- **块标量写法**是被替换掉的旧做法（8d08e23 之前 `description: |` 多行、`metadata:` 缩进 YAML）。

## Consequences

- **收益**：一份 `skills/` 六端可发现；CI 在 PR 阶段拦住格式回退，不用等真机验证。
- **代价与已知上限**：`description` 一行很长，可读性差，diff 里一处改动整行变红；`metadata` 未来增长仍得塞进一行 JSON。若 OpenClaw 上游放开块标量解析，可重访「单行」约束，但「单份 canonical」不随之改变。

## Verification

`bash scripts/check-openclaw-skills.sh`；本机装有 openclaw 时 `OPENCLAW_REAL_CHECK=1 bash scripts/check-openclaw-skills.sh`。
