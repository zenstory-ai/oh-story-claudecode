#!/usr/bin/env node
"use strict";

const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawn, spawnSync } = require("child_process");

const repoRoot = path.resolve(__dirname, "..");
const longUtilsPath = path.join(
  repoRoot,
  "skills/story-long-scan/scripts/cdp-utils.js"
);

function makeFakeAgentBrowser(tmpDir) {
  const fakeProgram = `#!/usr/bin/env node
const fs = require("fs");
if (process.env.AGENT_BROWSER_CAPTURE) {
  fs.writeFileSync(process.env.AGENT_BROWSER_CAPTURE, JSON.stringify(process.argv.slice(2)));
}
process.stdout.write(process.env.AGENT_BROWSER_STDOUT || "");
if (process.env.AGENT_BROWSER_STDERR) {
  process.stderr.write(process.env.AGENT_BROWSER_STDERR);
}
if (process.env.AGENT_BROWSER_EXIT) {
  process.exit(Number(process.env.AGENT_BROWSER_EXIT));
}
`;
  if (process.platform === "win32") {
    const program = path.join(tmpDir, "fake-agent-browser.js");
    fs.writeFileSync(program, fakeProgram, "utf8");
    // `npm install -g agent-browser` writes an agent-browser.cmd whose `%*` line
    // forwards to the real target (the native .exe, or here the Node wrapper).
    // cdp-utils reads that shim and execs the target directly, so the argv array
    // is passed verbatim instead of collapsing through cmd.exe `%*` or a
    // PowerShell splat.
    fs.writeFileSync(
      path.join(tmpDir, "agent-browser.cmd"),
      `@echo off\r\n"${process.execPath}" "%~dp0fake-agent-browser.js" %*\r\n`,
      "utf8"
    );
    return path.join(tmpDir, "agent-browser.cmd");
  }

  const bin = path.join(tmpDir, "agent-browser");
  fs.writeFileSync(bin, fakeProgram, "utf8");
  fs.chmodSync(bin, 0o755);
  return bin;
}

function withFakeAgentBrowser(testFn) {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "story-scan-runtime-"));
  const oldPath = process.env.PATH;
  const oldCapture = process.env.AGENT_BROWSER_CAPTURE;
  const oldStdout = process.env.AGENT_BROWSER_STDOUT;
  const oldStderr = process.env.AGENT_BROWSER_STDERR;
  const oldExit = process.env.AGENT_BROWSER_EXIT;
  try {
    delete process.env.AGENT_BROWSER_STDERR;
    delete process.env.AGENT_BROWSER_EXIT;
    makeFakeAgentBrowser(tmpDir);
    process.env.PATH = `${tmpDir}${path.delimiter}${oldPath}`;
    testFn(tmpDir);
  } finally {
    process.env.PATH = oldPath;
    if (oldCapture === undefined) delete process.env.AGENT_BROWSER_CAPTURE;
    else process.env.AGENT_BROWSER_CAPTURE = oldCapture;
    if (oldStdout === undefined) delete process.env.AGENT_BROWSER_STDOUT;
    else process.env.AGENT_BROWSER_STDOUT = oldStdout;
    if (oldStderr === undefined) delete process.env.AGENT_BROWSER_STDERR;
    else process.env.AGENT_BROWSER_STDERR = oldStderr;
    if (oldExit === undefined) delete process.env.AGENT_BROWSER_EXIT;
    else process.env.AGENT_BROWSER_EXIT = oldExit;
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
}

function loadFresh(modulePath) {
  delete require.cache[require.resolve(modulePath)];
  return require(modulePath);
}

// ---------------------------------------------------------------------------
// 采集脚本 end-to-end 夹具：一个按 eval 载荷分派响应的 agent-browser 替身，
// 加一个把 sleep/scrollLoad 掉空的预加载，让整条 main() 流程能在毫秒级跑完。
// ---------------------------------------------------------------------------

const SCRIPTED_AGENT_BROWSER = `#!/usr/bin/env node
"use strict";
const argv = process.argv.slice(2);
const evalIdx = argv.indexOf("eval");
const idx = evalIdx >= 0 ? evalIdx : argv.indexOf("open");
function out(value) {
  process.stdout.write(JSON.stringify(JSON.stringify(value)));
  process.exit(0);
}
if (argv[idx] === "open") {
  const url = argv[idx + 1] || "";
  if (process.env.SCAN_FAKE_FAIL_OPEN && url.indexOf(process.env.SCAN_FAKE_FAIL_OPEN) > -1) {
    process.stderr.write("navigate timeout\\n");
    process.exit(3);
  }
  process.exit(0);
}
const js =
  argv[idx + 1] === "-b"
    ? Buffer.from(argv[idx + 2] || "", "base64").toString("utf8")
    : argv[idx + 1] || "";
if (js.indexOf("host:location.host") > -1) {
  out({ host: process.env.SCAN_FAKE_HOST || "www.jjwxc.net", len: 5000 });
}
if (js.indexOf(".qm-switch-tab .item.active") > -1) {
  out({
    path: "/paihang/boy/hot/date/",
    channel: "男生榜",
    rankType: "大热榜",
    period: "日榜",
  });
}
if (js.indexOf("['日榜','月榜']") > -1) {
  out([
    {
      rank: 1,
      title: "七猫甲书",
      author: "七猫作者",
      genre: "玄幻",
      subGenre: "东方玄幻",
      status: "连载中",
      words: "100万字",
      heat: "100万",
      update: "第一章",
      desc: "简介",
    },
  ]);
}
if (js.indexOf("var headers=['点击榜'") > -1) {
  out(JSON.parse(process.env.SCAN_FAKE_CIWEIMAO || "[]"));
}
if (js.indexOf("var byId={}") > -1) {
  out([{ bookId: "1", title: "七猫甲书", url: "https://www.qimao.com/shuku/1/" }]);
}
if (js.indexOf("onebook.php") > -1) {
  // 晋江详情批次：模拟 ab() 的 20s 超时/非 JSON 返回
  if (process.env.SCAN_FAKE_FAIL_DETAIL) {
    process.stderr.write("spawnSync agent-browser ETIMEDOUT\\n");
    process.exit(1);
  }
  if (process.env.SCAN_FAKE_PARTIAL_DETAIL) {
    out({
      1: { id: "1", collect: "12345", words: "300000", status: "连载中" },
      2: { id: "2", err: "detail timeout" },
    });
  }
  out({ 1: { id: "1", collect: "12345", words: "300000", status: "连载中" } });
}
if (js.indexOf("result={channels:[]}") > -1) {
  const books = [{ title: "甲书", author: "作者甲", novelid: "1" }];
  if (process.env.SCAN_FAKE_TWO_BOOKS) {
    books.push({ title: "乙书", author: "作者乙", novelid: "2" });
  }
  out({ channels: [{ name: "古代言情", books }] });
}
if (js.indexOf("qdLibraryPageSnapshot") > -1) {
  // 起点书库列表页：载荷末尾是 (页码))，按页码取 SCAN_FAKE_QD_LIBRARY 里的页面快照
  const page = (js.match(/\\)\\((\\d+)\\)\\)\\s*$/) || [])[1];
  const file = process.env.SCAN_FAKE_QD_LIBRARY;
  const pages = file ? JSON.parse(require("fs").readFileSync(file, "utf8")) : {};
  out(pages[page] || {});
}
if (js.indexOf("blocked") > -1) out({ blocked: false, reason: "" });
if (js.indexOf("book-img-text") > -1) {
  out([
    {
      rank: 1,
      title: "起点甲书",
      url: "https://www.qidian.com/book/1/",
      author: "起作者",
      genre: "玄幻",
      status: "连载中",
      descText: "简介",
      updateText: "",
    },
  ]);
}
out({});
`;

const SLEEP_STUB = `// 预加载：掉空 sleep/scrollLoad，采集脚本的真实等待不必在测试里等
const utils = require(process.env.SCAN_TEST_UTILS);
utils.sleep = () => {};
if (process.env.SCAN_TEST_STUB_SCROLL) utils.scrollLoad = () => {};
`;

/** 在 tmpDir 里铺好 agent-browser 替身（含 Windows 的 .cmd shim）+ sleep 预加载 */
function makeScraperHarness(tmpDir) {
  const program = path.join(tmpDir, "fake-agent-browser.js");
  fs.writeFileSync(program, SCRIPTED_AGENT_BROWSER, "utf8");
  if (process.platform === "win32") {
    fs.writeFileSync(
      path.join(tmpDir, "agent-browser.cmd"),
      `@echo off\r\n"${process.execPath}" "%~dp0fake-agent-browser.js" %*\r\n`,
      "utf8"
    );
  } else {
    const bin = path.join(tmpDir, "agent-browser");
    fs.writeFileSync(bin, SCRIPTED_AGENT_BROWSER, "utf8");
    fs.chmodSync(bin, 0o755);
  }
  const preload = path.join(tmpDir, "stub-sleep.js");
  fs.writeFileSync(preload, SLEEP_STUB, "utf8");
  return preload;
}

/** 跑一个采集脚本的 CLI 主流程，返回 { status, stdout, stderr, files } */
function runScraper(scraperPath, args, env) {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "story-scan-e2e-"));
  try {
    const preload = makeScraperHarness(tmpDir);
    const outdir = path.join(tmpDir, "out");
    const result = spawnSync(
      process.execPath,
      ["--require", preload, scraperPath, ...args, "--outdir", outdir],
      {
        cwd: repoRoot,
        encoding: "utf8",
        timeout: 60000,
        env: {
          ...process.env,
          PATH: `${tmpDir}${path.delimiter}${process.env.PATH}`,
          SCAN_TEST_UTILS: path.join(path.dirname(scraperPath), "cdp-utils.js"),
          ...env,
        },
      }
    );
    const files = fs.existsSync(outdir) ? fs.readdirSync(outdir).sort() : [];
    const contents = files.map((name) =>
      fs.readFileSync(path.join(outdir, name), "utf8")
    );
    return { ...result, files, contents };
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
}

function testCdpUtils(modulePath) {
  withFakeAgentBrowser((tmpDir) => {
    const capture = path.join(tmpDir, "argv.json");
    const injected = path.join(tmpDir, "must-not-exist");
    process.env.AGENT_BROWSER_CAPTURE = capture;
    process.env.AGENT_BROWSER_STDOUT = "ok\n";

    const utils = loadFresh(modulePath);
    assert.strictEqual(typeof utils.evalJSONBase64, "function");

    // argv 合约：① 注入安全——参数绝不进 shell 求值；② 逐字透传真实参数里会出现的元字符
    // ——空格、& | ^ ; $()、中文，以及 URL 里的 & 和 =。裸双引号/反斜杠不在合约内：带引号的
    // eval 载荷一律经 base64 下发（evalJSONBase64 / evalJSON），命令行参数只会是 base64 串、
    // URL 和这类无引号 token，Windows 的 .cmd/PowerShell 无法逐字透传裸双引号。
    const shellLikeArg = `$(touch ${injected})`;
    const urlLikeArg = "https://x.example/rank?a=1&b=2&c=d#top";
    const unicodeSpecialArg = `中文参数 / 空 格 & | ^ ! $() ; [] {} = '`;
    assert.strictEqual(
      utils.ab(
        9222,
        "eval",
        shellLikeArg,
        urlLikeArg,
        "space arg",
        unicodeSpecialArg
      ),
      "ok"
    );
    assert.strictEqual(fs.existsSync(injected), false, "ab() must not invoke a shell");
    assert.deepStrictEqual(JSON.parse(fs.readFileSync(capture, "utf8")), [
      "--cdp",
      "9222",
      "eval",
      shellLikeArg,
      urlLikeArg,
      "space arg",
      unicodeSpecialArg,
    ]);

    process.env.AGENT_BROWSER_STDOUT = JSON.stringify(
      JSON.stringify({ ok: true, nested: "中文" })
    );
    assert.deepStrictEqual(utils.evalJSON(9222, "({ok:true})"), {
      ok: true,
      nested: "中文",
    });

    process.env.AGENT_BROWSER_CAPTURE = capture;
    assert.deepStrictEqual(utils.evalJSONBase64(9222, "window.__x = '$()'"), {
      ok: true,
      nested: "中文",
    });
    const base64Args = JSON.parse(fs.readFileSync(capture, "utf8"));
    assert.deepStrictEqual(base64Args.slice(0, 4), ["--cdp", "9222", "eval", "-b"]);
    assert.strictEqual(
      Buffer.from(base64Args[4], "base64").toString("utf8"),
      "window.__x = '$()'"
    );

    assert.strictEqual(utils.getArg(["--type=hot", "--top", "15"], "--type"), "hot");
    assert.strictEqual(utils.getArg(["--type=hot", "--top", "15"], "--top"), "15");
    assert.strictEqual(utils.getArg(["--top"], "--top"), null);

    process.env.AGENT_BROWSER_STDOUT = "";
    process.env.AGENT_BROWSER_STDERR = "CDP connection refused\n";
    process.env.AGENT_BROWSER_EXIT = "7";
    assert.throws(
      () => utils.ab(9222, "open", "https://example.com"),
      /agent-browser failed.*CDP connection refused/
    );

    delete process.env.AGENT_BROWSER_EXIT;
    delete process.env.AGENT_BROWSER_STDERR;
    process.env.AGENT_BROWSER_STDOUT = "not-json";
    assert.throws(
      () => utils.evalJSON(9222, "JSON.stringify({ok:true})"),
      /invalid JSON/
    );
  });
}

function testWindowsInvocationBuilder(modulePath) {
  const utils = loadFresh(modulePath);
  assert.strictEqual(typeof utils.buildAgentBrowserInvocation, "function");
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "story-scan-win-"));
  const oldPath = process.env.PATH;
  try {
    // npm's Windows shim: the `%*` line points to the real target (here the
    // native binary). buildAgentBrowserInvocation must resolve the shim to that
    // target and hand every argument to it as a distinct array element — never a
    // shell, never a space-joined string.
    fs.writeFileSync(
      path.join(tmpDir, "agent-browser.cmd"),
      `@ECHO off\r\n"%~dp0node_modules\\agent-browser\\bin\\agent-browser-win32-x64.exe" %*\r\n`,
      "utf8"
    );
    process.env.PATH = `${tmpDir}${path.delimiter}${oldPath}`;
    const shellLikeArg = '& calc.exe | echo "unsafe"';
    const unicodeSpecialArg = `中文参数 / 空 格 & | ^ ! $() ; [] {} = ' " \\`;
    const invocation = utils.buildAgentBrowserInvocation(
      9222,
      ["eval", shellLikeArg, "space arg", unicodeSpecialArg],
      "win32"
    );
    // Resolves to the native binary (Node refuses the .cmd; PowerShell collapses
    // the array) with every argument a distinct element — nothing shell-evaluated
    // or space-joined.
    assert.match(invocation.file, /agent-browser-win32-x64\.exe$/);
    assert.deepStrictEqual(invocation.args, [
      "--cdp",
      "9222",
      "eval",
      shellLikeArg,
      "space arg",
      unicodeSpecialArg,
    ]);
  } finally {
    process.env.PATH = oldPath;
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
}

