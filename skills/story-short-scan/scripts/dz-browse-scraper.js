#!/usr/bin/env node
/**
 * 点众阅读短篇采集脚本
 *
 * 配合 browser-cdp skill 使用。先启动 Chrome CDP 环境，再运行本脚本。
 * 采集策略：以 /book/{id} 链接为骨架，按 bookId 聚合每本书的多个 anchor
 * （封面/书名+评分/简介各一个），从中解出书名、评分、简介、作品页，再从卡片
 * 容器文本里解出 作者·标签·状态·字数 与最新章节。避免纯 innerText 行序解析把
 * UI 文字或简介误当书名。
 * 输出 Markdown 格式。
 *
 * 用法：
 *   node dz-browse-scraper.js --channel male              # 男频
 *   node dz-browse-scraper.js --channel female             # 女频
 *   node dz-browse-scraper.js --channel all                # 全部
 *
 * 前置：
 *   node {SKILL_DIR}/browser-cdp/scripts/setup-cdp-chrome.js 9222
 */

const fs = require("fs");
const path = require("path");
const { ab, sleep, evalJSONBase64, safeStr, scrollLoad, getArg, localDateStamp, runCli } = require("./cdp-utils");

const CHANNELS = [
  { id: "male", label: "男频", tab: "男频", url: "https://www.ishugui.com/browse" },
  { id: "female", label: "女频", tab: "女频", url: "https://www.ishugui.com/browse/on3" },
];

// ---------------------------------------------------------------------------
// 页面操作
// ---------------------------------------------------------------------------

/** 连通性 + 页面就绪自检 */
function probePage(port) {
  return evalJSONBase64(
    port,
    "JSON.stringify({host:location.host,len:(document.body&&document.body.innerText||'').length})"
  );
}

/** 点击指定文本的 tab */
function clickTab(port, text) {
  const js =
    "JSON.stringify((function(){" +
    "var all=document.querySelectorAll('div,span,a,button,li');" +
    "var el=Array.from(all).find(function(e){return (e.textContent||'').trim()===" + safeStr(text) + "});" +
    "if(el){el.click();return true}return false" +
    "})())";
  return evalJSONBase64(port, js);
}

/**
 * 以 /book/{id} 链接为骨架聚合每本书的字段。
 * 书名取自“书名+评分”anchor（去掉尾部 X.X分），简介取自最长 anchor，
 * 作者/标签/状态/字数从卡片容器文本里正则提取。
 */
function buildStoriesJS() {
  return `JSON.stringify((function(){
    var anchors=Array.from(document.querySelectorAll('a')).filter(function(a){
      return /\\/book\\/[0-9]+/.test(a.getAttribute('href')||'');
    });
    var byId={};var order=[];
    anchors.forEach(function(a){
      var m=(a.getAttribute('href')||'').match(/\\/book\\/([0-9]+)/);if(!m)return;
      var id=m[1];var txt=(a.innerText||a.textContent||'').replace(/\\s+/g,' ').trim();
      if(!byId[id]){byId[id]={id:id,texts:[],node:a};order.push(id);}
      if(txt)byId[id].texts.push(txt);
    });
    var out=[];
    order.forEach(function(id){
      var g=byId[id];
      var title='',score='';
      for(var i=0;i<g.texts.length;i++){
        var tm=g.texts[i].match(/^(.+?)\\s*([0-9]+(?:\\.[0-9]+)?)分$/);
        if(tm){title=tm[1].trim();score=tm[2]+'分';break;}
      }
      if(!title){
        var cand=g.texts.filter(Boolean).slice().sort(function(a,b){return a.length-b.length;});
        title=cand.length?cand[0]:'';
      }
      // 简介：最长的、不是“书名+评分”的 anchor 文本
      var desc='';
      g.texts.forEach(function(t){ if(/分$/.test(t))return; if(t.length>desc.length)desc=t; });
      // 卡片容器：从任一 anchor 向上找到含“字”的祖先
      var el=g.node;
      for(var j=0;j<6;j++){ if(el.parentElement){el=el.parentElement; if((el.innerText||'').indexOf('字')>-1)break;} }
      var card=(el.innerText||'').replace(/\\s+/g,' ');
      var tail=(desc&&card.indexOf(desc)>-1)?card.slice(card.indexOf(desc)+desc.length):card;
      var meta=tail.match(/([^·]{1,20}?)\\s*·\\s*([^·]{1,20}?)\\s*·\\s*(完结|完本|连载)\\s*·\\s*([0-9]+)\\s*字/);
      var author=meta?meta[1].trim():'';
      var tag=meta?meta[2].trim():'';
      var status=meta?meta[3]:'';
      var words=meta?meta[4]+'字':'';
      var um=card.match(/最新章节[:：\\s]*([^·]{1,40})/);
      var update=um?um[1].trim():'';
      out.push({rank:out.length+1,bookId:id,title:title,score:score,author:author,tag:tag,status:status,words:words,update:update,desc:desc.slice(0,200),url:'https://www.ishugui.com/book/'+id});
    });
    return out;
  })())`;
}

