#!/usr/bin/env node
/**
 * 七猫小说排行榜采集脚本
 *
 * 配合 browser-cdp skill 使用。先启动 Chrome CDP 环境，再运行本脚本。
 * 采集策略：tab 切换男生榜/女生榜和榜单类型，滚动加载后从页面文本解析结构化数据。
 * 输出的榜单 Markdown 格式见 aggregate-rank.js 文件头，聚合按它解析。
 *
 * 用法：
 *   node qimao-rank-scraper.js --channel male --type hot --period day    # 男生大热榜日榜
 *   node qimao-rank-scraper.js --channel male --type hot --period month  # 男生大热榜月榜
 *   node qimao-rank-scraper.js --channel male --type hot --period all    # 日榜+月榜
 *   node qimao-rank-scraper.js --channel female --type new      # 女生新书榜
 *   node qimao-rank-scraper.js --channel all --type all         # 全部采集
 *   node qimao-rank-scraper.js --source library --pages 3       # 书库筛选页：点击量前 3 页新书
 *
 * 前置（排行榜）：
 *   node {SKILL_DIR}/browser-cdp/scripts/setup-cdp-chrome.js 9222
 * 书库筛选页是服务端渲染，直接走 HTTPS，不需要 Chrome。
 */

const fs = require("fs");
const https = require("https");
const path = require("path");
const { ab, sleep, evalJSONBase64, scrollLoad, getArg, localDateStamp, runCli } = require("./cdp-utils");

const RANK_URL = "https://www.qimao.com/paihang";

/** 连通性 + 页面就绪自检 */
function probePage(port) {
  return evalJSONBase64(
    port,
    "JSON.stringify({host:location.host,path:location.pathname,len:(document.body&&document.body.innerText||'').length})"
  );
}

const CHANNELS = [
  { id: "male", label: "男频", tab: "男生榜", path: "boy" },
  { id: "female", label: "女频", tab: "女生榜", path: "girl" },
];

const RANK_TYPES = [
  { id: "hot", label: "大热榜", path: "hot" },
  { id: "new", label: "新书榜", path: "new" },
  { id: "finish", label: "完结榜", path: "over" },
  { id: "collect", label: "收藏榜", path: "collect" },
  { id: "update", label: "更新榜", path: "update" },
];

const PERIODS = [
  { id: "day", label: "日榜", path: "date" },
  { id: "month", label: "月榜", path: "month" },
];

// ---------------------------------------------------------------------------
// 页面操作
// ---------------------------------------------------------------------------

function rankUrl(channelId, rankTypeId, periodId) {
  const channel = CHANNELS.find((item) => item.id === channelId);
  const rankType = RANK_TYPES.find((item) => item.id === rankTypeId);
  const period = PERIODS.find((item) => item.id === (periodId || "day"));
  if (!channel || !rankType || !period) return "";
  return `${RANK_URL}/${channel.path}/${rankType.path}/${period.path}/`;
}

/** 读取页面实际 active 状态；输出文件标签必须由该状态校验后才能使用。 */
function extractObservedSelection(port) {
  const js = `JSON.stringify((function(){
    function text(selector){var e=document.querySelector(selector);return e?(e.textContent||'').replace(/\\s+/g,'').trim():'';}
    return {path:location.pathname,channel:text('.qm-switch-tab .item.active'),rankType:text('.child-tabs-item.menu-tab.active'),period:text('.date-type-tabs .tab.active')};
  })())`;
  return evalJSONBase64(port, js) || {};
}

function selectionMatches(observed, channelId, rankTypeId, periodId) {
  const channel = CHANNELS.find((item) => item.id === channelId);
  const rankType = RANK_TYPES.find((item) => item.id === rankTypeId);
  const period = periodId ? PERIODS.find((item) => item.id === periodId) : null;
  if (!channel || !rankType) return false;
  const expectedUrl = rankUrl(channelId, rankTypeId, periodId);
  if (!expectedUrl) return false;
  const expectedPath = new URL(expectedUrl).pathname;
  const actualPath = String(observed && observed.path || "").replace(/\/+$/, "/");
  return !!(
    actualPath === expectedPath &&
    String(observed.channel || "").includes(channel.tab) &&
    observed.rankType === rankType.label &&
    (!period || observed.period === period.label)
  );
}

/**
 * 从 DOM 获取书籍链接。每本书有多个 anchor（排名数字/书名/最近更新），
 * 按 bookId 聚合后取最像书名的文本（非纯数字、非"最近更新"前缀、最长），
 * 否则书名会被排名数字 anchor 覆盖，导致后续按书名回填链接全失败。
 */
