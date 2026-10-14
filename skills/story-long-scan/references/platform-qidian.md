# 起点：采集与分析

作者选了起点才读本文。排行榜优先走下面的协议采集，不启动 Chrome。原脚本仍可用：先读 `https://m.qidian.com` 移动端 SSR pageContext，移动端不可用时才回退 CDP/PC 页面，文件头 `抓取方式` 标 `mobile-ssr` 或 `cdp-pc`。书库新书除外：只能走 Chrome，先 `/browser-cdp`，开之前告诉作者。

## 协议采集

男频移动榜走本技能 `bridge/rankmin_cli.py`，不进详情页，不保存原始 HTML。依赖只有 Python 标准库。

```bash
python3 bridge/rankmin_cli.py --out {输出目录} --limit 20 --qidian yuepiao,hotsales,readindex
```

这一路的热度是「榜单值」，不写总推荐、签约和收费模式。女生精选和女生月票在请求前失败，报 unavailable，结论不含这两条。不要把 `sanjiang`、`collect` 写进这条命令。任一榜失败退出码 2，已经写出的文件保留，不要打开网页去补。书库新书不在这条命令里。

## 榜单与命令

`node scripts/qidian-rank-scraper.js --type {榜单} --outdir {输出目录}`（`--type all` 全采；`--mode mobile|cdp` 强制一种方式；`--detail yes` 进详情页补标签、简介、最新更新）

| 榜单 | --type | URL | 看什么 |
|------|--------|-----|--------|
| 新人签约新书榜 | newsign | qidian.com/rank/newsign/ | 新人签约作品，新风向 |
| 签约作者新书榜 | signnewbook | qidian.com/rank/signnewbook/ | 已签约作者新作风向 |
| 公众作者新书榜 | pubnewbook | qidian.com/rank/pubnewbook/ | 发现潜力作者 |
| 新人作者新书榜 | newauthor | qidian.com/rank/newauthor/ | 新人赛道 |
| 三江推荐 | sanjiang | qidian.com/sanjiang/ | 编辑精选，按周分组（非 /rank/ 路径） |
| 月票榜 | yuepiao | qidian.com/rank/yuepiao/ | 付费认可度最高 |
| 畅销榜 | hotsales | qidian.com/rank/hotsales/ | 真金白银投票 |
| 阅读指数榜 | readindex | qidian.com/rank/readindex/ | 阅读量综合 |
| 收藏榜 | collect | qidian.com/rank/collect/ | 读者关注热度 |
| 原创推荐榜 | recom | qidian.com/rank/recom/ | 平台推荐 |

默认组合：新人签约新书榜 + 签约作者新书榜 + 月票榜 + 畅销榜。文件名 `起点{榜单}_{YYYYMMDD}.md`。

### 书库新书

作者说「新书」「最近冒头」「什么在起量」时再加，不进默认组合（要开 Chrome）。全部作品筛选页 qidian.com/all/action0-size1-update1/：男生、连载、30 万字以下、三日内更新，按人气排，每页 20 本。能补上已下新书榜、还在更新的新书。

```bash
node scripts/qidian-rank-scraper.js --type library --pages 3 --outdir {输出目录}   # 默认 3 页，最多 10，不进 --type all
```

所有页写进一份 `起点男频书库人气新书_{YYYYMMDD}.md`，名次接着排，就是人气排名；只收 30 万字以下，会拉低字数中位。字数从加密字体解出；签约、收费从移动端作品页补，补不到写 `[待补]`；总推荐单列为「新书总推荐」，不进热度口径。跟作者说「起点最近三天还在更新的 30 万字以内新书，按人气取前 3 页，要开浏览器」。

## 字段

排名、书名、作者、题材（主类·子类；聚合时主类作题材、子类进标签）、状态、签约、收费模式、字数、总推荐（聚合的热度口径）、标签/最新更新/简介（详情页）、作品页链接。额外必填：题材、字数、总推荐，缺的写 `[待补]`。

## 分析维度

| 维度 | 看什么 |
|---|---|
| 月票榜/畅销榜 | 付费认可与持续追读，最硬的指标 |
| 各新书榜 | 新作者、新题材的早期信号；和月票/畅销榜的题材占比对照 |
| 三江推荐 | 平台力推方向 |
| 追读率 | 决定推荐位分配（榜单上看不到，只能从月票/畅销间接推断） |