function listScraperPaths() {
  return [
    ...fs
      .readdirSync(path.join(repoRoot, "skills/story-long-scan/scripts"))
      .filter((name) => name.endsWith("-scraper.js"))
      .map((name) => path.join(repoRoot, "skills/story-long-scan/scripts", name)),
    ...fs
      .readdirSync(path.join(repoRoot, "skills/story-short-scan/scripts"))
      .filter((name) => name.endsWith("-scraper.js"))
      .map((name) => path.join(repoRoot, "skills/story-short-scan/scripts", name)),
  ].sort();
}

function testScraperImports() {
  const scraperPaths = listScraperPaths();

  assert(scraperPaths.length >= 7, "expected all rank scraper modules");
  for (const scraperPath of scraperPaths) {
    const probe = spawnSync(
      process.execPath,
      [
        "-e",
        "require(process.argv[1]);",
        scraperPath,
      ],
      { cwd: repoRoot, encoding: "utf8", timeout: 2000 }
    );
    assert.strictEqual(
      probe.error && probe.error.code,
      undefined,
      `${path.basename(scraperPath)} import timed out or failed to start`
    );
    assert.strictEqual(
      probe.status,
      0,
      `${path.basename(scraperPath)} import failed: ${probe.stderr || probe.stdout}`
    );
    assert.strictEqual(
      probe.stderr,
      "",
      `${path.basename(scraperPath)} emitted stderr while imported`
    );
  }
}

function testCliResultGate(modulePath) {
  const probe = (body) =>
    spawnSync(
      process.execPath,
      ["-e", `const {runCli}=require(process.argv[1]);${body}`, modulePath],
      { cwd: repoRoot, encoding: "utf8", timeout: 2000 }
    );

  const success = probe("runCli(() => 2, 'probe');");
  assert.strictEqual(success.status, 0, success.stderr);

  const partial = probe(
    "runCli(() => ({planned: 3, written: 2, failed: 1, partialReasons: ['one rank failed']}), 'probe');"
  );
  assert.strictEqual(partial.status, 2, "partial-output CLI runs need a distinct status");
  assert.match(partial.stderr, /probe partial: wrote 2\/3; failed 1; one rank failed/);

  const empty = probe("runCli(() => 0, 'probe');");
  assert.strictEqual(empty.status, 1, "zero-output CLI runs must fail");
  assert.match(empty.stderr, /probe failed: no output was written/);

  const rejected = probe("runCli(async () => { throw new Error('boom'); }, 'probe');");
  assert.strictEqual(rejected.status, 1, "rejected CLI runs must fail");
  assert.match(rejected.stderr, /probe failed: boom/);
}

// 输出文件名的日期戳必须是本地日历日。用 UTC（toISOString）的话，UTC+8 作者在本地
// 00:00-08:00 之间采集会退回前一天的文件名——文件名是唯一去重键，前一晚的报告被静默覆盖。
function testLocalDateStamp(modulePath) {
  const utils = loadFresh(modulePath);
  assert.strictEqual(typeof utils.localDateStamp, "function");

  // new Date(y,m,d,...) 按本地时间构造，因此这两条断言与宿主时区无关
  assert.strictEqual(utils.localDateStamp(new Date(2026, 6, 27, 0, 30)), "20260727");
  assert.strictEqual(utils.localDateStamp(new Date(2026, 0, 1, 23, 59)), "20260101");
  assert.match(utils.localDateStamp(), /^\d{8}$/);

  // 回归点本体：北京时间 2026-07-27 07:30 的那一刻，UTC 日期还是 07-26
  const probe = spawnSync(
    process.execPath,
    [
      "-e",
      "const {localDateStamp}=require(process.argv[1]);" +
        'const d=new Date("2026-07-26T23:30:00Z");' +
        "process.stdout.write(JSON.stringify({local:localDateStamp(d)," +
        'utc:d.toISOString().slice(0,10).replace(/-/g,""),offset:d.getTimezoneOffset()}));',
      modulePath,
    ],
    {
      cwd: repoRoot,
      encoding: "utf8",
      timeout: 5000,
      env: { ...process.env, TZ: "Asia/Shanghai" },
    }
  );
  assert.strictEqual(probe.status, 0, probe.stderr);
  const seen = JSON.parse(probe.stdout);
  // 只有运行时真的认了 TZ=Asia/Shanghai 才断言跨日界行为（Windows 上 TZ 可能被忽略）
  if (seen.offset === -480) {
    assert.strictEqual(seen.utc, "20260726", "UTC 日期确实落在前一天");
    assert.strictEqual(seen.local, "20260727", "文件名日期必须跟本地日历日");
  }
}

// 晋江：详情批次瞬时失败只该丢详情，不该丢已解析的列表，更不该掐掉后面的榜单
function testJjwxcDetailFailureIsolation() {
  const scraper = path.join(
    repoRoot,
    "skills/story-long-scan/scripts/jjwxc-rank-scraper.js"
  );
  const run = runScraper(scraper, ["--type", "all"], {
    SCAN_FAKE_FAIL_DETAIL: "1",
  });
  assert.strictEqual(
    run.status,
    2,
    `详情失败应保留列表但标成 partial: ${run.stderr || run.stdout}`
  );
  assert.strictEqual(
    run.files.length,
    6,
    `--type all 的 6 个榜单都应落盘，实际 ${run.files.length}: ${run.files.join(", ")}`
  );
  assert.match(run.stderr, /详情批次 1（1 本）获取失败，跳过/);
  assert.match(run.stderr, /晋江采集 partial:/);
  for (const content of run.contents) {
    assert.match(content, /数据质量：\[详情解析异常\/登录态缺失\]/);
    assert.match(content, /### #1 甲书/, "已解析的列表数据必须保住");
  }

  // 对照：详情正常时质量门不误报
  const healthy = runScraper(scraper, ["--type", "12"], {});
  assert.strictEqual(healthy.status, 0, healthy.stderr);
  assert.strictEqual(healthy.files.length, 1);
  assert.match(healthy.contents[0], /数据质量：\[OK\]/);
  assert.match(healthy.contents[0], /收藏 1\.2万/);

  const partial = runScraper(scraper, ["--type", "12"], {
    SCAN_FAKE_TWO_BOOKS: "1",
    SCAN_FAKE_PARTIAL_DETAIL: "1",
  });
  assert.strictEqual(partial.status, 2, partial.stderr);
  assert.match(partial.stderr, /晋江采集 partial:/);
  assert.match(partial.contents[0], /详情采集：1 \/ 2/);
  assert.match(partial.contents[0], /数据质量：\[部分详情缺失\]/);
}

// 起点：一个榜单打不开只跳这一个，剩下 9 个照采（--type all 不再被一次超时掐死）
function testQidianRankIsolation() {
  const scraper = path.join(
    repoRoot,
    "skills/story-long-scan/scripts/qidian-rank-scraper.js"
  );
  const run = runScraper(scraper, ["--type", "all", "--mode", "cdp"], {
    SCAN_FAKE_FAIL_OPEN: "hotsales",
    SCAN_FAKE_HOST: "www.qidian.com",
    SCAN_TEST_STUB_SCROLL: "1",
  });
  assert.strictEqual(
    run.status,
    2,
    `单个榜单失败应保留其余产物但标成 partial: ${run.stderr || run.stdout}`
  );
  assert.match(run.stderr, /\[qidian\] 畅销榜 采集失败，跳过/);
  assert.match(run.stderr, /起点采集 partial: wrote 9\/10; failed 1/);
  assert.strictEqual(
    run.files.length,
    9,
    `失败的畅销榜之外 9 个榜单都应落盘，实际 ${run.files.length}: ${run.files.join(", ")}`
  );
  assert(
    !run.files.some((name) => name.startsWith("起点畅销榜_")),
    "打不开的榜单不该写出空文件"
  );
  // 书库只走 CDP，不进 --type all（all 默认不需要 Chrome；9/10 也靠这一条）
  assert(
    !run.files.some((name) => name.startsWith("起点男频书库")),
    `--type all 不该带上书库: ${run.files.join(", ")}`
  );

  // 参数错误仍要快速失败，不能被 per-榜单隔离吞掉
  const badMode = runScraper(scraper, ["--type", "all", "--mode", "bogus"], {});
  assert.strictEqual(badMode.status, 1, "未知 --mode 必须失败");
  assert.match(badMode.stderr, /未知 --mode: bogus/);
  assert.strictEqual(badMode.files.length, 0);
}

// 起点：移动端已有的 cnt 必须作为独立字数字段输出；四个契约字段在两种模式下都要
// 保持同一结构，拿不到就明确 [待补]，不能塞进 status 或静默省略。简介统一按 100 字清洗。
function testQidianFieldContractAndDescriptionLimit() {
  const scraperPath = path.join(
    repoRoot,
    "skills/story-long-scan/scripts/qidian-rank-scraper.js"
  );
  const qidian = loadFresh(scraperPath);
  assert.strictEqual(typeof qidian.cleanDesc, "function");

  const normalized = qidian.normalizeMobileBook(
    {
      bName: "样书",
      bid: "1",
      bAuth: "作者",
      cat: "玄幻",
      cnt: "383.68万字",
      rankCnt: "999",
      totalRecommend: "12345",
      signStatus: "已签约",
      vipStatus: "VIP",
      desc: "简介",
    },
    0
  );
  assert.strictEqual(normalized.words, "383.68万字");
  assert.strictEqual(normalized.rankValue, "999");
  assert.strictEqual(normalized.totalRecommendations, "12345");
  assert.strictEqual(normalized.signing, "已签约");
  assert.strictEqual(normalized.pricing, "VIP");
  assert(!/万字/.test(normalized.status || ""), "字数不能继续混装进 status");

  const longDesc = `第一句。${"甲".repeat(110)}第二句。`;
  const markdown = qidian.renderMarkdown(
    { label: "测试榜" },
    [{ ...normalized, descText: longDesc }],
    "https://example.invalid",
    "test"
  );
  assert.match(markdown, /字数：383\.68万字/);
  assert.match(markdown, /总推荐：12345/);
  assert.match(markdown, /签约：已签约/);
  assert.match(markdown, /收费模式：VIP/);
  assert(!markdown.includes(longDesc), "起点简介不得原样输出超过 100 字");
  assert(qidian.cleanDesc(longDesc).length <= 103, "简介截断后只允许额外的 ...");

  const missing = qidian.renderMarkdown(
    { label: "测试榜" },
    [{ rank: 1, title: "缺字段", author: "作者", descText: "短简介" }],
    "https://example.invalid",
    "test"
  );
  for (const label of ["字数", "总推荐", "签约", "收费模式"]) {
    assert.match(missing, new RegExp(`${label}：\\[待补\\]`));
  }
}

// ---------------------------------------------------------------------------
// 起点书库（--type library）：反爬字体解码、翻页、名次、去重、partial。全程离线：
// 列表页走假 agent-browser（按 qdLibraryPageSnapshot 分派），字体与移动端作品页走
// 预加载替身的 https.get，字体在这里现场合成，不提交任何真实 .ttf。
// ---------------------------------------------------------------------------

const QD_SCRAPER = path.join(repoRoot, "skills/story-long-scan/scripts/qidian-rank-scraper.js");
const QD_FONT_URL = (name) => `https://qdfepccdn.qidian.com/gtimg/qd_anti_spider/${name}.ttf`;
const QD_CIPHER_RE = /[\uE000-\uF8FF\u{17000}-\u{18D8F}\u{F0000}-\u{10FFFF}]/u;

/** Mac 标准字形序里用得到的几个下标（post 2.0 下标 < 258） */
const TEST_MAC_GLYPH_INDEX = {
  ".notdef": 0,
  period: 17,
  zero: 19,
  one: 20,
  two: 21,
  three: 22,
  four: 23,
  five: 24,
  six: 25,
  seven: 26,
  eight: 27,
  nine: 28,
};
const TEST_DIGIT_GLYPHS = {
  0: "zero",
  1: "one",
  2: "two",
  3: "three",
  4: "four",
  5: "five",
  6: "six",
  7: "seven",
  8: "eight",
  9: "nine",
  ".": "period",
};

/**
 * 合成一个最小 TrueType：表目录 + cmap（format 12 或 4）+ post 2.0。
 * entries 是 [码点, 字形名]；customNames 里的名字即便有 Mac 标准下标也写成 Pascal 串（走 >=258 分支）。
 */
function buildTestFont({ entries, cmapFormat = 12, customNames = [], postVersion = 0x00020000, magic = 0x00010000 }) {
  const glyphs = [".notdef"];
  const gidOf = {};
  for (const [, name] of entries) {
    if (!(name in gidOf)) {
      gidOf[name] = glyphs.length;
      glyphs.push(name);
    }
  }
  const extra = [];
  const indices = glyphs.map((name) => {
    if (name in TEST_MAC_GLYPH_INDEX && !customNames.includes(name)) return TEST_MAC_GLYPH_INDEX[name];
    extra.push(name);
    return 258 + extra.length - 1;
  });
  const post = Buffer.alloc(34 + indices.length * 2 + extra.reduce((n, s) => n + 1 + s.length, 0));
  post.writeUInt32BE(postVersion, 0);
  post.writeUInt16BE(glyphs.length, 32);
  indices.forEach((idx, i) => post.writeUInt16BE(idx, 34 + i * 2));
  let at = 34 + indices.length * 2;
  for (const name of extra) {
    post.writeUInt8(name.length, at);
    post.write(name, at + 1, "latin1");
    at += 1 + name.length;
  }

  const pairs = entries.map(([cp, name]) => [cp, gidOf[name]]).sort((a, b) => a[0] - b[0]);
  let sub;
  if (cmapFormat === 12) {
    sub = Buffer.alloc(16 + pairs.length * 12);
    sub.writeUInt16BE(12, 0);
    sub.writeUInt32BE(sub.length, 4);
    sub.writeUInt32BE(pairs.length, 12);
    pairs.forEach(([cp, gid], i) => {
      sub.writeUInt32BE(cp, 16 + i * 12);
      sub.writeUInt32BE(cp, 20 + i * 12);
      sub.writeUInt32BE(gid, 24 + i * 12);
    });
  } else {
    const segs = [...pairs, [0xffff, null]];
    const n = segs.length;
    sub = Buffer.alloc(16 + n * 8);
    sub.writeUInt16BE(4, 0);
    sub.writeUInt16BE(sub.length, 2);
    sub.writeUInt16BE(n * 2, 6);
    segs.forEach(([cp, gid], i) => {
      sub.writeUInt16BE(cp, 14 + i * 2);
      sub.writeUInt16BE(cp, 16 + n * 2 + i * 2);
      sub.writeUInt16BE(gid === null ? 1 : (gid - cp) & 0xffff, 16 + n * 4 + i * 2);
    });
  }
  const cmapHead = Buffer.alloc(12);
  cmapHead.writeUInt16BE(1, 2);
  cmapHead.writeUInt16BE(3, 4);
  cmapHead.writeUInt16BE(cmapFormat === 12 ? 10 : 1, 6);
  cmapHead.writeUInt32BE(12, 8);
  const tables = [
    ["cmap", Buffer.concat([cmapHead, sub])],
    ["post", post],
  ];
  const head = Buffer.alloc(12 + tables.length * 16);
  head.writeUInt32BE(magic, 0);
  head.writeUInt16BE(tables.length, 4);
  let offset = head.length;
  const bodies = [];
  tables.forEach(([tag, body], i) => {
    const rec = 12 + i * 16;
    head.write(tag, rec, "latin1");
    head.writeUInt32BE(offset, rec + 8);
    head.writeUInt32BE(body.length, rec + 12);
    const padded = Buffer.alloc(Math.ceil(body.length / 4) * 4);
    body.copy(padded);
    bodies.push(padded);
    offset += padded.length;
  });
  return Buffer.concat([head, ...bodies]);
}

/** 一套「数字 → 密文码点」的乱序表，生成对应字体与密文 */
function makeCipher(base, order) {
  const codeOf = {};
  order.split("").forEach((ch, i) => {
    codeOf[ch] = base + i;
  });
  return {
    font: (opts = {}) =>
      buildTestFont({
        entries: Object.entries(codeOf).map(([ch, cp]) => [cp, TEST_DIGIT_GLYPHS[ch]]),
        ...opts,
      }),
    encode: (text) => text.split("").map((ch) => codeOf[ch]),
  };
}

function testQidianCaptchaCheckIgnoresBookText() {
  // 书库页前 3000 字里有整段简介和章节名：书里写到「验证」「拖动」不能当成被拦，
  // 否则白等 3 次重试和 120 秒人工验证；真被拦（没有作品链接）时照旧判拦。
  const qidian = loadFresh(QD_SCRAPER);
  const run = (bookLinks, text, hasContainer) => JSON.parse(require("vm").runInNewContext(qidian.captchaCheckJS(), {
    document: {
      body: { innerText: text },
      querySelectorAll: (selector) => (selector.includes("/book/") ? new Array(bookLinks).fill({}) : []),
      querySelector: () => (hasContainer ? {} : null),
    },
  }));
  assert.deepStrictEqual(run(20, "第88章 身份验证 拖动滑块解谜", true), { blocked: false, reason: "" });
  assert.strictEqual(run(0, "请完成验证后继续访问", false).blocked, true);
  assert.strictEqual(run(0, "请完成验证后继续访问", true).blocked, true, "只有容器、没有作品链接时关键词照样生效");
  assert.strictEqual(run(0, "", false).reason, "页面无榜单内容(可能被拦截)");
}

function testQidianLibraryFontDecoding() {
  const qidian = loadFresh(QD_SCRAPER);
  // 码点顺序故意打乱（0x187b7 起依次是 8、2、1、6…），和真实字体一样不按数字顺序排
  const order = "8216405973.";
  assert.strictEqual(new Set(order).size, 11);
  const real = makeCipher(0x187b7, order);

  // format 12 + post 2.0：密文码点在辅助平面，必须靠 format 12
  const map = qidian.parseAntiSpiderFont(real.font());
  assert.strictEqual(map.size, 11);
  assert.strictEqual(qidian.decodeLibraryWords(real.encode("12.34"), "万字", map), "12.34万字");
  assert.strictEqual(qidian.decodeLibraryWords(real.encode("8000"), "字", map), "8000字");

  // 字形名存成 Pascal 串（下标 >= 258）也要认得
  const custom = qidian.parseAntiSpiderFont(real.font({ customNames: ["one", "period"] }));
  assert.strictEqual(qidian.decodeLibraryWords(real.encode("1.1"), "万字", custom), "1.1万字");

  // format 4（BMP 私用区）同样能解
  const bmp = makeCipher(0xe100, order);
  const bmpMap = qidian.parseAntiSpiderFont(bmp.font({ cmapFormat: 4 }));
  assert.strictEqual(qidian.decodeLibraryWords(bmp.encode("26.14"), "万字", bmpMap), "26.14万字");

  // 解不出来一律返回 ""：未知码点、单位不明、拼出来不是数字、字形名不在白名单
  assert.strictEqual(qidian.decodeLibraryWords([...real.encode("12"), 0x18000], "万字", map), "");
  assert.strictEqual(qidian.decodeLibraryWords(real.encode("12"), "", map), "");
  assert.strictEqual(qidian.decodeLibraryWords(real.encode("1..2"), "万字", map), "");
  const bogus = buildTestFont({
    entries: [
      [0x18800, "one"],
      [0x18801, "bogus"],
    ],
  });
  const bogusMap = qidian.parseAntiSpiderFont(bogus);
  assert.strictEqual(qidian.decodeLibraryWords([0x18800], "万字", bogusMap), "1万字");
  assert.strictEqual(
    qidian.decodeLibraryWords([0x18800, 0x18801], "万字", bogusMap),
    "",
    "白名单外的字形名不能被当成数字"
  );

  // 坏字体一律抛错（调用方据此写 [待补]）
  const good = real.font();
  const badMagic = Buffer.from(good);
  badMagic.writeUInt32BE(0xdeadbeef, 0);
  assert.throws(() => qidian.parseAntiSpiderFont(badMagic), /不是 TrueType/);
  assert.throws(() => qidian.parseAntiSpiderFont(good.subarray(0, 40)), /越界/);
  assert.throws(() => qidian.parseAntiSpiderFont(Buffer.from("not a font")), /太短/);
  assert.throws(
    () => qidian.parseAntiSpiderFont(real.font({ postVersion: 0x00030000 })),
    /post 表版本/
  );
  assert.throws(
    () => qidian.parseAntiSpiderFont(buildTestFont({ entries: [[0x18800, "bogus"]] })),
    /没有可识别的数字字形/
  );
}

const QD_LIBRARY_HTTPS_STUB = `// 预加载：https.get 离线替身（字体与 m.qidian.com 作品页），按 URL 查计划表
"use strict";
const fs = require("fs");
const https = require("https");
const { EventEmitter } = require("events");
const { PassThrough } = require("stream");
const plan = JSON.parse(fs.readFileSync(process.env.QD_LIBRARY_HTTPS_PLAN, "utf8"));
https.get = function (url, options, callback) {
  const href = String(url);
  fs.appendFileSync(process.env.QD_LIBRARY_HTTPS_LOG, href + "\\n");
  const req = new EventEmitter();
  req.destroy = (err) => { if (err) process.nextTick(() => req.emit("error", err)); };
  process.nextTick(() => {
    const hit = plan[href];
    if (!hit) { req.emit("error", new Error("offline stub: unexpected " + href)); return; }
    const res = new PassThrough();
    res.statusCode = hit.status || 200;
    res.headers = {};
    callback(res);
    res.end(hit.base64 ? Buffer.from(hit.base64, "base64") : Buffer.from(hit.text || "", "utf8"));
  });
  return req;
};
`;

/** 跑起点书库 CLI：pages 是 {页码: 列表页快照}，https 是 {URL: {status, text|base64}} */
function runQidianLibrary(args, { pages = {}, https = {}, env = {} } = {}) {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "story-qd-library-"));
  try {
    const preload = makeScraperHarness(tmpDir);
    const stub = path.join(tmpDir, "stub-https.js");
    fs.writeFileSync(stub, QD_LIBRARY_HTTPS_STUB, "utf8");
    const pagesFile = path.join(tmpDir, "pages.json");
    fs.writeFileSync(pagesFile, JSON.stringify(pages), "utf8");
    const planFile = path.join(tmpDir, "https-plan.json");
    fs.writeFileSync(planFile, JSON.stringify(https), "utf8");
    const logFile = path.join(tmpDir, "https.log");
    fs.writeFileSync(logFile, "", "utf8");
    const outdir = path.join(tmpDir, "out");
    const result = spawnSync(
      process.execPath,
      ["--require", preload, "--require", stub, QD_SCRAPER, ...args, "--outdir", outdir],
      {
        cwd: repoRoot,
        encoding: "utf8",
        timeout: 60000,
        env: {
          ...process.env,
          PATH: `${tmpDir}${path.delimiter}${process.env.PATH}`,
          SCAN_TEST_UTILS: path.join(path.dirname(QD_SCRAPER), "cdp-utils.js"),
          SCAN_FAKE_QD_LIBRARY: pagesFile,
          QD_LIBRARY_HTTPS_PLAN: planFile,
          QD_LIBRARY_HTTPS_LOG: logFile,
          ...env,
        },
      }
    );
    const files = fs.existsSync(outdir) ? fs.readdirSync(outdir).sort() : [];
    const contents = files.map((name) => fs.readFileSync(path.join(outdir, name), "utf8"));
    const requests = fs.readFileSync(logFile, "utf8").split("\n").filter(Boolean);
    return { ...result, files, contents, requests };
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
}