function extractBookUrls(port) {
  const js = `JSON.stringify((function(){
    var byId={};var order=[];
    Array.from(document.querySelectorAll('a')).forEach(function(a){
      var h=a.getAttribute('href')||a.href||'';
      var m=h.match(/\\/(?:shuku|book)\\/([0-9]+)/);
      if(!m)return; var id=m[1];
      var t=(a.innerText||a.textContent||'').replace(/\\s+/g,' ').trim();
      if(!byId[id]){byId[id]='';order.push(id);}
      if(t&&!/^[0-9]+$/.test(t)&&!/^(最近更新|最新章节|最新)/.test(t)){
        if(t.length>byId[id].length)byId[id]=t;
      }
    });
    return order.map(function(id){return {bookId:id,title:byId[id],url:'https://www.qimao.com/shuku/'+id+'/'};});
  })())`;
  return evalJSONBase64(port, js) || [];
}

/**
 * 从页面 innerText 解析结构化书籍数据。
 * 七猫页面文本结构固定：排名→书名→作者→题材→子分类→状态→字数→简介→更新→热度
 */
function extractBooksFromText(port) {
  const js =
    "JSON.stringify((()=>{" +
    "var text=document.body.innerText||'';" +
    // 找到榜单数据起始位置
    "var start=-1;" +
    "['日榜','月榜'].forEach(function(m){if(start<0)start=text.indexOf(m)});" +
    "if(start<0)return[];" +
    "var lines=text.substring(start).split(/\\n/);" +
    "var books=[];var cur=null;var fieldIdx=0;" +
    "for(var i=0;i<lines.length;i++){" +
    "  var line=lines[i].trim();" +
    "  if(!line)continue;" +
    // 排行数据结束后的分页器/页脚必须立刻截断；否则“5 / 下一页 / 跳转 / 友情链接”
    // 会被串成一条字段齐全的假书目。
    "  if(/^(上一页|下一页|跳转|友情链接[:：]?)$/.test(line)){if(cur&&cur.title)books.push(cur);cur=null;break}" +
    // 排名标记：独立数字 1-99
    "  if(/^\\d{1,2}$/.test(line)&&parseInt(line)<100){" +
    "    if(cur&&cur.title)books.push(cur);" +
    "    cur={rank:parseInt(line),title:'',author:'',genre:'',subGenre:'',status:'',words:'',heat:'',update:'',desc:''};" +
    "    fieldIdx=0;continue" +
    "  }" +
    "  if(!cur)continue;" +
    // 跳过 UI 文字
    "  if(/^(加入书架|立即阅读|蝉联|榜首)/.test(line))continue;" +
    // 热度（兼容「12.3万 热度」与新书榜「8500 热度」）
    "  var hm=line.match(/^([\\d.]+(?:\\s*万)?)\\s*热度$/);" +
    "  if(hm){cur.heat=hm[1].replace(/\\s+/g,'');continue}" +
    // 最新更新
    "  if(line.indexOf('最近更新')===0){cur.update=line.replace(/^最近更新\\s*/,'');continue}" +
    // 状态
    "  if(/^(连载中|已完结)$/.test(line)){cur.status=line;continue}" +
    // 字数（兼容「12.3万字」与不足一万字的「8500字」）
    "  if(/^[\\d.]+万?字$/.test(line)){cur.words=line;continue}" +
    // 按序填充：书名→作者→题材→子分类
    "  if(fieldIdx===0){cur.title=line;fieldIdx=1;continue}" +
    "  if(fieldIdx===1){cur.author=line;fieldIdx=2;continue}" +
    "  if(fieldIdx===2){cur.genre=line;fieldIdx=3;continue}" +
    "  if(fieldIdx===3){cur.subGenre=line;fieldIdx=4;continue}" +
    // 其余为简介
    "  cur.desc+=(cur.desc?' ':'')+line" +
    "}" +
    "if(cur&&cur.title)books.push(cur);" +
    "return books" +
    "})())";
  return evalJSONBase64(port, js) || [];
}

/**
 * 排除分页器等被正文文本解析器误认成的伪书目。
 * 七猫榜单尾部会出现“5 / 下一页”这类纯 UI 文本；有效条目必须同时有正排名、书名和作者。
 */
function isUsableBook(book) {
  return !!(
    book &&
    Number.isInteger(book.rank) &&
    book.rank > 0 &&
    book.title &&
    book.author &&
    !/^(上一页|下一页|跳转)$/.test(book.title) &&
    !/^(上一页|下一页|跳转|友情链接[:：]?)$/.test(book.author)
  );
}

function cleanDesc(value) {
  const text = String(value || "")
    .replace(/\s*(?:飙升|上升|下降)\s*\d+\s*名\s*$/g, "")
    .replace(/\s*(?:上一页|下一页)\s*$/g, "")
    .replace(/\s+/g, " ")
    .trim();
  if (text.length <= 100) return text;
  const cut = text.slice(0, 100);
  const sentence = cut.match(/^[\s\S]*[。！？]/);
  return (sentence ? sentence[0] : cut) + "...";
}

