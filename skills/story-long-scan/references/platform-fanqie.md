# 番茄：采集与分析

作者选了番茄才读本文。分类榜优先走下面的协议采集，不启动 Chrome。全题材阅读榜和书库「最热」仍走原脚本：列表页有字体反爬，须先用 `/browser-cdp` 启动 Chrome，再由脚本从详情页（内嵌 JSON `bookName`/`author`/`abstract`/`categoryV2` + `<title>` + og:meta）多策略解码书名、作者、题材、标签、简介。

## 协议采集

```bash
python3 bridge/rankmin_cli.py --out {输出目录} --limit 20 --fanqie male-hot-xifangqihuan,male-newbook-xifangqihuan,female-hot-gufengshiqing,female-newbook-gufengshiqing
```

默认是这四个分类，不是全题材阅读榜，也不是书库。`hot` 是分类热门，`newbook` 是分类最新。要看正在起量的新书，把 `male-rising-<题材>`、`female-rising-<题材>` 加在同一条 `--fanqie` 后面：只留连载且纯数字字数严格小于 300000 的书。标签只取简介里成对的【】，没有就不写。依赖是 `bridge/requirements.txt` 里的 `curl_cffi`。任一榜失败退出码 2，已经写出的文件保留。

## 榜单与命令

URL `fanqienovel.com/rank/{channel}_{type}_{cat_id}`：channel 0=女频/1=男频，type 1=新书榜/2=阅读榜。

```bash
node scripts/fanqie-rank-scraper.js --channel 1 --type 2 --outdir {输出目录}     # 男频阅读榜（默认）
node scripts/fanqie-rank-scraper.js --channel all --top 15 --outdir {输出目录}   # 男女频，每题材前 15 本
```

脚本逐题材采集（每题材上限约 20，`--top N` 可调），每 5 本一批请求详情页。默认组合：男频阅读榜全题材 + 女频阅读榜全题材；要看新风向再加新书榜（`--type 1`）或下面的书库「最热」。文件名 `番茄{频道}{榜单}_全题材_{YYYYMMDD}.md`。一份全题材就是七百来条，只读聚合结果，不整份读原始文件。

题材 cat_id —— 男频 19 个：西方奇幻(1141) / 东方仙侠(1140) / 科幻末世(8) / 都市日常(261) / 都市修真(124) / 都市高武(1014) / 历史古代(273) / 战神赘婿(27) / 都市种田(263) / 传统玄幻(258) / 历史脑洞(272) / 悬疑脑洞(539) / 都市脑洞(262) / 玄幻脑洞(257) / 悬疑灵异(751) / 抗战谍战(504) / 游戏体育(746) / 动漫衍生(718) / 男频衍生(1016)；女频 18 个：古风世情(1139) / 科幻末世(8) / 游戏体育(746) / 女频衍生(1015) / 玄幻言情(248) / 种田(23) / 年代(79) / 现言脑洞(267) / 宫斗宅斗(246) / 悬疑脑洞(539) / 古言脑洞(253) / 快穿(24) / 青春甜宠(749) / 星光璀璨(745) / 女频悬疑(747) / 职场婚恋(750) / 豪门总裁(748) / 民国言情(1017)。

### 书库「最热」

URL `fanqienovel.com/library/{筛选}/page_{n}?sort=hottes`：筛选段 `audience1`=男生、`audience0`=女生（不写＝不分男女），`stat1`=连载中、`stat0`=已完结，`count0`=30 万字以下（`count1`-`count4` 依次 30-50 万、50-100 万、100-200 万、200 万以上），全不选时是 `all`。每页 18 本，按热度排。

```bash
node scripts/fanqie-rank-scraper.js --source library --channel all --outdir {输出目录}            # 男、女各一份：连载中、30 万字以下、前 3 页
node scripts/fanqie-rank-scraper.js --source library --channel mix --pages 5 --outdir {输出目录}  # 不分男女
```

`--stat 1|0|any`、`--count 0-4|any` 改筛选。默认组合（连载中、30 万字以下）是**正在起量的新书**：阅读榜被老书占住时，看它才知道新书里什么题材在冒头，文件名与列表名带「新书」，聚合时算进「新书榜」列。列表页书名和数字都被字体反爬，脚本只按页面顺序取 bookId，书名、题材、在读、字数都由详情页解码。

## 字段

排名、书名、作者、题材（详情页 categoryV2）、状态、在读（核心指标，聚合的热度口径）、字数、标签（简介开头 `【种田+慢热+西幻】`，题材细分的真实信号）、最新更新、bookId、作品页链接、简介。详情页没有数字评分，不输出评分。解码失败的书名显示 `（标题待解析）`，bookId 与链接保留供回查。

## 故障排查

文件头 `数据质量` 标 `[标题解析异常]`（书名多为 `（标题待解析）`）：多为详情页结构变动或被登录/验证页拦截。在已登录的 Chrome 里手动打开任一 `https://fanqienovel.com/page/{bookId}`，确认页面正常、不是验证页；控制台报 `CDP 无响应` 就按 browser-cdp 重新启动 Chrome。确认正常后重采。

## 分析维度

| 维度 | 看什么 |
|---|---|
| 阅读榜 | 流量与读者规模，在读数为核心指标 |
| 新书榜 | 新题材、新风向的早期信号（聚合表的「新书榜」列） |
| 题材分布 | 各品类在读数集中度（热度中位对照本数） |
| 在读数差距 | 同题材头部与腰部的流量差 |
| 标签热词 | 【】内标签组合揭示细分卖点 |
