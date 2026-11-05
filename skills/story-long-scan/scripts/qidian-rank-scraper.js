#!/usr/bin/env node
/**
 * 起点中文网 排行榜采集脚本
 *
 * 配合 browser-cdp skill 使用。先启动 Chrome CDP 环境，再运行本脚本。
 * 采集策略：
 *   1. 默认优先读取 m.qidian.com 的 SSR pageContext JSON（不依赖 CDP，规避 PC 站风控页）。
 *   2. 移动端不可用时再回退到 Chrome CDP 采集 PC 页面。
 * 输出的榜单 Markdown 格式见 aggregate-rank.js 文件头，聚合按它解析。
 *
 * 用法：
 *   node qidian-rank-scraper.js --type hotsales               # 畅销榜
 *   node qidian-rank-scraper.js --type yuepiao                 # 月票榜
 *   node qidian-rank-scraper.js --type signnewbook             # 签约作者新书榜
 *   node qidian-rank-scraper.js --type pubnewbook              # 公众作者新书榜
 *   node qidian-rank-scraper.js --type newauthor               # 新人作者新书榜
 *   node qidian-rank-scraper.js --type newsign                 # 新人签约新书榜
 *   node qidian-rank-scraper.js --type recom                   # 原创推荐榜
 *   node qidian-rank-scraper.js --type sanjiang                 # 三江推荐（/sanjiang/，非 /rank/ 路径）
 *   node qidian-rank-scraper.js --type all                     # 全部榜单
 *   node qidian-rank-scraper.js --type hotsales --mode mobile  # 仅使用移动端 SSR
 *   node qidian-rank-scraper.js --type hotsales --mode cdp     # 仅使用备用 CDP/PC 页面
 *   node qidian-rank-scraper.js --type library [--pages 3]     # 书库人气新书（只走 CDP，不进 all）
 *
 * 书库人气新书：男生·连载·30万字以下·三日内更新、人气排序的「全部作品」筛选页，
 * 翻前 N 页（--pages 取 1-10，默认 3；只对 --type library 有效，其他榜单传了直接报错）。
 * PC 页直接 HTTPS 会被风控拦，只能用 CDP 打开；字数靠解码页面的反爬字体，
 * 总推荐/签约/收费逐本取 m.qidian.com 作品页补齐。
 *
 * 前置：
 *   默认 mobile/auto 模式不需要 Chrome（--type library 除外）。
 *   cdp 模式与 --type library 需要：node {SKILL_DIR}/browser-cdp/scripts/setup-cdp-chrome.js 9222
 */

const fs = require("fs");
const https = require("https");
const path = require("path");
const { ab, sleep, evalJSON, scrollLoad, getArg, localDateStamp, runCli } = require("./cdp-utils");

const PC_BASE_URL = "https://www.qidian.com/rank";
const MOBILE_BASE_URL = "https://m.qidian.com";

/** 验证码自动重试最大次数 */
const MAX_CAPTCHA_RETRIES = 3;
/** 等待用户手动解决验证码的最大秒数 */
const MAX_CAPTCHA_WAIT_SEC = 120;
/** 轮询验证码是否解除的间隔（毫秒） */
const CAPTCHA_POLL_INTERVAL = 5000;

const MOBILE_HEADERS = {
  "User-Agent":
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) " +
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
  Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
  "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
  "Accept-Encoding": "identity",
};

const RANK_TYPES = [
  { id: "hotsales", label: "畅销榜", mobilePath: "/rank/hotsales/" },
  { id: "yuepiao", label: "月票榜", mobilePath: "/rank/yuepiao/" },
  {
    id: "signnewbook",
    label: "签约作者新书榜",
    mobilePath: "/rank/sign/",
    mobileLabel: "签约榜",
  },
  {
    id: "pubnewbook",
    label: "公众作者新书榜",
    mobilePath: "/rank/newbook/",
    mobileLabel: "新书榜",
  },
  { id: "newauthor", label: "新人作者新书榜", mobilePath: "/rank/newauthor/", mobileLabel: "新人榜" },
  {
    id: "newsign",
    label: "新人签约新书榜",
    mobilePath: "/rank/sign/",
    mobileLabel: "签约榜",
  },
  { id: "recom", label: "原创推荐榜", mobilePath: "/rank/rec/", mobileLabel: "推荐榜" },
  { id: "readindex", label: "阅读指数榜", mobilePath: "/rank/readindex/" },
  {
    id: "collect",
    label: "收藏榜",
    mobilePath: "/rank/newfans/",
    mobileLabel: "书友榜（移动端替代）",
  },
  {
    id: "sanjiang",
    label: "三江推荐",
    baseUrl: "https://www.qidian.com/sanjiang/",
    mobilePath: "/sanjiang/",
  },
  // 伪榜单：全部作品筛选页翻页。只走 CDP、不进 --type all（all 默认不需要 Chrome）。
  // 列表名带「新书」，聚合时进「新书榜」列。
  {
    id: "library",
    label: "男频书库人气新书",
    baseUrl: "https://www.qidian.com/all/action0-size1-update1/",
    library: true,
  },
];

// ---------------------------------------------------------------------------
// 页面提取
// ---------------------------------------------------------------------------

/**
 * 提取起点 SSR 榜单页面的书籍列表。
 * 起点页面结构：.book-img-text ul > li，每个 li 内：
 *   h2 > a          → 书名+链接
 *   p.author         → 作者 | 题材 · 子题材 | 状态
 *   p.intro          → 简介
 *   p.update > a+span → 最新更新章节+日期
 */
