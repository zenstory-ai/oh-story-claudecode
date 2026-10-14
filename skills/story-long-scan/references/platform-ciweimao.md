# 刺猬猫：采集与分析

作者选了刺猬猫才读本文。排行榜优先走下面的协议采集，不启动 Chrome，不下章节。原网页脚本仍可用：需先用 `/browser-cdp` 启动 Chrome。rank-index 单页展示全部榜单，脚本按文本解析，按书名归一回填作品页链接，带连通性自检与空结果重试。

## 协议采集

```bash
python3 bridge/rankmin_cli.py --out {输出目录} --limit 20 --ciweimao fans_value:week,favor:week,tsukkomi:week,yp_new:month
```

没有账号环境变量时，客户端自己注册游客。会话默认写在 `~/.oh-story/ciweimao-guest.json`，用 `CIWEIMAO_STATE` 改路径。出口用 `CIWEIMAO_PROXY_URL`，或 `KDL_SECRET_ID` / `KDL_SECRET_KEY`；密钥文件默认目录是 `~/.oh-story/ciweimao/`。不要把会话或代理地址写进报告。依赖见 `bridge/requirements.txt`：`curl_cffi`、`pycryptodome`，走快代理时再加 `kdl`。任一榜失败退出码 2，已经写出的文件保留。榜单值写 `[待补]` 时不要改去作品页补。

## 榜单与命令

`node scripts/ciweimao-rank-scraper.js --type {榜单} --outdir {输出目录}`：click 点击榜 / favor 收藏榜 / recommend 推荐榜 / subscribe 订阅榜 / monthly 月票榜 / tsukkomi 吐槽榜 / newbook 新书榜 / blade 刀片榜 / all 全部（默认）。

## 字段

排名、书名、作者（仅榜首条目带）、题材（其余条目带）、榜单值（聚合的热度口径；各榜含义不同，不跨榜比较）、作品页链接。刺猬猫是小平台：同方向不到 10 本才算稀疏，聚合时加 `--sparse 10`。

## 分析维度

| 维度 | 看什么 |
|---|---|
| 月票/订阅榜 | 付费认可 |
| 新书榜 | 二次元新梗与新设定 |
| 吐槽/刀片榜 | 读者互动强度与争议点 |
