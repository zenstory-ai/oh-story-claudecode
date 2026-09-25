#!/usr/bin/env node
/**
 * 晋江文学城排行榜采集脚本
 *
 * 配合 browser-cdp skill 使用。先启动 Chrome CDP 环境，再运行本脚本。
 * 采集策略：
 *   1) topten.php 列表页（纯文本，频道名直接出现，书名/作者交替行）解出频道分组。
 *   2) 从书名 anchor 取 novelid，逐本进 onebook.php 详情页补采核心指标
 *      （收藏数/营养液/积分/字数/状态），满足规范对晋江的硬性要求。
 * 晋江页面为 gb18030 编码：详情页用 fetch+arrayBuffer+TextDecoder('gb18030') 解码
 *   （同步 XHR 的 responseText 会按 UTF-8 解码导致中文乱码）。
 * 详情采集默认开启但有上限（每频道前 N + 总量上限），用 --list-only 可只采列表。
 *
 * 用法：
 *   node jjwxc-rank-scraper.js --type 12                  # 收入金榜（默认含详情）
 *   node jjwxc-rank-scraper.js --type 12 --top 15         # 每频道补采前 15 本
 *   node jjwxc-rank-scraper.js --type 12 --detail-limit 60 # 详情总量上限 60
 *   node jjwxc-rank-scraper.js --type 12 --list-only      # 只采列表（快，无核心指标）
 *   node jjwxc-rank-scraper.js --type all                 # 全部榜单
 *
 * 前置：
 *   node {SKILL_DIR}/browser-cdp/scripts/setup-cdp-chrome.js 9222
 */

const fs = require("fs");
const path = require("path");
const { ab, sleep, evalJSONBase64, getArg, localDateStamp, runCli } = require("./cdp-utils");

const BASE_URL = "https://www.jjwxc.net/topten.php";

const RANK_TYPES = [
  { id: "12", label: "收入金榜" },
  { id: "7", label: "月榜" },
  { id: "8", label: "季度榜" },
  { id: "14", label: "完结金榜" },
  { id: "15", label: "新手金榜" },
  { id: "17", label: "千字金榜" },
];

// 详情请求批大小（async fetch 并发，整批控制在 ab() 20s 超时内）
const DETAIL_CHUNK = 6;

/** 连通性 + 页面就绪自检 */
function probePage(port) {
  return evalJSONBase64(
    port,
    "JSON.stringify({host:location.host,len:(document.body&&document.body.innerText||'').length})"
  );
}

// ---------------------------------------------------------------------------
// 列表页提取
// ---------------------------------------------------------------------------

/**
 * 提取晋江榜单数据（频道分组 + 书名/作者交替），并从书名 anchor 附上 novelid。
 */
function extractRankData(port) {
  const js =
    "JSON.stringify((function(){" +
    "var result={channels:[]};" +
    "var text=document.body.innerText||'';" +
    "var lines=text.split(/\\n/).map(function(l){return l.trim()}).filter(Boolean);" +
    // 书名 anchor → novelid（排除霸王票"X向《书名》投了Y"这类记录）
    "var idMap={};" +
    "Array.from(document.querySelectorAll('a')).forEach(function(a){" +
    "  var hm=(a.getAttribute('href')||'').match(/novelid=([0-9]+)/);if(!hm)return;" +
    "  var t=(a.innerText||a.textContent||'').trim();" +
    "  if(!t||t.indexOf('向《')>-1||t.indexOf('投')>-1||t.length>30)return;" +
    "  if(!idMap[t])idMap[t]=hm[1];" +
    "});" +
    "var channels=['古代言情','现代言情','古代穿越','现代都市纯爱','现代幻想纯爱','古代纯爱','衍生纯爱','幻想现言','奇幻言情','未来游戏悬疑','百合','无CP','二次元言情','衍生言情','衍生无cp','未来幻想纯爱','原创轻小说','多元'];" +
    "var channelSet={};channels.forEach(function(c){channelSet[c]=true});" +
    "var curChannel='';" +
    "var channelBooks={};" +
    "var expectTitle=true;" +
    "var pendingTitle='';" +
    "for(var i=0;i<lines.length;i++){" +
    "  var line=lines[i];" +
    "  if(/上榜天数记录|榜单说明/.test(line)){break}" +
    "  if(/^(免费强推|vip强推|新晋作者|月榜|季榜|半年榜|长生殿|总分榜|字数榜|收入金榜|霸王票|霸王总榜|勤奋指数|完结金榜|新手金榜|栽培月榜|驻站|完结高分|千字金榜|完结全订榜)$/.test(line)){continue}" +
    "  if(line.length>30&&line.indexOf('·')>0)continue;" +
    "  if(channelSet[line]){" +
    "    if(curChannel&&channelBooks[curChannel])channelBooks[curChannel]._finished=true;" +
    "    curChannel=line;" +
    "    if(!channelBooks[curChannel])channelBooks[curChannel]={books:[]};" +
    "    expectTitle=true;pendingTitle='';continue" +
    "  }" +
    "  if(!curChannel)continue;" +
    "  if(expectTitle){" +
    "    pendingTitle=line;expectTitle=false" +
    "  }else{" +
    "    if(pendingTitle){" +
    "      channelBooks[curChannel].books.push({title:pendingTitle,author:line,novelid:idMap[pendingTitle]||''})" +
    "    }" +
    "    expectTitle=true;pendingTitle=''" +
    "  }" +
    "}" +
    "for(var name in channelBooks){" +
    "  if(channelBooks[name].books.length>0){" +
    "    result.channels.push({name:name,books:channelBooks[name].books})" +
    "  }" +
    "}" +
    "return result" +
    "})())";
  return evalJSONBase64(port, js);
}

