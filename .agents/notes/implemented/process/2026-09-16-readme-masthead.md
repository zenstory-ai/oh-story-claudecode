# Agent Note: README 头部统一为居中 masthead

Status: implemented

## Problem

六个仓库的 README 头部各不相同：标题有的用仓库 slug，徽章从 0 枚到 4 枚不等且风格混杂（Actions 徽章、social 样式、flat 样式并存），社区入口只有旗舰仓库有一个 Telegram 且埋在正文末尾。读者打开任何一个仓库，前一屏都看不出这是谁的项目、活不活跃、去哪提问。

## Decision

六个仓库的两份 README 共用同一个居中 masthead，顺序固定：品牌标记（76px，引用 `https://zenstory.ai/brand/zenstory-ai-mark.svg`）、`<h1>` 产品名、一句加粗的话、一行导航（项目主页 · 两个正文锚点 · 另一种语言）、一行 flat-square 徽章、一行 for-the-badge 社区按钮。徽章统一 flat-square 并使用品牌色：star 数 `#22D3EE`，Release 与计数 `#081431`，License `#1F6FEB`。核心四项是 Stars、Release、项目规模（Skills N 或 Workbenches N）、License；仓库特有的运行事实（Python 版本、CI、Validate、MiMo）接在其后。产品名用站点上的名字，不用仓库 slug。

## Alternatives considered

- **像 hypit 那样给每个产品做带字的 logo 图当标题**。最强理由：图片字标的视觉密度远高于文字，一眼能认出品牌。被否：六个产品要六张字标，是一次完整的设计工作，超出这次改动的范围；文字 `<h1>` 还能被搜索、目录和读屏软件读到。
- **把 logo 文件复制进每个仓库**。最强理由：不依赖外部站点，fork 和离线渲染都正常。被否：六份副本以后换标要改六处；已实测 GitHub 的 camo 代理能正确返回 zenstory.ai 上的这个 SVG。

## Consequences

- 收益：六个仓库第一屏一致，star、版本、规模、许可和提问入口都在固定位置；换品牌标记只改线上一个文件。
- 代价：logo 依赖 zenstory.ai 可访问；GitHub 给 `<h1>` 的下边框去不掉，标题与副标题之间会留一条横线。
- 本仓库顺带的取舍：无。

## Verification

27 个徽章 URL 逐个请求，全部返回 200 且标签正确（含 star 数、Release tag、CI/Validate 状态）；masthead 经 GitHub 官方 markdown 接口渲染，浅色与深色主题下目视确认。
