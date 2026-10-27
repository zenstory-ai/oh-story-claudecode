#!/usr/bin/env node
// setup-cdp-chrome.js
// 准备带有 CDP（Chrome DevTools Protocol）调试功能的 Chrome 环境（跨平台）。
// 通过此脚本，agent-browser 可以复用用户的 Chrome 登录态。
//
// 用法:
//   node setup-cdp-chrome.js [port] [options]
//
// Options:
//   --detect-only            只探测当前状态（结构化输出），不做任何修改
//   --yes                    确认杀死现有 Chrome，跳过交互提示
//   --reset                  清空 ~/chrome-debug-profile 后重新复制
//   --profile <name>         使用指定 Chrome profile（默认: Default）
//   --dry-run                打印将执行的操作，不实际执行
//
// 说明：CDP 端口已在监听时默认直接复用现有 Chrome 并退出 0；但传了 --reset 或显式
//       --profile 时不复用——这两个参数就是要重建 debug profile（登录态过期即走这条路），
//       会先关闭现有 Chrome（非 TTY 下需 --yes，否则 exit 3 报 NEEDS_CONSENT）。
//       重建路径上有两道硬闸门：关完进程后端口必须真的不再应答（否则在动 profile 之前就
//       exit 1 中止，绝不删一个还在运行的 Chrome 的 profile）；启动后必须证明「端口上应答的
//       就是本次启动的实例」——身份取得到且与重建前不同、spawn 出的进程还活着、端口的 LISTEN
//       持有者全在这棵进程树里、且树里确有一个持有者带着本次的 --remote-debugging-port。
//       任何一条证不出来（含查不到）都拒绝报成功，避免把别人的会话当新浏览器交出去。
//
// 退出码:
//   0  成功 / detect-only 完成
//   1  通用错误（环境缺失、超时等）
//   2  用户拒绝（TTY 模式下回答 N）
//   3  需要同意但当前为非 TTY 且未传 --yes
//
// detect-only 结构化输出（stdout，每行 KEY=value）:
//   CDP_STATUS=ready|needs-setup
//   CDP_URL=...                    (仅当 ready)
//   BROWSER=...                    (仅当 ready)
//   CHROME_RUNNING=yes|no
//   CHROME_PID_COUNT=N             (仅当 CHROME_RUNNING=yes)

"use strict";

const { execSync, spawn } = require("child_process");
const fs = require("fs");
const http = require("http");
const net = require("net");
const os = require("os");
const path = require("path");
const readline = require("readline");

// ---------------------------------------------------------------------------
// 参数解析
// ---------------------------------------------------------------------------

function parseArgs(argv) {
  const flags = { dryRun: false, yes: false, detectOnly: false, reset: false };
  let profile = "Default";
  // 是否显式传了 --profile：默认值 "Default" 无法区分「没传」和「传了 Default」，
  // 而这两种情况在"CDP 已就绪"分支上的语义不同（复用 vs 按指定 profile 重建）
  let profileExplicit = false;
  let port = null;

  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    switch (a) {
      case "--dry-run": flags.dryRun = true; break;
      case "--yes": case "-y": flags.yes = true; break;
      case "--detect-only": flags.detectOnly = true; break;
      case "--reset": flags.reset = true; break;
      case "--profile":
        profile = argv[++i];
        if (!profile) {
          console.error("❌ --profile 需要一个参数（例如: --profile \"Profile 1\"）");
          process.exit(1);
        }
        profileExplicit = true;
        break;
      default:
        if (/^\d+$/.test(a)) {
          port = parseInt(a, 10);
        } else if (a.startsWith("--")) {
          console.error(`⚠️  未知参数: ${a}`);
        } else {
          console.error(`⚠️  忽略参数: ${a}`);
        }
    }
  }

  if (port === null) port = 9222;
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    console.error(`❌ 端口非法: ${port}。必须是 1-65535 的整数。`);
    process.exit(1);
  }

  return { flags, profile, profileExplicit, port };
}

const ARGS = parseArgs(process.argv.slice(2));
const CDP_PORT = ARGS.port;
const PLATFORM = os.platform();

// ---------------------------------------------------------------------------
// 平台配置映射
// ---------------------------------------------------------------------------

