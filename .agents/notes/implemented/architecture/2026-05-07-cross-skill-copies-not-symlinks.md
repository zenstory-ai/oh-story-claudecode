# Agent Note: 跨 skill 共享文件用真实副本加显式清单，不用 symlink

Status: implemented

## Problem

多个 skill 需要同一份 reference（banned-words、anti-ai-writing）和运行时脚本（check-ai-patterns.js、cdp-utils.js）。每个 skill 必须能被独立安装和部署——`npx skills add`、marketplace、story-setup 复制到用户项目——symlink 与 `../` 跨 skill 路径在拆开安装或 Windows 无 symlink 权限时会断掉。

## Decision

- 每个 skill 目录自包含：跨 skill 共享内容以真实副本存在。never 在 skill 之间用 symlink 或 `../` 引用；`static-check.py` 拦截跨 Skill 文件引用，唯一例外是基础组件 `browser-cdp`（业务 skill 可引用它的启动器）。
- 副本一致性由两个显式清单管理，CI 的 `check-shared-files.sh` 串跑：
  - `scripts/shared-assets.json`：runtime 脚本，每组唯一 `source` + `targets`；改 source 后跑 `sync-shared-assets.py sync`；同名 runtime 只能属一个 group，target 必须保留 source basename，禁止改名绕过单一 owner。
  - `scripts/shared-references.json`：reference 文档的 source / targets；高相似但有意分化的派生关系必须在 `derived_groups` 说明来源与分化原因，由近似扫描（行级 Jaccard / containment）核对。
  - runtime 与 reference 清单按文件类型互斥，同一路径不得同时登记。
- 未在清单登记的重名或近似副本直接失败。
- 仓库级例外：`.agents/skills` 是指向 `../skills` 的相对 symlink（agentskills.io 标准路径），供 Codex / Reasonix 发现，不是第二份 skill；`check-codex-adapter.sh` 守卫它必须是有效相对 symlink（无效或绝对会让发现静默失效），Windows 需 `git core.symlinks=true`。

来源：89ff2c8 (#5)、4e8a2c8 (#17)、398795d (#189)、3f2a890

## Alternatives considered

- **`skills/shared/` + symlink**——最强理由：单一源头零漂移，145a635 曾建 16 个 symlink 替换脆弱的 `../` 引用。否：symlink 在独立安装与 Windows 下失效，89ff2c8 删掉 `skills/shared/`、4e8a2c8 把 16 个 symlink 全部换成真实副本。
- **跨 skill `../` 路径引用**——最强理由：不复制、改一处即生效。否：同样破坏独立部署，ce8216b 清掉残留后由 static-check 拦截。
- **只靠「同名文件字节一致」扫描、不登记 owner**——早期 `check-shared-files.sh` 的做法。否：说不清谁是 source，有意分化的文件（各 skill 自有的 output-templates.md）只能靠 IGNORE 名单，近似改写也查不到；显式清单取代之。

## Consequences

- **收益**：任一 skill 单独复制即可运行；每份副本有明确 owner；有意分化必须写理由。
- **代价与已知上限**：同一内容在仓库里多份（agent-references 又一份），改一处必须 sync 并提交全部副本，PR diff 变大；分化说明是维护负担。若所有目标端都能可靠解析 symlink、且部署器不再按目录复制，可重访。

## Verification

`bash scripts/check-shared-files.sh`；`python3 scripts/test-shared-assets.py`；`bash scripts/check-codex-adapter.sh` 中的 `.agents/skills` 断言。