function summarizeQuality(books, rawCount) {
  const linked = books.filter((book) => book.url).length;
  const heated = books.filter((book) => book.heat).length;
  const fieldCounts = [
    ["题材", "genre"],
    ["子分类", "subGenre"],
    ["状态", "status"],
    ["字数", "words"],
    ["热度", "heat"],
  ].map(([label, field]) => ({
    label,
    missing: books.filter((book) => !book[field]).length,
  }));
  const problems = [];
  if (rawCount > books.length) problems.push(`移除无效/UI条目 ${rawCount - books.length} 条`);
  if (linked < books.length) problems.push(`作品页链接缺失 ${books.length - linked} 条`);
  for (const field of fieldCounts) {
    if (field.missing) problems.push(`${field.label}缺失 ${field.missing} 条`);
  }
  if (books.length < 15) problems.push(`[数据稀疏] 实际采集 ${books.length} 条`);
  return {
    linked,
    heated,
    problems,
    quality: problems.length ? "[存在问题]" : "[OK]",
  };
}

function renderMarkdown(ch, rt, period, url, books, rawCount, now = new Date().toISOString()) {
  const periodLabel = period ? period.label : "";
  const summary = summarizeQuality(books, rawCount);
  const lines = [
    `# 七猫 · ${ch.label} · ${rt.label}${periodLabel}`,
    "",
    `- 数据质量：${summary.quality}`,
    `- 有效条目：${books.length} / ${rawCount}`,
    `- 问题摘要：${summary.problems.length ? summary.problems.join("；") : "无"}`,
    `- 作品页链接：${summary.linked} / ${books.length}`,
    `- 热度命中：${summary.heated} / ${books.length}`,
    `- 来源：${url}`,
    `- 抓取时间：${now}`,
    `- 条目数：${books.length}`,
    "",
    "---",
    "",
  ];

  for (const b of books) {
    try {
      lines.push(`### #${b.rank} ${b.title}`);
      const meta = [
        b.author || "[待补]",
        b.genre || "[待补]",
        b.subGenre || "[待补]",
        b.status || "[待补]",
        b.words || "[待补]",
        b.heat ? b.heat + "热度" : "[待补]",
      ].join(" · ");
      lines.push(`*${meta}*`);
      if (b.update) lines.push(`**最新更新：** ${b.update}`);
      if (b.url) lines.push(`[作品页](${b.url})`);
      const desc = cleanDesc(b.desc);
      if (desc) {
        lines.push("");
        lines.push("**简介**");
        lines.push("");
        lines.push(desc);
      }
      lines.push("", "---", "");
    } catch (bookErr) {
      console.error(`[qimao] ${ch.label}${rt.label} 第${b.rank}条处理出错: ${bookErr.message}`);
      lines.push("", "---", "");
    }
  }

  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// 书库筛选页（--source library）
// 全部频道 · 30万字以下 · 3天内更新 · 连载中 · 按点击量。页面服务端渲染，Node 直接取 HTML，
// 不开 Chrome。页面没有热度数字，名次就是点击量页序；只有子分类，主类另查分类页标题。
// ---------------------------------------------------------------------------

const LIBRARY_ID = "library";
const LIBRARY_LIST = "全站书库点击新书"; // 带「新书」：聚合时进「新书榜」列
const LIBRARY_HOST = "www.qimao.com";
const LIBRARY_TITLE_MARKS = ["3天内更新", "30万以下", "连载中"];
const LIBRARY_SORT = "按点击量";
const LIBRARY_SORT_OPTIONS = ["按点击量", "按总字数", "最近更新", "按收藏数"];
const LIBRARY_FILTER_NOTE = "全部频道·30万字以下·3天内更新·连载中";
const LIBRARY_DEFAULT_PAGES = 3;
const LIBRARY_MAX_PAGES = 10;
const LIBRARY_REQUEST_GAP_MS = 800;
const LIBRARY_SPARSE_BELOW = 15;
const DESKTOP_HEADERS = {
  "User-Agent":
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
  Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
  "Accept-Language": "zh-CN,zh;q=0.9",
  "Accept-Encoding": "identity",
};
const MAX_HTML_BYTES = 5 * 1024 * 1024;

/** 书库第 page 页。段位依次是频道-主类-子类-字数-更新-?-状态-排序-页码，a 表示不限。 */
function libraryPageUrl(page) {
  return `https://${LIBRARY_HOST}/shuku/a-a-a-1-1-a-0-click-${page}/`;
}

/** 只按主类筛选的书库页；它的 <title> 以「{主类}小说-」开头。 */
function categoryUrl(mainId) {
  return `https://${LIBRARY_HOST}/shuku/a-${mainId}-a-a-a-a-a-click-1/`;
}

/** 校验 --pages：1 到 10 的整数，默认 3。 */
function parseLibraryPages(raw) {
  if (raw === null || raw === undefined) return LIBRARY_DEFAULT_PAGES;
  const text = String(raw).trim();
  const pages = /^\d+$/.test(text) ? Number(text) : NaN;
  if (!Number.isInteger(pages) || pages < 1 || pages > LIBRARY_MAX_PAGES) {
    throw new Error(`未知 --pages: ${raw}（书库翻页取 1-${LIBRARY_MAX_PAGES} 的整数）`);
  }
  return pages;
}

/**
 * 取一页 HTML：桌面 UA、不压缩、15 秒超时、最多跟 3 次站内重定向；
 * 跳出 www.qimao.com/shuku/ 或状态码不是 200 都算这一页失败。
 * 七猫的响应头有折行（行首带空格的 content-security-policy 等），Node 默认的严格解析器会
 * 直接报 Parse Error，所以这一个请求放宽头部解析；只读公开页面，不影响别的请求。
 */
function fetchQimaoHtml(url, redirects = 3) {
  return new Promise((resolve, reject) => {
    const options = { headers: DESKTOP_HEADERS, timeout: 15000, insecureHTTPParser: true };
    const req = https.get(url, options, (res) => {
      const status = res.statusCode;
      if (status >= 300 && status < 400 && res.headers.location) {
        res.resume();
        if (redirects <= 0) {
          reject(new Error("重定向超过 3 次"));
          return;
        }
        let next;
        try {
          next = new URL(res.headers.location, url);
        } catch {
          reject(new Error(`重定向地址无效：${res.headers.location}`));
          return;
        }
        if (next.protocol !== "https:" || next.host !== LIBRARY_HOST || !next.pathname.startsWith("/shuku/")) {
          reject(new Error(`被重定向到 ${next.host}${next.pathname}，不是七猫书库页（可能被风控或登录页拦住）`));
          return;
        }
        fetchQimaoHtml(next.toString(), redirects - 1).then(resolve, reject);
        return;
      }
      if (status !== 200) {
        res.resume();
        reject(new Error(`HTTP ${status}`));
        return;
      }
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (chunk) => {
        body += chunk;
        if (body.length > MAX_HTML_BYTES) req.destroy(new Error("页面大小异常"));
      });
      res.on("end", () => resolve(body));
      res.on("error", reject);
    });
    req.on("timeout", () => req.destroy(new Error("请求超时（15 秒）")));
    req.on("error", reject);
  });
}

