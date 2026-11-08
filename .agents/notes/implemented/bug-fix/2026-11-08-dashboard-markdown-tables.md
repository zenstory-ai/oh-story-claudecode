# Agent Note: Dashboard 预览支持 Markdown 表格

Status: implemented

## Problem

Issue #537 报告 v0.10.3 卷纲预览保留表格的竖线和分隔线。自带卷纲也使用这种语法，但 Dashboard 的逐行 Markdown 解析器没有表格分支，所有表格行都落入普通段落。现有预览测试未覆盖表格。

## Decision

- 在现有解析器中识别表头和分隔行，输出语义化表格；支持可选首尾竖线、列对齐、转义竖线、缺列补空和多列截断。
- 表格继续使用先转义 HTML 再处理行内格式的路径；围栏代码和普通含竖线的段落保持原行为。首列记录对应源文件行号，分隔行不产生可见数据行。
- 复用现有主题变量添加边框、单元格间距和局部横向滚动，保留行号显示。
- Dashboard 资产属于 ClawHub 的 story 包；将其独立包版本从 1.0.36 递增为 1.0.37，使用 CI 固定的中央控制脚本重新生成内容摘要。
- 增加 Playwright 表格回归，覆盖桌面和移动视口、LF/CRLF、HTML 转义、代码块及相邻正文。按本次追加的整体 Dashboard 验证要求，另增保存冲突双分支、保存失败重试和删除冲突的浏览器回归。

## Alternatives considered

- 引入完整 Markdown 依赖：可以一次覆盖更多语法，但本次只需补齐明确缺失的表格能力，且仓库要求未经明确请求不增加依赖，因此沿用现有解析器。
- 只添加表格 CSS：改动最小，但当前根本没有生成 table 元素，不能解决原问题。

## Consequences

卷纲和其他 Markdown 文件中的表格可以直接预览，沿用离线静态资源部署。代价是继续维护自有 Markdown 子集；本次不承诺完整 CommonMark/GFM 兼容。

## Verification

- 修改前直接执行原始渲染函数：LF 和 CRLF 三行表格均生成 3 个 p、0 个 table。新增浏览器测试首次因本机缺少浏览器而无法启动，安装 Chromium 后测试在修复实现上通过；没有将该启动失败记作回归断言失败。
- `npm run test:dashboard`：27 项通过，0 失败、0 跳过。
- `npm run test:dashboard:e2e`：30 项通过（26 项桌面、4 项移动视口），包含表格、编辑安全、目录分页和搜索、异常提示、状态恢复、行号、换行保留及明暗主题。
- 实际 demo 卷纲的 10 张表格在桌面和手机视口均生成；检查明暗截图，控制台和页面错误均为 0。截图保存在本地忽略目录 `test-results/dashboard-visual-537/`，自动化表格截图在 `test-results/dashboard/`。
- `node --check`、`git diff --check`、`scripts/static-check.sh`、`scripts/skill-numbering.py check`、`scripts/check-doc-budget.sh`、`scripts/check-shared-files.sh` 和 `scripts/check-agent-notes.py` 通过。
- 验证环境为 macOS + Chromium；Windows 换行有 fixture 覆盖，未运行 Windows 实机浏览器。
- PR CI 中 Dashboard 的 Linux 浏览器测试和 Windows、Linux、macOS API 测试通过。ClawHub 首轮校验暴露遗漏的包摘要同步，补齐后按同一固定中央脚本运行基于主干 SHA 的离线校验。
