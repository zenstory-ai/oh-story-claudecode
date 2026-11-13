#!/usr/bin/env node
/**
 * 番茄小说排行榜采集脚本
 *
 * 配合 browser-cdp skill 使用。先启动 Chrome CDP 环境，再运行本脚本。
 * 采集策略：从榜单页 __INITIAL_STATE__ 取结构化列表，再逐本请求详情页解码真实
 * 书名/作者/简介/题材/标签（番茄列表页有字体反爬，详情页 HTML 里是明文）。
 * 输出的榜单 Markdown 格式见 aggregate-rank.js 文件头，聚合按它解析。
 *
 * 用法：
 *   node fanqie-rank-scraper.js --channel 1 --type 2              # 男频阅读榜
 *   node fanqie-rank-scraper.js --channel 0 --type 1              # 女频新书榜
 *   node fanqie-rank-scraper.js --channel 1 --type 2 --outdir ./  # 指定输出目录
 *   node fanqie-rank-scraper.js --channel all                     # 全部采集
 *   node fanqie-rank-scraper.js --channel 1 --top 15              # 每题材只取前 15 本
 *   node fanqie-rank-scraper.js --source library --channel all     # 书库「最热」：连载中、30 万字以下
 *   node fanqie-rank-scraper.js --source library --channel mix --pages 5  # 不分男女，取 5 页
 *
 * 前置：
 *   node {SKILL_DIR}/browser-cdp/scripts/setup-cdp-chrome.js 9222
 */

const fs = require("fs");
const path = require("path");
const { ab, sleep, evalJSONBase64, scrollLoad, getArg, localDateStamp, runCli } = require("./cdp-utils");

// 一次详情请求的并发批大小。番茄详情页用同步 XHR 拉取，批太大会撞上
// cdp-utils 里 ab() 的 20s 超时；超时会显式失败，这里分批是为了避免整个题材被中断。
const DETAIL_CHUNK = 5;

// ---------------------------------------------------------------------------
// 页面提取
// ---------------------------------------------------------------------------

/** 连通性 + 页面就绪自检 */
function probePage(port) {
  return evalJSONBase64(
    port,
    "JSON.stringify({host:location.host,hasState:!!window.__INITIAL_STATE__})"
  );
}

/** 构建：提取侧边菜单品类链接的浏览器 JS */
function buildCategoriesJS(prefix) {
  return `JSON.stringify((function(){
    var prefix=${JSON.stringify(prefix)};
    var out=[];var seen={};
    Array.from(document.querySelectorAll('a')).forEach(function(a){
      var href=a.getAttribute('href')||'';
      if(href.indexOf(prefix)===-1)return;
      var name=(a.innerText||a.textContent||'').trim();
      if(!name)return;
      if(seen[href])return;seen[href]=1;
      out.push({name:name,href:href});
    });
    return out;
  })())`;
}

/** 提取侧边菜单品类链接 */
function extractCategories(port, channel, type) {
  const prefix = `/rank/${channel}_${type}_`;
  return evalJSONBase64(port, buildCategoriesJS(prefix)) || [];
}

/**
 * 从 __INITIAL_STATE__ 提取当前品类页的作品列表。
 * 多路径尝试 + 深度兜底扫描，并把字段名归一，避免站点改 state 结构就全盘失败。
 */
function buildBookListJS() {
  return `JSON.stringify((function(){
    var s=window.__INITIAL_STATE__||{};
    var cands=[
      s.rank&&s.rank.book_list, s.rank&&s.rank.bookList, s.rank&&s.rank.rankList,
      s.rankData&&s.rankData.book_list, s.page&&s.page.book_list
    ];
    var list=null;
    for(var i=0;i<cands.length;i++){ if(Array.isArray(cands[i])&&cands[i].length){list=cands[i];break;} }
    if(!list){
      var found=null;
      (function walk(o,d){
        if(found||!o||d>6)return;
        if(Array.isArray(o)){
          if(o.length&&o[0]&&typeof o[0]==='object'&&(o[0].bookId||o[0].book_id)){found=o;return;}
          for(var j=0;j<o.length&&!found;j++)walk(o[j],d+1);return;
        }
        if(typeof o==='object'){ for(var k in o){ if(found)break; try{walk(o[k],d+1)}catch(e){} } }
      })(s,0);
      list=found||[];
    }
    return list.map(function(b){return {
      bookId:String(b.bookId||b.book_id||''),
      read_count:b.read_count||b.readCount||b.read||'',
      wordNumber:b.wordNumber||b.word_number||b.wordCount||'',
      creationStatus:(b.creationStatus!=null?b.creationStatus:(b.creation_status!=null?b.creation_status:b.status)),
      lastChapterTitle:b.lastChapterTitle||b.last_chapter_title||b.lastChapter||'',
      category:b.category||b.categoryName||b.category_name||''
    };}).filter(function(b){return b.bookId;});
  })())`;
}