function extractBookList(port) {
  const js =
    "JSON.stringify((()=>{" +
    "var items=[];" +
    "function metrics(text){" +
    "  var flat=String(text||'').replace(/\\s+/g,' ').trim();" +
    "  var words=flat.match(/([\\d.]+\\s*万?字)/);" +
    "  var total=flat.match(/([\\d.,]+\\s*万?)\\s*总推荐/);" +
    "  var signing=flat.match(/(?:^|\\s|·)(已签约|未签约|签约)(?=\\s|·|$)/);" +
    "  var pricing=flat.match(/(?:^|\\s|·)(VIP|免费)(?=\\s|·|$)/i);" +
    "  return {words:words?words[1].replace(/\\s+/g,''):'',totalRecommendations:total?total[1]:'',signing:signing?signing[1]:'',pricing:pricing?pricing[1].toUpperCase()==='VIP'?'VIP':pricing[1]:''};" +
    "}" +
    "var lis=document.querySelectorAll('.book-img-text ul li');" +
    "if(!lis.length){" +
    // 兜底：用 H2 链接定位
    "  var h2s=document.querySelectorAll('h2 a[href*=\"/book/\"]');" +
    "  h2s.forEach(function(a,idx){" +
    "    var c=a.parentElement;" +
    "    for(var j=0;j<3;j++){if(c.parentElement)c=c.parentElement}" +
    "    var text=c.innerText||'';" +
    "    var metric=metrics(text);" +
    "    var href=a.getAttribute('href')||a.href||'';" +
    "    var url=href?(href.indexOf('http')===0?href:'https:'+href):'';" +
    "    items.push({rank:idx+1,title:a.textContent.trim(),url:url,author:'',genre:'',status:'',words:metric.words,rankValue:'',totalRecommendations:metric.totalRecommendations,signing:metric.signing,pricing:metric.pricing,descText:'',updateText:text.replace(/\\s+/g,' ').trim().substring(0,300)})" +
    "  });" +
    "  return items" +
    "}" +
    "lis.forEach(function(li,idx){" +
    "  var titleEl=li.querySelector('h2 a');" +
    "  if(!titleEl)return;" +
    "  var title=titleEl.textContent.trim();" +
    "  var href=titleEl.getAttribute('href')||titleEl.href||'';" +
    "  var url=href?(href.indexOf('http')===0?href:'https:'+href):'';" +
    // 作者：p.author > a.name
    "  var authorEl=li.querySelector('p.author a.name');" +
    "  var author=authorEl?authorEl.textContent.trim():'';" +
    // 题材：p.author > a (非 .name 非 .go-sub-type)
    "  var genreEls=li.querySelectorAll('p.author a');" +
    "  var genre='';var subGenre='';" +
    "  genreEls.forEach(function(a){" +
    "    if(a.classList.contains('name'))return;" +
    "    if(!genre){genre=a.textContent.trim()}else if(!subGenre){subGenre=a.textContent.trim()}" +
    "  });" +
    // 状态：p.author > span:last-child
    "  var statusEl=li.querySelector('p.author span');" +
    "  var status=statusEl?statusEl.textContent.trim():'';" +
    // 简介：p.intro
    "  var introEl=li.querySelector('p.intro');" +
    "  var descText=introEl?introEl.textContent.trim():'';" +
    // 更新：p.update
    "  var updateEl=li.querySelector('p.update');" +
    "  var updateText=updateEl?updateEl.textContent.replace(/\\s+/g,' ').trim():'';" +
    "  var metric=metrics(li.innerText||'');" +
    "  if(title){" +
    "    items.push({rank:idx+1,title:title,url:url,author:author,genre:genre+(subGenre?'·'+subGenre:''),status:status,words:metric.words,rankValue:'',totalRecommendations:metric.totalRecommendations,signing:metric.signing,pricing:metric.pricing,descText:descText,updateText:updateText})" +
    "  }" +
    "});" +
    "return items" +
    "})())";
  return evalJSON(port, js) || [];
}

/** 从详情页提取标签和简介 */
function extractDetail(port) {
  const js =
    "JSON.stringify((()=>{" +
    "var tags=Array.from(document.querySelectorAll('[class*=\"tag\"] a,[class*=\"label\"] a')).map(function(a){return a.textContent.trim()});" +
    "var intro=document.querySelector('[class*=\"intro\"],[class*=\"summary\"],[class*=\"desc\"]');" +
    "var introText=intro?intro.textContent.trim():'';" +
    "var update=document.querySelector('[class*=\"update\"],[class*=\"latest\"]');" +
    "var updateText=update?update.textContent.trim():'';" +
    "var info=document.querySelector('.book-info,[class*=\"book-info\"],[class*=\"bookInfo\"]');" +
    "var infoText=info?(info.innerText||info.textContent||''):(document.body?document.body.innerText||'':'');" +
    "var words=infoText.match(/([\\d.]+\\s*万?字)/);" +
    "var total=infoText.match(/([\\d.,]+\\s*万?)\\s*总推荐/);" +
    "var signing=infoText.match(/(?:^|\\s|·)(已签约|未签约|签约)(?=\\s|·|$)/);" +
    "var pricing=infoText.match(/(?:^|\\s|·)(VIP|免费)(?=\\s|·|$)/i);" +
    "return {tags:tags,intro:introText,update:updateText,words:words?words[1].replace(/\\s+/g,''):'',totalRecommendations:total?total[1]:'',signing:signing?signing[1]:'',pricing:pricing?pricing[1].toUpperCase()==='VIP'?'VIP':pricing[1]:''}" +
    "})())";
  return evalJSON(port, js);
}

/**
 * 检测当前页面是否被验证码/安全验证拦截。
 * 起点常见拦截页面特征：页面中出现验证码关键词，或页面缺少榜单 DOM 元素。
 * @returns {{ blocked: boolean, reason: string } | null} 若被拦截返回原因对象，否则 null
 */
function captchaCheckJS() {
  return (
    "JSON.stringify((()=>{" +
    // 页面上已有成片的作品链接就是正常列表页：书库页前 3000 字里有整段简介和章节名，
    // 书里写到「验证」「拖动」之类的字不能当成被拦（会白等重试和 120 秒人工验证）。
    "if(document.querySelectorAll('a[href*=\"/book/\"]').length>=5)return {blocked:false,reason:''};" +
    "var bodyText=document.body?(document.body.innerText||'').substring(0,3000):'';" +
    "var lower=bodyText.toLowerCase();" +
    "var keywords=['验证','captcha','verify','安全验证','滑块','拖动','请完成验证'," +
    "'混元','人机验证','异常请求','访问验证','操作频繁','请求过于频繁','waf','请稍后再试'];" +
    "for(var i=0;i<keywords.length;i++){" +
    "  if(lower.indexOf(keywords[i])>-1){" +
    "    return {blocked:true,reason:keywords[i]};" +
    "  }" +
    "}" +
    // li[data-rid]：书库「全部作品」筛选页的条目。该页目前也套在 .book-img-text 里，
    // 显式列出是防它改版后被误判成被拦（白等 3 次重试 + 120 秒手动验证）
    "var hasContent=document.querySelector('.book-img-text ul li,.rank-body,.rank-list,.book-img-text,li[data-rid]');" +
    "if(!hasContent){" +
    "  return {blocked:true,reason:'页面无榜单内容(可能被拦截)'};" +
    "}" +
    "return {blocked:false,reason:''};" +
    "})())"
  );
}

function isCaptchaPage(port) {
  const result = evalJSON(port, captchaCheckJS());
  return result && result.blocked === true ? result : null;
}

/**
 * 打开 URL 并等待页面加载，自动处理验证码拦截。
 * 重试策略：
 *   1. 正常加载页面
 *   2. 检测到验证码 → 等待递增延时后刷新重试（最多 MAX_CAPTCHA_RETRIES 次）
 *   3. 仍被拦截 → 提示用户在 Chrome CDP 窗口手动完成验证，轮询等待直到解除或超时
 *
 * @returns {boolean} true=页面已就绪，false=无法通过验证码
 */