const QD_GOOD_FILTERS = ["全部", "连载", "全部", "30万字以下", "全部", "三日内", "全部", "全部"];

function qdLibraryPage(page, fontName, books, overrides = {}) {
  return {
    qdLibraryPage: page,
    path: page === 1 ? "/all/action0-size1-update1/" : `/all/action0-size1-update1-page${page}/`,
    site: "男生",
    filters: QD_GOOD_FILTERS,
    sort: "人气排序",
    pager: String(page),
    pagerMax: 50,
    fontUrls: { [fontName]: QD_FONT_URL(fontName) },
    items: books.map((b, i) => ({
      rid: String(i + 1),
      bookId: String(b.id),
      title: `书${b.id}`,
      author: `作者${b.id}`,
      genre: "玄幻",
      subGenre: "东方玄幻",
      status: "连载",
      intro: `简介${b.id}`,
      wordsFont: fontName,
      wordsCodes: b.codes,
      wordsUnit: "万字",
      latestChapter: `第${b.id}章`,
    })),
    ...overrides,
  };
}

function qdMobileBookHtml(info) {
  const ctx = { pageContext: { pageProps: { pageData: { bookInfo: info } } } };
  return `<html><script id="vite-plugin-ssr_pageContext" type="application/json">${JSON.stringify(ctx)}</script></html>`;
}

function qdMobilePlan(ids, { missing = [] } = {}) {
  const plan = {};
  for (const id of ids) {
    plan[`https://m.qidian.com/book/${id}/`] = missing.includes(id)
      ? { status: 404, text: "gone" }
      : {
          text: qdMobileBookHtml({
            bookId: id,
            recomAll: id,
            signStatus: "签约作品",
            isVip: 1,
            wordsCnt: 123456,
            updTime: "3小时前",
          }),
        };
  }
  return plan;
}

const range = (from, to) => Array.from({ length: to - from + 1 }, (_, i) => from + i);

