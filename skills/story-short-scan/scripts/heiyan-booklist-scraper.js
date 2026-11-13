#!/usr/bin/env node
/**
 * 黑岩短篇书库列表采集脚本
 *
 * ⚠️ 前置条件（必须）：
 *   1. 启动 Chrome CDP 环境
 *   2. 在 Chrome 中手动登录 https://manage.zhangwenpindu.cn
 *      登录后会生成 Admin-Token cookie，脚本需要它调用后端 API
 *      未登录 → 脚本报错「未检测到 Admin-Token」
 *
 * 采集策略：从 Cookie 提取 Bearer token，调用 ms.zhangwenpindu.cn 后端 API
 * 获取结构化 JSON 数据（书名、作者、字数、分类、标签等）。
 *
 * 用法：
 *   node heiyan-booklist-scraper.js --pages 5              # 采集前5页（每页20条）
 *   node heiyan-booklist-scraper.js --pages 3 --channel male   # 仅男频
 *   node heiyan-booklist-scraper.js --pages 2 --detail         # 含逐本详情（标签等）
 */

const fs = require("fs");
const path = require("path");
const { ab, sleep, evalJSON, safeStr, getArg, localDateStamp, runCli } = require("./cdp-utils");

const BOOKLIST_URL = "https://manage.zhangwenpindu.cn/books/booklist";
const API_BASE = "https://ms.zhangwenpindu.cn";
const PAGE_SIZE = 20;

// ---------------------------------------------------------------------------
// API 调用
// ---------------------------------------------------------------------------

/** 连通性自检：区分 CDP 未连 vs 已连但未登录 */
function probePage(port) {
  return evalJSON(port, "JSON.stringify({host:location.host})");
}

/** 从 Cookie 中提取 Admin-Token */
function getToken(port) {
  const js =
    "JSON.stringify((()=>{" +
    "var m=document.cookie.match(/Admin-Token=([^;]+)/);" +
    "return m?m[1]:''" +
    "})())";
  return evalJSON(port, js) || "";
}

/** 调用后端 API 获取书籍列表 */
function fetchBookList(port, token, pageNum, lang = "zh_TW") {
  const t = safeStr(token);
  const js =
    "fetch(" + safeStr(API_BASE + "/manage/book/list") + "," +
    "{method:'POST'," +
    "headers:{" +
    "'Content-Type':'application/x-www-form-urlencoded'," +
    "'Authorization':'Bearer '+" + t +
    "}," +
    "body:new URLSearchParams({pageNum:" + safeStr(pageNum) + ",pageSize:" + safeStr(PAGE_SIZE) + ",language:" + safeStr(lang) + "})" +
    "}).then(function(r){return r.json()})";
  return evalJSON(port, js);
}

/** 调用后端 API 获取书籍详情（标签等） */
function fetchBookDetail(port, token, bookId) {
  const t = safeStr(token);
  const js =
    "fetch(" + safeStr(API_BASE + "/manage/book/" + encodeURIComponent(bookId)) + "," +
    "{headers:{'Authorization':'Bearer '+" + t + "}}" +
    ").then(function(r){return r.json()})";
  return evalJSON(port, js);
}

// ---------------------------------------------------------------------------
// 主流程
// ---------------------------------------------------------------------------

const args = process.argv.slice(2);
const PORT = parseInt(getArg(args, "--port") || "9222", 10);
const OUTDIR = getArg(args, "--outdir") || ".";
const PAGES = parseInt(getArg(args, "--pages") || "5", 10);
const CHANNEL = getArg(args, "--channel") || "all";
const DETAIL = args.includes("--detail");

/**
 * 字数格式化：手写千分位，不能用 toLocaleString()。
 * 后者按宿主 ICU locale 取分隔符，de_* 会写成「123.456字」（读起来像 123 字），
 * fr_* 用 U+202F、en-IN 会分成「1,23,456」——同一份报告在不同机器上数字不一样。
 * 兼容接口把 words 返回成字符串的情况。
 */
function fmtWords(words) {
  const n =
    typeof words === "number"
      ? Math.trunc(words)
      : parseInt(String(words == null ? "" : words).replace(/[^0-9]/g, ""), 10);
  if (!Number.isFinite(n) || n <= 0) return "";
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",") + "字";
}

function outputFilename(channel, date) {
  if (!["all", "male", "female"].includes(channel)) {
    throw new Error(`未知 --channel: ${channel}（支持 male/female/all）`);
  }
  return `黑岩书库列表_${channel}_${date}.md`;
}

/**
 * 文件头「数据质量」：书库没有热度字段，列表模式只有书单；--detail 按详情取到几成定级。
 * 取值要在 aggregate-rank.js 的 QUALITY_WORDS 里，聚合「采集情况」才会翻成白话。
 */
function dataQuality(books, detail) {
  if (!detail) return "[仅列表-无核心指标]";
  const got = books.filter((b) => b && b.detailOk).length;
  if (got === books.length) return "[OK]";
  return got / books.length < 0.5 ? "[详情解析异常/登录态缺失]" : "[部分详情缺失]";
}