function openWithCaptchaHandling(port, url) {
  for (let attempt = 1; attempt <= MAX_CAPTCHA_RETRIES; attempt++) {
    ab(port, "open", url);
    // 首次 3 秒，后续每次多等 2 秒
    sleep(3000 + (attempt - 1) * 2000);

    const captcha = isCaptchaPage(port);
    if (!captcha) {
      return true;
    }
    console.log(`  ⚠ 检测到安全拦截 (${captcha.reason})，第 ${attempt}/${MAX_CAPTCHA_RETRIES} 次重试...`);
    // 递增等待后再次尝试
    sleep(attempt * 5000);
  }

  // 自动重试全部失败 → 等待用户手动处理
  console.log(`  ⚠ 自动重试未通过验证码，请在 Chrome CDP 窗口手动完成验证`);
  console.log(`  ⏳ 等待手动验证（最长 ${MAX_CAPTCHA_WAIT_SEC} 秒）...`);

  const startTime = Date.now();
  while (Date.now() - startTime < MAX_CAPTCHA_WAIT_SEC * 1000) {
    sleep(CAPTCHA_POLL_INTERVAL);
    // 刷新页面检查验证码是否已解除
    ab(port, "open", url);
    sleep(3000);
    const captcha = isCaptchaPage(port);
    if (!captcha) {
      console.log(`  ✓ 验证码已解除，继续采集`);
      return true;
    }
    const elapsed = Math.round((Date.now() - startTime) / 1000);
    process.stdout.write(`  等待中... (${elapsed}s)\r`);
  }
  console.log(`  ✗ 等待超时，验证码仍未解除`);
  return false;
}

// ---------------------------------------------------------------------------
// 移动端 SSR 提取（默认路径）
// ---------------------------------------------------------------------------

function mobileUrl(pathname) {
  if (!pathname) return "";
  return pathname.startsWith("http") ? pathname : `${MOBILE_BASE_URL}${pathname}`;
}

function fetchText(url, redirects = 3) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, { headers: MOBILE_HEADERS, timeout: 15000 }, (res) => {
      if (
        redirects > 0 &&
        res.statusCode >= 300 &&
        res.statusCode < 400 &&
        res.headers.location
      ) {
        res.resume();
        const nextUrl = new URL(res.headers.location, url).toString();
        fetchText(nextUrl, redirects - 1).then(resolve, reject);
        return;
      }

      let body = "";
      res.setEncoding("utf8");
      res.on("data", (chunk) => {
        body += chunk;
      });
      res.on("end", () => {
        if (res.statusCode < 200 || res.statusCode >= 300) {
          reject(new Error(`HTTP ${res.statusCode}`));
          return;
        }
        resolve(body);
      });
    });

    req.on("timeout", () => {
      req.destroy(new Error("request timeout"));
    });
    req.on("error", reject);
  });
}