// ---------------------------------------------------------------------------
// 详情页提取（gb18030 + itemprop 微数据）
// ---------------------------------------------------------------------------

/** 构建：一批 novelid 的详情解码 JS（async fetch + TextDecoder，返回 JSON 字符串） */
function buildDetailJS(ids) {
  return `Promise.all(${JSON.stringify(ids)}.map(function(id){
    return fetch('/onebook.php?novelid='+id)
      .then(function(r){return r.arrayBuffer()})
      .then(function(b){
        var h=new TextDecoder('gb18030').decode(new Uint8Array(b));
        function prop(n){var m=h.match(new RegExp('itemprop="'+n+'"[^>]*>([^<]*)<'));return m?m[1].trim():'';}
        var status=(h.match(/itemprop="updataStatus"[^>]*>\\s*([^<\\s]{1,6})/)||[,''])[1]
                 ||(h.match(/(连载中|已完结|完结)/)||[,''])[1]||'';
        return {id:id,collect:prop('collectedCount'),nutrition:prop('nutritionCount'),
                score:prop('scoreCount'),review:prop('reviewCount'),words:prop('wordCount'),status:status};
      })
      .catch(function(e){return {id:id,err:String(e&&e.message||e)}});
  })).then(function(arr){var map={};arr.forEach(function(o){map[o.id]=o});return JSON.stringify(map);})`;
}

/**
 * 分批解码详情，合并结果。
 * 每批单独 try/catch：整批的并发 fetch 贴着 ab() 的 20s 超时线，一次瞬时超时（或
 * 返回非 JSON）只该丢这 6 本，不能连坐后面几十本，更不能把已解析好的列表带走。
 */
function fetchDetails(port, ids) {
  const map = {};
  let failedChunks = 0;
  for (let i = 0; i < ids.length; i += DETAIL_CHUNK) {
    const chunk = ids.slice(i, i + DETAIL_CHUNK);
    try {
      const part = evalJSONBase64(port, buildDetailJS(chunk)) || {};
      Object.assign(map, part);
    } catch (chunkErr) {
      failedChunks++;
      console.error(
        `  ⚠ 详情批次 ${Math.floor(i / DETAIL_CHUNK) + 1}（${chunk.length} 本）获取失败，跳过: ${chunkErr.message}`
      );
    }
    sleep(400);
  }
  if (failedChunks > 0) {
    console.error(`  ⚠ 共 ${failedChunks} 个详情批次失败，这部分书只有列表数据。`);
  }
  return { map, failedChunks };
}

// ---------------------------------------------------------------------------
// 格式化
// ---------------------------------------------------------------------------

function fmtWan(s, unit) {
  if (s == null || s === "") return "";
  const n = parseInt(String(s).replace(/[^0-9]/g, ""), 10);
  if (isNaN(n)) return "";
  if (n >= 10000) return (n / 10000).toFixed(1) + "万" + (unit || "");
  return n + (unit || "");
}

// ---------------------------------------------------------------------------
// 主流程
// ---------------------------------------------------------------------------

const args = process.argv.slice(2);
const PORT = parseInt(getArg(args, "--port") || "9222", 10);
const OUTDIR = getArg(args, "--outdir") || ".";
const RANKTYPE = getArg(args, "--type") || "12";
const CHANNEL = getArg(args, "--channel") || "0";
const TOP = parseInt(getArg(args, "--top") || "10", 10);
const DETAIL_LIMIT = parseInt(getArg(args, "--detail-limit") || "100", 10);
const LIST_ONLY = args.includes("--list-only");

