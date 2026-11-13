# 刺猬猫：采集与分析

先用 `/browser-cdp` 启动 Chrome。刺猬猫是小平台，每榜只有前 10 本；同方向不足 10 本，聚合标为样本少。

## 默认命令

```bash
node scripts/ciweimao-rank-scraper.js --type monthly --outdir {outdir}    # 月票榜
node scripts/ciweimao-rank-scraper.js --type subscribe --outdir {outdir}  # 订阅榜
```

作者要看新书里在冒头的，再加新书榜：`--type newbook`。

## 可选参数

`--type`：click 点击榜 / favor 收藏榜 / recommend 推荐榜 / subscribe 订阅榜 / monthly 月票榜 / tsukkomi 吐槽榜 / newbook 新书榜 / blade 刀片榜 / update 更新榜 / all 全部（不写时默认）。

## 字段与热度口径

排名、书名、作者（页面常只在榜首显示）、题材（常在非榜首显示）、榜单值、作品页链接；若页面改版以文件头「数据质量」为准。各榜的榜单值口径不同（点击、收藏、月票……），多榜聚合时取同书最大的榜单值，不能拿来比热度，热度回查单榜。作者信息不齐时同一本书跨榜可能没合并，须核对样本本数。

## 采不到时

终端提示「未解析到榜单」或文件头「数据质量」标了问题：在 Chrome 里打开 `https://www.ciweimao.com/rank-index`，确认页面正常、没有跳到登录或验证页，再重采。

## 分析维度

| 维度 | 看什么 |
|---|---|
| 月票榜、订阅榜 | 付费认可 |
| 新书榜 | 二次元新梗与新设定 |
| 吐槽榜、刀片榜 | 互动强度；争议判断要有内容证据 |

## 本平台读者

二次元、轻小说、游戏/动漫同人与克系奇幻受众。重角色魅力、弹幕吐槽感与设定反差（严肃世界观配鲜活人设同样吃香）；雷区是脱离角色魅力的干瘪说教、强行喂刀或同人严重OOC。
