#!/usr/bin/env node
/**
 * 番茄小说排行榜采集脚本
 *
 * 配合 browser-cdp skill 使用。先启动 Chrome CDP 环境，再运行本脚本。
 * 采集策略：从榜单页 __INITIAL_STATE__ 取结构化列表，再逐本请求详情页解码真实
 * 书名/作者/简介/题材/标签（番茄列表页有字体反爬，详情页 HTML 里是明文）。
 * 输出 Markdown 格式匹配 scan-output-format.md 规范。
 *
 * 用法：
 *   node fanqie-rank-scraper.js --channel 1 --type 2              # 男频阅读榜
 *   node fanqie-rank-scraper.js --channel 0 --type 1              # 女频新书榜
 *   node fanqie-rank-scraper.js --channel 1 --type 2 --outdir ./  # 指定输出目录
 *   node fanqie-rank-scraper.js --channel all                     # 全部采集
 *   node fanqie-rank-scraper.js --channel 1 --top 15              # 每题材只取前 15 本
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
 * 批量解码详情：逐本同步 XHR 请求 /page/{id}，多策略解析明文字段。
 * 番茄列表页书名/作者被字体反爬，详情页 HTML 内嵌 JSON 与 <title> 是明文。
 * 字段名以真实 SSR(__INITIAL_STATE__) 为准：bookName/author/abstract 明文，
 * 题材在 categoryV2(转义 JSON 数组的首个 Name)，番茄 SSR 不含数字评分。
 * 返回 { id: {title, author, desc, category, tags} }。
 */
function buildDetailJS(ids) {
  return `JSON.stringify((function(){
    var ids=${JSON.stringify(ids)};
    var map={};
    function pick(h,res){for(var i=0;i<res.length;i++){var m=h.match(res[i]);if(m&&m[1])return m[1].trim();}return '';}
    for(var k=0;k<ids.length;k++){
      var id=ids[k];
      try{
        var x=new XMLHttpRequest();
        x.open('GET','/page/'+id,false);
        x.send();
        var h=x.responseText||'';
        var title=pick(h,[
          /"bookName"\\s*:\\s*"([^"]+)"/,
          /<title>([^<]*?)(?:完整版|最新章节|在线阅读|_番茄小说|-番茄小说|_番茄|-番茄)/,
          /<meta[^>]+property="og:title"[^>]+content="([^"]+)"/,
          /<title>([^<|_]{1,40})/
        ]);
        var author=pick(h,[
          /"author"\\s*:\\s*"([^"]+)"/,
          /"authorName"\\s*:\\s*"([^"]+)"/,
          /<meta[^>]+property="og:novel:author"[^>]+content="([^"]+)"/
        ]);
        // abstract(真实简介)优先；meta description 是平台模板("番茄小说提供...")，
        // 且常带 data-rh 属性，故用宽松属性匹配兜底。
        var abs=pick(h,[/"abstract"\\s*:\\s*"([^"]{6,}?)"/]);
        var desc=abs||pick(h,[
          /<meta[^>]+name="description"[^>]+content="([^"]+)"/,
          /<meta[^>]+property="og:description"[^>]+content="([^"]+)"/
        ]);
        // 题材：category 常为空字符串，真实题材在 categoryV2(转义 JSON)首个 Name。
        var category=pick(h,[
          /"categoryV2":"\\[\\{[\\s\\S]*?\\\\"Name\\\\":\\\\"([^"\\\\]+)/,
          /"category"\\s*:\\s*"([^"]{1,20})"/,
          /<meta[^>]+property="og:novel:category"[^>]+content="([^"]+)"/
        ]);
        // 标签：番茄简介开头常带【tag+tag+...】，是题材细分的真实信号。
        var tags='';
        var bm=(abs||desc||'').match(/[【\\[]([^】\\]]{2,40})[】\\]]/);
        if(bm){tags=bm[1].split(/[+、,\\/\\s]+/).filter(Boolean).slice(0,6).join('、');}
        map[id]={title:title,author:author,desc:desc,category:category,tags:tags};
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
    console.error(
      `  ✗ CDP 无响应。请确认已用 browser-cdp 启动 Chrome（端口 ${PORT}），且 agent-browser 可用。`
    );
    return null;
  }
  if (probe.host && probe.host.indexOf("fanqie") === -1) {
    console.error(
      `  ✗ 当前页面非番茄（host=${probe.host}），可能被重定向到登录/验证页，已跳过。`
    );
    return null;
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
          `*${author}${catSeg} · ${fmtStatus(b.creationStatus)} · ${fmtReads(b.read_count)} 在读 · ${fmtWords(b.wordNumber)}字*`
        );
        if (info.tags) bodyLines.push(`**标签：** ${info.tags}`);
        bodyLines.push(`**最新更新：** ${b.lastChapterTitle || "未知"}`);
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

  // 质量状态：标题解析比例是番茄采集成败的核心信号
  const ratio = totalBooks ? resolvedTitles / totalBooks : 0;
  const quality = totalBooks === 0
    ? "[无数据]"
    : ratio < 0.5
      ? "[标题解析异常]"
      : "[OK]";
  lines.splice(5, 0,
    `- 标题解析：成功 ${resolvedTitles} / 共 ${totalBooks}`,
    `- 数据质量：${quality}`
  );

  if (totalBooks > 0 && resolvedTitles === 0) {
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

function main() {
  if (!["0", "1", "all"].includes(CHANNEL)) {
    throw new Error(`未知 --channel: ${CHANNEL}`);
  }
  if (!["1", "2", "all"].includes(TYPE)) {
    throw new Error(`未知 --type: ${TYPE}`);
  }
  const channels = CHANNEL === "all" ? ["1", "0"] : [CHANNEL];
  const types = TYPE === "all" ? ["2", "1"] : [TYPE];
  let written = 0;

  for (const ch of channels) {
    for (const ty of types) {
      try {
        const content = scrapeChannel(ch, ty);
        if (!content) continue;

        const filename = `番茄${channelLabel(ch)}${typeLabel(ty)}_全题材_${localDateStamp()}.md`;
        fs.mkdirSync(OUTDIR, { recursive: true });
        const filepath = path.join(OUTDIR, filename);
        fs.writeFileSync(filepath, content, "utf-8");
        written++;
        console.log(`  ✓ 已保存: ${filepath}`);
      } catch (chErr) {
        console.error(
          `[fanqie] ${channelLabel(ch)}${typeLabel(ty)} 采集失败，跳过: ${chErr && chErr.message ? chErr.message : chErr}`
        );
      }
    }
  }
  return written;
}

if (require.main === module) {
  runCli(main, "番茄采集");
}