function extractBookList(port) {
  const list = evalJSONBase64(port, buildBookListJS());
  return Array.isArray(list) ? list : [];
}

/**
 * 解析一本书的详情页 HTML。buildDetailJS 用 toString 把它拼进浏览器端脚本，
 * 所以必须自包含：不引用模块作用域里的任何东西，也不能含反引号。
 * 番茄列表页书名/作者被字体反爬，详情页 HTML 内嵌 JSON 与 <title> 是明文。
 * 字段名以真实 SSR(__INITIAL_STATE__) 为准：bookName/author/abstract 明文，
 * 题材在 categoryV2(转义 JSON 数组的首个 Name)，readCount/wordNumber 可能是数字或字符串。
 * 详情页里可能先出现推荐书对象（同样带 bookName/readCount/lastChapterTitle），
 * 所以书名、作者、数字和最新章节只从「正文这本书」的对象里取：先按 bookId 定位，
 * 定位不到再按 <title> 里的书名定位；都定位不到时书名作者退回 <title>/meta，数字留空，
 * 宁可「未知」也不把推荐书的数字记到这本书头上。
 */
function parseDetailHtml(h, id) {
  function pick(src, res) {
    for (var i = 0; i < res.length; i++) {
      var m = src.match(res[i]);
      if (m && m[1]) return m[1].trim();
    }
    return "";
  }
  function jsonString(src, key) {
    var m = src.match(new RegExp('"' + key + '"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)"'));
    if (!m) return "";
    try {
      return String(JSON.parse('"' + m[1] + '"')).trim();
    } catch (e) {
      return m[1].replace(/\\"/g, '"').trim();
    }
  }
  function jsonNumber(src, key) {
    var m = src.match(new RegExp('"' + key + '"\\s*:\\s*"?([0-9]+)'));
    return m ? m[1] : "";
  }
  // 从 JSON 起点按字符串感知扫描，返回包住 pos 的最内层对象文本。
  function enclosingObject(src, pos) {
    var start = src.lastIndexOf("__INITIAL_STATE__", pos);
    if (start >= 0) {
      start = src.indexOf("{", start);
    } else {
      start = src.lastIndexOf("<script", pos);
      start = start >= 0 ? src.indexOf(">", start) + 1 : 0;
    }
    if (start < 0 || start > pos) return "";
    var stack = [];
    var inStr = false;
    var esc = false;
    for (var i = start; i < src.length; i++) {
      var c = src.charAt(i);
      if (inStr) {
        if (esc) esc = false;
        else if (c === "\\") esc = true;
        else if (c === '"') inStr = false;
        continue;
      }
      if (c === '"') inStr = true;
      else if (c === "{") stack.push(i);
      else if (c === "}") {
        var open = stack.pop();
        if (open === undefined) return "";
        if (open <= pos && i >= pos) return src.slice(open, i + 1);
      }
    }
    return "";
  }
  function regionAt(re) {
    var m;
    re.lastIndex = 0;
    while ((m = re.exec(h))) {
      var obj = enclosingObject(h, m.index);
      if (obj.indexOf('"bookName"') >= 0) return obj;
    }
    return "";
  }

  var titleTag = pick(h, [
    /<title>([^<]*?)(?:完整版|最新章节|在线阅读|_番茄小说|-番茄小说|_番茄|-番茄)/,
    /<meta[^>]+property="og:title"[^>]+content="([^"]+)"/,
    /<title>([^<|_]{1,40})/,
  ]);
  var safeId = String(id).replace(/[^0-9A-Za-z_]/g, "");
  var region = safeId
    ? regionAt(new RegExp('"(?:bookId|book_id)"\\s*:\\s*"?' + safeId + '(?![0-9A-Za-z_])', "g"))
    : "";
  if (!region && titleTag) {
    var escTitle = titleTag.replace(/[.*+?^$()|[\]\\{}]/g, "\\$&");
    region = regionAt(new RegExp('"bookName"\\s*:\\s*"' + escTitle + '"', "g"));
  }

  var title = (region && jsonString(region, "bookName")) || titleTag;
  var author = (region && (jsonString(region, "author") || jsonString(region, "authorName"))) ||
    pick(h, [/<meta[^>]+property="og:novel:author"[^>]+content="([^"]+)"/]);
  // abstract(真实简介)优先；meta description 是平台模板("番茄小说提供...")，
  // 且常带 data-rh 属性，故用宽松属性匹配兜底。
  var abs = region ? jsonString(region, "abstract") : "";
  if (abs.length < 6) abs = "";
  var desc = abs || pick(h, [
    /<meta[^>]+name="description"[^>]+content="([^"]+)"/,
    /<meta[^>]+property="og:description"[^>]+content="([^"]+)"/,
  ]);
  // 题材：category 常为空字符串，真实题材在 categoryV2(转义 JSON)首个 Name。
  var category = (region && pick(region, [
    /"categoryV2":"\[\{[\s\S]*?\\"Name\\":\\"([^"\\]+)/,
    /"category"\s*:\s*"([^"]{1,20})"/,
  ])) || pick(h, [/<meta[^>]+property="og:novel:category"[^>]+content="([^"]+)"/]);
  // 标签：番茄简介开头常带【tag+tag+...】，是题材细分的真实信号。
  var tags = "";
  var bm = (abs || desc || "").match(/[【\[]([^】\]]{2,40})[】\]]/);
  if (bm) tags = bm[1].split(/[+、,\/\s]+/).filter(Boolean).slice(0, 6).join("、");
  // 书库列表的在读数、字数也被字体反爬，详情页的 SSR 数字是明文。
  return {
    title: title,
    author: author,
    desc: desc,
    category: category,
    tags: tags,
    readCount: region ? jsonNumber(region, "readCount") : "",
    wordNumber: region ? jsonNumber(region, "wordNumber") : "",
    creationStatus: region ? jsonNumber(region, "creationStatus") : "",
    lastChapterTitle: region ? jsonString(region, "lastChapterTitle") : "",
  };
}