const PLATFORM_CONFIG = {
  darwin: {
    chromePaths: [
      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ],
    profileDir: path.join(
      os.homedir(),
      "Library",
      "Application Support",
      "Google",
      "Chrome"
    ),
    findChrome() {
      for (const p of this.chromePaths) if (fs.existsSync(p)) return p;
      return null;
    },
    listChromePids() {
      try {
        const out = execSync("pgrep -x 'Google Chrome'", { encoding: "utf-8" }).trim();
        return out.split("\n").map(Number).filter((n) => n > 0);
      } catch { return []; }
    },
    killChrome() {
      try { execSync("pkill -9 -x 'Google Chrome'", { stdio: "ignore" }); } catch {}
    },
  },
  win32: {
    chromePaths: [
      path.join(process.env["PROGRAMFILES(X86)"] || "", "Google", "Chrome", "Application", "chrome.exe"),
      path.join(process.env.PROGRAMFILES || "", "Google", "Chrome", "Application", "chrome.exe"),
      path.join(process.env.LOCALAPPDATA || "", "Google", "Chrome", "Application", "chrome.exe"),
    ],
    profileDir: path.join(
      process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local"),
      "Google", "Chrome", "User Data"
    ),
    findChrome() {
      for (const p of this.chromePaths) if (p && fs.existsSync(p)) return p;
      return null;
    },
    listChromePids() {
      try {
        const out = execSync('tasklist /FI "IMAGENAME eq chrome.exe" /NH /FO CSV', { encoding: "utf-8" }).trim();
        return out.split("\n").map((line) => {
          const m = line.match(/"chrome.exe","(\d+)"/i);
          return m ? parseInt(m[1], 10) : 0;
        }).filter((n) => n > 0);
      } catch { return []; }
    },
    killChrome() {
      try { execSync("taskkill /F /IM chrome.exe", { stdio: "ignore" }); } catch {}
    },
  },
  linux: {
    chromePaths: [
      "/usr/bin/google-chrome-stable",
      "/usr/bin/google-chrome",
      "/opt/google/chrome/google-chrome",
    ],
    profileDir: path.join(os.homedir(), ".config", "google-chrome"),
    findChrome() {
      for (const p of this.chromePaths) if (fs.existsSync(p)) return p;
      return null;
    },
    listChromePids() {
      // 覆盖常见的 Chrome 进程命名
      const patterns = ["google-chrome-stable", "google-chrome", "chrome"];
      const pids = new Set();
      for (const pat of patterns) {
        try {
          const out = execSync(`pgrep -x ${pat}`, { encoding: "utf-8" }).trim();
          out.split("\n").map(Number).filter((n) => n > 0).forEach((n) => pids.add(n));
        } catch {}
      }
      return [...pids];
    },
    killChrome() {
      for (const pat of ["google-chrome-stable", "google-chrome", "chrome"]) {
        try { execSync(`pkill -9 -x ${pat}`, { stdio: "ignore" }); } catch {}
      }
    },
  },
};

// ---------------------------------------------------------------------------
// 工具函数
// ---------------------------------------------------------------------------

function log(msg) { console.log(msg); }
function warn(msg) { console.warn("⚠️  " + msg); }
function ok(msg) { console.log("✅ " + msg); }
function err(msg) { console.error("❌ " + msg); }

function getConfig() {
  const config = PLATFORM_CONFIG[PLATFORM];
  if (!config) {
    err(`不支持的平台: ${PLATFORM}。支持 darwin/win32/linux。`);
    process.exit(1);
  }
  return config;
}

/** 同步等待 ms 毫秒（不依赖 setTimeout / 系统 sleep） */
function sleepSync(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

/**
 * HTTP GET 读取版本响应，只接受 2xx；协议元数据由 cdpIdentity 校验。
 * agent:false 是必须的——Node 19+ 的 http.globalAgent 默认 keepAlive，探测用过的 socket 会留在
 * 连接池里；而本脚本用 sleepSync 死堵事件循环（等进程退出/等启动），期间服务端按 5s 空闲把这条
 * 连接关掉，客户端来不及处理 FIN。下一次探测复用这条死 socket 就是 ECONNRESET，于是"端口还活着"
 * 被误判成"没人应答"。这种假阴性会直接骗过下面的端口闸门，必须一次一条新连接。
 */
function httpGet(url) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, { timeout: 3000, agent: false }, (res) => {
      let body = "";
      res.on("data", (chunk) => (body += chunk));
      res.on("end", () => {
        if (res.statusCode < 200 || res.statusCode >= 300) {
          reject(new Error(`HTTP ${res.statusCode}`));
        } else {
          resolve(body);
        }
      });
    });
    req.on("error", reject);
    req.on("timeout", () => {
      req.destroy();
      reject(new Error("timeout"));
    });
  });
}

async function probeCDP(port) {
  try {
    const version = await httpGet(`http://127.0.0.1:${port}/json/version`);
    return version;
  } catch {
    return null;
  }
}

/** 原始 TCP 探测：HTTP 500/畸形 JSON 仍表示端口被占用，不能据此解锁 profile 破坏操作。 */
function probeTcp(port, timeoutMs = 1000) {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host: "127.0.0.1", port });
    let settled = false;
    const done = (listening) => {
      if (settled) return;
      settled = true;
      socket.destroy();
      resolve(listening);
    };
    socket.setTimeout(timeoutMs);
    socket.once("connect", () => done(true));
    socket.once("error", () => done(false));
    socket.once("timeout", () => done(false));
  });
}

/**
 * 验证版本 JSON 的 Browser 与浏览器级 ws/wss 地址，取能区分实例的标识。
 * Chrome 每次启动都会换一个新的 browser GUID（webSocketDebuggerUrl 尾段），最适合做这件事。
 * 取不到就返回 null——调用方必须把 null 当作「无法比对」，绝不能当作「相同」或「不同」。
 */
function cdpIdentity(version) {
  if (!version) return null;
  try {
    const obj = JSON.parse(version);
    if (typeof obj?.Browser !== "string" || !obj.Browser.trim() ||
        typeof obj.webSocketDebuggerUrl !== "string") return null;
    const endpoint = new URL(obj.webSocketDebuggerUrl);
    if (!["ws:", "wss:"].includes(endpoint.protocol) ||
        !/^\/devtools\/browser\/[^/]+$/.test(endpoint.pathname)) return null;
    return obj.webSocketDebuggerUrl;
  } catch {}
  return null;
}

/**
 * 等 TCP 端口真的不再监听；true = 端口已空出来，false = 超时后仍有人监听。
 * 不能用 probeCDP：HTTP 500/畸形响应只说明“不是健康 CDP”，不说明“端口空闲”。
 */