function extractStories(port) {
  const list = evalJSONBase64(port, buildStoriesJS());
  return Array.isArray(list) ? list : [];
}

// ---------------------------------------------------------------------------
// 主流程
// ---------------------------------------------------------------------------

const args = process.argv.slice(2);
const PORT = parseInt(getArg(args, "--port") || "9222", 10);
const OUTDIR = getArg(args, "--outdir") || ".";
const CHANNEL = getArg(args, "--channel") || "male";

function scrapeChannel(port, channelId) {
  const ch = CHANNELS.find((c) => c.id === channelId);
  if (!ch) return null;

  console.log(`\n→ 采集 点众${ch.label}短篇...`);

  let stories;
  try {
    ab(port, "open", ch.url);
    sleep(3000);

    // 连通性自检：CDP 未起/被重定向时给可操作报错，而非静默产空
    const probe = probePage(port);
    if (!probe) {
      console.error(
        `  ✗ CDP 无响应。请确认已用 browser-cdp 启动 Chrome（端口 ${port}），且 agent-browser 可用。`
      );
      return null;
    }
    if (probe.host && probe.host.indexOf("ishugui") === -1) {
      console.error(`  ✗ 当前页面非点众（host=${probe.host}），可能被重定向，已跳过。`);
      return null;
    }

    // 切换频道（female 已有独立 URL，tab 失败不致命）
    try {
      if (clickTab(port, ch.tab)) {
        console.log(`  ✓ 切换到${ch.tab}`);
        sleep(2000);
      }
    } catch (tabErr) {
      console.error(`[dz] ${ch.label} tab切换出错，继续采集: ${tabErr.message}`);
    }

    scrollLoad(port, 8);
    sleep(1000);

    stories = extractStories(port);
  } catch (err) {
    console.error(`[dz] ${ch.label} 页面加载或提取出错: ${err.message}`);
    return null;
  }

  if (!stories.length) {
    console.error(
      `[dz] 采集失败：未解析到书目（页面结构可能变动或未加载）。请人工打开 ${ch.url} 确认页面正常。`
    );
    return null;
  }

  // 质量门：书名命中率是点众采集成败的核心信号
  const titled = stories.filter((s) => s.title).length;
  const ratio = titled / stories.length;
  const quality = ratio < 0.5 ? "[书名解析异常]" : "[OK]";
  console.log(`  ✓ 提取 ${stories.length} 条（书名 ${titled}/${stories.length}）`);
  if (ratio < 0.5) {
    console.error(`  ⚠ 书名解析率偏低（${titled}/${stories.length}），结果质量已标注。`);
  }

  const now = new Date().toISOString();
  const lines = [
    `# 点众 · ${ch.label}短篇`,
    "",
    `- 来源：${ch.url}`,
    `- 抓取时间：${now}`,
    `- 条目数：${stories.length}`,
    `- 书名解析：${titled} / ${stories.length}`,
    `- 数据质量：${quality}`,
    "",
    "---",
    "",
  ];

  stories.forEach((s, i) => {
    try {
      lines.push(`### #${i + 1} ${s.title || "（书名待解析）"}`);
      const meta = [s.author, s.tag, s.status, s.words, s.score].filter(Boolean).join(" · ");
      if (meta) lines.push(`*${meta}*`);
      if (s.update) lines.push(`**最新：** ${s.update}`);
      if (s.url) lines.push(`[作品页](${s.url})`);
      if (s.desc) {
        lines.push("");
        lines.push(`> ${s.desc.substring(0, 150)}${s.desc.length > 150 ? "..." : ""}`);
      }
      lines.push("", "---", "");
    } catch (storyErr) {
      console.error(`[dz] ${ch.label} 第${i + 1}条处理出错: ${storyErr.message}`);
      lines.push("", "---", "");
    }
  });

  return lines.join("\n");
}

function main() {
  const channels = CHANNEL === "all" ? CHANNELS.map((c) => c.id) : [CHANNEL];
  let written = 0;

  for (const ch of channels) {
    const content = scrapeChannel(PORT, ch);
    if (!content) continue;

    const chInfo = CHANNELS.find((c) => c.id === ch);
    const filename = `点众${chInfo.label}短篇_${localDateStamp()}.md`;
    fs.mkdirSync(OUTDIR, { recursive: true });
    const filepath = path.join(OUTDIR, filename);
    fs.writeFileSync(filepath, content, "utf-8");
    written++;
    console.log(`  ✓ 已保存: ${filepath}`);
  }
  return written;
}

if (require.main === module) {
  runCli(main, "点众采集");
}