/**
 * 批量解码详情：逐本同步 XHR 请求 /page/{id}，交给 parseDetailHtml 解析。
 * 返回 { id: {title, author, desc, category, tags, readCount, wordNumber, creationStatus, lastChapterTitle} }。
 */
function buildDetailJS(ids) {
  return `JSON.stringify((function(){
    var ids=${JSON.stringify(ids)};
    var parseDetailHtml=${parseDetailHtml.toString()};
    var map={};
    for(var k=0;k<ids.length;k++){
      var id=ids[k];
      try{
        var x=new XMLHttpRequest();
        x.open('GET','/page/'+id,false);
        x.send();
        map[id]=parseDetailHtml(x.responseText||'',id);
      }catch(e){
        map[id]={title:'',author:'',desc:'',category:'',tags:'',err:String(e&&e.message||e)};
      }
    }
    return map;
  })())`;
}

function fetchDetailsChunk(port, ids) {
  return evalJSONBase64(port, buildDetailJS(ids)) || {};
}

/** 分批解码，避免单次 eval 超时；返回合并后的 map */
function fetchDetails(port, bookIds) {
  const map = {};
  for (let i = 0; i < bookIds.length; i += DETAIL_CHUNK) {
    const chunk = bookIds.slice(i, i + DETAIL_CHUNK);
    const part = fetchDetailsChunk(port, chunk);
    Object.assign(map, part);
    sleep(300);
  }
  return map;
}

// ---------------------------------------------------------------------------
// 格式化
// ---------------------------------------------------------------------------

function fmtReads(count) {
  if (!count || count === "0") return "未知";
  const n = parseInt(count, 10);
  if (isNaN(n)) return "未知";
  if (n >= 10000) return (n / 10000).toFixed(1) + "万";
  return String(n);
}