function buildAndSave(allBooks, total, filtered, filepath, detail = DETAIL) {
  const now = new Date().toISOString();
  const maleBooks = filtered.filter((b) => b.classifyStr === "男频");
  const femaleBooks = filtered.filter((b) => b.classifyStr === "女频");
  const otherBooks = filtered.filter(
    (b) => b.classifyStr !== "男频" && b.classifyStr !== "女频"
  );

  const groups = [
    { label: "男频", books: maleBooks },
    { label: "女频", books: femaleBooks },
  ];
  if (otherBooks.length) {
    groups.push({ label: "其他", books: otherBooks });
  }

  const lines = [
    `# 黑岩 · 书库列表`,
    "",
    `- 来源：${BOOKLIST_URL}`,
    `- 抓取时间：${now}`,
    `- 总条目：${total}`,
    `- 已采集：${filtered.length} 条（${Math.ceil(allBooks.length / PAGE_SIZE)} 页）`,
    detail ? "- 含详情（标签、简介）" : "- 列表模式（加 --detail 获取标签和简介）",
    `- 数据质量：${dataQuality(filtered, detail)}`,
    "",
    "---",
    "",
  ];

  for (const g of groups) {
    if (!g.books.length) continue;
    lines.push(`## ${g.label}短篇 — ${g.books.length} 本`, "");

    for (let i = 0; i < g.books.length; i++) {
      try {
        const b = g.books[i];
        lines.push(`### #${i + 1} ${b.name}`);
        // 聚合按位置认「作者 · 题材」：缺作者时用占位，否则题材会被当成作者
        const meta = [
          b.userName || "佚名",
          // 分别入数组再拼：预先 classifyStr + "/" + typeDesc 会把缺字段拼成
          // 「undefined/undefined」这种真值字符串，filter(Boolean) 拦不住，直接写进报告
          [b.classifyStr, b.typeDesc].filter(Boolean).join("/"),
          fmtWords(b.words),
          b.price ? b.price + "钻" : "",
          b.open ? "公开" : "未公开",
        ].filter(Boolean).join(" · ");
        if (meta) lines.push(`*${meta}*`);

        if (b.createTime) lines.push(`**创建：** ${b.createTime}`);
        if (b.updateTime) lines.push(`**更新：** ${b.updateTime}`);

        if (b.tags && b.tags.length) {
          lines.push(`**标签：** ${b.tags.join("、")}`);
        }

        if (b.description) {
          lines.push("");
          lines.push(`> ${b.description.substring(0, 200)}${b.description.length > 200 ? "..." : ""}`);
        }

        lines.push("");
      } catch (bookErr) {
        console.error(`[heiyan] ${g.label} 第${i + 1}条处理出错: ${bookErr.message}`);
        lines.push("");
      }
    }

    lines.push("---", "");
  }

  fs.mkdirSync(OUTDIR, { recursive: true });
  fs.writeFileSync(filepath, lines.join("\n"), "utf-8");
  console.log(`  ✓ 已保存: ${filepath}`);
}