function scrapeRank(port, rankTypeId, channelId) {
  const rt = RANK_TYPES.find((r) => r.id === rankTypeId);
  if (!rt) {
    console.log(`  ⚠ 未知榜单类型: ${rankTypeId}`);
    return null;
  }

  const url = `${BASE_URL}?orderstr=${rankTypeId}&t=${channelId}`;
  const chLabel = channelId === "0" ? "全站" : `频道${channelId}`;
  console.log(`\n→ 采集 晋江${rt.label}（${chLabel}）...`);
  console.log(`  URL: ${url}`);

  let data;
  try {
    ab(port, "open", url);
    sleep(4000);

    // 连通性自检：CDP 未起/被重定向时给可操作报错，而非误报"结构已变"
    const probe = probePage(port);
    if (!probe) {
      console.error(
        `  ✗ CDP 无响应。请确认已用 browser-cdp 启动 Chrome（端口 ${port}），且 agent-browser 可用。`
      );
      return null;
    }
    if (probe.host && probe.host.indexOf("jjwxc") === -1) {
      console.error(`  ✗ 当前页面非晋江（host=${probe.host}），可能被重定向，已跳过。`);
      return null;
    }

    data = extractRankData(port);
    if (!data?.channels?.length) {
      console.error(`[jjwxc] 采集失败：未解析到榜单（页面结构可能变动或未加载）。请人工打开 ${url} 确认。`);
      return null;
    }
  } catch (err) {
    console.error(`[jjwxc] ${rt.label} 页面加载或提取出错: ${err.message}`);
    return null;
  }

  let totalBooks = 0;
  data.channels.forEach((ch) => {
    totalBooks += ch.books.length;
    const authors = new Set(ch.books.map((b) => b.author));
    if (ch.books.length >= 5 && authors.size / ch.books.length < 0.2) {
      console.log(`  ⚠ ${ch.name}：${ch.books.length} 本只有 ${authors.size} 个唯一作者，可能提取有误`);
    }
  });
  console.log(`  ✓ 列表：${data.channels.length} 个频道，共 ${totalBooks} 本`);

  // 选取每频道前 TOP 本（有 novelid 的）补采详情，受 DETAIL_LIMIT 总量约束
  let detailMap = {};
  let detailPlanned = 0;
  let detailOk = 0;
  let detailFailedChunks = 0;
  if (!LIST_ONLY) {
    const picked = [];
    for (const ch of data.channels) {
      let n = 0;
      for (const b of ch.books) {
        if (picked.length >= DETAIL_LIMIT) break;
        if (n >= TOP) break;
        if (b.novelid) { picked.push(b.novelid); n++; }
      }
      if (picked.length >= DETAIL_LIMIT) break;
    }
    detailPlanned = picked.length;
    if (picked.length) {
      console.log(`  → 补采详情 ${picked.length} 本（每频道前 ${TOP}，上限 ${DETAIL_LIMIT}）...`);
      // 详情是列表的增补，不是前提：整段失败也要保住已解析好的列表落盘
      // （下面的质量门会把 detailOk===0 标成 [详情解析异常/登录态缺失]）
      try {
        const detailResult = fetchDetails(port, picked);
        detailMap = detailResult.map;
        detailFailedChunks = detailResult.failedChunks;
      } catch (detailErr) {
        detailMap = {};
        detailFailedChunks = Math.max(1, Math.ceil(picked.length / DETAIL_CHUNK));
        console.error(`  ⚠ 详情补采整体失败，仅保留列表数据: ${detailErr.message}`);
      }
      detailOk = Object.values(detailMap).filter((d) => d && d.collect).length;
      console.log(`  ✓ 详情命中收藏数 ${detailOk}/${picked.length}`);
    }
  }

  // 质量状态：详情开启时，收藏数命中率是核心信号
  let quality = "[OK]";
  const detailPartial =
    !LIST_ONLY &&
    detailPlanned > 0 &&
    (detailFailedChunks > 0 || detailOk < detailPlanned);
  if (!LIST_ONLY && detailPlanned > 0 && detailOk === 0) {
    quality = "[详情解析异常/登录态缺失]";
    console.error(`  ⚠ 详情全部无收藏数：可能页面结构变动或需登录，已在文件头标注。`);
  } else if (detailPartial) {
    quality = "[部分详情缺失]";
    console.error(`  ⚠ 详情仅命中 ${detailOk}/${detailPlanned}，已按部分结果标注。`);
  } else if (LIST_ONLY) {
    quality = "[仅列表-无核心指标]";
  }

  const now = new Date().toISOString();
  const lines = [
    `# 晋江 · ${rt.label}`,
    "",
    `- 来源：${url}`,
    `- 抓取时间：${now}`,
    `- 频道数：${data.channels.length}`,
    `- 总条目数：${totalBooks}`,
    `- 详情采集：${detailOk} / ${detailPlanned}（每频道前 ${TOP}，上限 ${DETAIL_LIMIT}）`,
    `- 数据质量：${quality}`,
    "",
    "---",
    "",
  ];

  for (const ch of data.channels) {
    try {
      lines.push(`## ${ch.name} — ${ch.books.length} 本`, "");
      for (let i = 0; i < ch.books.length; i++) {
        try {
          const b = ch.books[i];
          lines.push(`### #${i + 1} ${b.title}`);
          const d = b.novelid ? detailMap[b.novelid] : null;
          const seg = [b.author || ""];
          if (d) {
            if (d.collect) seg.push("收藏 " + fmtWan(d.collect));
            if (d.nutrition) seg.push("营养液 " + fmtWan(d.nutrition));
            if (d.score) seg.push("积分 " + d.score);
            if (d.words) seg.push("字数 " + fmtWan(d.words, "字"));
            if (d.status) seg.push(d.status);
          }
          const meta = seg.filter(Boolean).join(" · ");
          if (meta) lines.push(`*${meta}*`);
          if (b.novelid) lines.push(`[作品页](https://www.jjwxc.net/onebook.php?novelid=${b.novelid})`);
          lines.push("");
        } catch (bookErr) {
          console.error(`[jjwxc] ${rt.label} ${ch.name} 第${i + 1}条处理出错: ${bookErr.message}`);
          lines.push("");
        }
      }
      lines.push("---", "");
    } catch (chErr) {
      console.error(`[jjwxc] ${rt.label} 频道「${ch.name}」处理出错，跳过: ${chErr.message}`);
    }
  }

  return {
    content: lines.join("\n"),
    partial: detailPartial,
    partialReason: detailPartial
      ? `${rt.label}: detail ${detailOk}/${detailPlanned}, failed chunks ${detailFailedChunks}`
      : "",
  };
}