function fmtWords(count) {
  if (!count) return "未知";
  const n = parseInt(count, 10);
  if (isNaN(n)) return "未知";
  if (n >= 10000) return (n / 10000).toFixed(1) + "万";
  return String(n);
}

function fmtStatus(s) {
  const v = String(s);
  if (v === "1") return "连载中";
  if (v === "0" || v === "2") return "已完结";
  return s ? String(s) : "未知";
}

/** 清洗简介：去平台模板文本 → 折叠空白 → 句末截断 100 字 */
function cleanDesc(raw) {
  if (!raw) return "";
  let d = String(raw)
    // 简介取自 JSON 字符串原文，先还原常见转义（\n \uXXXX \" 等）
    .replace(/\\u([0-9a-fA-F]{4})/g, (_, h) => String.fromCharCode(parseInt(h, 16)))
    .replace(/\\[nrt]/g, " ")
    .replace(/\\"/g, '"')
    .replace(/番茄小说[^。！？]*?(?:免费阅读|完整版|在线阅读)[^。！？]*[。！？]/g, "")
    .replace(/番茄小说[^。！？]*?(?:免费阅读|完整版|在线阅读)[^。！？]*$/g, "")
    .replace(/\s+/g, " ")
    .trim();
  if (d.length <= 100) return d;
  const cut = d.slice(0, 100);
  const m = cut.match(/^[\s\S]*[。！？]/);
  return (m ? m[0] : cut) + "...";
}

// ---------------------------------------------------------------------------
// 主流程
// ---------------------------------------------------------------------------

const args = process.argv.slice(2);
const PORT = parseInt(getArg(args, "--port") || "9222", 10);
const OUTDIR = getArg(args, "--outdir") || ".";
const CHANNEL = getArg(args, "--channel") || "1";
const TYPE = getArg(args, "--type") || "2";
const TOP = parseInt(getArg(args, "--top") || "20", 10);
const SOURCE = getArg(args, "--source") || "rank";
const PAGES = parseInt(getArg(args, "--pages") || "3", 10);
const STAT = getArg(args, "--stat") || "1";
const COUNT = getArg(args, "--count") || "0";

function channelLabel(ch) {
  return ch === "1" ? "男频" : "女频";
}

function typeLabel(t) {
  return t === "2" ? "阅读榜" : "新书榜";
}

function scrapeChannel(ch, type) {
  const chLabel = channelLabel(ch);
  const tyLabel = typeLabel(type);
  console.log(`\n→ 采集 ${chLabel}${tyLabel}...`);

  // 用已知品类 ID 作为入口，确保菜单只显示当前频道/类型的品类
  const initCatId = ch === "1" ? "1141" : "1139"; // 男频:西方奇幻 / 女频:古风世情
  const initUrl = `https://fanqienovel.com/rank/${ch}_${type}_${initCatId}`;
  ab(PORT, "open", initUrl);
  sleep(3000);

  // 连通性自检：把"静默写出一堆 bookId"变成可操作的报错
  const probe = probePage(PORT);
  if (!probe) {
    throw new Error(`CDP 无响应。请确认已用 browser-cdp 启动 Chrome（端口 ${PORT}），且 agent-browser 可用`);
  }
  if (probe.host && probe.host.indexOf("fanqie") === -1) {
    throw new Error(`当前页面非番茄（host=${probe.host}），可能被重定向到登录/验证页`);
  }
  if (!probe.hasState) {
    console.error(`  ⚠ 页面未挂载 __INITIAL_STATE__，将尝试兜底扫描，结果可能不完整。`);
  }

  let categories = extractCategories(PORT, ch, type);
  if (!categories.length) {
    // 菜单可能懒加载，滚动后重试一次
    scrollLoad(PORT, 2);
    sleep(1000);
    categories = extractCategories(PORT, ch, type);
  }
  if (!categories.length) {
    // 仍失败：降级为只采当前入口页，至少产出数据而不是空跑
    console.log(`  ⚠ 未提取到品类菜单，降级为单题材采集（入口页）`);
    categories = [{ name: "全部（入口页）", href: `/rank/${ch}_${type}_${initCatId}` }];
  } else {
    console.log(`  发现 ${categories.length} 个品类`);
  }

  const now = new Date().toISOString();
  const lines = [
    `# 番茄 · ${chLabel}${tyLabel} · 全 ${categories.length} 题材`,
    "",
    `- 频道参数：channel=${ch}，type=${type}`,
    `- 抓取时间：${now}`,
    `- 每题材上限 ≈ ${TOP}`,
    "",
    "---",
    "",
  ];

  let totalBooks = 0;
  let resolvedTitles = 0;
  const bodyLines = [];

  for (let ci = 0; ci < categories.length; ci++) {
    const cat = categories[ci];
    console.log(`  [${ci + 1}/${categories.length}] ${cat.name}`);

    try {
      ab(PORT, "open", `https://fanqienovel.com${cat.href}`);
      sleep(2500);
      scrollLoad(PORT, 2);

      let books = extractBookList(PORT);
      if (!Array.isArray(books) || !books.length) {
        bodyLines.push(`## ${cat.name} — 0 本`, "", "---", "");
        continue;
      }
      if (books.length > TOP) books = books.slice(0, TOP);

      // 分批解码真实书名/作者/简介/题材/评分/标签
      const bookIds = books.map((b) => String(b.bookId));
      const details = fetchDetails(PORT, bookIds);

      bodyLines.push(`## ${cat.name} — ${books.length} 本`, "");

      for (let i = 0; i < books.length; i++) {
        const b = books[i];
        const info = details[String(b.bookId)] || {};
        totalBooks++;
        const resolved = !!info.title;
        if (resolved) resolvedTitles++;

        const title = info.title || "（标题待解析）";
        const author = info.author || "未知";
        const category = info.category || b.category || "";
        const catSeg = category ? ` · ${category}` : "";

        bodyLines.push(`### #${i + 1} ${title}`);
        bodyLines.push(
          `*${author}${catSeg} · ${fmtStatus(info.creationStatus || b.creationStatus)} · ${fmtReads(info.readCount || b.read_count)} 在读 · ${fmtWords(info.wordNumber || b.wordNumber)}字*`
        );
        if (info.tags) bodyLines.push(`**标签：** ${info.tags}`);
        bodyLines.push(`**最新更新：** ${info.lastChapterTitle || b.lastChapterTitle || "未知"}`);
        bodyLines.push(`**bookId：** ${b.bookId}`);
        bodyLines.push(`[作品页](https://fanqienovel.com/page/${b.bookId})`);
        const desc = cleanDesc(info.desc);
        if (desc) {
          bodyLines.push("");
          bodyLines.push("**简介**");
          bodyLines.push("");
          bodyLines.push(desc);
        }
        bodyLines.push("");
      }

      bodyLines.push("---", "");
    } catch (catErr) {
      console.error(
        `  [fanqie] 品类 ${cat.name} 处理出错，跳过: ${catErr && catErr.message ? catErr.message : catErr}`
      );
      bodyLines.push(`## ${cat.name} — 采集失败`, "", "---", "");
    }
  }

  // 一本都没采到时不写文件、计为失败：空榜单进了聚合只会让结论悄悄少一块。
  if (totalBooks === 0) {
    throw new Error("所有题材一本都没采到（页面结构可能变了，或被登录/验证页拦住）");
  }

  // 质量状态：标题解析比例是番茄采集成败的核心信号
  const ratio = resolvedTitles / totalBooks;
  const quality = ratio < 0.5 ? "[标题解析异常]" : "[OK]";
  lines.splice(5, 0,
    `- 标题解析：成功 ${resolvedTitles} / 共 ${totalBooks}`,
    `- 数据质量：${quality}`
  );

  if (resolvedTitles === 0) {
    console.error(
      `  ✗ ${chLabel}${tyLabel}：${totalBooks} 本全部标题解析失败。多为详情页结构变动或登录/验证拦截，` +
      `请在 Chrome 内手动打开任一 https://fanqienovel.com/page/{bookId} 确认页面正常。`
    );
  } else if (ratio < 0.5) {
    console.error(
      `  ⚠ ${chLabel}${tyLabel}：标题解析率偏低（${resolvedTitles}/${totalBooks}），结果质量已标注。`
    );
  }

  return lines.concat(bodyLines).join("\n");
}


// ---------------------------------------------------------------------------
// 书库「最热」：/library/{筛选}/page_{n}?sort=hottes，每页 18 本，按热度排序
// ---------------------------------------------------------------------------

const LIB_STAT = { "1": "连载中", "0": "已完结", any: "" };
const LIB_COUNT = { "0": "30万字以下", "1": "30-50万字", "2": "50-100万字", "3": "100-200万字", "4": "200万字以上", any: "" };

/** 书库筛选段：audience1=男生、audience0=女生，stat1=连载中，count0=30万字以下；全不选时站点用 all。 */
function libraryPath(ch) {
  const segs = [];
  if (ch !== "mix") segs.push(`audience${ch}`);
  if (STAT !== "any") segs.push(`stat${STAT}`);
  if (COUNT !== "any") segs.push(`count${COUNT}`);
  return segs.length ? segs.join("-") : "all";
}

function libraryLabel(ch) {
  const who = ch === "mix" ? "全站" : channelLabel(ch);
  const filters = [LIB_STAT[STAT], LIB_COUNT[COUNT]].filter(Boolean).join("·");
  return { who, filters };
}

/** 列表页书名、在读数都被字体反爬；只按页面顺序取 bookId，其余字段由详情页解码。 */
function buildLibraryIdsJS() {
  return `JSON.stringify((function(){
    var seen={},out=[];
    Array.from(document.querySelectorAll('a[href*="/page/"]')).forEach(function(a){
      var m=(a.getAttribute('href')||'').match(/\\/page\\/(\\d+)/);
      if(m&&!seen[m[1]]){seen[m[1]]=1;out.push(m[1]);}
    });
    return out;
  })())`;
}

function scrapeLibrary(ch) {
  const { who, filters } = libraryLabel(ch);
  const seg = libraryPath(ch);
  console.log(`\n→ 采集 番茄书库最热 · ${who}${filters ? "（" + filters + "）" : ""}...`);
  const ids = [];
  for (let page = 1; page <= PAGES; page++) {
    const url = `https://fanqienovel.com/library/${seg}/page_${page}?sort=hottes`;
    ab(PORT, "open", url);
    sleep(3000);
    if (page === 1) {
      const probe = probePage(PORT);
      if (!probe) {
        throw new Error(`CDP 无响应。请确认已用 browser-cdp 启动 Chrome（端口 ${PORT}），且 agent-browser 可用`);
      }
      if (probe.host && probe.host.indexOf("fanqie") === -1) {
        throw new Error(`当前页面非番茄（host=${probe.host}），可能被重定向到登录/验证页`);
      }
    }
    const readIds = () => {
      const got = evalJSONBase64(PORT, buildLibraryIdsJS());
      return Array.isArray(got) ? got : [];
    };
    let pageIds = readIds();
    if (!pageIds.length) {
      sleep(2000);
      pageIds = readIds();
    }
    const fresh = pageIds.filter((id) => !ids.includes(id));
    console.log(`  第 ${page} 页：${fresh.length} 本`);
    if (!fresh.length) break;
    ids.push(...fresh);
  }

  if (!ids.length) {
    // 一本都没抓到时不写空文件：空文件进了聚合只会让结论悄悄少一块。
    throw new Error("书库列表页一本都没抓到（可能被登录/验证页拦住，或页面改版）");
  }
  const details = fetchDetails(PORT, ids);
  const now = new Date().toISOString();
  let resolved = 0;
  const body = [`## 全部（书库最热） — ${ids.length} 本`, ""];
  ids.forEach((id, i) => {
    const info = details[id] || {};
    if (info.title) resolved++;
    const catSeg = info.category ? ` · ${info.category}` : "";
    body.push(`### #${i + 1} ${info.title || "（标题待解析）"}`);
    body.push(`*${info.author || "未知"}${catSeg} · ${fmtStatus(info.creationStatus)} · ${fmtReads(info.readCount)} 在读 · ${fmtWords(info.wordNumber)}字*`);
    if (info.tags) body.push(`**标签：** ${info.tags}`);
    body.push(`**最新更新：** ${info.lastChapterTitle || "未知"}`);
    body.push(`**bookId：** ${id}`);
    body.push(`[作品页](https://fanqienovel.com/page/${id})`);
    const desc = cleanDesc(info.desc);
    if (desc) body.push("", "**简介**", "", desc);
    body.push("");
  });
  const quality = resolved / ids.length < 0.5 ? "[标题解析异常]" : "[OK]";
  if (resolved / ids.length < 0.5) {
    console.error(`  ⚠ 标题解析率偏低（${resolved}/${ids.length}），请在 Chrome 内手动打开任一作品页确认不是验证页。`);
  }
  // 列表名带「新书」：连载中、30 万字以下按热度排，本质是新书热度，聚合时进「新书榜」列。
  const listName = `${who}书库最热${COUNT === "0" && STAT === "1" ? "新书" : ""}`;
  const head = [
    `# 番茄 · ${listName}`,
    "",
    `- 来源：https://fanqienovel.com/library/${seg}/page_1?sort=hottes`,
    `- 筛选：${filters || "不限"}；按「最热」排序，取前 ${PAGES} 页`,
    `- 抓取时间：${now}`,
    `- 标题解析：成功 ${resolved} / 共 ${ids.length}`,
    `- 数据质量：${quality}`,
    "",
    "---",
    "",
  ];
  return { content: head.concat(body).join("\n"), name: `番茄${who}${listName.replace(who, "")}_${libraryPath(ch)}_${localDateStamp()}.md` };
}

function mainLibrary() {
  if (!["0", "1", "all", "mix"].includes(CHANNEL)) throw new Error(`未知 --channel: ${CHANNEL}（书库用 1 / 0 / all / mix）`);
  if (!(STAT in LIB_STAT)) throw new Error(`未知 --stat: ${STAT}（1 连载中 / 0 已完结 / any）`);
  if (!(COUNT in LIB_COUNT)) throw new Error(`未知 --count: ${COUNT}（0-4 或 any）`);
  const channels = CHANNEL === "all" ? ["1", "0"] : [CHANNEL];
  const failures = [];
  let written = 0;
  for (const ch of channels) {
    try {
      const out = scrapeLibrary(ch);
      fs.mkdirSync(OUTDIR, { recursive: true });
      const filepath = path.join(OUTDIR, out.name);
      fs.writeFileSync(filepath, out.content, "utf-8");
      written++;
      console.log(`  ✓ 已保存: ${filepath}`);
    } catch (err) {
      const reason = `书库${libraryLabel(ch).who}：${err && err.message ? err.message : err}`;
      console.error(`[fanqie] ${reason}，跳过`);
      failures.push(reason);
    }
  }
  return outcome(channels.length, written, failures);
}

/** 按 runCli 的结构报结果：一份没写出就整体失败，部分失败 exit 2 并列原因。 */
function outcome(planned, written, failures) {
  if (!written) throw new Error(failures.join("；") || "no output was written");
  return { planned, written, failed: failures.length, partialReasons: failures };
}

function main() {
  if (SOURCE === "library") return mainLibrary();
  if (SOURCE !== "rank") throw new Error(`未知 --source: ${SOURCE}（rank / library）`);
  if (!["0", "1", "all"].includes(CHANNEL)) {
    throw new Error(`未知 --channel: ${CHANNEL}`);
  }
  if (!["1", "2", "all"].includes(TYPE)) {
    throw new Error(`未知 --type: ${TYPE}`);
  }
  const channels = CHANNEL === "all" ? ["1", "0"] : [CHANNEL];
  const types = TYPE === "all" ? ["2", "1"] : [TYPE];
  const failures = [];
  let written = 0;

  for (const ch of channels) {
    for (const ty of types) {
      try {
        const content = scrapeChannel(ch, ty);

        const filename = `番茄${channelLabel(ch)}${typeLabel(ty)}_全题材_${localDateStamp()}.md`;
        fs.mkdirSync(OUTDIR, { recursive: true });
        const filepath = path.join(OUTDIR, filename);
        fs.writeFileSync(filepath, content, "utf-8");
        written++;
        console.log(`  ✓ 已保存: ${filepath}`);
      } catch (chErr) {
        const reason = `${channelLabel(ch)}${typeLabel(ty)}：${chErr && chErr.message ? chErr.message : chErr}`;
        console.error(`[fanqie] ${reason}，跳过`);
        failures.push(reason);
      }
    }
  }
  return outcome(channels.length * types.length, written, failures);
}

if (require.main === module) {
  runCli(main, "番茄采集");
}

module.exports = { parseDetailHtml, buildDetailJS, cleanDesc };
