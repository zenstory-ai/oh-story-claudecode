# Agent Note: Source-bound release contract

Status: implemented

## Problem

仓库缺少把稳定版本、精确 main 提交、CI 结果、GitHub Release 字节与 ClawHub 交接绑定起来的统一发布契约。历史 Release 可以人工创建，但无法在写权限前证明来源和产物身份；由 `GITHUB_TOKEN` 创建的 Release 也不会自动触发现有 `release.published` 流程。

## Decision

仓库采用组织级、标准库实现的 source-release 控制器，并由本仓库用固定完整提交 SHA 调用。PR 只运行只读契约检查；main 手动运行只打包和验证；只有稳定 `vX.Y.Z` tag push 可进入追加式 GitHub Release 发布。源 Release 成功后，以 tag 与 40 位提交 SHA 显式派发既有 ClawHub 工作流，并只记录 `CLAWHUB_QUEUED`。

### 2026-10-27：Dashboard 进入精确提交发布门禁

2026-10-27：release policy 把 Dashboard 的三平台 API 与 Ubuntu e2e 四个真实 job 名列为 exact-SHA 必需检查。控制器按 GitHub job 的 `name` 精确匹配，不写 YAML job id。Dashboard 对 main 的 push 不再按路径过滤，保证文档提交等任一可发布 main SHA 都有对应检查；PR 保留路径过滤并补 release policy 变更触发。代价是每次 main 提交都运行 Dashboard CI，不降低现有发布条件。

## Alternatives considered

- 继续人工创建 GitHub Release：改动最少，也保留维护者完全控制；但无法稳定证明精确 CI、版本元数据与公开字节一致，也会继续漏掉 ClawHub 的自动交接。
- 在每个仓库复制完整发布脚本：仓库自治最强；但四个同类 skill 仓库会重复维护 CI 查询、归档、安全链接与不可覆盖语义，修复容易漂移。

## Consequences

发布流程增加一个受评审的组织控制 SHA 和仓库内策略文件。版本不因此提升，skill 正文、ClawHub 单 skill 版本、发布者与扫描门禁不改变。正式 tag 仍是单独发布操作；异步 ClawHub 派发成功不等于已经公开或扫描通过。

## Verification

发布策略由共享控制器对已提交版本、dated changelog、必需文件和可复现归档做离线检查；仓库原有守卫、测试与 workflow `actionlint` 保持为合入证据。正式发布仍须在替换完整控制 SHA 后通过受保护分支 CI，当前实现没有创建 tag、Release 或外部写入。

2026-10-27：读取并运行固定控制版本 `d098c09a27f8fe58ccf3a13a894ecc3804747b7c` 的实际 policy / CI 校验函数，四个真实 Dashboard job 全成功时通过，逐一缺失、失败、跳过、取消的 16 个场景全部拒绝。验证只用内存 API 结果，不发布、不访问写权限接口；当前机器未安装 actionlint。