const HTML_ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };

function decodeEntities(text) {
  return String(text || "").replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (whole, name) => {
    if (name[0] === "#") {
      const code = /^#x/i.test(name) ? parseInt(name.slice(2), 16) : parseInt(name.slice(1), 10);
      return Number.isInteger(code) && code > 0 && code <= 0x10ffff ? String.fromCodePoint(code) : whole;
    }
    const decoded = HTML_ENTITIES[name.toLowerCase()];
    return decoded === undefined ? whole : decoded;
  });
}

/** 去标签、解实体、压空白：先去标签再解实体，&lt;b&gt; 这样的书名原样保留。
 *  注释和标签反复删到不再变化，再删掉散落的尖括号：「<!<!---->--」这类嵌套、没闭合的写法
 *  删一遍会拼出新的「<!--」。正文里真正的尖括号在源码中都是实体，最后解码才还原，不会误删。 */
function htmlText(html) {
  let stripped = String(html || "");
  for (let previous = null; stripped !== previous; ) {
    previous = stripped;
    // 没闭合的注释照 HTML 规则一直注释到结尾
    stripped = stripped.replace(/<!--[\s\S]*?(?:-->|$)/g, "").replace(/<[^>]*>/g, " ");
  }
  return decodeEntities(stripped.replace(/[<>]/g, "")).replace(/\s+/g, " ").trim();
}

function attrValue(attrs, name) {
  const m = String(attrs || "").match(
    new RegExp(`(?:^|\\s)${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)'|([^\\s>]+))`, "i")
  );
  if (!m) return null;
  return decodeEntities(m[1] !== undefined ? m[1] : m[2] !== undefined ? m[2] : m[3]);
}

/** 所有 class 同时含 classNames 的元素（Vue 的 data-v-xxx 属性照常容忍）。 */
function findByClass(html, classNames, limit = Infinity) {
  const wanted = [].concat(classNames);
  const found = [];
  const re = /<([a-zA-Z][\w-]*)\b([^>]*)>/g;
  let m;
  while ((m = re.exec(html)) && found.length < limit) {
    const cls = attrValue(m[2], "class");
    if (cls === null) continue;
    const tokens = cls.split(/\s+/);
    if (!wanted.every((name) => tokens.includes(name))) continue;
    const tag = m[1].toLowerCase();
    const closeRe = new RegExp(`</${tag}\\s*>`, "ig");
    closeRe.lastIndex = re.lastIndex;
    const close = closeRe.exec(html);
    found.push({ attrs: m[2], inner: html.slice(re.lastIndex, close ? close.index : html.length) });
  }
  return found;
}

function firstByClass(html, classNames) {
  return findByClass(html, classNames, 1)[0] || null;
}

