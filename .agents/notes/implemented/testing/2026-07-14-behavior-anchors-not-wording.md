# Agent Note: 仓库门禁只锚行为，不钉措辞

Status: implemented

## Problem

早期守卫用 grep 断言「UPGRADING / README 必须写到某句话」、追踪契约用词法匹配固定句子。改一个词就红，少补一条 changelog 也红，但少写一条并不会让任何东西跑坏；反过来措辞对了行为也可能错——#283 给另三端加追踪门时 Claude 侧静默漏了一整版，规范串 grep 一致的断言没有发现（issue #305）。

## Decision

- 静态与契约守卫 must 只锚「跑起来会坏」的东西：跨文件必须对齐的阈值（`agents_version`）、部署到用户手里的 agent 模板必须带住的关键行为规则、部署行为锚点。文档完整性（是否补 UPGRADING、README 段落顺序）由发版清单和人把关，never 进 CI。
- 行为用真实执行覆盖：hook 用合成 stdin/stdout 跑（`test-codex-hooks.sh`、`test-zcode-hooks.sh`、部署检查里的假 node 垫片）；四端 parity 按「同一工程同一次写入，bash 拦不拦 == JS 核拦不拦」逐场景比对，并锚死每个场景的期望方向——否则两端一起漏拦也能 diff 干净。
- 无法由隔离测试证明的依赖方向（scraper 输出文件名依赖本地日期 helper、CDP 探测源码策略）才用源码策略守卫，且 must 配变异测试证明无关或死代码关键词骗不过它。
- 涉及 agent / skill / plugin / hook 协议的断言，先核对对应项目官方文档，再以真实 CLI 输出复核；不从其他 agent 的相似字段推断。

来源：12a9655 (#240)、6af0529 (#359)、739a427 (#243)、1ced63d (#265)

## Alternatives considered

- **规范串三端 grep 一致**（parity 旧 A 层）——最强理由：CI 安全、零运行时依赖，改一处漏改另一处直接红。否：只能证明文本相同，证明不了行为相同，也抓不到整端缺失；6af0529 删掉，改为 fixture 上逐字相等的功能 parity。
- **UPGRADING 措辞断言**（部署检查旧 TS10）——最强理由：逼维护者补升级说明。否：测的是措辞不是行为，12a9655 删掉并把 TS10 改名为「版本阈值 + 部署行为锚点」。
- **词法追踪契约**（`test-tracking-workflow-contracts.py`）——同样毛病，6af0529 删掉，只保留 `test-tracking-commit.py` 的行为回归。

## Consequences

- **收益**：改措辞不再红；漏一端会被抓；守卫失败信息指向真实行为。
- **代价与已知上限**：行为测试更慢（`check-story-setup-deployment.sh` 超过两分钟）；文档漂移没有 CI 兜底，只靠人；源码策略守卫要靠变异测试防被骗，多一层维护。若某条行为无法在 CI 环境执行（如 cmd.exe 路径），只能退回静态保形并在注释里写明是 best-effort。

## Verification

`bash scripts/test-prose-net-parity.sh`；`python3 scripts/test-scan-runtime-policy.py`；`bash scripts/check-story-setup-deployment.sh` TS10。