function extractMobilePageContext(html) {
  const m = html.match(
    /<script[^>]+id=["']vite-plugin-ssr_pageContext["'][^>]*>([\s\S]*?)<\/script>/i
  );
  if (!m) return null;
  try {
    return JSON.parse(m[1]);
  } catch (e) {
    console.log(`  ⚠ 移动端 pageContext JSON 解析失败: ${e.message}`);
    return null;
  }
}

function normalizeMobileBook(record, idx) {
  const title = record.bName || record.bookName || "";
  const bid = record.bid || record.bookId || "";
  const genre = [record.cat, record.subCat].filter(Boolean).join("·");
  const first = (...keys) => {
    for (const key of keys) {
      const value = record[key];
      if (value !== undefined && value !== null && value !== "") return String(value);
    }
    return "";
  };

  return {
    rank: record.rankNum || idx + 1,
    title,
    url: bid ? `${MOBILE_BASE_URL}/book/${bid}/` : "",
    author: record.bAuth || record.author || "",
    genre,
    status: first("status", "bookStatus", "serializationStatus"),
    words: first("cnt", "wordCount", "words", "wordCnt"),
    rankValue: first("rankCnt", "rankValue"),
    totalRecommendations: first(
      "totalRecommend",
      "totalRecommendations",
      "recommendCount",
      "totalRec"
    ),
    signing: first("signStatus", "signing", "contractStatus"),
    pricing: first("vipStatus", "pricing", "chargeStatus"),
    descText: record.desc || "",
    updateText: "",
  };
}

/** 清洗简介：折叠空白，超过 100 字时优先在句末截断。 */
function cleanDesc(raw) {
  const desc = String(raw || "").replace(/\s+/g, " ").trim();
  if (desc.length <= 100) return desc;
  const cut = desc.slice(0, 100);
  const sentence = cut.match(/^[\s\S]*[。！？]/);
  return (sentence ? sentence[0] : cut) + "...";
}

/** 排行榜条目里题材或字数缺失超过这个比例，「数据质量」标为有问题（多半是页面改版） */
const RANK_FIELD_MISSING_RATIO = 0.5;

/** 排行榜的「数据质量」「问题摘要」两行；书库新书自己算好后经 extraLines 传入，不走这里。 */
function rankQualityLines(books) {
  const problems = [];
  for (const [field, label] of [["genre", "题材"], ["words", "字数"]]) {
    const missing = books.filter((b) => !b[field]).length;
    if (missing > books.length * RANK_FIELD_MISSING_RATIO) problems.push(`${label}缺失 ${missing} / ${books.length} 条`);
  }
  const noHeat = books.filter((b) => !b.totalRecommendations && !b.rankValue).length;
  if (noHeat > books.length * RANK_FIELD_MISSING_RATIO) problems.push(`总推荐缺失 ${noHeat} / ${books.length} 条`);
  return [
    `- 数据质量：${problems.length ? "[存在问题]" : "[OK]"}`,
    `- 问题摘要：${problems.length ? problems.join("；") : "无"}`,
  ];
}

function renderMarkdown(rt, books, url, sourceMode, extraLines = []) {
  const now = new Date().toISOString();
  const quality = extraLines.some((line) => /^- 数据质量：/.test(line)) ? [] : rankQualityLines(books);
  const lines = [
    `# 起点 · ${rt.label}`,
    "",
    `- 来源：${url}`,
    `- 抓取方式：${sourceMode}`,
    `- 抓取时间：${now}`,
    `- 条目数：${books.length}`,
    ...extraLines,
    ...quality,
    "",
    "---",
    "",
  ];

  for (let i = 0; i < books.length; i++) {
    const b = books[i];
    lines.push(`## #${b.rank || i + 1} ${b.title}`);
    const meta = [b.author, b.genre, b.status].filter(Boolean).join(" · ");
    if (meta) lines.push(`*${meta}*`);
    const required = (value) =>
      value === undefined || value === null || value === "" ? "[待补]" : String(value);
    lines.push(`**字数：${required(b.words)}**`);
    if (b.rankValue) lines.push(`**榜单值：${b.rankValue}**`);
    // 书库新书的总推荐只有几千到几万，和月票、畅销榜的老书混算会把题材热度中位拉低两个数量级；
    // 换个行名单列，聚合不把它当热度口径（书库按名次即人气排名），数字留在原始条目里供抽样看。
    if (b.library) lines.push(`**新书总推荐：${required(b.newBookRecom)}**`);
    else lines.push(`**总推荐：${required(b.totalRecommendations)}**`);
    lines.push(`**签约：${required(b.signing)}**`);
    lines.push(`**收费模式：${required(b.pricing)}**`);
    if (b.updateText) lines.push(`**最新更新：** ${b.updateText}`);
    if (b.tags?.length) lines.push(`**标签：** ${b.tags.join("、")}`);
    if (b.url) lines.push(`[作品页](${b.url})`);
    const desc = cleanDesc(b.descText);
    if (desc) {
      lines.push("");
      lines.push("**简介**");
      lines.push("");
      lines.push(desc);
    }
    lines.push("", "---", "");
  }

  return lines.join("\n");
}

async function scrapeRankMobile(rankTypeId) {
  const rt = RANK_TYPES.find((r) => r.id === rankTypeId);
  if (!rt) {
    console.log(`  ⚠ 未知榜单类型: ${rankTypeId}`);
    return null;
  }
  if (!rt.mobilePath) {
    console.log(`  ⚠ 榜单 ${rankTypeId} 暂无移动端 SSR 路径`);
    return null;
  }

  const url = mobileUrl(rt.mobilePath);
  console.log(`\n→ 采集 起点${rt.label}（移动端 SSR）...`);
  console.log(`  URL: ${url}`);

  const html = await fetchText(url);
  const pageContext = extractMobilePageContext(html);
  const pageData = pageContext?.pageContext?.pageProps?.pageData;
  const records = pageData?.records || [];
  const books = records.map(normalizeMobileBook).filter((b) => b.title);

  if (!books.length) {
    console.log("  ⚠ 移动端 SSR 未提取到书籍");
    return null;
  }

  console.log(`  ✓ 提取 ${books.length} 本`);

  const extraLines = [];
  if (rt.mobileLabel && rt.mobileLabel !== rt.label) {
    extraLines.push(`- 移动端实际榜单：${rt.mobileLabel}`);
  }
  if (FETCH_DETAIL) {
    extraLines.push("- 说明：移动端 SSR 已包含简介；--detail 在 mobile/auto 模式下不会额外打开详情页。");
  }

  return renderMarkdown(rt, books, url, "mobile-ssr", extraLines);
}

// ---------------------------------------------------------------------------
// 书库人气新书（--type library）：全部作品筛选页翻页 + 反爬字体解码 + 移动端详情补字段
// ---------------------------------------------------------------------------

const LIBRARY_DEFAULT_PAGES = 3;
const LIBRARY_MAX_PAGES = 10;
/** 页面上必须真处于选中状态的筛选项；对不上就不能把这页写成「人气新书」 */
const LIBRARY_SITE = "男生";
const LIBRARY_FILTERS = ["连载", "30万字以下", "三日内"];
const LIBRARY_SORT = "人气排序";
/** 逐本取移动端详情的间隔（毫秒） */
const LIBRARY_DETAIL_GAP_MS = 400;
/** 详情失败超过这个比例，问题摘要里要写明 */
const LIBRARY_DETAIL_FAIL_RATIO = 0.5;

const FONT_HOST = "qdfepccdn.qidian.com";
const FONT_PATH_RE = /^\/gtimg\/qd_anti_spider\/([A-Za-z0-9]+)\.ttf$/;
const FONT_MAX_BYTES = 2 * 1024 * 1024;
const FONT_HEADERS = {
  "User-Agent":
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " +
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
  Accept: "*/*",
  "Accept-Encoding": "identity",
  Referer: "https://www.qidian.com/",
};

/** 字形名 → 字符：只认 zero..nine 与 period，其余字形一律算解不出 */
const GLYPH_CHARS = {
  zero: "0",
  one: "1",
  two: "2",
  three: "3",
  four: "4",
  five: "5",
  six: "6",
  seven: "7",
  eight: "8",
  nine: "9",
  period: ".",
};
/** post 2.0 里下标 < 258 的是 Mac 标准字形序；只列出用得到的几个 */
const MAC_STANDARD_GLYPHS = {
  17: "period",
  19: "zero",
  20: "one",
  21: "two",
  22: "three",
  23: "four",
  24: "five",
  25: "six",
  26: "seven",
  27: "eight",
  28: "nine",
};
/** 单张 cmap 最多展开的码点数，防畸形字体把区间写成整个 Unicode */
const CMAP_MAX_ENTRIES = 70000;

/**
 * 反爬字数用的码点（西夏文区与私用区）。输出里绝不能出现这些字符：
 * 解不出来就写 [待补]，而不是把乱码写进报告。
 */
const CIPHER_CHARS_RE = /[\uE000-\uF8FF\u{17000}-\u{18D8F}\u{F0000}-\u{10FFFF}]/gu;

function stripCipherChars(value) {
  return String(value === undefined || value === null ? "" : value)
    .replace(CIPHER_CHARS_RE, "")
    .replace(/\s+/g, " ")
    .trim();
}

function libraryPageUrl(page) {
  const base = RANK_TYPES.find((r) => r.library).baseUrl;
  return page === 1 ? base : base.replace(/\/$/, `-page${page}/`);
}

/** --pages 校验：只接受 1..LIBRARY_MAX_PAGES 的整数；未传时用默认值 */
function parseLibraryPages(raw, given) {
  if (!given) return LIBRARY_DEFAULT_PAGES;
  const text = raw === null || raw === undefined ? "" : String(raw).trim();
  const n = /^\d+$/.test(text) ? Number(text) : NaN;
  if (!Number.isInteger(n) || n < 1 || n > LIBRARY_MAX_PAGES) {
    throw new Error(`未知 --pages: ${text || "（空）"}（取 1-${LIBRARY_MAX_PAGES} 的整数）`);
  }
  return n;
}

/**
 * 书库相关参数的快速失败（在打开浏览器、联网之前）。
 * 返回书库要翻的页数；非书库榜单返回 null。
 */
function validateLibraryArgs(rankType, mode, pagesRaw, pagesGiven) {
  const rt = RANK_TYPES.find((r) => r.id === rankType);
  if (!rt || !rt.library) {
    if (pagesGiven) {
      throw new Error(`--pages 只用于 --type library（当前 --type ${rankType}）`);
    }
    return null;
  }
  if (mode === "mobile") {
    throw new Error("--type library 不支持 --mode mobile：书库筛选页只能用 Chrome（CDP）打开");
  }
  return parseLibraryPages(pagesRaw, pagesGiven);
}

// ---- 反爬字体（qd_anti_spider）：纯 Node 解析 TrueType 的 cmap + post ----

function readCmapTable(cmap) {
  const numTables = cmap.readUInt16BE(2);
  const result = new Map();
  const put = (cp, gid) => {
    if (gid && !result.has(cp)) result.set(cp, gid);
    if (result.size > CMAP_MAX_ENTRIES) throw new Error("cmap 码点过多");
  };
  for (let i = 0; i < numTables; i++) {
    const rec = 4 + i * 8;
    const offset = cmap.readUInt32BE(rec + 4);
    const format = cmap.readUInt16BE(offset);
    if (format === 12) {
      const groups = cmap.readUInt32BE(offset + 12);
      for (let g = 0; g < groups; g++) {
        const at = offset + 16 + g * 12;
        const start = cmap.readUInt32BE(at);
        const end = cmap.readUInt32BE(at + 4);
        const startGid = cmap.readUInt32BE(at + 8);
        if (end < start || end - start > CMAP_MAX_ENTRIES) throw new Error("cmap 区间异常");
        for (let cp = start; cp <= end; cp++) put(cp, startGid + (cp - start));
      }
    } else if (format === 4) {
      const segX2 = cmap.readUInt16BE(offset + 6);
      const seg = segX2 / 2;
      const endAt = offset + 14;
      const startAt = endAt + segX2 + 2;
      const deltaAt = startAt + segX2;
      const rangeAt = deltaAt + segX2;
      for (let s = 0; s < seg; s++) {
        const end = cmap.readUInt16BE(endAt + s * 2);
        const start = cmap.readUInt16BE(startAt + s * 2);
        const delta = cmap.readInt16BE(deltaAt + s * 2);
        const rangeOffset = cmap.readUInt16BE(rangeAt + s * 2);
        if (start === 0xffff || end < start) continue;
        for (let cp = start; cp <= end; cp++) {
          let gid;
          if (rangeOffset === 0) {
            gid = (cp + delta) & 0xffff;
          } else {
            gid = cmap.readUInt16BE(rangeAt + s * 2 + rangeOffset + (cp - start) * 2);
            if (gid) gid = (gid + delta) & 0xffff;
          }
          put(cp, gid);
        }
      }
    }
  }
  return result;
}

function readPostGlyphNames(post) {
  const version = post.readUInt32BE(0);
  if (version !== 0x00020000) {
    throw new Error(`post 表版本 0x${version.toString(16)} 不带字形名`);
  }
  const numGlyphs = post.readUInt16BE(32);
  const indices = [];
  for (let i = 0; i < numGlyphs; i++) indices.push(post.readUInt16BE(34 + i * 2));
  const extra = [];
  let at = 34 + numGlyphs * 2;
  while (at < post.length) {
    const len = post.readUInt8(at);
    if (at + 1 + len > post.length) break;
    extra.push(post.toString("latin1", at + 1, at + 1 + len));
    at += 1 + len;
  }
  return indices.map((idx) => (idx < 258 ? MAC_STANDARD_GLYPHS[idx] || "" : extra[idx - 258] || ""));
}

/**
 * 解析反爬字体，返回 Map<码点, "0".."9"|".">。
 * 结构不对（magic、表越界、缺 cmap/post、post 不是 2.0）一律抛错；调用方据此写 [待补]。
 */
function parseAntiSpiderFont(buf) {
  if (!Buffer.isBuffer(buf) || buf.length < 12) throw new Error("字体文件太短");
  const magic = buf.readUInt32BE(0);
  if (magic !== 0x00010000 && magic !== 0x74727565 && magic !== 0x4f54544f) {
    throw new Error("不是 TrueType/OpenType 字体");
  }
  const numTables = buf.readUInt16BE(4);
  if (12 + numTables * 16 > buf.length) throw new Error("字体表目录越界");
  const tables = {};
  for (let i = 0; i < numTables; i++) {
    const rec = 12 + i * 16;
    const tag = buf.toString("latin1", rec, rec + 4);
    const offset = buf.readUInt32BE(rec + 8);
    const length = buf.readUInt32BE(rec + 12);
    if (offset + length > buf.length) throw new Error(`字体表 ${tag.trim()} 越界`);
    // subarray 视图：表内读取越出本表长度时 Buffer 自己抛 RangeError
    tables[tag] = buf.subarray(offset, offset + length);
  }
  if (!tables.cmap || !tables.post) throw new Error("字体缺 cmap 或 post 表");
  const names = readPostGlyphNames(tables.post);
  const map = new Map();
  for (const [cp, gid] of readCmapTable(tables.cmap)) {
    const name = names[gid];
    if (name && Object.prototype.hasOwnProperty.call(GLYPH_CHARS, name)) {
      map.set(cp, GLYPH_CHARS[name]);
    }
  }
  if (!map.size) throw new Error("字体里没有可识别的数字字形");
  return map;
}

/**
 * 用字体映射把密文码点解成字数，如 [0x187B9, ...] + "万字" → "26.14万字"。
 * 任一码点不在映射里、解出来不是数字、或单位不明，都返回 ""（由调用方写 [待补]）。
 */
function decodeLibraryWords(codes, unit, fontMap) {
  if (!(fontMap instanceof Map) || !Array.isArray(codes) || !codes.length) return "";
  if (unit !== "万字" && unit !== "字") return "";
  let digits = "";
  for (const code of codes) {
    const ch = fontMap.get(Number(code));
    if (ch === undefined) return "";
    digits += ch;
  }
  if (!/^\d+(\.\d+)?$/.test(digits)) return "";
  return `${digits}${unit}`;
}

function fontUrlAllowed(url) {
  try {
    const u = new URL(url);
    return u.protocol === "https:" && u.hostname === FONT_HOST && FONT_PATH_RE.test(u.pathname);
  } catch {
    return false;
  }
}

/** 只从 qdfepccdn.qidian.com 下字体：15 秒超时、不跟跳转、限大小 */
function fetchFontBuffer(url) {
  return new Promise((resolve, reject) => {
    if (!fontUrlAllowed(url)) {
      reject(new Error(`字体地址不在白名单：${url}`));
      return;
    }
    const req = https.get(url, { headers: FONT_HEADERS, timeout: 15000 }, (res) => {
      if (res.statusCode < 200 || res.statusCode >= 300) {
        res.resume();
        reject(new Error(`字体下载 HTTP ${res.statusCode}`));
        return;
      }
      const chunks = [];
      let size = 0;
      res.on("data", (chunk) => {
        size += chunk.length;
        if (size > FONT_MAX_BYTES) {
          req.destroy(new Error("字体文件过大"));
          return;
        }
        chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
      });
      res.on("end", () => resolve(Buffer.concat(chunks)));
      res.on("error", reject);
    });
    req.on("timeout", () => {
      req.destroy(new Error("字体下载超时"));
    });
    req.on("error", reject);
  });
}

/** 同一字体名本次运行内只下载、解析一次（失败也缓存，避免反复请求） */
const libraryFontCache = new Map();

function loadLibraryFont(name, url) {
  if (!libraryFontCache.has(name)) {
    const task = (async () => {
      const m = fontUrlAllowed(url) ? new URL(url).pathname.match(FONT_PATH_RE) : null;
      if (!m || m[1] !== name) throw new Error(`字体 ${name} 没有可用的下载地址`);
      return parseAntiSpiderFont(await fetchFontBuffer(url));
    })().then(
      (map) => ({ map, error: "" }),
      (err) => ({ map: null, error: err && err.message ? err.message : String(err) })
    );
    libraryFontCache.set(name, task);
  }
  return libraryFontCache.get(name);
}

// ---- 列表页：浏览器端提取 + Node 端校验、规整 ----

/**
 * 在书库列表页里执行的提取函数，经 toString() 拼进 eval 载荷：
 * 必须自包含（不引用模块作用域）、不含反引号。
 * 字数只从本条 p.update 里带类名的密文 span 取码点；最新章节取链接的 title，
 * 不读 p.update 的整段文字（里面混着 @font-face 和密文）。
 */
function qdLibraryPageSnapshot(qdLibraryPage) {
  function txt(el) {
    return el ? String(el.textContent || "").replace(/\s+/g, " ").trim() : "";
  }
  var panels = Array.prototype.filter.call(document.querySelectorAll(".select-list"), function (el) {
    return el.offsetParent !== null;
  });
  var filters = panels.length ? Array.prototype.map.call(panels[0].querySelectorAll(".act"), txt) : [];
  var fontUrls = {};
  Array.prototype.forEach.call(document.querySelectorAll("style"), function (st) {
    var re = /https:\/\/qdfepccdn\.qidian\.com\/gtimg\/qd_anti_spider\/([A-Za-z0-9]+)\.ttf/g;
    var m;
    while ((m = re.exec(st.textContent || ""))) fontUrls[m[1]] = m[0];
  });
  var pagerMax = 0;
  Array.prototype.forEach.call(document.querySelectorAll(".lbf-pagination-item-list a[data-page]"), function (a) {
    var n = parseInt(a.getAttribute("data-page"), 10);
    if (n > pagerMax) pagerMax = n;
  });
  var items = Array.prototype.map.call(document.querySelectorAll("li[data-rid]"), function (li) {
    var titleEl = li.querySelector("h2 a");
    var href = titleEl ? titleEl.getAttribute("href") || "" : "";
    var idMatch = href.match(/\/book\/(\d+)/);
    var genre = "";
    var links = li.querySelectorAll("p.author a");
    for (var i = 0; i < links.length; i++) {
      if (links[i].classList.contains("name") || links[i].classList.contains("go-sub-type")) continue;
      genre = txt(links[i]);
      break;
    }
    var update = li.querySelector("p.update");
    var secret = null;
    if (update) {
      var spans = update.querySelectorAll("span[class]");
      for (var j = 0; j < spans.length; j++) {
        if (/^[A-Za-z0-9]+$/.test(spans[j].className)) {
          secret = spans[j];
          break;
        }
      }
    }
    var unit = "";
    if (secret && secret.nextSibling) {
      var unitMatch = String(secret.nextSibling.textContent || "").match(/^\s*(万字|字)/);
      unit = unitMatch ? unitMatch[1] : "";
    }
    var chapter = update ? update.querySelector("a[title]") || update.querySelector("a") : null;
    return {
      rid: li.getAttribute("data-rid") || "",
      bookId: idMatch ? idMatch[1] : "",
      title: titleEl ? titleEl.getAttribute("title") || txt(titleEl) : "",
      author: txt(li.querySelector("p.author a.name")),
      genre: genre,
      subGenre: txt(li.querySelector("p.author a.go-sub-type")),
      status: txt(li.querySelector("p.author span")),
      intro: txt(li.querySelector("p.intro")),
      wordsFont: secret ? secret.className : "",
      wordsCodes: secret
        ? Array.from(secret.textContent || "").map(function (c) {
            return c.codePointAt(0);
          })
        : [],
      wordsUnit: unit,
      latestChapter: chapter ? chapter.getAttribute("title") || txt(chapter) : "",
    };
  });
  return {
    qdLibraryPage: qdLibraryPage,
    path: location.pathname,
    site: txt(document.querySelector(".site .site-item.act")),
    filters: filters,
    sort: txt(document.querySelector(".select-wrap a.act")),
    pager: txt(document.querySelector(".lbf-pagination-current")),
    pagerMax: pagerMax,
    fontUrls: fontUrls,
    items: items,
  };
}

/** 构造书库第 page 页的 eval 载荷 */
function buildLibraryPageJS(page) {
  return `JSON.stringify((${qdLibraryPageSnapshot.toString()})(${Number(page)}))`;
}

/**
 * 核对页面实际选中的筛选、排序与页码（只认可见的那套筛选面板）。
 * 返回不符项列表；空数组表示这页确实是「男生·连载·30万字以下·三日内·人气排序·第 page 页」。
 */
function checkLibraryPage(snapshot, page) {
  if (!snapshot || typeof snapshot !== "object" || !Array.isArray(snapshot.items)) {
    return ["页面没有返回列表数据"];
  }
  const problems = [];
  if (snapshot.site !== LIBRARY_SITE) problems.push(`频道是「${snapshot.site || "无"}」`);
  const filters = Array.isArray(snapshot.filters) ? snapshot.filters : [];
  for (const want of LIBRARY_FILTERS) {
    if (!filters.includes(want)) problems.push(`没选中「${want}」`);
  }
  if (snapshot.sort !== LIBRARY_SORT) problems.push(`排序是「${snapshot.sort || "无"}」`);
  if (String(snapshot.pager) !== String(page)) {
    problems.push(`分页停在第「${snapshot.pager || "?"}」页`);
  }
  return problems;
}

/** 浏览器端条目 → book；缺书名/作者/题材的条目返回 null（宁可不收，也不让元信息错位） */
function normalizeLibraryItem(item) {
  if (!item || typeof item !== "object") return null;
  const bookId = /^\d+$/.test(String(item.bookId || "")) ? String(item.bookId) : "";
  const title = stripCipherChars(item.title);
  const author = stripCipherChars(item.author);
  const mainGenre = stripCipherChars(item.genre);
  const subGenre = stripCipherChars(item.subGenre);
  if (!bookId || !title || !author || !mainGenre) return null;
  const codes = Array.isArray(item.wordsCodes)
    ? item.wordsCodes.map(Number).filter((n) => Number.isInteger(n) && n > 0)
    : [];
  return {
    bookId,
    title,
    url: `https://www.qidian.com/book/${bookId}/`,
    author,
    genre: subGenre ? `${mainGenre}·${subGenre}` : mainGenre,
    status: stripCipherChars(item.status),
    words: "",
    wordsFont: /^[A-Za-z0-9]+$/.test(String(item.wordsFont || "")) ? String(item.wordsFont) : "",
    wordsCodes: codes,
    wordsUnit: item.wordsUnit === "万字" || item.wordsUnit === "字" ? item.wordsUnit : "",
    latestChapter: stripCipherChars(item.latestChapter),
    totalRecommendations: "",
    signing: "",
    pricing: "",
    descText: stripCipherChars(item.intro),
    updateText: "",
  };
}

/** 移动端 bookInfo 的字数（整数）→ 「26.14万字」/「8000字」 */
function formatWordsCount(count) {
  const n = Number(count);
  if (!Number.isFinite(n) || n <= 0) return "";
  return n >= 10000 ? `${(n / 10000).toFixed(2)}万字` : `${Math.round(n)}字`;
}

/** 把 m.qidian.com/book/{id}/ 的 bookInfo 补到 book 上：总推荐、签约、收费、更新时间、兜底字数 */
function applyMobileBookInfo(book, info) {
  if (!info || typeof info !== "object") return false;
  if (Number.isFinite(Number(info.recomAll)) && Number(info.recomAll) >= 0 && info.recomAll !== "") {
    book.totalRecommendations = String(info.recomAll);
  }
  const sign = stripCipherChars(info.signStatus);
  if (sign) book.signing = sign;
  else if (info.isSign === 1) book.signing = "签约";
  else if (info.isSign === 0) book.signing = "未签约";
  if (info.isVip === 1) book.pricing = "VIP";
  else if (info.isVip === 0) book.pricing = "免费";
  if (!book.words) {
    book.words = formatWordsCount(info.wordsCnt);
    if (book.words) book.wordsFromDetail = true;
  }
  const updated = stripCipherChars(info.updTime);
  if (updated) book.updateTime = updated;
  return true;
}

async function fetchMobileBookInfo(bookId) {
  const html = await fetchText(`${MOBILE_BASE_URL}/book/${bookId}/`);
  const info = extractMobilePageContext(html)?.pageContext?.pageProps?.pageData?.bookInfo;
  if (!info || String(info.bookId) !== String(bookId)) throw new Error("详情页没有这本书的 bookInfo");
  return info;
}

/**
 * 翻页采集书库。返回 { content, partialReasons }；一本都没采到时抛错（不写空文件）。
 * 某页失败就停在那里：保留前面各页（partial），后面的页不再翻，免得名次错位。
 */
async function scrapeLibrary(port, pages) {
  const rt = RANK_TYPES.find((r) => r.library);
  console.log(`\n→ 采集 起点${rt.label}（CDP/PC，前 ${pages} 页）...`);
  const books = [];
  const seen = new Set();
  const fontUrls = {};
  const pageFailures = [];
  const notes = [];
  let skipped = 0;
  let pagerMax = 0;
  let lastPage = 0;

  for (let page = 1; page <= pages; page++) {
    if (pagerMax && page > pagerMax) {
      notes.push(`站点只有 ${pagerMax} 页`);
      break;
    }
    const url = libraryPageUrl(page);
    console.log(`  第 ${page} 页：${url}`);
    let snapshot;
    try {
      if (!openWithCaptchaHandling(port, url)) throw new Error("页面无法通过验证码拦截");
      snapshot = evalJSON(port, buildLibraryPageJS(page));
      const problems = checkLibraryPage(snapshot, page);
      if (problems.length) throw new Error(`筛选状态不符（${problems.join("，")}）`);
    } catch (err) {
      const reason = `第 ${page} 页没取到：${err && err.message ? err.message : err}`;
      console.error(`[qidian] 书库${reason}`);
      pageFailures.push(reason);
      break;
    }
    lastPage = page;
    pagerMax = Number(snapshot.pagerMax) || pagerMax;
    for (const [name, fontUrl] of Object.entries(snapshot.fontUrls || {})) fontUrls[name] = fontUrl;
    const normalized = [];
    for (const item of snapshot.items) {
      const book = normalizeLibraryItem(item);
      if (book) normalized.push(book);
      else skipped++;
    }
    const fresh = normalized.filter((b) => !seen.has(b.bookId));
    console.log(`  第 ${page} 页：${snapshot.items.length} 条，新书 ${fresh.length} 本`);
    if (!fresh.length) {
      notes.push(`第 ${page} 页没有新书，停止翻页`);
      break;
    }
    for (const book of fresh) {
      seen.add(book.bookId);
      book.rank = books.length + 1;
      books.push(book);
    }
  }

  if (!books.length) {
    throw new Error(pageFailures[0] || "书库列表页一本都没抓到（可能被验证页拦住，或页面改版）");
  }

  // 字数：先解反爬字体
  let decoded = 0;
  const fontErrors = new Set();
  for (const book of books) {
    if (!book.wordsFont) continue;
    const font = await loadLibraryFont(book.wordsFont, fontUrls[book.wordsFont] || "");
    if (!font.map) {
      fontErrors.add(font.error);
      continue;
    }
    book.words = decodeLibraryWords(book.wordsCodes, book.wordsUnit, font.map);
    if (book.words) decoded++;
  }
  console.log(`  字数解码：${decoded} / ${books.length}`);
  for (const message of fontErrors) console.log(`  ⚠ 字体解码失败：${message}`);

  // 总推荐/签约/收费（字数解不出时兜底）：逐本取移动端作品页
  let detailOk = 0;
  for (let i = 0; i < books.length; i++) {
    if (i > 0) sleep(LIBRARY_DETAIL_GAP_MS);
    try {
      if (applyMobileBookInfo(books[i], await fetchMobileBookInfo(books[i].bookId))) detailOk++;
    } catch (err) {
      console.log(`    详情失败 ${books[i].title}：${err && err.message ? err.message : err}`);
    }
  }
  console.log(`  详情补全：${detailOk} / ${books.length}`);

  for (const book of books) {
    book.updateText = [book.latestChapter, book.updateTime].filter(Boolean).join(" · ");
  }

  const problems = [...pageFailures.map((r) => `${r}（已保留前 ${lastPage} 页）`)];
  const missingWords = books.filter((b) => !b.words).length;
  if (missingWords) problems.push(`字数缺失 ${missingWords} 条（字体解码与详情页都没拿到）`);
  const detailFailed = books.length - detailOk;
  if (detailFailed > books.length * LIBRARY_DETAIL_FAIL_RATIO) {
    problems.push(`超过一半的书没取到详情（${detailFailed} / ${books.length}），总推荐、签约、收费多为 [待补]`);
  }
  if (skipped) problems.push(`缺书名/作者/题材的条目 ${skipped} 条，已跳过`);
  if (books.length < 15) problems.push(`[数据稀疏] 实际采集 ${books.length} 条`);

  for (const b of books) {
    b.library = true;
    b.newBookRecom = b.totalRecommendations;
  }
  const extraLines = [
    `- 筛选：${LIBRARY_SITE}·${LIBRARY_FILTERS.slice(0, 2).join("·")}·${LIBRARY_FILTERS[2]}更新；${LIBRARY_SORT}，取前 ${pages} 页`,
    `- 实际翻页：${lastPage} 页${notes.length ? `（${notes.join("；")}）` : ""}`,
    `- 字数来源：反爬字体解码 ${decoded} 条，详情页兜底 ${books.filter((b) => b.wordsFromDetail).length} 条，缺失 ${missingWords} 条`,
    `- 详情补全：成功 ${detailOk} / 共 ${books.length}`,
    "- 热度：名次即人气排名；作品页的总推荐单列为「新书总推荐」，不进聚合的热度口径",
    `- 数据质量：${problems.length ? "[存在问题]" : "[OK]"}`,
    `- 问题摘要：${problems.length ? problems.join("；") : "无"}`,
  ];
  return {
    content: renderMarkdown(rt, books, libraryPageUrl(1), "cdp-pc", extraLines),
    partialReasons: pageFailures,
  };
}

// ---------------------------------------------------------------------------
// 主流程
// ---------------------------------------------------------------------------

const args = process.argv.slice(2);
const PORT = parseInt(getArg(args, "--port") || "9222", 10);
const OUTDIR = getArg(args, "--outdir") || ".";
const RANKTYPE = getArg(args, "--type") || "hotsales";
const SCRAPE_MODE = getArg(args, "--mode") || "auto"; // auto | mobile | cdp
const FETCH_DETAIL = (getArg(args, "--detail") || "no") === "yes";
// --pages 只对 --type library 有效；记下「传没传」，好让别的榜单传了也能报错而不是静默忽略
const PAGES_RAW = getArg(args, "--pages");
const PAGES_GIVEN = args.some((arg) => arg === "--pages" || String(arg).startsWith("--pages="));

function scrapeRankCDP(port, rankTypeId) {
  const rt = RANK_TYPES.find((r) => r.id === rankTypeId);
  if (!rt) {
    console.log(`  ⚠ 未知榜单类型: ${rankTypeId}`);
    return null;
  }

  const url = rt.baseUrl || `${PC_BASE_URL}/${rankTypeId}/`;
  console.log(`\n→ 采集 起点${rt.label}（CDP/PC）...`);
  console.log(`  URL: ${url}`);

  const pageReady = openWithCaptchaHandling(port, url);
  if (!pageReady) {
    console.log("  ✗ 起点采集失败：页面无法通过验证码拦截");
    return null;
  }

  scrollLoad(port, 3);
  sleep(1000);

  const books = extractBookList(port);
  if (!books.length) {
    console.log("  ⚠ 未提取到书籍");
    return null;
  }
  console.log(`  ✓ 提取 ${books.length} 本`);

  // 可选：逐条获取详情页补充数据
  if (FETCH_DETAIL) {
    console.log("  正在获取详情页补充数据...");
    for (let i = 0; i < Math.min(books.length, 20); i++) {
      const b = books[i];
      if (!b.url) continue;
      ab(port, "open", b.url);
      sleep(1500);
      const detail = extractDetail(port);
      if (detail) {
        if (detail.tags?.length) b.tags = detail.tags;
        if (detail.intro) b.descText = detail.intro;
        if (detail.update) b.updateText = detail.update;
        for (const field of ["words", "totalRecommendations", "signing", "pricing"]) {
          if (detail[field]) b[field] = detail[field];
        }
      }
      console.log(`    [${i + 1}/${books.length}] ${b.title}`);
    }
    // 返回榜单页
    ab(port, "open", url);
    sleep(2000);
  }

  return renderMarkdown(rt, books, url, "cdp-pc");
}

async function scrapeRank(rankTypeId) {
  if (!["auto", "mobile", "cdp"].includes(SCRAPE_MODE)) {
    throw new Error(`未知 --mode: ${SCRAPE_MODE}（可选 auto/mobile/cdp）`);
  }

  if (SCRAPE_MODE !== "cdp") {
    try {
      const content = await scrapeRankMobile(rankTypeId);
      if (content || SCRAPE_MODE === "mobile") return content;
    } catch (e) {
      console.log(`  ⚠ 移动端 SSR 采集失败: ${e.message}`);
      if (SCRAPE_MODE === "mobile") return null;
    }
  }

  if (SCRAPE_MODE !== "mobile") {
    console.log("  → 回退到 CDP/PC 页面采集");
    return scrapeRankCDP(PORT, rankTypeId);
  }

  return null;
}

async function main() {
  // 参数错误是配置问题，不是单个榜单的瞬时失败：先于 per-榜单隔离快速失败
  if (RANKTYPE !== "all" && !RANK_TYPES.some((rank) => rank.id === RANKTYPE)) {
    throw new Error(`未知 --type: ${RANKTYPE}`);
  }
  if (!["auto", "mobile", "cdp"].includes(SCRAPE_MODE)) {
    throw new Error(`未知 --mode: ${SCRAPE_MODE}（可选 auto/mobile/cdp）`);
  }
  const libraryPages = validateLibraryArgs(RANKTYPE, SCRAPE_MODE, PAGES_RAW, PAGES_GIVEN);

  // 书库只走 CDP，不进 --type all：all 默认不需要 Chrome
  const rankTypes =
    RANKTYPE === "all" ? RANK_TYPES.filter((r) => !r.library).map((r) => r.id) : [RANKTYPE];
  let written = 0;
  let failed = 0;
  let partial = false;
  const partialReasons = [];

  for (const rt of rankTypes) {
    // per-榜单隔离：移动端 SSR 失败后的 CDP 回退会直接抛（ab() 不吞错），
    // 一个榜单的瞬时失败不该掐掉 --type all 后面的榜单（与番茄/刺猬猫一致）
    try {
      const rtInfo = RANK_TYPES.find((r) => r.id === rt);
      let content;
      if (rtInfo.library) {
        const library = await scrapeLibrary(PORT, libraryPages);
        content = library.content;
        if (library.partialReasons.length) {
          partial = true;
          partialReasons.push(...library.partialReasons.map((reason) => `${rtInfo.label}: ${reason}`));
        }
      } else {
        content = await scrapeRank(rt);
      }
      if (!content) {
        failed++;
        partialReasons.push(`${rtInfo ? rtInfo.label : rt}: no usable data`);
        continue;
      }

      const filename = `起点${rtInfo.label}_${localDateStamp()}.md`;
      fs.mkdirSync(OUTDIR, { recursive: true });
      const filepath = path.join(OUTDIR, filename);
      fs.writeFileSync(filepath, content, "utf-8");
      written++;
      console.log(`  ✓ 已保存: ${filepath}`);
    } catch (rankErr) {
      failed++;
      const rtInfo = RANK_TYPES.find((r) => r.id === rt);
      const message = rankErr && rankErr.message ? rankErr.message : String(rankErr);
      partialReasons.push(`${rtInfo ? rtInfo.label : rt}: ${message}`);
      console.error(
        `[qidian] ${rtInfo ? rtInfo.label : rt} 采集失败，跳过: ${message}`
      );
    }
  }
  return {
    planned: rankTypes.length,
    written,
    failed,
    partial: partial || failed > 0,
    partialReasons,
  };
}

if (require.main === module) {
  runCli(main, "起点采集");
}

module.exports = {
  extractBookList,
  mobileUrl,
  extractMobilePageContext,
  normalizeMobileBook,
  cleanDesc,
  renderMarkdown,
  rankQualityLines,
  parseAntiSpiderFont,
  decodeLibraryWords,
  captchaCheckJS,
};
