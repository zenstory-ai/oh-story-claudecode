# Agent Note: 检测器、扫榜运行时与 Dashboard 测试：一条契约一个守卫，负例必须走到被测分支

Status: implemented

## Problem

一轮只读测试审计在检测器、扫榜运行时和 Dashboard 三块发现同一类问题：测试在「看起来覆盖」，变异后却不红。

- 密度类规则（微动作、套式反应、抽象总结、动作清单、套词、比喻、解释链、过度精炼）的「引号内…不应报」负例全靠低密度通过；把密度函数里的 `stripQuoted(trimmed)` 换成 `trimmed`，这些负例仍全绿。退化检测器的纯台词复沓用「我不走。」，短于复读长度门槛，同样测不到去引号。
- 同一件事被多处重复断言：`test-ai-patterns.sh` / `test-outline-copy.sh` 逐字比对检测器副本，与 `sync-shared-assets.py check` 重复；`test-scan-runtime.js` 对逐字同步的 short-scan `cdp-utils.js` 再跑一遍；`dashboard-bundle-contract.test.mjs` 的 manifest 断言与 `check-plugin-packaging.py` 重复；CI 的「Verify cdp-utils loads」没有断言。
- `testScraperImports` 要求 scraper「必须导出可测试 helper」，逼四个 scraper 留着没人 require 的导出。

## Decision

- 副本一致性只由 `scripts/check-shared-files.sh` 里的 `sync-shared-assets.py check` 负责；测试脚本只测 source 副本的行为。
- `test-ai-patterns.sh` 用一张表驱动用例把八条密度规则正例原句放进台词引号里，断言都不报；去引号变异后八条全红。`test-degeneration.sh` 的纯台词复沓改用 ≥12 字长台词（紧邻两次、全文三次），紧邻复读与长句复读两个分支分别变异都会红。
- scraper 只保留无副作用 import 检查，不再要求导出；ciweimao、jjwxc、dz-browse、fanqie 的测试专用导出删除。
- Claude 打包身份只由 `check-plugin-packaging.py` 负责；Dashboard 静态资源改在 `dashboard-server.test.mjs` 的真实 HTTP 边界验证：取 `/`，按页面引用逐个取回资源。
- CI 的 sleep 检查断言 `sleep(100)` 至少阻塞 90ms，无断言的 cdp-utils 加载步骤删除（两端都已跑 `test-scan-runtime.js`）。

## Alternatives considered

- **测试里保留副本逐字比对作双保险**——最强理由：单跑某个检测器测试时也能发现副本漂移。否：CI 每个平台都跑 `check-shared-files.sh`，漂移报错信息更准（指出组名和文件），两处比对只是改一处要记着改两处。
- **给每条密度规则单独补一个引号负例**——最强理由：失败信息更贴近单条规则。否：八段几乎一样的 shell 样板；表驱动用例一次汇报所有失败的规则，失败信息同样逐条列出。
- **保留 scraper 导出以便日后写单元测试**——最强理由：纯函数有了导出才好测。否：现在没有任何消费方，扫榜行为已由 `runScraper` 驱动 CLI 的回归覆盖；真需要时在同一改动里连同测试一起加回。

## Consequences

- **收益**：每条保留的负例都经过变异证明能红；重复断言删掉后，同一契约改动只需改一处；四个 scraper 不再挂着无人使用的导出。
- **代价**：单独跑 `test-ai-patterns.sh` 不再发现检测器副本漂移，必须同时跑 `check-shared-files.sh`；Dashboard 的 API job 不再因 `.claude-plugin/marketplace.json` 变动而触发，打包变动只由 cross-platform 的打包守卫把关。

## Verification

`bash scripts/test-ai-patterns.sh`；`bash scripts/test-degeneration.sh`；`bash scripts/test-outline-copy.sh`；`node scripts/test-scan-runtime.js`；`bash scripts/check-shared-files.sh`；`npm run test:dashboard`；`python3 scripts/check-plugin-packaging.py`。