function main() {
  console.log("\n→ 采集 黑岩书库列表（API 模式）...");
  console.log(`  计划采集: ${PAGES} 页（每页 ${PAGE_SIZE} 条）`);

  const filename = outputFilename(CHANNEL, localDateStamp());
  const filepath = path.join(OUTDIR, filename);

  // 先导航到管理后台获取 token
  let token;
  try {
    ab(PORT, "open", BOOKLIST_URL);
    sleep(3000);

    // 连通性自检：把"CDP 没起来"和"没登录"分开，避免误导用户去登录
    const probe = probePage(PORT);
    if (!probe) {
      console.error(
        `  ✗ CDP 无响应。请确认已用 browser-cdp 启动 Chrome（端口 ${PORT}），且 agent-browser 可用。`
      );
      return 0;
    }

    token = getToken(PORT);
  } catch (err) {
    console.error(`[heiyan] 页面加载或 token 提取出错: ${err.message}`);
    return 0;
  }

  if (!token) {
    console.log("  ✗ 未检测到 Admin-Token（CDP 已连，但当前未登录）");
    console.log("  → 请先在 Chrome 中打开 https://manage.zhangwenpindu.cn 并登录");
    console.log("  → 登录后重新运行本脚本");
    return 0;
  }
  console.log("  ✓ 获取到认证 token");

  // 分页采集（默认接口语种 zh_TW；若首页正常返回但为空，自动回退试一次 zh_CN）
  const allBooks = [];
  let total = 0;
  let activeLang = "zh_TW";

  for (let p = 1; p <= PAGES; p++) {
    try {
      sleep(800);
      let resp = fetchBookList(PORT, token, p, activeLang);
      if (
        p === 1 &&
        resp &&
        resp.code !== 401 &&
        (!resp.data || !resp.data.rows || !resp.data.rows.length) &&
        (resp.code == null || resp.code === 0 || resp.code === 200)
      ) {
        activeLang = "zh_CN";
        resp = fetchBookList(PORT, token, 1, activeLang);
      }

      // 区分失败：接口无响应(超时/CDP) / 401 未授权
      if (!resp) {
        console.error(`  ✗ 第${p}页接口无响应（请求超时或 CDP 中断），已停止。`);
        break;
      }
      if (resp.code === 401) {
        console.log(`  ⚠ 第${p}页认证失败（401），请重新登录后重试。`);
        break;
      }

      const rows = resp?.data?.rows;
      if (!rows || !rows.length) {
        // 仅在无数据时才用 code 区分"服务端错误"与"正常到底"，避免把
        // 携带非常规成功 code 的有效响应误判为错误（成功带 rows 一律放行）
        if (resp.code != null && resp.code !== 0 && resp.code !== 200) {
          console.error(`  ✗ 第${p}页接口返回错误 code=${resp.code} ${resp.msg || ""}，已停止。`);
        } else {
          console.log(`  第${p}页无数据，停止`);
        }
        break;
      }

      if (p === 1) {
        total = parseInt(resp.data.total) || 0;
        console.log(`  总条目: ${total}`);
      }

      allBooks.push(...rows);
      console.log(`  第${p}页: ${rows.length} 条 (累计 ${allBooks.length})`);
    } catch (pageErr) {
      console.error(`[heiyan] 第${p}页采集出错，跳过: ${pageErr.message}`);
      if (allBooks.length > 0) {
        console.log(`  已采集 ${allBooks.length} 条，继续处理已有数据`);
      }
      break;
    }
  }

  if (!allBooks.length) {
    console.error("[heiyan] 采集失败：未取到任何书目。多为登录态过期或接口变动，请重新登录后重试。");
    return 0;
  }

  // 质量门：核心字段命中率。API 改字段名时会整片 undefined，必须拦截而非静默写盘。
  // classifyStr 同样要查：它决定男频/女频分组和 --channel 筛选，字段一改全部书都掉进
  // 「其他」、--channel male 直接筛成 0 条，写出一份「已采集：0 条」的假成功报告。
  const CORE_FIELDS = [
    { key: "name", label: "书名" },
    { key: "classifyStr", label: "频道(classifyStr)" },
  ];
  for (const f of CORE_FIELDS) {
    const hit = allBooks.filter((b) => b && b[f.key]).length;
    if (hit / allBooks.length < 0.5) {
      console.error(
        `[heiyan] 采集失败：${allBooks.length} 条里仅 ${hit} 条有${f.label}，疑似接口字段变动，已放弃写盘。`
      );
      return 0;
    }
  }

  // 频道筛选
  let filtered = allBooks;
  if (CHANNEL === "male" || CHANNEL === "female") {
    const want = CHANNEL === "male" ? "男频" : "女频";
    filtered = allBooks.filter((b) => b.classifyStr === want);
    if (!filtered.length) {
      // 筛成 0 条不能算成功：把实际 classifyStr 分布打出来，区分「接口字段变了」
      // 和「这个频道确实没作品」，而不是写一份看不出差别的空报告
      const seen = {};
      for (const b of allBooks) {
        const k = b && b.classifyStr ? b.classifyStr : "(空)";
        seen[k] = (seen[k] || 0) + 1;
      }
      const dist = Object.keys(seen).map((k) => `${k}×${seen[k]}`).join("、");
      console.error(
        `[heiyan] 采集失败：--channel ${CHANNEL} 筛选后 0 条（${allBooks.length} 条的 classifyStr 取值：${dist}），已放弃写盘。`
      );
      console.error(`  → 若确实没有${want}作品，去掉 --channel 重跑即可拿到全部书目。`);
      return 0;
    }
  }

  // 可选：逐本获取详情（标签等）
  if (DETAIL && filtered.length) {
    console.log(`  获取 ${filtered.length} 本详情...`);
    for (let i = 0; i < filtered.length; i++) {
      try {
        sleep(500);
        const detail = fetchBookDetail(PORT, token, filtered[i].id);
        if (detail?.data) {
          filtered[i].tags = detail.data.tags || [];
          filtered[i].description = detail.data.description || "";
          filtered[i].chapterCount = detail.data.chapterCount || 0;
          filtered[i].detailOk = true;
        }
        if ((i + 1) % 10 === 0) {
          console.log(`    已获取 ${i + 1}/${filtered.length}`);
        }
      } catch (detailErr) {
        console.error(`[heiyan] 第${i + 1}本详情获取出错，跳过: ${detailErr.message}`);
      }
    }
    console.log("  ✓ 详情获取完成");
  }

  buildAndSave(allBooks, total, filtered, filepath);
  return 1;
}

if (require.main === module) {
  runCli(main, "黑岩采集");
}

module.exports = {
  probePage,
  getToken,
  fetchBookList,
  fetchBookDetail,
  fmtWords,
  outputFilename,
  dataQuality,
  buildAndSave,
};