function main() {
  if (RANKTYPE !== "all" && !RANK_TYPES.some((rank) => rank.id === RANKTYPE)) {
    throw new Error(`未知 --type: ${RANKTYPE}`);
  }
  // 当前脚本只实现全站榜（t=0）；不能把任意数字静默标成“频道 N”。
  // 若后续支持分频道，先从页面提取并维护明确 ID 白名单再开放。
  if (CHANNEL !== "0") {
    throw new Error(`未知 --channel: ${CHANNEL}（当前仅支持 0=全站）`);
  }
  const rankTypes = RANKTYPE === "all" ? RANK_TYPES.map((r) => r.id) : [RANKTYPE];
  const channels = [CHANNEL]; // 晋江频道 ID 需从页面获取，默认全站
  let written = 0;
  let failed = 0;
  let partial = false;
  const partialReasons = [];

  for (const rt of rankTypes) {
    for (const ch of channels) {
      // per-榜单隔离：一个榜单出错不该掐掉 --type all 后面的榜单（与番茄/刺猬猫一致）
      try {
        const result = scrapeRank(PORT, rt, ch);
        if (!result) {
          failed++;
          const rtInfo = RANK_TYPES.find((r) => r.id === rt);
          partialReasons.push(`${rtInfo ? rtInfo.label : rt}: no usable data`);
          continue;
        }
        if (result.partial) {
          partial = true;
          if (result.partialReason) partialReasons.push(result.partialReason);
        }

        const rtInfo = RANK_TYPES.find((r) => r.id === rt);
        const chLabel = ch === "0" ? "全站" : `频道${ch}`;
        const filename = `晋江${rtInfo.label}_${chLabel}_${localDateStamp()}.md`;
        fs.mkdirSync(OUTDIR, { recursive: true });
        const filepath = path.join(OUTDIR, filename);
        fs.writeFileSync(filepath, result.content, "utf-8");
        written++;
        console.log(`  ✓ 已保存: ${filepath}`);
      } catch (rankErr) {
        failed++;
        const rtInfo = RANK_TYPES.find((r) => r.id === rt);
        const message = rankErr && rankErr.message ? rankErr.message : String(rankErr);
        partialReasons.push(`${rtInfo ? rtInfo.label : rt}: ${message}`);
        console.error(
          `[jjwxc] ${rtInfo ? rtInfo.label : rt} 采集失败，跳过: ${message}`
        );
      }
    }
  }
  return {
    planned: rankTypes.length * channels.length,
    written,
    failed,
    partial: partial || failed > 0,
    partialReasons,
  };
}

if (require.main === module) {
  runCli(main, "晋江采集");
}