async function waitForPortFree(port, maxMs = 8000, stepMs = 500, needQuiet = 2) {
  const start = Date.now();
  let quiet = 0;
  for (;;) {
    if (await probeTcp(port)) {
      quiet = 0;
    } else if (++quiet >= needQuiet) {
      return true;
    }
    if (Date.now() - start >= maxMs) return false;
    sleepSync(stepMs);
  }
}

/** 尽力查出占用端口的进程，只用于诊断（查不到就返回 null，不影响判定） */
function describePortHolder(port) {
  const cmd =
    PLATFORM === "win32"
      ? `netstat -ano -p tcp | findstr LISTENING | findstr :${port}`
      : `lsof -nP -iTCP:${port} -sTCP:LISTEN`;
  try {
    const out = execSync(cmd, {
      encoding: "utf-8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
    const line = out
      .split("\n")
      .map((l) => l.trim())
      .filter((l) => l && !/^COMMAND\s/.test(l))[0];
    return line ? line.slice(0, 200) : null;
  } catch {
    return null;
  }
}

/** 跑一条只读的查询命令，拿 stdout；命令不存在/非零退出/超时一律返回 null */
function queryStdout(cmd) {
  try {
    const out = execSync(cmd, {
      encoding: "utf-8",
      stdio: ["ignore", "pipe", "ignore"],
      timeout: 5000,
      maxBuffer: 8 * 1024 * 1024,
    });
    return typeof out === "string" ? out : String(out);
  } catch {
    return null;
  }
}

/**
 * 列出正在 LISTEN 指定端口的进程 pid。
 * 只在「已经探到 CDP 应答」之后调用——那一刻端口必然有人在监听，所以空结果只可能是
 * 工具缺失或看不见，一律返回 null 表示「无从判断」，绝不能被当成「没人占用」而放行。
 */
function listPortListenerPids(port) {
  const queries =
    PLATFORM === "win32"
      ? [
          {
            kind: "pid",
            cmd: `powershell -NoProfile -NonInteractive -Command "Get-NetTCPConnection -State Listen -LocalPort ${port} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess"`,
          },
          {
            kind: "pid",
            cmd: `pwsh -NoProfile -NonInteractive -Command "Get-NetTCPConnection -State Listen -LocalPort ${port} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess"`,
          },
          { kind: "netstat", cmd: "netstat -ano -p tcp" },
        ]
      : [
          { kind: "pid", cmd: `lsof -nP -iTCP:${port} -sTCP:LISTEN -t` },
          // Linux 上 lsof 经常不预装，用 ss / fuser 兜底
          { kind: "ss", cmd: `ss -H -ltnp "sport = :${port}"` },
          { kind: "pid", cmd: `fuser -n tcp ${port}` },
        ];
  for (const { kind, cmd } of queries) {
    const out = queryStdout(cmd);
    if (out === null) continue;
    const pids = new Set();
    if (kind === "netstat") {
      // 不读取本地化的状态文字。监听行的稳定形状是 TCP + 本地目标端口 +
      // foreign port 0 + 最后一列 Owning PID；已建立连接的 foreign port 非 0。
      for (const line of out.split("\n")) {
        const fields = line.trim().split(/\s+/);
        if (fields.length < 5 || fields[0].toUpperCase() !== "TCP") continue;
        const localPort = Number((fields[1].match(/:(\d+)$/) || [])[1]);
        const foreignPort = Number((fields[2].match(/:(\d+)$/) || [])[1]);
        const pid = Number(fields[fields.length - 1]);
        if (localPort === port && foreignPort === 0 && Number.isInteger(pid) && pid > 0) {
          pids.add(pid);
        }
      }
    } else if (kind === "ss") {
      for (const m of out.matchAll(/pid=(\d+)/g)) pids.add(Number(m[1]));
    } else {
      // PowerShell OwningProcess / lsof -t / fuser：一堆纯数字 pid
      for (const tok of out.split(/\s+/)) {
        const n = Number(tok);
        if (Number.isInteger(n) && n > 0) pids.add(n);
      }
    }
    const list = [...pids].filter((n) => n > 0);
    if (list.length > 0) return list;
  }
  return null;
}

/** 全机 pid -> ppid 表；查不到返回 null（无从判断，不是「没有父进程」） */
function listProcessParents() {
  const cmds =
    PLATFORM === "win32"
      ? [
          // wmic 在新版 Windows 上已被移除，退回 PowerShell CIM（5.1 / 7 都试）
          "wmic process get ProcessId,ParentProcessId /format:csv",
          'powershell -NoProfile -NonInteractive -Command "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId | ConvertTo-Csv -NoTypeInformation"',
          'pwsh -NoProfile -NonInteractive -Command "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId | ConvertTo-Csv -NoTypeInformation"',
        ]
      : ["ps -A -o pid=,ppid="]; // macOS(BSD) 与 Linux(procps) 都认这一条
  for (const cmd of cmds) {
    const out = queryStdout(cmd);
    if (out === null) continue;
    const map = new Map();
    if (PLATFORM === "win32") {
      // 两个来源的列序不一样（wmic 按字母序，PowerShell 按 Select 顺序），按表头定位
      const lines = out.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
      const head = lines.findIndex(
        (l) => /processid/i.test(l) && /parentprocessid/i.test(l)
      );
      if (head < 0) continue;
      const cols = lines[head]
        .split(",")
        .map((c) => c.replace(/"/g, "").trim().toLowerCase());
      const pidCol = cols.indexOf("processid");
      const ppidCol = cols.indexOf("parentprocessid");
      if (pidCol < 0 || ppidCol < 0) continue;
      for (const line of lines.slice(head + 1)) {
        const cells = line.split(",").map((c) => c.replace(/"/g, "").trim());
        const pid = Number(cells[pidCol]);
        const ppid = Number(cells[ppidCol]);
        if (pid > 0 && Number.isInteger(ppid)) map.set(pid, ppid);
      }
    } else {
      for (const line of out.split("\n")) {
        const m = line.trim().match(/^(\d+)\s+(\d+)$/);
        if (m) map.set(Number(m[1]), Number(m[2]));
      }
    }
    if (map.size > 0) return map;
  }
  return null;
}

/** 取某个 pid 的完整命令行；取不到返回 null */
function processCommandLine(pid) {
  const cmds =
    PLATFORM === "win32"
      ? [
          `wmic process where "ProcessId=${pid}" get CommandLine /value`,
          `powershell -NoProfile -NonInteractive -Command "(Get-CimInstance Win32_Process -Filter 'ProcessId=${pid}').CommandLine"`,
          `pwsh -NoProfile -NonInteractive -Command "(Get-CimInstance Win32_Process -Filter 'ProcessId=${pid}').CommandLine"`,
        ]
      : [`ps -ww -o command= -p ${pid}`]; // -ww：不许按终端宽度截断，Chrome 的命令行很长
  for (const cmd of cmds) {
    const out = queryStdout(cmd);
    if (out === null) continue;
    const text =
      PLATFORM === "win32" ? out.replace(/^\s*CommandLine=/im, "") : out;
    const trimmed = text.trim();
    if (trimmed) return trimmed;
  }
  return null;
}

/** pid 是否在 rootPid 的进程树里（含 rootPid 本身）；沿 ppid 往上走 */
function isInProcessTree(pid, rootPid, parents) {
  let cur = pid;
  for (let hops = 0; hops < 64; hops++) {
    if (cur === rootPid) return true;
    if (!Number.isInteger(cur) || cur <= 1) return false;
    const next = parents.get(cur);
    if (next === undefined || next === cur) return false;
    cur = next;
  }
  return false;
}

function commandLineHasArgument(commandLine, argument) {
  const escaped = argument.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(?:^|[\\s"'])${escaped}(?=$|[\\s"'])`).test(commandLine);
}

/**
 * 证明端口上应答的那个端点确实归本次 spawn 出来的进程所有。两件事都要成立：
 *   ① 端口上所有 LISTEN 持有者都在 rootPid 这棵进程树里——Chrome 会另起 browser 进程，
 *      macOS 上启动的二进制还可能 re-exec，所以比的是整棵树而不是直系 pid；反过来，
 *      子进程继承了监听 fd 也会被 lsof 列出来，所以要求「全都在树里」而不是「有一个在」。
 *   ② 树里确实有一个持有者带着本次启动的 --remote-debugging-port=<port>——证明应答的是
 *      我们配出来的那个实例，而不是树里某个别的进程顺手占了这个端口。
 * 任何一步查不出来都返回 unverifiable：宁可硬失败，也不能把「证明不了」当成「证明了」。
 */
function verifyPortOwnedByLaunch(port, rootPid) {
  const fail = (code, lines) => ({ ok: false, code, lines: [`${code}: ${lines[0]}`, ...lines.slice(1)] });
  const unverifiable = (why) =>
    fail("CDP_OWNER_UNVERIFIABLE", [
      `无法确认端口 ${port} 的 LISTEN 持有者归属（${why}）。`,
      "拒绝报成功：证明不了这个端点属于本次启动，就不能把它交给后续采集。",
      PLATFORM === "win32"
        ? "本机需要 netstat 加 wmic 或 PowerShell 才能查进程归属。"
        : "本机需要 lsof（或 ss / fuser）加 ps 才能查进程归属。",
      `处理办法：装上上述工具后重跑，或手动确认 ${port} 上跑的确实是刚启动的 Chrome。`,
    ]);

  if (!rootPid) return unverifiable("spawn 没拿到 pid");
  const listeners = listPortListenerPids(port);
  if (!listeners) return unverifiable("查不到监听该端口的进程");

  // 持有者就是 spawn 出来的那个 pid 时不必读进程表——最常见的形态（Chrome 的 browser
  // 进程就是我们启动的那个）因此不依赖 wmic/ps 之外的任何东西
  let outside = listeners.filter((pid) => pid !== rootPid);
  if (outside.length > 0) {
    const parents = listProcessParents();
    if (!parents) return unverifiable("读不到进程表（pid/ppid）");
    outside = outside.filter((pid) => !isInProcessTree(pid, rootPid, parents));
  }
  if (outside.length > 0) {
    const holder = describePortHolder(port);
    return fail("CDP_PORT_NOT_OURS", [
      `端口 ${port} 的 LISTEN 持有者（pid ${outside.join(", ")}）不在本次启动的进程树里（根 pid ${rootPid}）。`,
      "拒绝报成功：端口被别的进程握着，再往下用，每一次采集读到的都是别人的会话。",
      ...(holder ? [`占用者：${holder}`] : []),
      `处理办法：结束占用 ${port} 的进程后重跑，或换一个端口。`,
    ]);
  }

  const marker = `--remote-debugging-port=${port}`;
  let sawCommandLine = false;
  for (const pid of listeners) {
    const cmdline = processCommandLine(pid);
    if (cmdline === null) continue;
    sawCommandLine = true;
    if (commandLineHasArgument(cmdline, marker)) return { ok: true, pids: listeners, pid };
  }
  if (!sawCommandLine) return unverifiable("读不到持有者的命令行");
  return fail("CDP_OWNER_NOT_LAUNCHED_INSTANCE", [
    `端口 ${port} 的 LISTEN 持有者（pid ${listeners.join(", ")}）在本次启动的进程树里，但没有一个带着 ${marker}。`,
    "拒绝报成功：应答的不是本次启动的那个 Chrome，只是同一棵树里另一个占了这个端口的进程。",
    `处理办法：确认 ${port} 没被别的进程占用，或换一个端口重跑。`,
  ]);
}

/** spawn 出来的 Chrome 是否还活着（exitCode/signalCode 权威，兜底 kill(pid,0)） */
function isChildAlive(child) {
  if (!child || !child.pid) return false;
  if (child.exitCode !== null || child.signalCode !== null) return false;
  try {
    process.kill(child.pid, 0);
    return true;
  } catch {
    return false;
  }
}

function isPidAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

/** 只清理由本次 spawn 拉起的进程树；绝不调用全局 killChrome 连坐用户的其他窗口。 */
function terminateLaunchTree(rootPid) {
  if (!Number.isInteger(rootPid) || rootPid <= 0) return;
  if (PLATFORM === "win32") {
    try {
      execSync(`taskkill /F /T /PID ${rootPid}`, { stdio: "ignore" });
    } catch {}
    return;
  }

  const parents = listProcessParents();
  const tree = [];
  if (parents) {
    for (const pid of parents.keys()) {
      if (pid !== process.pid && isInProcessTree(pid, rootPid, parents)) tree.push(pid);
    }
  }
  if (!tree.includes(rootPid)) tree.push(rootPid);

  // 子孙先停、launcher 最后停，避免 detached listener 在父进程先死后被 reparent 而丢失归属。
  const depth = (pid) => {
    let current = pid;
    for (let hops = 0; hops < 64; hops++) {
      if (current === rootPid) return hops;
      const next = parents?.get(current);
      if (!next || next === current) return -1;
      current = next;
    }
    return -1;
  };
  tree.sort((left, right) => depth(right) - depth(left));
  for (const pid of tree) {
    try { process.kill(pid, "SIGTERM"); } catch {}
  }
  sleepSync(200);
  for (const pid of tree) {
    if (!isPidAlive(pid)) continue;
    try { process.kill(pid, "SIGKILL"); } catch {}
  }
}

/** 复制文件（吞掉 ENOENT；其他错误打印一次警告供用户排查） */
function copyFileSafe(src, dest) {
  try {
    fs.copyFileSync(src, dest);
    return true;
  } catch (e) {
    if (e.code !== "ENOENT") {
      warn(`复制失败: ${src} -> ${dest} (${e.code || e.message})`);
    }
    return false;
  }
}

/** 递归复制目录 */
function copyDirRecursive(src, dest) {
  fs.cpSync(src, dest, { recursive: true, force: true });
}

/** 递归删除目录 */
function rmDirSafe(dir) {
  fs.rmSync(dir, { recursive: true, force: true });
}

/**
 * 刷新登录态相关文件（在 debugProfile 已存在的"增量"路径上使用）。
 * 同时尝试 Chrome 当前可能存在的 Default/Cookies 与 Default/Network/Cookies，
 * 包含各类 -journal / -wal / -shm 旁路文件，以及 Google 账号登录数据。
 */
function refreshAuthFiles(srcDefault, destDefault) {
  const targets = [
    "Cookies", "Cookies-journal",
    "Login Data", "Login Data-journal",
    "Login Data For Account", "Login Data For Account-journal",
    "Web Data", "Web Data-journal",
    path.join("Network", "Cookies"),
    path.join("Network", "Cookies-journal"),
  ];
  let copied = 0;
  for (const rel of targets) {
    const src = path.join(srcDefault, rel);
    if (!fs.existsSync(src)) continue;
    const dest = path.join(destDefault, rel);
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    if (copyFileSafe(src, dest)) copied++;
  }
  return copied;
}

/** 清理 Chrome singleton 锁，避免上次崩溃后下次启动失败 */
function clearSingletonLocks(profileDir) {
  const names = ["SingletonLock", "SingletonCookie", "SingletonSocket"];
  for (const n of names) {
    try { fs.unlinkSync(path.join(profileDir, n)); } catch {}
  }
}

/** 等待 Chrome PID 列表为空 */
function waitForChromeExit(config, maxMs = 8000, stepMs = 500) {
  const start = Date.now();
  while (Date.now() - start < maxMs) {
    if (config.listChromePids().length === 0) return true;
    sleepSync(stepMs);
  }
  return false;
}

/** TTY 交互式问询 */
function promptYesNo(question) {
  return new Promise((resolve) => {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    rl.question(question, (answer) => {
      rl.close();
      resolve(/^y(es)?$/i.test((answer || "").trim()));
    });
  });
}

// ---------------------------------------------------------------------------
// detect-only 模式
// ---------------------------------------------------------------------------

async function runDetectOnly(config) {
  const version = await probeCDP(CDP_PORT);
  if (cdpIdentity(version) !== null) {
    log("CDP_STATUS=ready");
    log(`CDP_URL=http://127.0.0.1:${CDP_PORT}/json/version`);
    // 尝试从 JSON 提取浏览器版本（容错）
    try {
      const obj = JSON.parse(version);
      if (obj.Browser) log(`BROWSER=${obj.Browser}`);
    } catch {}
    process.exit(0);
  }
  log("CDP_STATUS=needs-setup");
  const pids = config.listChromePids();
  if (pids.length > 0) {
    log("CHROME_RUNNING=yes");
    log(`CHROME_PID_COUNT=${pids.length}`);
  } else {
    log("CHROME_RUNNING=no");
  }
  process.exit(0);
}

// ---------------------------------------------------------------------------
// 同意流程：返回 true 继续，false 用户拒绝
// ---------------------------------------------------------------------------

async function ensureConsentToKill(pids) {
  if (pids.length === 0) return true;
  if (ARGS.flags.yes) return true;

  // 非 TTY：拒绝静默杀进程，给调用方（Claude / 上层脚本）一个明确信号
  if (!process.stdin.isTTY) {
    err(`NEEDS_CONSENT: ${pids.length} running Chrome process(es) will be killed.`);
    err(`Pass --yes to confirm (after asking the user), or stop Chrome manually first.`);
    process.exit(3);
  }

  // TTY：交互问询
  warn(`检测到 ${pids.length} 个正在运行的 Chrome 进程。`);
  warn("继续将杀死它们，你在常规 Chrome 中未保存的工作可能丢失。");
  return promptYesNo("继续？[y/N] ");
}

// ---------------------------------------------------------------------------
// 主流程
// ---------------------------------------------------------------------------

async function main() {
  const config = getConfig();
  const debugProfile = path.join(os.homedir(), "chrome-debug-profile");

  // 1) 检测 Chrome 可执行路径（detect-only 也需要 profileDir）
  const chromePath = config.findChrome();

  // detect-only：不修改任何状态
  if (ARGS.flags.detectOnly) {
    if (!chromePath) {
      log("CDP_STATUS=needs-setup");
      log("CHROME_INSTALLED=no");
      process.exit(0);
    }
    return runDetectOnly(config);
  }

  log("=== CDP Chrome 环境准备 ===");
  log(`平台: ${PLATFORM} | CDP 端口: ${CDP_PORT} | profile: ${ARGS.profile}`);

  if (!chromePath) {
    err("未找到 Google Chrome。请确保已安装。");
    err(`搜索路径: ${JSON.stringify(config.chromePaths, null, 2)}`);
    process.exit(1);
  }
  log(`Chrome 路径: ${chromePath}`);

  // 2) dry-run：先于任何副作用（包括"复用现有 CDP"）打印计划，让用户能看到真要执行时的步骤
  const defaultProfile = path.join(config.profileDir, ARGS.profile);
  const hasProfile = fs.existsSync(defaultProfile);

  if (ARGS.flags.dryRun) {
    const cdpAlive = cdpIdentity(await probeCDP(CDP_PORT)) !== null;
    const tcpOccupied = await probeTcp(CDP_PORT);
    // --reset / 显式 --profile 会跳过复用（见下方第 3 步），dry-run 必须照实说
    const willReuse = cdpAlive && !ARGS.flags.reset && !ARGS.profileExplicit;
    const cdpNote = !tcpOccupied
      ? "未监听"
      : !cdpAlive
        ? "有 TCP 监听，但不是健康 CDP（实际运行会在动 profile 前硬失败）"
      : willReuse
        ? "已就绪（实际运行时会直接复用）"
        : "已就绪（但传了 --reset/--profile，实际运行会重建，不复用）";
    log(`Chrome profile: ${defaultProfile} (${hasProfile ? "存在" : "不存在"})`);
    log(`CDP 端口 ${CDP_PORT}: ${cdpNote}`);
    const runningPids = config.listChromePids();
    log(`检测到 ${runningPids.length} 个 Chrome 进程`);
    log("\n--- dry-run 模式：只打印操作，不执行 ---");
    if (willReuse) {
      log("0. CDP 已就绪，实际运行会直接复用并退出 0（以下步骤仅供参考）");
    } else if (cdpAlive) {
      log("0. CDP 已就绪，但传了 --reset/--profile：实际运行不复用，按下列步骤重建");
    }
    // 步骤号按真实执行顺序动态编号：先杀进程、再确认端口空了，之后才碰 profile 目录
    let stepNo = 0;
    const step = (msg) => log(`${++stepNo}. ${msg}`);
    if (runningPids.length > 0) {
      step(`${ARGS.flags.yes ? "（已同意）" : "请求同意后 "}杀死 ${runningPids.length} 个 Chrome 进程`);
    } else {
      step("无 Chrome 进程，无需杀死");
    }
    step(`用 TCP 确认端口 ${CDP_PORT} 已释放（任何监听仍在都中止：不删 profile、不启动）`);
    if (ARGS.flags.reset) step(`删除 ${debugProfile}`);
    if (hasProfile) {
      step(`复制 profile: ${defaultProfile} -> ${debugProfile}/Default`);
    } else {
      step("⚠️ 无用户 profile，将以空 profile 启动");
    }
    step("清理 SingletonLock / SingletonCookie / SingletonSocket");
    step("启动 Chrome（含 --remote-allow-origins=*, --no-first-run 等）");
    step(
      `验证 http://127.0.0.1:${CDP_PORT}/json/version 来自本次启动的实例` +
        "（身份取得到且已变 + 进程存活 + 端口的 LISTEN 持有者就在这棵进程树里）"
    );
    ok("dry-run 完成。");
    process.exit(0);
  }

  // 3) 若 CDP 已就绪 → 复用，直接退出。
  //    但 --reset / 显式 --profile 的语义就是"重建 debug profile"：登录态过期时文档正是
  //    让用户跑 --reset，而那时 CDP 恰恰是活着的（过期是从这个会话里发现的）。若照旧复用，
  //    这两个参数会被静默丢掉，还以 exit 0 报"成功"。因此这两种情况不复用，继续往下重建。
  const existing = await probeCDP(CDP_PORT);
  const portWasListening = await probeTcp(CDP_PORT);
  const staleIdentity = cdpIdentity(existing);
  if (staleIdentity !== null) {
    if (!ARGS.flags.reset && !ARGS.profileExplicit) {
      ok("CDP 已就绪，复用现有 Chrome。");
      log(existing.split("\n").slice(0, 5).join("\n"));
      process.exit(0);
    }
    const requested = ARGS.flags.reset ? "--reset" : `--profile ${ARGS.profile}`;
    warn(`CDP 端口 ${CDP_PORT} 已在监听，但传了 ${requested}：不复用，将关闭现有 Chrome 后重建 debug profile。`);
  }

  if (!hasProfile) {
    err(`未找到 Chrome profile: ${defaultProfile}`);
    err("请确保已安装 Google Chrome 并至少使用过一次，或用 --profile <name> 指定其他 profile。");
    process.exit(1);
  }

  // 4) 同意流程：如有 Chrome 进程要杀，先征得同意
  const runningPids = config.listChromePids();
  const consented = await ensureConsentToKill(runningPids);
  if (!consented) {
    err("用户拒绝，已中止。");
    process.exit(2);
  }

  // 5) 杀死现有 Chrome 进程，等待退出
  if (runningPids.length > 0) {
    log(`正在停止 ${runningPids.length} 个 Chrome 进程...`);
    config.killChrome();
    if (!waitForChromeExit(config, 6000)) {
      warn("首轮 kill 后仍有 Chrome 进程，再试一次...");
      config.killChrome();
      waitForChromeExit(config, 4000);
    }
    const remain = config.listChromePids();
    if (remain.length > 0) {
      err(`仍有 ${remain.length} 个 Chrome 进程未退出，已中止。`);
      err("未删除、未改动 debug profile，也未启动新 Chrome——状态保持原样。");
      process.exit(1);
    } else {
      ok("Chrome 已退出。");
    }
  }

  // 5.5) 硬闸门：端口必须真的空出来，才允许动 profile 目录、才允许启动新实例。
  //      顺序是刻意的——闸门在删 profile 之前。旧实例还活着就往下走会撞上最坏的一种结果：
  //      先删掉一个正在运行的 Chrome 的 profile（本身就是破坏性的），新进程又因端口被占起不来，
  //      而第 10 步的 probeCDP 恰好被旧端点答上，于是 exit 0 报「重建成功」——调用方以为拿到了
  //      新浏览器，之后每一次采集读的都是旧会话/别人的会话。这里只能硬失败。
  //      无论 /json/version 是否健康都执行：HTTP 500 也可能正占着端口。
  // 杀过进程才值得给宽限期；没有已识别 Chrome 时，占用者不会自己退出，快速确认后失败。
  const graceMs = runningPids.length > 0 ? 8000 : 1000;
  if (!(await waitForPortFree(CDP_PORT, graceMs))) {
    const remain = config.listChromePids();
    err(
      existing
        ? `CDP 端口 ${CDP_PORT} 上的旧实例仍在应答，已中止。`
        : `CDP 端口 ${CDP_PORT} 仍被占用、未释放，已中止。`
    );
    if (remain.length > 0) {
      err(`原因：${remain.length} 个 Chrome 进程没能退出（kill 无效，可能权限不足或进程卡死）。`);
    } else if (runningPids.length === 0) {
      err("原因：端口被无法识别的进程占用——没找到任何 Chrome 进程，脚本无从关闭它。");
    } else {
      err("原因：Chrome 进程已退出，但另有进程仍守着这个端口。");
    }
    const holder = describePortHolder(CDP_PORT);
    if (holder) err(`占用者：${holder}`);
    err("未删除、未改动 debug profile，也未启动新 Chrome——状态保持原样。");
    err(`处理办法：手动结束占用 ${CDP_PORT} 的进程后重跑，或换一个端口（node setup-cdp-chrome.js <其他端口> ...）。`);
    process.exit(1);
  }
  if (portWasListening) {
    ok(`CDP 端口 ${CDP_PORT} 已释放。`);
  }

  // 6) --reset：清空 debug profile
  if (ARGS.flags.reset) {
    log(`正在删除 debug profile: ${debugProfile}`);
    rmDirSafe(debugProfile);
  }

  // 7) 复制 / 刷新 profile（此时 Chrome 已关闭，SQLite 一致）
  const debugDefault = path.join(debugProfile, "Default");
  if (!fs.existsSync(debugDefault)) {
    log("正在复制 Chrome profile 到 debug 目录...");
    fs.mkdirSync(debugProfile, { recursive: true });
    try { fs.chmodSync(debugProfile, 0o700); } catch {}
    copyDirRecursive(defaultProfile, debugDefault);
    ok(`Profile 已复制到: ${debugProfile}`);
  } else {
    log("debug profile 已存在，刷新登录态相关文件...");
    try { fs.chmodSync(debugProfile, 0o700); } catch {}
    const n = refreshAuthFiles(defaultProfile, debugDefault);
    ok(`已刷新 ${n} 个登录态文件`);
  }

  // 8) 清理 singleton 锁
  clearSingletonLocks(debugProfile);

  // 9) 以 CDP 模式启动 Chrome
  log(`正在以 CDP 模式启动 Chrome（端口 ${CDP_PORT}）...`);
  const chromeArgs = [
    `--remote-debugging-port=${CDP_PORT}`,
    `--user-data-dir=${debugProfile}`,
    "--remote-allow-origins=*",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-features=ChromeWhatsNewUI",
  ];
  const child = spawn(chromePath, chromeArgs, { detached: true, stdio: "ignore" });
  const childPid = child.pid;
  let spawnError = null;
  child.on("error", (e) => { spawnError = e; });
  child.unref();

  /** 启动后验证没过：只清掉自己刚起的进程（端口上那个不是我们的，不该连坐杀别人的 Chrome） */
  function abortAfterLaunch(reasons) {
    for (const line of reasons) err(line);
    err("正在清理刚启动的 Chrome 进程...");
    terminateLaunchTree(childPid);
    process.exit(1);
  }

  // 10) 等待启动并验证。光有人应答不算成功——那可能是没被关掉的旧实例，也可能是别的进程
  //     顺手占了这个端口。四条全过才算：
  //     ① 新端点的 browser GUID 取得到（取不到＝无法比对，按合约不能当作相同或不同）；
  //     ② 这个 GUID 与重建前不同（配合第 5.5 步已确认旧端点消失过）；
  //     ③ 刚 spawn 的进程还活着（它死了，端口上应答的就一定不是本次启动的实例）；
  //     ④ 端口的 LISTEN 持有者确实在这棵 spawn 出来的进程树里，且带着本次的
  //        --remote-debugging-port。前三条都是间接证据——「旧端点消失过 + 身份变了 +
  //        launcher 还活着」推不出「端口归它」，只有第 ④ 条才真的把端口和进程绑上。
  log("等待 Chrome 启动...");
  let identityMisses = 0;
  for (let i = 1; i <= 15; i++) {
    sleepSync(2000);
    if (spawnError) {
      abortAfterLaunch([`启动 Chrome 失败: ${spawnError.message}`]);
    }
    const version = await probeCDP(CDP_PORT);
    if (version) {
      const identity = cdpIdentity(version);
      if (identity === null) {
        // 端点刚起来时理论上可能先答上 HTTP，给两轮宽限；之后仍取不到就硬失败。
        if (++identityMisses < 3) {
          log(`   端口有应答但取不到实例身份，重试 ${identityMisses}/3...`);
          continue;
        }
        abortAfterLaunch([
          `CDP_IDENTITY_UNVERIFIABLE: 端口 ${CDP_PORT} 有 HTTP 应答，但 /json/version 里取不到实例身份（webSocketDebuggerUrl）。`,
          "拒绝报成功：身份取不到就无法证明这是新起的实例——按合约它既不算相同也不算不同，只能当作没证出来。",
          `处理办法：确认 ${CDP_PORT} 上跑的是 Chrome 的 CDP 端点（而不是别的 HTTP 服务），或换一个端口重跑。`,
        ]);
      }
      if (staleIdentity && identity === staleIdentity) {
        abortAfterLaunch([
          `端口 ${CDP_PORT} 应答的仍是重建前那个实例（${identity}），不是新启动的 Chrome。`,
          "拒绝报成功：再往下用，每一次采集读到的都会是旧会话。",
        ]);
      }
      if (!isChildAlive(child)) {
        const holder = describePortHolder(CDP_PORT);
        abortAfterLaunch([
          `端口 ${CDP_PORT} 上有 CDP 应答，但刚启动的 Chrome（pid ${childPid}）已经退出。`,
          "拒绝报成功：这个端点不属于本次启动的实例。",
          ...(holder ? [`占用者：${holder}`] : []),
          `处理办法：确认 ${CDP_PORT} 没被别的进程占用，或换一个端口重跑。`,
        ]);
      }
      const owner = verifyPortOwnedByLaunch(CDP_PORT, childPid);
      if (!owner.ok) abortAfterLaunch(owner.lines);
      ok(`Chrome 已成功以 CDP 模式启动（端口 ${CDP_PORT}）`);
      log(version.split("\n").slice(0, 5).join("\n"));
      process.exit(0);
    }
    log(`   尝试 ${i}/15...`);
  }

  // 11) 失败清理：杀死刚才启动的孤儿 Chrome
  err("30 秒内未能启动 Chrome CDP 环境。");
  err("正在清理刚启动的 Chrome 进程...");
  terminateLaunchTree(childPid);
  err("可能原因：");
  err("  - Chrome 不支持 --remote-debugging-port");
  err(`  - 端口 ${CDP_PORT} 已被其他进程占用`);
  err("  - debug profile 目录已损坏（试试 --reset）");
  process.exit(1);
}

main().catch((e) => {
  err(`启动失败: ${e.message}`);
  process.exit(1);
});