function normalizeWords(text) {
  const t = String(text || "").replace(/\s+/g, "");
  if (/^[\d.]+万?字$/.test(t)) return t;
  if (/^[\d.]+万?$/.test(t)) return `${t}字`;
  return "";
}

/**
 * 解析一页书库 HTML。每个 li.qm-cover-text-item 是一本书：
 * .s-tit a（书名、/shuku/{bookId}/）、.s-category（子分类，链接里带主类 id）、
 * .s-status、.s-words-num、.s-desc、.s-author、.s-update-time。
 */
function parseShukuPage(html) {
  const source = String(html || "");
  const titleMatch = source.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
  const sortTabs = findByClass(source, ["tab-inner", "active"])
    .map((el) => htmlText(el.inner))
    .filter((label) => LIBRARY_SORT_OPTIONS.includes(label));
  const pagerNumbers = findByClass(source, ["page-btn", "num"]).map((el) => ({
    n: /^\d+$/.test(htmlText(el.inner)) ? Number(htmlText(el.inner)) : null,
    active: (attrValue(el.attrs, "class") || "").split(/\s+/).includes("active"),
  }));
  const numbered = pagerNumbers.filter((p) => p.n !== null);
  const activePager = numbered.find((p) => p.active);

  const starts = [];
  const liRe = /<li\b([^>]*)>/gi;
  let m;
  while ((m = liRe.exec(source))) {
    const cls = attrValue(m[1], "class") || "";
    if (cls.split(/\s+/).includes("qm-cover-text-item")) starts.push(m.index);
  }
  const items = starts.map((start, i) => {
    const nextStart = i + 1 < starts.length ? starts[i + 1] : source.length;
    const end = source.indexOf("</li>", start);
    const chunk = source.slice(start, end > start && end < nextStart ? end : nextStart);
    const titleEl = firstByClass(chunk, "s-tit");
    const anchor = titleEl && titleEl.inner.match(/<a\b([^>]*)>([\s\S]*?)<\/a\s*>/i);
    const href = anchor ? attrValue(anchor[1], "href") || "" : "";
    const idMatch = href.match(/\/shuku\/(\d+)\/?(?:[?#]|$)/);
    const categoryEl = firstByClass(chunk, "s-category");
    const categoryHref = categoryEl ? attrValue(categoryEl.attrs, "href") || "" : "";
    const categoryIds = categoryHref.match(/\/shuku\/a-(\d+)-(\d+)-/);
    const text = (cls) => {
      const el = firstByClass(chunk, cls);
      return el ? htmlText(el.inner) : "";
    };
    const bookId = idMatch ? idMatch[1] : "";
    return {
      bookId,
      title: anchor ? htmlText(anchor[2]) : "",
      url: bookId ? `https://${LIBRARY_HOST}/shuku/${bookId}/` : "",
      author: text("s-author"),
      genre: "",
      subGenre: categoryEl ? htmlText(categoryEl.inner) : "",
      mainId: categoryIds ? categoryIds[1] : "",
      status: text("s-status"),
      words: normalizeWords(text("s-words-num")),
      update: text("s-update-time"),
      desc: text("s-desc"),
    };
  });

  return {
    title: titleMatch ? htmlText(titleMatch[1]) : "",
    sort: sortTabs.length === 1 ? sortTabs[0] : "",
    activePage: activePager ? activePager.n : null,
    maxPage: numbered.length ? Math.max(...numbered.map((p) => p.n)) : null,
    items,
  };
}

/** 页面实际生效的筛选必须和文件头写的一致（#340）：标题三项齐全，读得到排序时必须是按点击量。 */
function libraryPageProblems(page, requestedPage) {
  const problems = [];
  const missing = LIBRARY_TITLE_MARKS.filter((mark) => !page.title.includes(mark));
  if (missing.length) {
    problems.push(`页面标题「${page.title || "空"}」缺少「${missing.join("」「")}」，筛选没生效（可能被风控页拦住）`);
  }
  if (page.sort && page.sort !== LIBRARY_SORT) {
    problems.push(`页面排序是「${page.sort}」，不是「${LIBRARY_SORT}」`);
  }
  if (page.activePage !== null && page.activePage !== requestedPage) {
    problems.push(`请求第 ${requestedPage} 页，页面停在第 ${page.activePage} 页`);
  }
  return problems;
}

/** 主类页 <title>「都市小说-好看的都市小说-…」→「都市」；对不上就返回空串。 */
function parseCategoryTitle(html) {
  const m = String(html || "").match(/<title[^>]*>([\s\S]*?)<\/title>/i);
  const title = m ? htmlText(m[1]) : "";
  const name = title.match(/^([^\s\-—|]+?)小说-/);
  return name ? name[1] : "";
}

function metaPart(value) {
  return String(value || "").replace(/\*/g, "").replace(/\s*·\s*/g, "·").trim();
}

function summarizeLibraryQuality(books, rawCount, pageProblems) {
  const count = (pred) => books.filter(pred).length;
  const linked = count((book) => book.url);
  const problems = [...pageProblems];
  if (rawCount > books.length) problems.push(`移除无效条目 ${rawCount - books.length} 条`);
  if (linked < books.length) problems.push(`作品页链接缺失 ${books.length - linked} 条`);
  const missing = [
    ["主类未解析", (book) => !book.genre],
    ["子分类缺失", (book) => !book.subGenre],
    ["状态缺失", (book) => !book.status],
    ["字数缺失", (book) => !book.words],
  ];
  for (const [label, pred] of missing) {
    const n = count(pred);
    if (n) problems.push(`${label} ${n} 条`);
  }
  // 书库页本来就没有热度数字，缺热度不算问题，名次即点击量页序。
  if (books.length < LIBRARY_SPARSE_BELOW) problems.push(`[数据稀疏] 实际采集 ${books.length} 条`);
  return { linked, problems, quality: problems.length ? "[存在问题]" : "[OK]" };
}

function renderLibraryMarkdown({ books, rawCount, pages, pagesRead, pageProblems = [], now = new Date().toISOString() }) {
  const summary = summarizeLibraryQuality(books, rawCount, pageProblems);
  const range = pagesRead < pages ? `取前 ${pages} 页（实取 ${pagesRead} 页）` : `取前 ${pages} 页`;
  const lines = [
    `# 七猫 · ${LIBRARY_LIST}`,
    "",
    `- 数据质量：${summary.quality}`,
    `- 有效条目：${books.length} / ${rawCount}`,
    `- 问题摘要：${summary.problems.length ? summary.problems.join("；") : "无"}`,
    `- 作品页链接：${summary.linked} / ${books.length}`,
    `- 来源：${libraryPageUrl(1)}`,
    `- 筛选：${LIBRARY_FILTER_NOTE}；${LIBRARY_SORT}排序，${range}；名次即页序，书库页没有热度数字`,
    `- 抓取时间：${now}`,
    `- 条目数：${books.length}`,
    "",
    "---",
    "",
  ];
  for (const b of books) {
    lines.push(`### #${b.rank} ${b.title}`);
    // 元信息按位置聚合：作者、题材（主类，取不到时退用子分类）、子分类进标签、状态、字数。
    const meta = [
      metaPart(b.author),
      metaPart(b.genre || b.subGenre),
      b.genre ? metaPart(b.subGenre) : "",
      metaPart(b.status) || "[待补]",
      b.words || "[待补]",
    ].filter(Boolean);
    lines.push(`*${meta.join(" · ")}*`);
    if (b.update) lines.push(`**最新更新：** ${b.update}`);
    if (b.url) lines.push(`[作品页](${b.url})`);
    const desc = cleanDesc(b.desc);
    if (desc) lines.push("", "**简介**", "", desc);
    lines.push("", "---", "");
  }
  return { content: lines.join("\n"), summary };
}

/**
 * 翻页采集书库。按 bookId 去重、按首次出现连续编号；某页没有新书就停。
 * 第 1 页失败或一本没采到 → 抛错（不写文件）；后面某页失败 → 保留已采到的页，partial。
 */
async function scrapeLibrary(pages) {
  console.log(`\n→ 采集 七猫${LIBRARY_LIST}（${LIBRARY_FILTER_NOTE}，${LIBRARY_SORT}，前 ${pages} 页）...`);
  const books = [];
  const seen = new Set();
  const pageProblems = [];
  let invalid = 0;
  let pagesRead = 0;
  let maxPage = null;
  let requested = 0;
  const politeGet = async (url) => {
    if (requested++ > 0) sleep(LIBRARY_REQUEST_GAP_MS);
    return fetchQimaoHtml(url);
  };

  for (let page = 1; page <= pages; page++) {
    if (maxPage !== null && page > maxPage) {
      console.log(`  书库只有 ${maxPage} 页，停止翻页`);
      break;
    }
    let parsed;
    try {
      parsed = parseShukuPage(await politeGet(libraryPageUrl(page)));
      const problems = libraryPageProblems(parsed, page);
      if (problems.length) throw new Error(problems.join("；"));
    } catch (err) {
      const reason = `第 ${page} 页没取到：${err && err.message ? err.message : err}`;
      if (!books.length) throw new Error(reason);
      console.error(`  ✗ ${reason}，保留前 ${pagesRead} 页`);
      pageProblems.push(reason);
      break;
    }
    pagesRead++;
    if (page === 1) maxPage = parsed.maxPage;
    let fresh = 0;
    let duplicate = 0;
    for (const item of parsed.items) {
      if (!item.title || !item.author) {
        invalid++;
        continue;
      }
      const key = item.bookId || `${item.title}|${item.author}`;
      if (seen.has(key)) {
        duplicate++;
        continue;
      }
      seen.add(key);
      books.push({ ...item, rank: books.length + 1 });
      fresh++;
    }
    console.log(`  第 ${page} 页：新书 ${fresh} 本${duplicate ? `，跨页重复 ${duplicate} 本` : ""}`);
    if (!fresh) break;
  }

  if (!books.length) {
    throw new Error(`书库第 1 页一本书都没解析出来（页面条目 ${invalid} 个），页面可能改版`);
  }

  // 书库页只有子分类；主类按分类页标题查，每个主类 id 本次运行只请求一次。
  const mainNames = new Map();
  for (const id of new Set(books.map((book) => book.mainId).filter(Boolean))) {
    try {
      mainNames.set(id, parseCategoryTitle(await politeGet(categoryUrl(id))));
    } catch (err) {
      console.error(`  ⚠ 主类 ${id} 没查到：${err && err.message ? err.message : err}`);
      mainNames.set(id, "");
    }
  }
  for (const book of books) book.genre = mainNames.get(book.mainId) || "";

  const { content, summary } = renderLibraryMarkdown({
    books,
    rawCount: books.length + invalid,
    pages,
    pagesRead,
    pageProblems,
  });
  console.log(`  ✓ 提取 ${books.length} 本（链接 ${summary.linked}/${books.length}，${summary.quality}）`);
  return { content, partialReasons: pageProblems };
}

// ---------------------------------------------------------------------------
// 主流程
// ---------------------------------------------------------------------------

const args = process.argv.slice(2);
const PORT = parseInt(getArg(args, "--port") || "9222", 10);
const OUTDIR = getArg(args, "--outdir") || ".";
const CHANNEL = getArg(args, "--channel") || "male";
const RANKTYPE = getArg(args, "--type") || "hot";
const PERIOD = getArg(args, "--period") || "day";
const SOURCE = getArg(args, "--source") || "rank";
const PAGES_ARG = getArg(args, "--pages");

/** 参数是否显式出现过（含 --x=value 写法）；书库模式下用来拒绝排行榜专用参数。 */
function hasArg(argv, name) {
  return argv.some((arg) => arg === name || String(arg).startsWith(`${name}=`));
}

function scrapeRank(port, channelId, rankTypeId, periodId) {
  const ch = CHANNELS.find((c) => c.id === channelId);
  const rt = RANK_TYPES.find((r) => r.id === rankTypeId);
  const period = periodId ? PERIODS.find((p) => p.id === periodId) : null;
  if (!ch || !rt) {
    console.log("  ⚠ 未知频道或榜单类型");
    return null;
  }

  const periodLabel = period ? period.label : "";
  const url = rankUrl(channelId, rankTypeId, periodId);
  console.log(`\n→ 采集 七猫${ch.label}${rt.label}${periodLabel}...`);

  let books, urls, rawCount;
  try {
    ab(port, "open", url);
    sleep(3000);

    // 连通性自检：CDP 未起/被重定向时给可操作报错，而非静默产空
    const probe = probePage(port);
    if (!probe) {
      console.error(
        `  ✗ CDP 无响应。请确认已用 browser-cdp 启动 Chrome（端口 ${port}），且 agent-browser 可用。`
      );
      return null;
    }
    if (probe.host && probe.host.indexOf("qimao") === -1) {
      console.error(`  ✗ 当前页面非七猫（host=${probe.host}），可能被重定向，已跳过。`);
      return null;
    }
    const observed = extractObservedSelection(port);
    if (!selectionMatches(observed, channelId, rankTypeId, periodId)) {
      console.error(
        `  ✗ 页面实际榜单与请求不一致（请求 ${ch.tab}/${rt.label}/${periodLabel || "日榜"}，` +
        `实际 ${observed.channel || "?"}/${observed.rankType || "?"}/${observed.period || "?"}，path=${observed.path || probe.path || "?"}），已跳过。`
      );
      return null;
    }
    console.log(`  ✓ 已验证页面实际榜单：${observed.channel}/${observed.rankType}${observed.period ? "/" + observed.period : ""}`);

    // 滚动加载更多
    scrollLoad(port, 5);
    sleep(1000);

    // 文本解析获取书籍数据 + DOM 获取链接
    const rawBooks = extractBooksFromText(port);
    rawCount = rawBooks.length;
    books = rawBooks.filter(isUsableBook);
    urls = extractBookUrls(port);
  } catch (err) {
    console.error(`[qimao] ${ch.label}${rt.label}${periodLabel} 页面加载或提取出错: ${err.message}`);
    return null;
  }

  if (!books.length) {
    console.error(`[qimao] 采集失败：页面结构可能已变（选择器没匹配到数据），请检查榜单URL或更新选择器 (${RANK_URL} ${ch.label}${rt.label}${periodLabel})`);
    return null;
  }

  // 按标题匹配 URL（书名归一后比对，吸收空白差异）
  const norm = (s) => (s || "").replace(/\s+/g, "");
  for (const b of books) {
    try {
      const matched = urls.find((u) => norm(u.title) === norm(b.title));
      if (matched) b.url = matched.url;
    } catch (matchErr) {
      console.error(`[qimao] URL匹配出错（#${b.rank} ${b.title}）: ${matchErr.message}`);
    }
  }

  const summary = summarizeQuality(books, rawCount);
  console.log(
    `  ✓ 提取 ${books.length} 本（链接 ${summary.linked}/${books.length}，热度 ${summary.heated}/${books.length}）`
  );
  return renderMarkdown(ch, rt, period, url, books, rawCount);
}

function buildTargets(channel, rankType, period, source = "rank") {
  // 书库只有一个目标：全站一份，不进 --type all（它不需要 Chrome，筛选也和排行榜无关）。
  if (source === LIBRARY_ID) return [{ channel: "all", rankType: LIBRARY_ID, period: null }];
  const channels = channel === "all" ? CHANNELS.map((item) => item.id) : [channel];
  const rankTypes = rankType === "all" ? RANK_TYPES.map((item) => item.id) : [rankType];
  const targets = [];
  for (const channelId of channels) {
    for (const rankTypeId of rankTypes) {
      if (rankTypeId === "hot") {
        const periods = period === "all" ? PERIODS.map((item) => item.id) : [period];
        for (const periodId of periods) {
          targets.push({ channel: channelId, rankType: rankTypeId, period: periodId });
        }
      } else {
        targets.push({ channel: channelId, rankType: rankTypeId, period: null });
      }
    }
  }
  return targets;
}

function outputFilename(channelId, rankTypeId, periodId, date) {
  if (rankTypeId === LIBRARY_ID) return `七猫${LIBRARY_LIST}_${date}.md`;
  const channel = CHANNELS.find((item) => item.id === channelId);
  const rankType = RANK_TYPES.find((item) => item.id === rankTypeId);
  const period = periodId ? PERIODS.find((item) => item.id === periodId) : null;
  return `七猫${channel.label}${rankType.label}${period ? period.label : ""}_${date}.md`;
}

/** 参数全部在联网、开浏览器之前校验；返回本次要采的目标与书库页数。 */
function resolvePlan() {
  if (SOURCE !== "rank" && SOURCE !== LIBRARY_ID) {
    throw new Error(`未知 --source: ${SOURCE}（rank / ${LIBRARY_ID}）`);
  }
  if (SOURCE === LIBRARY_ID) {
    const rankOnly = ["--channel", "--type", "--period"].filter((name) => hasArg(args, name));
    if (rankOnly.length) {
      throw new Error(
        `--source library 不能配 ${rankOnly.join("、")}：书库筛选固定为${LIBRARY_FILTER_NOTE}、${LIBRARY_SORT}`
      );
    }
    return { targets: buildTargets(null, null, null, LIBRARY_ID), pages: parseLibraryPages(PAGES_ARG) };
  }
  if (hasArg(args, "--pages")) {
    throw new Error("--pages 只用于 --source library");
  }
  if (CHANNEL !== "all" && !CHANNELS.some((channel) => channel.id === CHANNEL)) {
    throw new Error(`未知 --channel: ${CHANNEL}`);
  }
  if (RANKTYPE !== "all" && !RANK_TYPES.some((rank) => rank.id === RANKTYPE)) {
    throw new Error(`未知 --type: ${RANKTYPE}`);
  }
  if (PERIOD !== "all" && !PERIODS.some((period) => period.id === PERIOD)) {
    throw new Error(`未知 --period: ${PERIOD}`);
  }
  return { targets: buildTargets(CHANNEL, RANKTYPE, PERIOD), pages: 0 };
}

async function main() {
  const { targets, pages } = resolvePlan();
  let written = 0;
  let failed = 0;
  const partialReasons = [];

  for (const target of targets) {
    let content;
    if (target.rankType === LIBRARY_ID) {
      // 书库一次只有一个目标：整份失败直接抛错（exit 1，不写文件），页级失败带回 partialReasons。
      const library = await scrapeLibrary(pages);
      content = library.content;
      partialReasons.push(...library.partialReasons);
    } else {
      content = scrapeRank(PORT, target.channel, target.rankType, target.period);
    }
    if (!content) {
      failed++;
      continue;
    }

    const filename = outputFilename(target.channel, target.rankType, target.period, localDateStamp());
    fs.mkdirSync(OUTDIR, { recursive: true });
    const filepath = path.join(OUTDIR, filename);
    fs.writeFileSync(filepath, content, "utf-8");
    written++;
    console.log(`  ✓ 已保存: ${filepath}`);
  }
  return {
    planned: targets.length,
    written,
    failed,
    partial: failed > 0 || partialReasons.length > 0,
    partialReasons,
  };
}

if (require.main === module) {
  runCli(main, "七猫采集");
}

module.exports = {
  extractBooksFromText,
  isUsableBook,
  cleanDesc,
  renderMarkdown,
  rankUrl,
  selectionMatches,
  buildTargets,
  outputFilename,
};
