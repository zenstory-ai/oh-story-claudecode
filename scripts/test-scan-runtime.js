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
  res.end(JSON.stringify(payload));
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
function runSetupCdp(scenario) {
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

testCdpUtils(longUtilsPath);
testWindowsInvocationBuilder(longUtilsPath);
testLocalDateStamp(longUtilsPath);
testScraperImports();
testCliResultGate(longUtilsPath);
testJjwxcDetailFailureIsolation();
testQidianRankIsolation();
testQidianFieldContractAndDescriptionLimit();
testQimaoPeriodPlan();
testQimaoPartialTargetStatus();
testLongScanArgumentValidation();
testHeiyanFieldDriftAndWordFormat();
testCdpPlainReuseUnchanged();
testCdpResetRefusesStaleEndpoint();
testCdpResetRefusesUnhealthyTcpHolder();
testCdpRejectsEndpointNotFromThisLaunch();
testCdpRejectsForeignHolderWhileLauncherAlive();
testCdpRejectsPortHeldOutsideSpawnedTree();
testCdpRejectsUnverifiableIdentity();
testCdpAcceptsPortHeldByLaunchedChildProcess();
testCdpResetSucceedsWhenPortActuallyFrees();
console.log("OK: scan runtime uses shell-safe CDP calls and side-effect-free scraper modules");