function testQidianLibraryPagingE2E() {
  const fontA = makeCipher(0x187b7, "8216405973.");
  const fontB = makeCipher(0x18800, "7.093826154");
  const page1 = range(1001, 1020).map((id) => ({ id, codes: fontA.encode("12.34") }));
  // 1005 的密文里混进一个字体里没有的码点：解不出来就用详情页字数兜底，不输出乱码
  page1[4].codes = [...fontA.encode("12"), 0x18d00];
  // 第 2 页开头两本是第 1 页的书（翻页时名次变动）：去重后按首次出现编号
  const page2 = [1019, 1020, ...range(1021, 1038)].map((id) => ({ id, codes: fontB.encode("5.6") }));
  const page3 = page2.slice(0, 5);
  const ids = range(1001, 1038);
  const https = {
    [QD_FONT_URL("QdTestAa")]: { base64: fontA.font().toString("base64") },
    [QD_FONT_URL("QdTestBb")]: { base64: fontB.font().toString("base64") },
    ...qdMobilePlan(ids, { missing: [1030] }),
  };
  const pages = {
    1: qdLibraryPage(1, "QdTestAa", page1),
    2: qdLibraryPage(2, "QdTestBb", page2),
    3: qdLibraryPage(3, "QdTestBb", page3),
  };

  // --pages 10（上限），但第 3 页没有新书就停：第 4 页一旦被打开就会失败（exit 2），
  // 所以 exit 0 证明没翻过去
  const run = runQidianLibrary(["--type", "library", "--pages", "10"], {
    pages,
    https,
    env: { SCAN_FAKE_FAIL_OPEN: "update1-page4/" },
  });
  assert.strictEqual(run.status, 0, `书库正常采集应 exit 0:\n${run.stdout}\n${run.stderr}`);
  assert.strictEqual(run.files.length, 1, run.files.join(", "));
  assert.match(run.files[0], /^起点男频书库人气新书_\d{8}\.md$/);
  const md = run.contents[0];
  assert.strictEqual(md.split("\n")[0], "# 起点 · 男频书库人气新书", "首行决定聚合的平台与「新书榜」列");
  assert.match(md, /- 来源：https:\/\/www\.qidian\.com\/all\/action0-size1-update1\/\n/);
  assert.match(md, /- 抓取方式：cdp-pc\n/);
  assert.match(md, /- 筛选：男生·连载·30万字以下·三日内更新；人气排序，取前 10 页\n/);
  assert.match(md, /- 实际翻页：3 页（第 3 页没有新书，停止翻页）\n/);
  assert.match(md, /- 条目数：38\n/);
  assert.match(md, /- 字数来源：反爬字体解码 37 条，详情页兜底 1 条，缺失 0 条\n/);
  assert.match(md, /- 详情补全：成功 37 \/ 共 38\n/);
  assert.match(md, /- 数据质量：\[OK\]\n- 问题摘要：无\n/);

  const ranks = [...md.matchAll(/^## #(\d+) /gm)].map((m) => Number(m[1]));
  assert.deepStrictEqual(ranks, range(1, 38), "名次跨页连续，不按页重排");
  assert.strictEqual((md.match(/^## #\d+ 书1020$/gm) || []).length, 1, "跨页重复的书只出现一次");
  assert.match(md, /^## #20 书1020$/m);
  assert.match(md, /^## #21 书1021$/m, "去重后第 2 页的第一本新书接着第 1 页编号");
  assert(!/^## .*\n/m.test(md.split("---")[0]), "文件头里不能有按页的分组标题");

  const entry = (id) => md.slice(md.indexOf(` 书${id}\n`), md.indexOf("\n---", md.indexOf(` 书${id}\n`)));
  assert.match(entry(1001), /\*作者1001 · 玄幻·东方玄幻 · 连载\*/);
  assert.match(entry(1001), /\*\*字数：12\.34万字\*\*/);
  assert.match(entry(1001), /\*\*新书总推荐：1001\*\*/);
  assert(!/^\*\*总推荐：/m.test(md), "书库条目的总推荐单列为新书总推荐，不能进聚合的热度口径");
  assert.match(md, /^- 热度：名次即人气排名/m);
  assert.match(entry(1001), /\*\*签约：签约作品\*\*/);
  assert.match(entry(1001), /\*\*收费模式：VIP\*\*/);
  assert.match(entry(1001), /\*\*最新更新：\*\* 第1001章 · 3小时前/);
  assert.match(entry(1001), /\[作品页\]\(https:\/\/www\.qidian\.com\/book\/1001\/\)/);
  assert.match(entry(1005), /\*\*字数：12\.35万字\*\*/, "字体解不出时用详情页 wordsCnt 兜底");
  assert.match(entry(1021), /\*\*字数：5\.6万字\*\*/, "每页的字体各自解码");
  assert.match(entry(1030), /\*\*新书总推荐：\[待补\]\*\*/, "单本详情失败写 [待补]");
  assert.match(entry(1030), /\*\*签约：\[待补\]\*\*/);
  assert(!QD_CIPHER_RE.test(md), "输出里不能出现反爬密文字符");

  // 字体只从白名单 host 下载、同名字体只下一次；详情只打 m.qidian.com
  assert.strictEqual(run.requests.filter((u) => u === QD_FONT_URL("QdTestAa")).length, 1);
  assert.strictEqual(run.requests.filter((u) => u === QD_FONT_URL("QdTestBb")).length, 1);
  for (const url of run.requests) {
    assert.match(url, /^https:\/\/(qdfepccdn\.qidian\.com\/gtimg\/qd_anti_spider\/|m\.qidian\.com\/book\/)/);
  }

  // 第 2 页打不开（URL 形状 -page2/）：保留第 1 页、写文件、exit 2，并写明原因；不传 --pages 默认 3 页
  const partial = runQidianLibrary(["--type", "library"], {
    pages,
    https,
    env: { SCAN_FAKE_FAIL_OPEN: "/all/action0-size1-update1-page2/" },
  });
  assert.strictEqual(partial.status, 2, `部分页失败必须 exit 2:\n${partial.stdout}\n${partial.stderr}`);
  assert.match(partial.stderr, /起点采集 partial: wrote 1\/1; 男频书库人气新书: 第 2 页没取到/);
  assert.strictEqual(partial.files.length, 1);
  assert.match(partial.contents[0], /- 条目数：20\n/);
  assert.match(partial.contents[0], /取前 3 页\n/);
  assert.match(partial.contents[0], /- 数据质量：\[存在问题\]/);
  assert.match(partial.contents[0], /- 问题摘要：第 2 页没取到：.*（已保留前 1 页）/);

  // 第 1 页实际选中的频道/筛选/排序对不上：不能写成「男频书库人气新书」，exit 1、不写文件
  for (const [override, message] of [
    [{ sort: "总收藏" }, /排序是「总收藏」/],
    [{ site: "女生" }, /频道是「女生」/],
    [{ filters: ["全部", "连载", "全部", "30万字以下", "全部", "七日内"] }, /没选中「三日内」/],
  ]) {
    const wrong = runQidianLibrary(["--type", "library"], {
      pages: { ...pages, 1: { ...pages[1], ...override } },
      https,
    });
    assert.strictEqual(wrong.status, 1, wrong.stderr);
    assert.strictEqual(wrong.files.length, 0);
    assert.match(wrong.stderr, /第 1 页没取到：筛选状态不符（/);
    assert.match(wrong.stderr, message);
    assert.match(wrong.stderr, /起点采集 failed: no output was written/);
  }

  // 站点静默退回第 1 页（分页器停在 1）：第 2 页不能当成新的 20 本写进去
  const fellBack = runQidianLibrary(["--type", "library", "--pages", "2"], {
    pages: { ...pages, 2: { ...pages[1], qdLibraryPage: 2, pager: "1" } },
    https,
  });
  assert.strictEqual(fellBack.status, 2, fellBack.stderr);
  assert.match(fellBack.stderr, /第 2 页没取到：筛选状态不符（分页停在第「1」页）/);
  assert.match(fellBack.contents[0], /- 条目数：20\n/);

  // 第 1 页一本都没有：exit 1、不写空文件
  const empty = runQidianLibrary(["--type", "library"], {
    pages: { 1: qdLibraryPage(1, "QdTestAa", []) },
    https,
  });
  assert.strictEqual(empty.status, 1, empty.stderr);
  assert.strictEqual(empty.files.length, 0);
  assert.match(empty.stderr, /书库列表页一本都没抓到/);

  // 字体地址不在白名单（换了 host）：不下载；某本详情也失败时字数写 [待补] 并进问题摘要，
  // 绝不把密文写出去。替身其实能答这个地址——下载了就会解出字数，断言就会红
  // 同一页里一条缺作者（宁可不收，免得元信息错位）、一条书名混进密文字符（要剥掉）
  const evilFont = "https://qdfepccdn.qidian.com.evil.example/gtimg/qd_anti_spider/QdTestAa.ttf";
  const dirtyItems = pages[1].items.map((item) => ({ ...item }));
  dirtyItems[5].author = "";
  dirtyItems[6].title = "书1007\u{187B9}";
  const noFont = runQidianLibrary(["--type", "library", "--pages", "1"], {
    pages: { 1: { ...pages[1], items: dirtyItems, fontUrls: { QdTestAa: evilFont } } },
    https: {
      [evilFont]: { base64: fontA.font().toString("base64") },
      ...qdMobilePlan(range(1001, 1020), { missing: [1003] }),
    },
  });
  assert.strictEqual(noFont.status, 0, noFont.stderr);
  assert(!noFont.requests.includes(evilFont), "白名单外的字体地址不得请求");
  const md2 = noFont.contents[0];
  assert.match(md2, /- 条目数：19\n/);
  assert.match(md2, /- 字数来源：反爬字体解码 0 条，详情页兜底 18 条，缺失 1 条\n/);
  assert.match(md2, /- 数据质量：\[存在问题\]\n- 问题摘要：字数缺失 1 条.*；缺书名\/作者\/题材的条目 1 条，已跳过/);
  assert.match(md2, /## #3 书1003\n[^#]*\*\*字数：\[待补\]\*\*/);
  assert(!md2.includes("书1006"), "缺作者的条目不该写进去");
  assert.match(md2, /^## #6 书1007$/m, "跳过的条目不占名次，书名里的密文字符被剥掉");
  assert(!QD_CIPHER_RE.test(md2), "字体解不出时不能把密文写进输出");
}

// 七猫大热榜：日/月必须是显式采集维度，并进入文件名；非大热榜只采一次。
function testQimaoPeriodPlan() {
  const scraperPath = path.join(
    repoRoot,
    "skills/story-long-scan/scripts/qimao-rank-scraper.js"
  );
  const qimao = loadFresh(scraperPath);
  assert.strictEqual(typeof qimao.buildTargets, "function");
  assert.strictEqual(typeof qimao.outputFilename, "function");
  assert.strictEqual(
    qimao.isUsableBook({ rank: 1, title: "真书", author: "作者" }),
    true
  );
  assert.strictEqual(
    qimao.isUsableBook({ rank: 5, title: "下一页", author: "跳转", genre: "友情链接：" }),
    false,
    "分页器文本不得被当成榜单书目"
  );
  assert.strictEqual(
    qimao.rankUrl("male", "hot", "month"),
    "https://www.qimao.com/paihang/boy/hot/month/"
  );
  assert.strictEqual(
    qimao.selectionMatches(
      { path: "/paihang/boy/hot/month/", channel: "男生榜", rankType: "大热榜", period: "月榜" },
      "male",
      "hot",
      "month"
    ),
    true
  );
  assert.strictEqual(
    qimao.selectionMatches(
      { path: "/paihang/boy/hot/date/", channel: "男生榜", rankType: "大热榜", period: "日榜" },
      "male",
      "hot",
      "month"
    ),
    false,
    "实际仍在日榜时不得写成月榜文件"
  );
  const dirtyDesc = `${"甲".repeat(110)}。 飙升 18名`;
  const cleanDesc = qimao.cleanDesc(dirtyDesc);
  assert(cleanDesc.length <= 103, "七猫简介必须截断到 100 字 + ...");
  assert(!cleanDesc.includes("飙升 18名"), "七猫排名变化 UI 文本不得混入简介");

  const incompleteBook = {
    rank: 1,
    title: "字段不全的样书",
    author: "作者",
    genre: "玄幻",
    subGenre: "",
    status: "连载中",
    words: "",
    heat: "100万",
    url: "https://www.qimao.com/shuku/1/",
  };
  const incomplete = qimao.renderMarkdown(
    { label: "男频" },
    { label: "大热榜" },
    { label: "日榜" },
    "https://www.qimao.com/paihang/boy/hot/date/",
    [incompleteBook],
    1,
    "2026-08-11T00:00:00.000Z"
  );
  assert.match(incomplete, /数据质量：\[存在问题\]/);
  assert.match(incomplete, /问题摘要：.*子分类缺失 1 条.*字数缺失 1 条/);
  assert.match(incomplete, /\[待补\]/);

  const completeBook = {
    ...incompleteBook,
    subGenre: "东方玄幻",
    words: "100万字",
  };
  const complete = qimao.renderMarkdown(
    { label: "男频" },
    { label: "大热榜" },
    { label: "日榜" },
    "https://www.qimao.com/paihang/boy/hot/date/",
    Array.from({ length: 15 }, (_, index) => ({
      ...completeBook,
      rank: index + 1,
      title: `样书${index + 1}`,
    })),
    15,
    "2026-08-11T00:00:00.000Z"
  );
  assert.match(complete, /数据质量：\[OK\]/);
  assert.match(complete, /问题摘要：无/);
  assert.match(complete, /热度命中：15 \/ 15/);
  assert(!complete.includes("[待补]"));

  assert.deepStrictEqual(qimao.buildTargets("male", "hot", "all"), [
    { channel: "male", rankType: "hot", period: "day" },
    { channel: "male", rankType: "hot", period: "month" },
  ]);
  assert.deepStrictEqual(qimao.buildTargets("female", "new", "month"), [
    { channel: "female", rankType: "new", period: null },
  ]);
  assert.strictEqual(
    qimao.outputFilename("male", "hot", "day", "20260811"),
    "七猫男频大热榜日榜_20260811.md"
  );
  assert.strictEqual(
    qimao.outputFilename("male", "hot", "month", "20260811"),
    "七猫男频大热榜月榜_20260811.md"
  );
}

function testQimaoPartialTargetStatus() {
  const run = runScraper(
    path.join(repoRoot, "skills/story-long-scan/scripts/qimao-rank-scraper.js"),
    ["--channel", "male", "--type", "hot", "--period", "all"],
    { SCAN_FAKE_HOST: "www.qimao.com", SCAN_FAKE_FAIL_OPEN: "/month/" }
  );
  assert.strictEqual(
    run.status,
    2,
    `七猫部分失败必须 exit 2，实际 ${run.status}:\n${run.stdout}\n${run.stderr}`
  );
  assert.strictEqual(run.files.length, 1, "日榜成功、月榜失败时应只写一份报告");
  assert.match(run.stderr, /七猫采集 partial: wrote 1\/2; failed 1/);
}

function testCiweimaoPartialTargetStatus() {
  const scraper = path.join(repoRoot, "skills/story-long-scan/scripts/ciweimao-rank-scraper.js");
  const names = ["点击榜", "收藏榜", "推荐榜", "订阅榜", "月票榜", "吐槽榜", "新书榜", "刀片榜", "更新榜"];
  const sections = names.map((name) => ({
    name, entries: [{ rank: 1, title: "刺猬猫样本", author: "作者", metric: "100" }],
  }));
  const run = (selected, args = ["--type", "all"]) => runScraper(scraper, args, {
    SCAN_FAKE_HOST: "www.ciweimao.com",
    SCAN_FAKE_CIWEIMAO: JSON.stringify(selected),
    SCAN_TEST_STUB_SCROLL: "1",
  });
  const partial = run(sections.slice(0, 1));
  assert.strictEqual(partial.status, 2, partial.stdout + partial.stderr);
  assert.strictEqual(partial.files.length, 1);
  assert.match(partial.stderr, /partial: wrote 1\/9; failed 8/);
  assert.match(partial.stderr, /收藏榜/);
  const complete = run(sections);
  assert.strictEqual(complete.status, 0, complete.stdout + complete.stderr);
  assert.strictEqual(complete.files.length, 9);
  const single = run(sections.slice(0, 1), ["--type", "click"]);
  assert.strictEqual(single.status, 0, single.stdout + single.stderr);
  assert.strictEqual(single.files.length, 1);
  const empty = run([]);
  assert.strictEqual(empty.status, 1, empty.stdout + empty.stderr);
  assert.strictEqual(empty.files.length, 0);
}

// ---------------------------------------------------------------------------
// 七猫书库（--source library）：走 Node https，不开 Chrome。预加载把 https.get 换成按 URL
// 查夹具的替身，并把 sleep / ab 换成记账，断言请求顺序、限速和「全程没碰 CDP」。
// ---------------------------------------------------------------------------

const QIMAO_SCRAPER = path.join(
  repoRoot,
  "skills/story-long-scan/scripts/qimao-rank-scraper.js"
);
const QIMAO_LIBRARY_STUB = `// 预加载：书库测试一律离线
const fs = require("fs");
const https = require("https");
const { EventEmitter } = require("events");
const { PassThrough } = require("stream");
const routes = JSON.parse(fs.readFileSync(process.env.SCAN_FAKE_HTTPS_ROUTES, "utf8"));
const record = (line) => fs.appendFileSync(process.env.SCAN_FAKE_CALLS, line + "\\n");
const utils = require(process.env.SCAN_TEST_UTILS);
utils.sleep = (ms) => record("sleep " + ms);
utils.ab = () => { record("ab"); throw new Error("library mode must not touch CDP"); };
https.get = function fakeGet(url, options, callback) {
  const target = String(url);
  record("GET " + target);
  const req = new EventEmitter();
  req.destroy = (err) => setImmediate(() => req.emit("error", err || new Error("destroyed")));
  setImmediate(() => {
    // 真站的响应头有折行，Node 严格解析器会在这里报错（实测）；替身照样拒绝严格解析的请求。
    if (!options || options.insecureHTTPParser !== true) {
      req.emit("error", new Error("Parse Error: Unexpected whitespace after header value"));
      return;
    }
    const route = routes[target];
    if (!route) {
      req.emit("error", new Error("no fixture for " + target));
      return;
    }
    const res = new PassThrough();
    res.statusCode = route.status || 200;
    res.headers = route.location ? { location: route.location } : {};
    callback(res);
    res.end(route.body || "");
  });
  return req;
};
`;

const QM_PAGE = (n) => `https://www.qimao.com/shuku/a-a-a-1-1-a-0-click-${n}/`;
const QM_CATEGORY = (id) => `https://www.qimao.com/shuku/a-${id}-a-a-a-a-a-click-1/`;
const QM_TITLE = "3天内更新-30万以下-连载中-七猫免费小说-七猫中文网";
const QM_MAINS = {
  203: ["都市", "203", "都市异能"],
  1: ["现代言情", "1", "总裁豪门"],
  207: ["N次元", "207", "衍生同人"],
  202: ["玄幻奇幻", "202", "东方玄幻"],
};

/** 书库一本书：照真实页面结构（data-v 属性、换行简介、绝对链接）。 */
function qmBook(id, main = 203, overrides = {}) {
  const [, mainId, sub] = QM_MAINS[main];
  return {
    id,
    title: `书${id}`,
    author: `作者${id}`,
    mainId,
    subId: "301",
    sub,
    status: "连载中",
    words: "12.3万字",
    update: "2026-10-09更新",
    desc: `第一行简介${id}\n第二行`,
    ...overrides,
  };
}

function qmShukuHtml({ page, books, maxPage = 67, title = QM_TITLE, sort = "按点击量" }) {
  const v = "data-v-3e833f26";
  const items = books.map((b) => {
    const words = b.words === null ? "" : ` <em class="s-words-num" ${v}>${b.words}</em>`;
    return (
      `<li class="qm-cover-text-item horizontal spacing-16 font-size-1" ${v}>` +
      `<div class="cover-content left-col" ${v}><a href="https://www.qimao.com/shuku/${b.id}/" target="_blank"><img alt="${b.title}"></a></div> ` +
      `<div class="text-content right-col" ${v}><div class="text-top-row" ${v}>` +
      `<span class="s-tit" ${v}><a href="https://www.qimao.com/shuku/${b.id}/" target="_blank" ${v}>${b.title}</a></span> ` +
      `<span class="tags-gather" ${v}><a href="https://www.qimao.com/shuku/a-${b.mainId}-${b.subId}-a-a-a-a-click-1/" target="" class="s-category" ${v}>${b.sub}</a> ` +
      `<em class="s-status" ${v}>${b.status}</em>${words}</span> ` +
      `<span class="s-desc" ${v}>\n                        ${b.desc}\n                    </span></div> ` +
      `<div class="text-bottom-row" ${v}><span ${v}><a href="https://www.qimao.com/zuozhe/x/" target="_blank" class="s-author" ${v}>${b.author}</a> ` +
      `<em class="s-update-time" ${v}>${b.update}</em></span></div></div> </li>`
    );
  });
  const sortTabs = ["按点击量", "按总字数", "最近更新", "按收藏数"]
    .map(
      (label) =>
        `<li class="qm-tab-list-item"><div class="tab-inner${label === sort ? " active" : ""}" data-v-223ba5bd>` +
        `<span class="radio-icon"></span> <span>${label}</span> <!----></div></li>`
    )
    .join("");
  const pager = [...new Set([1, 2, 3, maxPage].filter((n) => n <= maxPage))]
    .map(
      (n) =>
        `<li class="page-number-item"><div class="number-item"><span class="page-btn num${n === page ? " active" : ""}" data-v-29399e2c>${n}</span></div></li>`
    )
    .join("");
  return (
    `<!doctype html><html><head><title>${title}</title></head><body>` +
    `<ul class="qm-tab-list clearfix">${sortTabs}</ul>` +
    `<ul class="qm-cover-text-list">${items.join("")}</ul>` +
    `<div class="qm-page"><ul class="qm-page-number-list clearfix">${pager}</ul></div></body></html>`
  );
}

function qmCategoryHtml(name) {
  return `<!doctype html><html><head><title>${name}小说-好看的${name}小说-${name}小说排行榜--七猫免费小说-七猫中文网</title></head><body></body></html>`;
}

function qmCategoryRoutes(...mains) {
  return Object.fromEntries(
    mains.map((main) => [QM_CATEGORY(QM_MAINS[main][1]), { body: qmCategoryHtml(QM_MAINS[main][0]) }])
  );
}

function runQimaoLibrary(args, routes) {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "story-scan-qimao-library-"));
  try {
    const preload = path.join(tmpDir, "stub-https.js");
    fs.writeFileSync(preload, QIMAO_LIBRARY_STUB, "utf8");
    const routesFile = path.join(tmpDir, "routes.json");
    fs.writeFileSync(routesFile, JSON.stringify(routes), "utf8");
    const callsFile = path.join(tmpDir, "calls.log");
    const outdir = path.join(tmpDir, "out");
    const result = spawnSync(
      process.execPath,
      ["--require", preload, QIMAO_SCRAPER, ...args, "--outdir", outdir],
      {
        cwd: repoRoot,
        encoding: "utf8",
        timeout: 60000,
        env: {
          ...process.env,
          SCAN_TEST_UTILS: path.join(path.dirname(QIMAO_SCRAPER), "cdp-utils.js"),
          SCAN_FAKE_HTTPS_ROUTES: routesFile,
          SCAN_FAKE_CALLS: callsFile,
        },
      }
    );
    const files = fs.existsSync(outdir) ? fs.readdirSync(outdir).sort() : [];
    const contents = files.map((name) => fs.readFileSync(path.join(outdir, name), "utf8"));
    const calls = fs.existsSync(callsFile)
      ? fs.readFileSync(callsFile, "utf8").split("\n").filter(Boolean)
      : [];
    return { ...result, files, contents, calls, gets: calls.filter((c) => c.startsWith("GET ")).map((c) => c.slice(4)) };
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
}

// 翻页：名次跨页连续、按 bookId 去重、某页没有新书就停；主类按分类页标题查且每类只查一次；
// 请求之间限速；一份文件、首行能被聚合认成「七猫」平台的新书榜。
function testQimaoLibraryPagedCollection() {
  const page1 = Array.from({ length: 15 }, (_, i) => qmBook(1001 + i, [203, 1, 207][i % 3]));
  page1[0] = qmBook(1001, 203, { title: "风&amp;雨&#x4E66;", desc: "甲&lt;乙&gt;\n丙<!<!---->--" });
  const page2 = [
    page1[13],
    page1[14],
    ...Array.from({ length: 13 }, (_, i) => qmBook(2001 + i, 203)),
  ];
  const page3 = page2.slice(2, 7);
  const run = runQimaoLibrary(["--source", "library", "--pages", "4"], {
    [QM_PAGE(1)]: { status: 302, location: "/shuku/a-a-a-1-1-a-0-click-1/?r=1" },
    [`${QM_PAGE(1)}?r=1`]: { body: qmShukuHtml({ page: 1, books: page1 }) },
    [QM_PAGE(2)]: { body: qmShukuHtml({ page: 2, books: page2 }) },
    [QM_PAGE(3)]: { body: qmShukuHtml({ page: 3, books: page3 }) },
    ...qmCategoryRoutes(203, 1, 207),
  });
  assert.strictEqual(run.status, 0, `书库采集应成功:\n${run.stdout}\n${run.stderr}`);
  assert.deepStrictEqual(run.gets, [
    QM_PAGE(1),
    `${QM_PAGE(1)}?r=1`,
    QM_PAGE(2),
    QM_PAGE(3),
    QM_CATEGORY(203),
    QM_CATEGORY(1),
    QM_CATEGORY(207),
  ], "第 3 页没有新书就停，不请求第 4 页；每个主类只查一次");
  assert(!run.calls.includes("ab"), "书库模式不得调用 agent-browser");
  const sleeps = run.calls.filter((c) => c.startsWith("sleep "));
  assert.strictEqual(sleeps.length, 5, `3 页 + 3 个主类之间各隔一次: ${run.calls.join(" | ")}`);
  assert(sleeps.every((c) => Number(c.slice(6)) >= 800), `请求间隔不得低于 800ms: ${sleeps}`);

  assert.strictEqual(run.files.length, 1);
  assert.match(run.files[0], /^七猫全站书库点击新书_\d{8}\.md$/);
  const md = run.contents[0];
  assert.strictEqual(md.split("\n")[0], "# 七猫 · 全站书库点击新书");
  assert.match(md, /数据质量：\[OK\]/);
  assert.match(md, /问题摘要：无/);
  assert.match(md, /有效条目：28 \/ 28/);
  assert.match(md, /来源：https:\/\/www\.qimao\.com\/shuku\/a-a-a-1-1-a-0-click-1\//);
  assert.match(md, /筛选：.*3天内更新.*连载中.*按点击量.*没有热度/);
  assert(!md.includes("[待补]"), "字段齐全时不得出现占位");
  assert(!/^## /m.test(md), "不按页写分组标题");

  const ranks = [...md.matchAll(/^### #(\d+) /gm)].map((m) => Number(m[1]));
  assert.deepStrictEqual(ranks, Array.from({ length: 28 }, (_, i) => i + 1), "名次跨页连续");
  const ids = [...md.matchAll(/^\[作品页\]\(https:\/\/www\.qimao\.com\/shuku\/(\d+)\/\)$/gm)].map((m) => m[1]);
  assert.deepStrictEqual(ids, [
    ...Array.from({ length: 15 }, (_, i) => String(1001 + i)),
    ...Array.from({ length: 13 }, (_, i) => String(2001 + i)),
  ], "跨页重复的书只保留首次出现");

  assert.match(md, /^### #1 风&雨书$/m, "书名里的 HTML 实体要解码");
  assert.match(md, /^\*作者1001 · 都市 · 都市异能 · 连载中 · 12\.3万字\*$/m);
  assert.match(md, /^\*作者1002 · 现代言情 · 总裁豪门 · 连载中 · 12\.3万字\*$/m);
  assert.match(md, /^\*作者1003 · N次元 · 衍生同人 · 连载中 · 12\.3万字\*$/m);
  assert.match(md, /^\*\*最新更新：\*\* 2026-10-09更新$/m);
  assert.match(md, /^甲<乙> 丙$/m, "简介换行压成空格、实体解码，嵌套注释删干净");
  assert(!md.includes("<!--"), "嵌套、没闭合的注释删一遍会拼出新的「<!--」，不能留进输出");
}

// 失败分级：第 1 页失败、筛选没生效、一本没采到 → exit 1 且不写文件；
// 后面某页失败 → 保留已采到的页，exit 2，文件头写清第几页、为什么。
function testQimaoLibraryPageFailures() {
  const page1 = Array.from({ length: 15 }, (_, i) => qmBook(1001 + i));
  const okPage1 = { [QM_PAGE(1)]: { body: qmShukuHtml({ page: 1, books: page1 }) } };
  const fatal = [
    ["第 1 页 HTTP 500", { [QM_PAGE(1)]: { status: 500 } }, /七猫采集 failed: 第 1 页没取到：HTTP 500/],
    [
      "第 1 页被转去别的站",
      { [QM_PAGE(1)]: { status: 302, location: "https://passport.qimao.com/login" } },
      /第 1 页没取到：被重定向到 passport\.qimao\.com\/login/,
    ],
    [
      "筛选标题不符",
      { [QM_PAGE(1)]: { body: qmShukuHtml({ page: 1, books: page1, title: "7天内更新-30万以下-连载中-七猫免费小说" }) } },
      /第 1 页没取到：.*缺少「3天内更新」.*筛选没生效/,
    ],
    [
      "排序不是按点击量",
      { [QM_PAGE(1)]: { body: qmShukuHtml({ page: 1, books: page1, sort: "按总字数" }) } },
      /第 1 页没取到：页面排序是「按总字数」/,
    ],
    [
      "第 1 页一本书都没有",
      { [QM_PAGE(1)]: { body: qmShukuHtml({ page: 1, books: [] }) } },
      /七猫采集 failed: 书库第 1 页一本书都没解析出来/,
    ],
  ];
  for (const [label, routes, message] of fatal) {
    const run = runQimaoLibrary(["--source", "library", "--pages", "3"], { ...routes, ...qmCategoryRoutes(203) });
    assert.strictEqual(run.status, 1, `${label} 必须 exit 1:\n${run.stderr}`);
    assert.match(run.stderr, message, label);
    assert.strictEqual(run.files.length, 0, `${label} 不得写文件`);
    assert.deepStrictEqual(run.gets, [QM_PAGE(1)], `${label} 不得继续翻页、查主类或跟去别的站`);
  }

  const partial = [
    ["第 2 页 HTTP 503", { status: 503 }, /第 2 页没取到：HTTP 503/],
    [
      "第 2 页被站点退回第 1 页",
      { body: qmShukuHtml({ page: 1, books: page1 }) },
      /第 2 页没取到：请求第 2 页，页面停在第 1 页/,
    ],
  ];
  for (const [label, page2, reason] of partial) {
    const run = runQimaoLibrary(["--source", "library", "--pages", "3"], {
      ...okPage1,
      [QM_PAGE(2)]: page2,
      ...qmCategoryRoutes(203),
    });
    assert.strictEqual(run.status, 2, `${label} 应保留第 1 页并 exit 2:\n${run.stderr}`);
    assert.match(run.stderr, new RegExp(`七猫采集 partial: wrote 1/1; ${reason.source}`));
    assert.strictEqual(run.files.length, 1, `${label} 已采到的页必须落盘`);
    assert(!run.gets.includes(QM_PAGE(3)), `${label} 后不再翻页`);
    const md = run.contents[0];
    assert.match(md, /数据质量：\[存在问题\]/);
    assert.match(md, new RegExp(`问题摘要：.*${reason.source}`));
    assert.match(md, /有效条目：15 \/ 15/);
  }
}

// 页数以分页器为准提前停；主类查不到时题材位退用子分类并记进问题摘要；缺字段、条目太少都要标出来。
function testQimaoLibraryFallbacksAndQuality() {
  const books = [
    qmBook(1001, 203),
    qmBook(1002, 202),
    qmBook(1003, 203, { words: null }),
  ];
  const run = runQimaoLibrary(["--source", "library"], {
    [QM_PAGE(1)]: { body: qmShukuHtml({ page: 1, books, maxPage: 1 }) },
    ...qmCategoryRoutes(203),
    [QM_CATEGORY(202)]: { status: 500 },
  });
  assert.strictEqual(run.status, 0, `只缺主类不算采集失败:\n${run.stderr}`);
  assert.deepStrictEqual(run.gets, [QM_PAGE(1), QM_CATEGORY(203), QM_CATEGORY(202)], "书库只有 1 页时不再翻页");
  const md = run.contents[0];
  assert.match(md, /数据质量：\[存在问题\]/);
  assert.match(md, /问题摘要：.*主类未解析 1 条/);
  assert.match(md, /问题摘要：.*字数缺失 1 条/);
  assert.match(md, /问题摘要：.*\[数据稀疏\] 实际采集 3 条/);
  assert(!/热度/.test(md.split("---")[0].replace(/没有热度数字/, "")), "书库没有热度，不得把缺热度记成问题");
  assert.match(md, /^\*作者1002 · 东方玄幻 · 连载中 · 12\.3万字\*$/m, "主类缺失时题材位退用子分类");
  assert.match(md, /^\*作者1003 · 都市 · 都市异能 · 连载中 · \[待补\]\*$/m);
}

// 书库参数在联网前就要拒绝：不发请求、不碰 CDP、不写文件。
function testQimaoLibraryArgumentValidation() {
  const cases = [
    [["--source", "library", "--pages", "0"], /未知 --pages: 0/],
    [["--source", "library", "--pages", "11"], /未知 --pages: 11/],
    [["--source", "library", "--pages", "abc"], /未知 --pages: abc/],
    [["--source", "bogus"], /未知 --source: bogus/],
    [["--source", "library", "--type", "hot"], /--source library 不能配 --type/],
    [["--source", "library", "--channel=male", "--period", "day"], /--source library 不能配 --channel、--period/],
    [["--pages", "3"], /--pages 只用于 --source library/],
  ];
  for (const [args, message] of cases) {
    const run = runQimaoLibrary(args, {});
    assert.strictEqual(run.status, 1, `${args.join(" ")} 必须 exit 1: ${run.stderr}`);
    assert.match(run.stderr, message);
    assert.strictEqual(run.files.length, 0, `${args.join(" ")} 不得写文件`);
    assert.deepStrictEqual(run.calls, [], `${args.join(" ")} 不得联网或打开浏览器`);
  }
}

// 参数错误必须在打开浏览器/进入 per-target 容错前快速失败，给出具体参数名和值。
function testLongScanArgumentValidation() {
  const cases = [
    ["fanqie-rank-scraper.js", ["--channel", "2"], /未知 --channel: 2/],
    ["fanqie-rank-scraper.js", ["--type", "3"], /未知 --type: 3/],
    ["qimao-rank-scraper.js", ["--channel", "bogus"], /未知 --channel: bogus/],
    ["qimao-rank-scraper.js", ["--period", "week"], /未知 --period: week/],
    ["jjwxc-rank-scraper.js", ["--channel", "bogus"], /未知 --channel: bogus/],
    ["jjwxc-rank-scraper.js", ["--channel", "999"], /未知 --channel: 999/],
    ["qidian-rank-scraper.js", ["--type", "bogus", "--mode", "cdp"], /未知 --type: bogus/],
    // 起点书库只能走 CDP；--pages 取 1-10 的整数，且只对书库有效（其他榜单传了报错而不是静默忽略）
    ["qidian-rank-scraper.js", ["--type", "library", "--mode", "mobile"], /--type library 不支持 --mode mobile/],
    ["qidian-rank-scraper.js", ["--type", "library", "--pages", "0"], /未知 --pages: 0（取 1-10 的整数）/],
    ["qidian-rank-scraper.js", ["--type", "library", "--pages", "11"], /未知 --pages: 11/],
    ["qidian-rank-scraper.js", ["--type", "library", "--pages", "abc"], /未知 --pages: abc/],
    ["qidian-rank-scraper.js", ["--type", "library", "--pages", "2.5"], /未知 --pages: 2\.5/],
    ["qidian-rank-scraper.js", ["--type", "library", "--pages="], /未知 --pages: （空）/],
    ["qidian-rank-scraper.js", ["--type", "hotsales", "--mode", "cdp", "--pages", "2"], /--pages 只用于 --type library/],
    ["qidian-rank-scraper.js", ["--type", "all", "--mode", "cdp", "--pages", "2"], /--pages 只用于 --type library/],
  ];

  for (const [name, args, message] of cases) {
    const run = runScraper(
      path.join(repoRoot, "skills/story-long-scan/scripts", name),
      args,
      {}
    );
    assert.strictEqual(run.status, 1, `${name} 非法参数必须 exit 1: ${run.stderr}`);
    assert.match(run.stderr, message);
    assert.strictEqual(run.files.length, 0, `${name} 非法参数不得写文件`);
  }
}

// 黑岩：字段漂移必须拦在写盘前，字数格式不许随宿主 locale 变
function testHeiyanFieldDriftAndWordFormat() {
  const heiyan = loadFresh(
    path.join(repoRoot, "skills/story-short-scan/scripts/heiyan-booklist-scraper.js")
  );
  assert.strictEqual(typeof heiyan.fmtWords, "function");
  assert.strictEqual(heiyan.fmtWords(123456), "123,456字");
  assert.strictEqual(heiyan.fmtWords("123456"), "123,456字");
  assert.strictEqual(heiyan.fmtWords(0), "");
  assert.strictEqual(heiyan.fmtWords(undefined), "");
  assert.strictEqual(typeof heiyan.outputFilename, "function");
  const date = "20260806";
  const channelFiles = ["male", "female", "all"].map((channel) =>
    heiyan.outputFilename(channel, date)
  );
  assert.strictEqual(
    new Set(channelFiles).size,
    channelFiles.length,
    `黑岩产物名必须包含频道，不能同日互相覆盖: ${channelFiles.join(", ")}`
  );
  assert.deepStrictEqual(channelFiles, [
    `黑岩书库列表_male_${date}.md`,
    `黑岩书库列表_female_${date}.md`,
    `黑岩书库列表_all_${date}.md`,
  ]);
  assert.throws(() => heiyan.outputFilename("../../escape", date), /未知 --channel/);

  // toLocaleString() 在 de_* 下会写成 123.456（读起来像 123 字），fmtWords 必须不受影响
  const probe = spawnSync(
    process.execPath,
    [
      "-e",
      "const {fmtWords}=require(process.argv[1]);process.stdout.write(fmtWords(123456));",
      path.join(repoRoot, "skills/story-short-scan/scripts/heiyan-booklist-scraper.js"),
    ],
    {
      cwd: repoRoot,
      encoding: "utf8",
      timeout: 5000,
      env: { ...process.env, LC_ALL: "de_DE.UTF-8", LANG: "de_DE.UTF-8" },
    }
  );
  assert.strictEqual(probe.status, 0, probe.stderr);
  assert.strictEqual(probe.stdout, "123,456字", "字数格式不能跟宿主 locale 变");

  // 缺字段不能被拼成 "undefined/undefined" 写进报告
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "story-scan-heiyan-"));
  try {
    const filepath = path.join(tmpDir, "out.md");
    const books = [
      { name: "甲书", userName: "作者甲", classifyStr: "男频", typeDesc: "都市", words: 123456 },
      { name: "乙书", userName: "作者乙", classifyStr: "女频", typeDesc: null, words: 50000 },
    ];
    const origLog = console.log;
    console.log = () => {};
    try {
      heiyan.buildAndSave(books, 2, books, filepath);
    } finally {
      console.log = origLog;
    }
    const written = fs.readFileSync(filepath, "utf8");
    assert(!written.includes("undefined"), `报告里不能出现 undefined:\n${written}`);
    assert(!written.includes("/null"), `报告里不能出现 null:\n${written}`);
    assert(written.includes("*作者甲 · 男频/都市 · 123,456字 · 未公开*"), written);
    assert(written.includes("*作者乙 · 女频 · 50,000字 · 未公开*"), written);

    const malePath = path.join(tmpDir, heiyan.outputFilename("male", date));
    const femalePath = path.join(tmpDir, heiyan.outputFilename("female", date));
    console.log = () => {};
    try {
      heiyan.buildAndSave(books, 2, [books[0]], malePath);
      heiyan.buildAndSave(books, 2, [books[1]], femalePath);
    } finally {
      console.log = origLog;
    }
    assert(fs.existsSync(malePath), "男频报告不应被女频采集覆盖");
    assert(fs.existsSync(femalePath), "女频报告必须独立落盘");
    assert(fs.readFileSync(malePath, "utf8").includes("甲书"));
    assert(fs.readFileSync(femalePath, "utf8").includes("乙书"));

    // 缺作者：聚合按位置认「作者 · 题材」，不占位题材会被当成作者、书掉进分组名
    const noAuthorDir = path.join(tmpDir, "no-author");
    const noAuthorPath = path.join(noAuthorDir, heiyan.outputFilename("female", date));
    fs.mkdirSync(noAuthorDir);
    const noAuthor = [
      { name: "丙书", userName: "作者丙", classifyStr: "女频", typeDesc: "虐恋", words: 32000 },
      { name: "丁书", userName: "", classifyStr: "女频", typeDesc: "复仇", words: 28000 },
      { name: "戊书", classifyStr: "女频", typeDesc: "虐恋", words: 30000 },
    ];
    console.log = () => {};
    try {
      heiyan.buildAndSave(noAuthor, 3, noAuthor, noAuthorPath, false);
    } finally {
      console.log = origLog;
    }
    const noAuthorText = fs.readFileSync(noAuthorPath, "utf8");
    assert(noAuthorText.includes("*佚名 · 女频/复仇 · 28,000字 · 未公开*"), noAuthorText);
    assert(noAuthorText.includes("- 已采集：3 条（1 页）"), `页数按实际取到的条数算: ${noAuthorText}`);
    assert(noAuthorText.includes("- 数据质量：[仅列表-无核心指标]"), noAuthorText);
    const agg = spawnSync(
      process.execPath,
      [path.join(repoRoot, "skills/story-short-scan/scripts/aggregate-rank.js"), noAuthorDir, "--scale", "short", "--json"],
      { cwd: repoRoot, encoding: "utf8", timeout: 10000 }
    );
    assert.strictEqual(agg.status, 0, agg.stderr);
    const hy = JSON.parse(agg.stdout).platforms.find((p) => p.platform === "黑岩");
    assert.deepStrictEqual(
      hy.genres.map((g) => g.name).sort(),
      ["复仇", "虐恋"],
      `缺作者的书题材不能丢: ${JSON.stringify(hy.genres)}`
    );
    const aggMd = spawnSync(
      process.execPath,
      [path.join(repoRoot, "skills/story-short-scan/scripts/aggregate-rank.js"), noAuthorDir, "--scale", "short"],
      { cwd: repoRoot, encoding: "utf8", timeout: 10000 }
    );
    assert.match(aggMd.stdout, /黑岩 · 书库列表：3 条，\d{4}-\d{2}-\d{2}，只有书单，缺热度等关键数字/);

    // 数据质量：列表模式只有书单；--detail 按详情取到几成定级，取值都在聚合的白话表里
    const withDetail = (n, ok) => Array.from({ length: n }, (_, i) => ({ detailOk: i < ok }));
    assert.strictEqual(heiyan.dataQuality(withDetail(4, 4), false), "[仅列表-无核心指标]");
    assert.strictEqual(heiyan.dataQuality(withDetail(4, 4), true), "[OK]");
    assert.strictEqual(heiyan.dataQuality(withDetail(4, 3), true), "[部分详情缺失]");
    assert.strictEqual(heiyan.dataQuality(withDetail(4, 1), true), "[详情解析异常/登录态缺失]");
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
}

// ---------------------------------------------------------------------------
// setup-cdp-chrome.js 的 --reset 闸门夹具。
// 全程只碰 127.0.0.1 上一个临时端口，不发外部请求、不碰真 Chrome：
//   fake-cdp.js          只答 /json/version 的假 CDP 端点，identity 由 --id 决定
//   fake-chrome-*.js     假 Chrome：立刻退出 / 起一个新 identity 的端点并常驻
//   cdp-preload.js       把脚本对系统的三处依赖换掉——Chrome 可执行路径的探测、
//                        spawn 的目标、以及 pgrep/pkill（tasklist/taskkill）的语义
// 进程存活一律走文件标记，不用真信号，Windows 上同样成立。
// ---------------------------------------------------------------------------

const FAKE_CDP = `"use strict";
const fs = require("fs");
const http = require("http");
function arg(name, def) {
  const i = process.argv.indexOf(name);
  if (i > -1 && process.argv[i + 1] !== undefined) return process.argv[i + 1];
  for (const a of process.argv) if (a.startsWith(name + "=")) return a.slice(name.length + 1);
  return def;
}
const id = arg("--id", "fake-cdp");
const portfile = arg("--portfile", null);
const stopfile = arg("--stopfile", null);
const status = Number(arg("--status", 200));
const body = arg("--body", null);
// --no-identity：照答 /json/version，但不给 webSocketDebuggerUrl，模拟「身份取不到」
const noIdentity = process.argv.indexOf("--no-identity") > -1;
let port = Number(arg("--port", arg("--remote-debugging-port", 0)));
if (!Number.isInteger(port) || port < 0) port = 0;
const server = http.createServer((req, res) => {
  if (req.url !== "/json/version") { res.writeHead(404); res.end("nope"); return; }
  res.writeHead(status, { "Content-Type": "application/json" });
  const payload = { Browser: id, "Protocol-Version": "1.3" };
  if (!noIdentity) {
    payload.webSocketDebuggerUrl =
      "ws://127.0.0.1:" + server.address().port + "/devtools/browser/" + id;
  }
  res.end(body === null ? JSON.stringify(payload) : body);
});
server.listen(port, "127.0.0.1", () => {
  if (portfile) fs.writeFileSync(portfile, String(server.address().port), "utf8");
});
// 停机也走文件标记：跨平台，不依赖真信号
if (stopfile) setInterval(() => { if (fs.existsSync(stopfile)) process.exit(0); }, 50);
`;

const FAKE_CHROME_DIES = `process.exit(0);\n`;

const FAKE_CHROME_FRESH = `"use strict";
const path = require("path");
let port = 0;
for (const a of process.argv) {
  const m = a.match(/^--remote-debugging-port=(\\d+)$/);
  if (m) port = Number(m[1]);
}
// 用自己的 stopfile（H_STOPFILE 那个在 pkill 时就写过了，会让新端点一起来就退）
process.argv = [process.argv[0], "fake-cdp", "--port", String(port),
  "--id", "fresh-launched-cdp", "--stopfile", process.env.H_STOPFILE_NEW];
require(path.join(__dirname, "fake-cdp.js"));
`;

// 假 Chrome：把端点甩给一个脱离的孙进程，自己立刻退出。spawn 出来的 pid 死了，
// 但端口上有个「新身份」的端点在应答——identity 检查挡不住，只能靠 pid 存活检查挡。
const FAKE_CHROME_ORPHAN = `"use strict";
const path = require("path");
const { spawn } = require("child_process");
let port = 0;
for (const a of process.argv) {
  const m = a.match(/^--remote-debugging-port=(\\d+)$/);
  if (m) port = Number(m[1]);
}
const child = spawn(
  process.execPath,
  [path.join(__dirname, "fake-cdp.js"), "--port", String(port),
   "--remote-debugging-port=" + String(port) + "0", "--id", "foreign-orphan-cdp",
   "--stopfile", process.env.H_STOPFILE_NEW],
  { detached: true, stdio: "ignore" }
);
child.unref();
setTimeout(() => process.exit(0), 300);
`;

// 同上，但 launcher 常驻——这就是复审给的最小变异。于是「旧端点消失过 + 身份变了 +
// spawn 出的进程还活着」三条间接证据全成立，而端口其实握在另一个进程手里。
// 光靠这三条推不出「端口归它」，只有把端口和进程真正绑上的检查才拦得住。
const FAKE_CHROME_FOREIGN_ALIVE = `"use strict";
const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");
let port = 0;
for (const a of process.argv) {
  const m = a.match(/^--remote-debugging-port=(\\d+)$/);
  if (m) port = Number(m[1]);
}
const child = spawn(
  process.execPath,
  [path.join(__dirname, "fake-cdp.js"), "--port", String(port), "--id", "foreign-orphan-cdp",
   "--stopfile", process.env.H_STOPFILE_NEW],
  { detached: true, stdio: "ignore" }
);
child.unref();
// 变异点：launcher 不退出，只在测试收尾写 stopfile 时才退
setInterval(() => { if (fs.existsSync(process.env.H_STOPFILE_NEW)) process.exit(0); }, 50);
`;

// 端口被一个「不在本次 spawn 的进程树里」的进程握着，而 launcher 照样活着。
// 两级 spawn：中间那层立刻退出，端点进程被 init 收养，脱离本次启动的进程树。
// 它还故意带上和本次启动一模一样的 --remote-debugging-port=<port>，唯一的区别就是
// 「不是我们起的」——这条测的正是 pid 归属本身。
const FAKE_CHROME_OUTSIDE_TREE = `"use strict";
const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");
let port = 0;
for (const a of process.argv) {
  const m = a.match(/^--remote-debugging-port=(\\d+)$/);
  if (m) port = Number(m[1]);
}
const relay = spawn(
  process.execPath,
  ["-e",
   "const {spawn}=require('child_process');" +
   "const c=spawn(process.argv[1],process.argv.slice(2),{detached:true,stdio:'ignore'});" +
   "c.unref();process.exit(0);",
   process.execPath,
   path.join(__dirname, "fake-cdp.js"), "--remote-debugging-port=" + port,
   "--id", "outside-tree-cdp", "--stopfile", process.env.H_STOPFILE_NEW],
  { detached: true, stdio: "ignore" }
);
relay.unref();
setInterval(() => { if (fs.existsSync(process.env.H_STOPFILE_NEW)) process.exit(0); }, 50);
`;

// 真 Chrome 的常见形态：launcher 自己不监听，端口由它拉起来的 browser 进程持有
// （macOS 上启动的二进制还可能 re-exec）。这个子进程继承了本次启动的
// --remote-debugging-port，人也在 spawn 出来的进程树里——归属校验必须认这种形态，
// 否则真实启动会被误杀。这是归属校验的假阴性守卫。
const FAKE_CHROME_CHILD_BROWSER = `"use strict";
const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");
let port = 0;
for (const a of process.argv) {
  const m = a.match(/^--remote-debugging-port=(\\d+)$/);
  if (m) port = Number(m[1]);
}
spawn(
  process.execPath,
  [path.join(__dirname, "fake-cdp.js"), "--remote-debugging-port=" + port,
   "--id", "child-browser-cdp", "--stopfile", process.env.H_STOPFILE_NEW],
  { stdio: "ignore" }
);
setInterval(() => { if (fs.existsSync(process.env.H_STOPFILE_NEW)) process.exit(0); }, 50);
`;

// 端口由 launcher 本进程亲自绑住（归属这条是真成立的），但 /json/version 里没有
// webSocketDebuggerUrl——cdpIdentity() 返回 null。按它自己的合约，null 只能当「无法比对」。
const FAKE_CHROME_NO_IDENTITY = `"use strict";
const path = require("path");
let port = 0;
for (const a of process.argv) {
  const m = a.match(/^--remote-debugging-port=(\\d+)$/);
  if (m) port = Number(m[1]);
}
process.argv = [process.argv[0], "fake-cdp", "--port", String(port), "--id", "no-identity-cdp",
  "--no-identity", "--stopfile", process.env.H_STOPFILE_NEW];
require(path.join(__dirname, "fake-cdp.js"));
`;

const CDP_PRELOAD = `"use strict";
const fs = require("fs");
const cp = require("child_process");
// Chrome 可执行文件的候选路径是按平台硬编码的，这里按「长得像 Chrome 可执行文件」来认，
// 不必在测试里重抄一份平台表
const CHROME_RE = /(?:Google Chrome|google-chrome(?:-stable)?|chrome\\.exe)$/;
const realExistsSync = fs.existsSync;
fs.existsSync = function (p) {
  if (typeof p === "string" && CHROME_RE.test(p)) return true;
  return realExistsSync.call(fs, p);
};
const realSpawn = cp.spawn;
cp.spawn = function (file, args, opts) {
  if (typeof file === "string" && CHROME_RE.test(file)) {
    return realSpawn.call(cp, process.execPath, [process.env.H_FAKE_CHROME, ...(args || [])], opts);
  }
  return realSpawn.call(cp, file, args, opts);
};
const realExecSync = cp.execSync;
cp.execSync = function (cmd, opts) {
  if (/^(pgrep|tasklist)/.test(cmd)) {
    if (process.env.H_PIDS === "old" && !realExistsSync.call(fs, process.env.H_KILLED_MARK)) {
      return process.platform === "win32" ? '"chrome.exe","424242"' : "424242\\n";
    }
    const e = new Error("no process found"); // pgrep 找不到进程时的真实行为：非零退出
    e.status = 1;
    throw e;
  }
  if (/^pkill/.test(cmd) || /^taskkill\\s+\\/F\\s+\\/IM\\s+chrome\\.exe/i.test(cmd)) {
    fs.writeFileSync(process.env.H_KILLED_MARK, "killed", "utf8");
    // kill 生效的场景才真的让旧端点停下来；noop 场景模拟「kill 没起作用」
    if (process.env.H_KILL === "real") fs.writeFileSync(process.env.H_STOPFILE, "stop", "utf8");
    return "";
  }
  return realExecSync.call(cp, cmd, opts);
};
`;

/**
 * 跑一次 setup-cdp-chrome.js。scenario 决定 pgrep/pkill 语义与假 Chrome 行为。
 * 返回 { status, stdout, stderr, sentinelSurvived, debugProfileSurvived }。
 */
function runSetupCdp(scenario, versionBody) {
  const setup = path.join(
    repoRoot,
    "skills/browser-cdp/scripts/setup-cdp-chrome.js"
  );
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "story-cdp-reset-"));
  let oldCdp = null;
  let port = null;
  try {
    for (const [name, body] of [
      ["fake-cdp.js", FAKE_CDP],
      ["fake-chrome-dies.js", FAKE_CHROME_DIES],
      ["fake-chrome-fresh.js", FAKE_CHROME_FRESH],
      ["fake-chrome-orphan.js", FAKE_CHROME_ORPHAN],
      ["fake-chrome-foreign-alive.js", FAKE_CHROME_FOREIGN_ALIVE],
      ["fake-chrome-outside-tree.js", FAKE_CHROME_OUTSIDE_TREE],
      ["fake-chrome-child-browser.js", FAKE_CHROME_CHILD_BROWSER],
      ["fake-chrome-no-identity.js", FAKE_CHROME_NO_IDENTITY],
      ["cdp-preload.js", CDP_PRELOAD],
    ]) {
      fs.writeFileSync(path.join(tmpDir, name), body, "utf8");
    }

    // 假 HOME：源 profile + 一个已存在的 debug profile（里面的哨兵文件用来证明中止时没被删）
    const home = path.join(tmpDir, "home");
    const srcDefault = path.join(
      home,
      process.platform === "darwin"
        ? "Library/Application Support/Google/Chrome/Default"
        : process.platform === "win32"
          ? "AppData/Local/Google/Chrome/User Data/Default"
          : ".config/google-chrome/Default"
    );
    fs.mkdirSync(srcDefault, { recursive: true });
    fs.writeFileSync(path.join(srcDefault, "Cookies"), "src-cookies", "utf8");
    const debugProfile = path.join(home, "chrome-debug-profile");
    fs.mkdirSync(path.join(debugProfile, "Default"), { recursive: true });
    const sentinel = path.join(debugProfile, "SENTINEL");
    fs.writeFileSync(sentinel, "must-survive-an-abort", "utf8");

    const plan = {
      staleHolder: { args: ["--reset", "--yes"], pids: "empty", kill: "noop", chrome: "fake-chrome-dies.js" },
      unhealthyHolder: { args: ["--reset", "--yes"], pids: "empty", kill: "noop", chrome: "fake-chrome-dies.js", oldStatus: 500 },
      genuineReset: { args: ["--reset", "--yes"], pids: "old", kill: "real", chrome: "fake-chrome-fresh.js" },
      plainReuse: { args: [], pids: "empty", kill: "noop", chrome: "fake-chrome-dies.js" },
      detectOnly: { args: ["--detect-only"], pids: "empty", kill: "noop", chrome: "fake-chrome-dies.js" },
      redirectedDetect: { args: ["--detect-only"], pids: "empty", kill: "noop", chrome: "fake-chrome-dies.js", oldStatus: 302 },
      orphanEndpoint: { args: ["--reset", "--yes"], pids: "old", kill: "real", chrome: "fake-chrome-orphan.js" },
      foreignHeldPort: { args: ["--reset", "--yes"], pids: "old", kill: "real", chrome: "fake-chrome-foreign-alive.js" },
      outsideTreeHolder: { args: ["--reset", "--yes"], pids: "old", kill: "real", chrome: "fake-chrome-outside-tree.js" },
      childHoldsPort: { args: ["--reset", "--yes"], pids: "old", kill: "real", chrome: "fake-chrome-child-browser.js" },
      nullIdentity: { args: ["--reset", "--yes"], pids: "old", kill: "real", chrome: "fake-chrome-no-identity.js" },
    }[scenario];
    assert(plan, `harness: 未知场景 ${scenario}`);

    // 起「旧 CDP」，让它自己挑端口并报回来——测试之间不会抢固定端口
    const portfile = path.join(tmpDir, "port");
    const stopfile = path.join(tmpDir, "stop");
    oldCdp = spawn(
      process.execPath,
      [
        path.join(tmpDir, "fake-cdp.js"),
        "--port", "0",
        "--id", "stale-existing-cdp",
        "--portfile", portfile,
        "--stopfile", stopfile,
        "--status", String(plan.oldStatus || 200),
        ...(versionBody === undefined ? [] : ["--body", versionBody]),
      ],
      { stdio: "ignore" }
    );
    for (let i = 0; i < 200 && port === null; i++) {
      sleepSyncMs(50);
      if (fs.existsSync(portfile)) port = fs.readFileSync(portfile, "utf8").trim();
    }
    assert(port, "harness: 假旧 CDP 没起来");

    const result = spawnSync(
      process.execPath,
      ["--require", path.join(tmpDir, "cdp-preload.js"), setup, port, ...plan.args],
      {
        cwd: repoRoot,
        encoding: "utf8",
        timeout: 120000,
        env: {
          ...process.env,
          HOME: home,
          USERPROFILE: home,
          LOCALAPPDATA: path.join(home, "AppData", "Local"),
          H_FAKE_CHROME: path.join(tmpDir, plan.chrome),
          H_PIDS: plan.pids,
          H_KILL: plan.kill,
          H_KILLED_MARK: path.join(tmpDir, "killed"),
          H_STOPFILE: stopfile,
          H_STOPFILE_NEW: path.join(tmpDir, "stop-new"),
        },
      }
    );
    return {
      ...result,
      port,
      sentinelSurvived: fs.existsSync(sentinel),
      debugProfileSurvived: fs.existsSync(debugProfile),
      listenerAliveBeforeCleanup: canConnectTcp(port),
    };
  } finally {
    // 收掉旧端点和假 Chrome 留下的常驻端点：先让它们自己按 stopfile 退（跨平台可靠），
    // 再用 lsof/netstat 兜底，最后才删目录
    for (const f of ["stop", "stop-new"]) {
      try { fs.writeFileSync(path.join(tmpDir, f), "stop", "utf8"); } catch {}
    }
    if (oldCdp && oldCdp.pid) { try { process.kill(oldCdp.pid); } catch {} }
    sleepSyncMs(300);
    if (port) killPortListener(port);
    sleepSyncMs(200);
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
}

function sleepSyncMs(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

/** 同步探测 TCP 端口，专门用于在 harness finally 清理前观察被测脚本是否收掉了启动树。 */
function canConnectTcp(port) {
  const probe = spawnSync(
    process.execPath,
    [
      "-e",
      "const net=require('net');const s=net.createConnection({host:'127.0.0.1',port:Number(process.argv[1])});" +
        "s.setTimeout(500);s.once('connect',()=>{s.destroy();process.exit(0)});" +
        "s.once('error',()=>process.exit(1));s.once('timeout',()=>{s.destroy();process.exit(1)});",
      String(port),
    ],
    { stdio: "ignore", timeout: 2000 }
  );
  return probe.status === 0;
}

/** 收掉测试期间还占着端口的假端点（尽力而为，失败不影响断言） */
function killPortListener(port) {
  try {
    const out =
      process.platform === "win32"
        ? spawnSync("netstat", ["-ano", "-p", "tcp"], { encoding: "utf8" }).stdout || ""
        : spawnSync("lsof", ["-ti", `tcp:${port}`, "-sTCP:LISTEN"], { encoding: "utf8" }).stdout || "";
    const pids = new Set();
    if (process.platform === "win32") {
      for (const line of out.split("\n")) {
        const m = line.match(new RegExp(`:${port}\\s+\\S+\\s+LISTENING\\s+(\\d+)`));
        if (m) pids.add(Number(m[1]));
      }
    } else {
      for (const line of out.split("\n")) {
        const n = Number(line.trim());
        if (n > 0) pids.add(n);
      }
    }
    for (const pid of pids) { try { process.kill(pid, "SIGKILL"); } catch {} }
  } catch {}
}

// 回归点：--reset 撞上一个关不掉的旧 CDP 时，绝不许报「重建成功」。
// 老行为是最坏的一种结果——照样删 debug profile、照样启动，然后 probeCDP 被旧端点答上，
// exit 0 报成功，调用方以为拿到了新浏览器，之后每一次采集读的都是旧会话。
function testCdpResetRefusesStaleEndpoint() {
  const run = runSetupCdp("staleHolder");

  assert.strictEqual(
    run.status,
    1,
    `关不掉的旧 CDP 必须让 --reset 非零退出，实际 ${run.status}:\n${run.stdout}\n${run.stderr}`
  );
  assert.match(run.stderr, /仍在应答，已中止/);
  // 端口被无法识别的进程占用：必须点名说清，不能静默复用
  assert.match(run.stderr, /端口被无法识别的进程占用/);

  // 闸门在动 profile 之前——删一个还在跑的 Chrome 的 profile 本身就是破坏性的
  assert(
    run.sentinelSurvived,
    "中止时不许删 debug profile（哨兵文件必须还在）"
  );
  assert(run.debugProfileSurvived, "中止时 debug profile 目录必须保留");
  assert(
    !/正在删除 debug profile/.test(run.stdout),
    `中止路径上不该走到删 profile:\n${run.stdout}`
  );
  assert(
    !/正在以 CDP 模式启动 Chrome/.test(run.stdout),
    `端口没空出来就不该启动 Chrome:\n${run.stdout}`
  );
  assert(
    !/已成功以 CDP 模式启动/.test(run.stdout),
    `绝不许报成功:\n${run.stdout}`
  );
  // 旧端点的响应也不该被当成「新实例」打出来
  assert(
    !run.stdout.includes("stale-existing-cdp"),
    `不该把旧实例的 /json/version 当成结果输出:\n${run.stdout}`
  );
}

// 回归点：/json/version 返回 500 时 probeCDP 为 null，但 TCP 端口仍被旧服务占着。
// “不是健康 CDP”绝不等于“端口空闲”；破坏 profile 之前必须用原始 TCP 探测确认端口已释放。
function testCdpResetRefusesUnhealthyTcpHolder() {
  const run = runSetupCdp("unhealthyHolder");
  assert.strictEqual(
    run.status,
    1,
    `旧端口仍监听但 /json/version=500 时必须非零退出:\n${run.stdout}\n${run.stderr}`
  );
  assert(run.sentinelSurvived, "不健康监听者仍占端口时不许删除 debug profile");
  assert(run.debugProfileSurvived, "不健康监听者仍占端口时 debug profile 必须保留");
  assert(!/正在删除 debug profile/.test(run.stdout), run.stdout);
  assert(!/正在以 CDP 模式启动 Chrome/.test(run.stdout), run.stdout);
  assert.match(run.stderr, /端口.*仍被占用|端口.*未释放/);
}

// 反向：端口真的空出来、新实例真的起来了（端口就绑在 spawn 出来的那个进程上，
// 命令行里带着本次的 --remote-debugging-port），--reset 照样成功——闸门不是把功能关掉。
// 这一条同时是归属校验的假阳性守卫：lsof/ps 查出来的持有者必须真能匹配上本次启动。
function testCdpResetSucceedsWhenPortActuallyFrees() {
  const run = runSetupCdp("genuineReset");
  assert.strictEqual(
    run.status,
    0,
    `旧端点确实消失 + 新端点起来了，--reset 必须成功:\n${run.stdout}\n${run.stderr}`
  );
  assert(
    !/CDP_OWNER_|CDP_PORT_NOT_OURS|CDP_IDENTITY_UNVERIFIABLE/.test(run.stderr),
    `真实启动不许被归属/身份校验误杀:\n${run.stderr}`
  );
  assert.match(run.stdout, /已释放/);
  assert.match(run.stdout, /正在删除 debug profile/);
  assert.match(run.stdout, /已成功以 CDP 模式启动/);
  // 报出来的必须是新实例的身份，不是重建前那个
  assert(run.stdout.includes("fresh-launched-cdp"), run.stdout);
  assert(!run.stdout.includes("stale-existing-cdp"), run.stdout);
}

function testCdpRequiresVersionMetadata() {
  const valid = runSetupCdp("detectOnly");
  assert.strictEqual(valid.status, 0, valid.stderr);
  assert.match(valid.stdout, /^CDP_STATUS=ready$/m);
  for (const body of [
    "not a CDP endpoint",
    JSON.stringify({}),
    JSON.stringify({ Browser: "Chrome/148", webSocketDebuggerUrl: 123 }),
    JSON.stringify({ webSocketDebuggerUrl: "ws://127.0.0.1:9222/devtools/browser/id" }),
    JSON.stringify({ Browser: "Chrome/148", webSocketDebuggerUrl: "https://127.0.0.1/devtools/browser/id" }),
    JSON.stringify({ Browser: "Chrome/148", webSocketDebuggerUrl: "ws://127.0.0.1/devtools/page/id" }),
  ]) {
    const detected = runSetupCdp("detectOnly", body);
    assert.strictEqual(detected.status, 0, detected.stderr);
    assert.match(detected.stdout, /^CDP_STATUS=needs-setup$/m);
    assert.doesNotMatch(detected.stdout, /^CDP_STATUS=ready$/m);
    assert(detected.sentinelSurvived && detected.listenerAliveBeforeCleanup);
  }
  const redirect = runSetupCdp("redirectedDetect");
  assert.match(redirect.stdout, /^CDP_STATUS=needs-setup$/m);
  const reused = runSetupCdp("plainReuse", "ordinary HTTP server");
  assert.strictEqual(reused.status, 1, reused.stdout + reused.stderr);
  assert(reused.sentinelSurvived && reused.listenerAliveBeforeCleanup);
}

// 不带 --reset/--profile 的复用快路径必须一字不变：直接复用现有 CDP、立刻退出 0
function testCdpPlainReuseUnchanged() {
  const run = runSetupCdp("plainReuse");
  assert.strictEqual(run.status, 0, `复用路径必须成功:\n${run.stdout}\n${run.stderr}`);
  assert.match(run.stdout, /CDP 已就绪，复用现有 Chrome。/);
  assert(run.stdout.includes("stale-existing-cdp"), run.stdout);
  // 复用就是复用：不许杀进程、不许动 profile、不许启动
  assert(run.sentinelSurvived, "复用路径不许动 debug profile");
  assert(!/正在停止/.test(run.stdout), run.stdout);
  assert(!/正在删除 debug profile/.test(run.stdout), run.stdout);
  assert(!/正在以 CDP 模式启动 Chrome/.test(run.stdout), run.stdout);
  // 复用快路径没有「本次启动的实例」可言，归属/身份校验一概不该在这里跑
  assert(
    !/CDP_OWNER_|CDP_PORT_NOT_OURS|CDP_IDENTITY_UNVERIFIABLE/.test(run.stderr),
    `复用快路径不该跑启动后的归属/身份校验:\n${run.stderr}`
  );
}

// 端口空出来了，但刚 spawn 的 Chrome 死了、端口被另一个进程接手：identity 变了也不算成功
function testCdpRejectsEndpointNotFromThisLaunch() {
  const run = runSetupCdp("orphanEndpoint");
  assert.strictEqual(
    run.status,
    1,
    `应答的端点不属于本次启动，必须非零退出:\n${run.stdout}\n${run.stderr}`
  );
  assert.match(run.stderr, /刚启动的 Chrome（pid \d+）已经退出/);
  assert.match(run.stderr, /这个端点不属于本次启动的实例/);
  assert(
    !/已成功以 CDP 模式启动/.test(run.stdout),
    `不许把别人的端点报成启动成功:\n${run.stdout}`
  );
  assert(
    !run.stdout.includes("foreign-orphan-cdp"),
    `不该把外来端点的 /json/version 当成结果输出:\n${run.stdout}`
  );
}

// 回归点：launcher 活着，但端口握在它 detach 出去的另一个进程手里。
// 「旧端点消失过 + 身份变了 + spawn 的进程还活着」这三条间接证据全成立——推不出「端口归它」。
// 必须真的把端口和本次启动的实例绑上：LISTEN 持有者要在这棵进程树里，且树里确有一个
// 带着本次的 --remote-debugging-port 的持有者。否则拿到的就是别人的登录态。
function testCdpRejectsForeignHolderWhileLauncherAlive() {
  const run = runSetupCdp("foreignHeldPort");

  assert.strictEqual(
    run.status,
    1,
    `端口握在别的进程手里（哪怕 launcher 还活着）必须非零退出，实际 ${run.status}:\n${run.stdout}\n${run.stderr}`
  );
  // 查得出归属就点名 NOT_LAUNCHED_INSTANCE；查不出来（本机没有 lsof/ps 一类工具）也只能
  // UNVERIFIABLE 硬失败——两条都是「证不出来就不放行」，唯独不许 exit 0。
  assert.match(
    run.stderr,
    /CDP_OWNER_NOT_LAUNCHED_INSTANCE|CDP_OWNER_UNVERIFIABLE/,
    `必须点名说清为什么不认这个端点:\n${run.stderr}`
  );
  // 这次 launcher 是活着的：不许靠「进程已退出」那条老分支蒙对
  assert(
    !/已经退出/.test(run.stderr),
    `launcher 活着时不该走到「进程已退出」分支:\n${run.stderr}`
  );
  assert(
    !/已成功以 CDP 模式启动/.test(run.stdout),
    `不许把别人握着的端口报成启动成功:\n${run.stdout}`
  );
  assert(
    !run.stdout.includes("foreign-orphan-cdp"),
    `不该把外来端点的 /json/version 当成结果输出:\n${run.stdout}`
  );
  assert(
    !run.listenerAliveBeforeCleanup,
    "启动后归属校验失败时必须清理整棵本次启动的进程树，不能只杀 launcher 留下 detached listener"
  );
}

// 回归点：端口被一个不在本次 spawn 进程树里的进程握着（launcher 照样活着），
// 而且那个进程带着和本次一模一样的 --remote-debugging-port——唯一的区别就是「不是我们起的」。
// 这一条测的正是 pid 归属本身。
function testCdpRejectsPortHeldOutsideSpawnedTree() {
  const run = runSetupCdp("outsideTreeHolder");

  assert.strictEqual(
    run.status,
    1,
    `端口持有者不在本次启动的进程树里必须非零退出，实际 ${run.status}:\n${run.stdout}\n${run.stderr}`
  );
  assert.match(
    run.stderr,
    /CDP_PORT_NOT_OURS|CDP_OWNER_UNVERIFIABLE/,
    `必须点名说清为什么不认这个端点:\n${run.stderr}`
  );
  assert(
    !/已成功以 CDP 模式启动/.test(run.stdout),
    `不许把树外进程握着的端口报成启动成功:\n${run.stdout}`
  );
  assert(
    !run.stdout.includes("outside-tree-cdp"),
    `不该把树外端点的 /json/version 当成结果输出:\n${run.stdout}`
  );
}

// 反向：真 Chrome 常常不是 launcher 自己监听，而是它拉起来的 browser 进程持有端口
// （macOS 上还可能 re-exec）。树里更深一层的持有者必须照样算成功——归属校验是拦别人的，
// 不是把真实启动拦掉。
function testCdpAcceptsPortHeldByLaunchedChildProcess() {
  const run = runSetupCdp("childHoldsPort");

  assert.strictEqual(
    run.status,
    0,
    `端口由本次启动拉起的子进程持有，必须算成功:\n${run.stdout}\n${run.stderr}`
  );
  assert.match(run.stdout, /已成功以 CDP 模式启动/);
  assert(run.stdout.includes("child-browser-cdp"), run.stdout);
  assert(
    !/CDP_OWNER_|CDP_PORT_NOT_OURS|CDP_IDENTITY_UNVERIFIABLE/.test(run.stderr),
    `进程树里更深一层的持有者不许被误杀:\n${run.stderr}`
  );
}

// 回归点：/json/version 应答里取不到实例身份时，cdpIdentity() 返回 null。
// 它的合约写死了 null 只能当「无法比对」——既不是相同也不是不同。放它过去就等于
// 把「证明不了」当成「证明了」，所以必须硬失败，哪怕端口归属这条其实是成立的。
function testCdpRejectsUnverifiableIdentity() {
  const run = runSetupCdp("nullIdentity");

  assert.strictEqual(
    run.status,
    1,
    `取不到实例身份必须非零退出，实际 ${run.status}:\n${run.stdout}\n${run.stderr}`
  );
  assert.match(run.stderr, /CDP_IDENTITY_UNVERIFIABLE/);
  assert.match(run.stderr, /取不到实例身份/);
  assert(
    !/已成功以 CDP 模式启动/.test(run.stdout),
    `身份没证出来就不许报成功:\n${run.stdout}`
  );
  assert(
    !run.stdout.includes("no-identity-cdp"),
    `不该把没身份的端点当成结果输出:\n${run.stdout}`
  );
}

// 起点排行榜、刺猬猫：文件头要有「数据质量」，聚合的「采集情况」才不会显示「质量未标」
function testRankQualityHeaders() {
  const qidian = loadFresh(QD_SCRAPER);
  const ok = qidian.renderMarkdown(
    { label: "月票榜" },
    [
      { rank: 1, title: "甲", author: "a", genre: "玄幻·东方玄幻", words: "12万字" },
      { rank: 2, title: "乙", author: "b", genre: "都市·都市生活", words: "" },
    ],
    "https://m.qidian.com/rank/yuepiao/",
    "mobile-ssr"
  );
  assert.match(ok, /- 数据质量：\[OK\]\n- 问题摘要：无\n/);
  const broken = qidian.renderMarkdown(
    { label: "月票榜" },
    [
      { rank: 1, title: "甲", author: "a", genre: "玄幻·东方玄幻", words: "12万字" },
      { rank: 2, title: "乙", author: "b", genre: "", words: "8万字" },
      { rank: 3, title: "丙", author: "c", genre: "", words: "9万字" },
    ],
    "https://m.qidian.com/rank/yuepiao/",
    "mobile-ssr"
  );
  assert.match(broken, /- 数据质量：\[存在问题\]\n- 问题摘要：题材缺失 2 \/ 3 条\n/);
  const library = qidian.renderMarkdown(
    { label: "男频书库人气新书" },
    [{ rank: 1, title: "甲", library: true }],
    "https://www.qidian.com/all/action0-size1-update1/",
    "cdp-pc",
    ["- 数据质量：[OK]", "- 问题摘要：无"]
  );
  assert.strictEqual((library.match(/数据质量/g) || []).length, 1, "书库新书自带质量行，不能再加一份");

  const ciweimao = loadFresh(path.join(repoRoot, "skills/story-long-scan/scripts/ciweimao-rank-scraper.js"));
  const full = Array.from({ length: 10 }, (_, i) =>
    i === 0
      ? { rank: 1, title: "书1", author: "猫作者", metric: "1.2万" }
      : { rank: i + 1, title: `书${i + 1}`, genre: "同人", metric: "9876" }
  );
  const urls = full.map((e) => ({ title: e.title, url: `https://www.ciweimao.com/book/${e.rank}` }));
  const good = ciweimao.renderRankFile({ label: "月票榜" }, full, urls, "2026-10-17T02:00:00.000Z");
  assert.match(good, /- 数据质量：\[OK\]\n- 问题摘要：无\n/);
  assert(good.includes("### #1 书1\n*猫作者 · 1.2万*\n[作品页](https://www.ciweimao.com/book/1)"), good);
  assert(good.includes("### #2 书2\n*同人 · 9876*"), good);
  const thin = ciweimao.renderRankFile({ label: "月票榜" }, full.slice(0, 3), [], "2026-10-17T02:00:00.000Z");
  assert.match(thin, /- 数据质量：\[存在问题\]\n- 问题摘要：只解析到 3 条（每榜 10 条）；作品页链接只匹配到 0 \/ 3 条\n/);
}

testCdpUtils(longUtilsPath);
testWindowsInvocationBuilder(longUtilsPath);
testLocalDateStamp(longUtilsPath);
testScraperImports();
testCliResultGate(longUtilsPath);
testJjwxcDetailFailureIsolation();
testQidianRankIsolation();
testQidianFieldContractAndDescriptionLimit();
testRankQualityHeaders();
testQidianCaptchaCheckIgnoresBookText();
testQidianLibraryFontDecoding();
testQidianLibraryPagingE2E();
testQimaoPeriodPlan();
testQimaoPartialTargetStatus();
testCiweimaoPartialTargetStatus();
testQimaoLibraryPagedCollection();
testQimaoLibraryPageFailures();
testQimaoLibraryFallbacksAndQuality();
testQimaoLibraryArgumentValidation();
testLongScanArgumentValidation();
testHeiyanFieldDriftAndWordFormat();
testCdpPlainReuseUnchanged();
testCdpRequiresVersionMetadata();
testCdpResetRefusesStaleEndpoint();
testCdpResetRefusesUnhealthyTcpHolder();
testCdpRejectsEndpointNotFromThisLaunch();
testCdpRejectsForeignHolderWhileLauncherAlive();
testCdpRejectsPortHeldOutsideSpawnedTree();
testCdpRejectsUnverifiableIdentity();
testCdpAcceptsPortHeldByLaunchedChildProcess();
testCdpResetSucceedsWhenPortActuallyFrees();
console.log("OK: scan runtime uses shell-safe CDP calls and side-effect-free scraper modules");
