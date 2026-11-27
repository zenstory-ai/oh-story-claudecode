---
name: browser-cdp
description: "Use this skill when you need to control a Chrome browser via CDP (Chrome DevTools Protocol) to reuse existing login sessions. Covers: launching Chrome in debug mode, opening URLs, waiting for page load, evaluating JavaScript, taking snapshots, and extracting auth tokens. Trigger phrases: browser automation, CDP, agent-browser, 浏览器操作, 操作浏览器, Chrome CDP, 复用登录态, extract token from browser."
metadata: {"openclaw":{"requires":{"bins":["agent-browser"]},"source":"https://github.com/zenstory-ai/oh-story-claudecode"}}
---
# Browser CDP 操作工具

通过 CDP（Chrome DevTools Protocol）连接 Chrome，复用登录态并执行浏览器操作。

## 前置条件

- macOS / Linux / Windows（实验性），已安装并使用过 Google Chrome，来源 profile 已存在
- Node.js 20+
- `agent-browser` 已安装：`npm install -g agent-browser`

> 启动或重建时，若需结束 Chrome 进程，先按下方流程征得同意；未保存的标签页或草稿可能丢失。

---

## 启动流程（每次都按这个顺序）

下文 `{SKILL_DIR}` 指本 skill（browser-cdp）的目录。

**第一步：探测当前状态（无副作用）**

```bash
node {SKILL_DIR}/scripts/setup-cdp-chrome.js 9222 --detect-only
```

输出含 `CDP_STATUS=ready`（附 `CDP_URL`、`BROWSER`）或 `CDP_STATUS=needs-setup`（附 `CHROME_INSTALLED=no` 或 `CHROME_RUNNING=yes/no` 与 `CHROME_PID_COUNT`）。

**第二步：根据探测结果分支**

- `CDP_STATUS=needs-setup` 且 `CHROME_INSTALLED=no` → 本机没找到 Chrome，告诉用户先安装并用它登录一次需要的网站，不要运行 setup。
- `CDP_STATUS=ready` 且本次只需连接 → 直接使用 `agent-browser --cdp 9222 ...`，**不要运行 setup**。
- 明确请求 `--reset` / `--profile` → 即使 ready 也走重建，按下方「需要结束 Chrome 时」处理。
- `CDP_STATUS=needs-setup` 且 `CHROME_RUNNING=no` → 安全启动：
  ```bash
  node {SKILL_DIR}/scripts/setup-cdp-chrome.js 9222 --yes
  ```
- `CDP_STATUS=needs-setup` 且 `CHROME_RUNNING=yes` → 按下方「需要结束 Chrome 时」处理。

**需要结束 Chrome 时（同意流程）**：凡是会结束正在运行的 Chrome 的命令（Chrome 在运行时启动、`--reset`、显式 `--profile`），都按这三步走：

1. 带上原定选项加 `--dry-run` 跑一次，看会结束几个 Chrome 进程；
2. 告诉用户会结束 N 个 Chrome 进程、未保存的标签页或草稿可能丢失，问是否继续；
3. 用户同意后，去掉 `--dry-run`、加 `--yes` 重跑；用户拒绝就放弃这次自动化。

非 TTY 调用中，Chrome 在运行且未传 `--yes` 时，脚本以退出码 3 报 `NEEDS_CONSENT: ...` 并中止。取得同意后再重跑，不自动补 `--yes`。

**换端口**：9222 被别的程序占用时可以换一个端口（如 9333），之后所有 `agent-browser --cdp` 命令用同一个端口，扫榜脚本加 `--port 9333`，查资料助手传 `cdp_port: 9333`。

---

## 启动脚本选项

| 选项 | 说明 |
|------|------|
| `--detect-only` | 只探测，不修改任何状态 |
| `--yes` | 已征得同意，跳过交互提示 |
| `--reset` | 启动前清空 `~/chrome-debug-profile`（登录失效时用） |
| `--profile <name>` | 指定来源 profile（默认 `Default`，如 `"Profile 1"`）；显式传入即重建 |
| `--dry-run` | 打印将执行的步骤，不执行 |

退出码：`0` 成功 / `1` 通用错误 / `2` 参数错误或用户拒绝（TTY）/ `3` 需同意但缺 `--yes`。

---

## 常用操作

```bash
# 打开页面并等待加载
agent-browser --cdp 9222 open "<URL>"
agent-browser --cdp 9222 wait 3000

# 提取页面文本或 Auth Token（实际存储位置按站点确认）
agent-browser --cdp 9222 eval 'document.body.innerText.substring(0, 8000)'
agent-browser --cdp 9222 eval 'localStorage.getItem("token") || document.cookie'

# 页面交互（snapshot 拿交互元素引用）
agent-browser --cdp 9222 snapshot -i
agent-browser --cdp 9222 click "<CSS or @e1>"
agent-browser --cdp 9222 type "<sel>" "<text>"

# 复杂 JS（含引号 / $ / 反引号，用 base64 或 --stdin 防转义错误）
agent-browser --cdp 9222 eval -b "$(echo -n "document.querySelectorAll('a').length" | base64)"
cat <<'EOF' | agent-browser --cdp 9222 eval --stdin
const links = document.querySelectorAll('a');
links.length;
EOF
```

---

## 停止 / 清理

- 关掉 debug Chrome 窗口即可；无响应时须先按 `--user-data-dir` 核验 debug 实例 PID 再单独结束，**严禁按 Chrome 可执行文件名批量结束进程**：
  - macOS / Linux：`pgrep -af chrome-debug-profile` → `kill -9 {PID}`
  - Windows（PowerShell）：`Get-CimInstance Win32_Process | Where-Object CommandLine -like '*chrome-debug-profile*' | Select-Object ProcessId,CommandLine` → `taskkill /F /PID {PID}`
- 登录态失效：按同意流程跑 `setup-cdp-chrome.js 9222 --reset`；Chrome 127+ 加密未带出 Cookie 时，直接在 debug 窗口登录一次（不传 `--reset` 会持久保留）。

## 超时与常见问题

耗时页面加载或批量采集应每页独立加 30s 超时（macOS 默认无 GNU `timeout`，用已有 Node 跨平台包装；Linux 也可用 `timeout 30`）：

```bash
node -e 'const {spawnSync}=require("child_process");const r=spawnSync("agent-browser",["--cdp","9222","eval",process.argv[1]],{timeout:30000,stdio:"inherit"});if(r.error?.code==="ETIMEDOUT"){console.error("⏱ CDP 操作超时（30s）");process.exit(124);}process.exit(r.status??1);' "window.location.replace('https://www.qidian.com/rank/')"
```

持续卡死由用户在宿主按 `ESC` 打断；失败后从断点继续。

| 问题 | 处理 |
|------|------|
| `NEEDS_CONSENT`（退出码 3）/ `--reset` / `--profile` | 走同意流程：先 `--dry-run`，同意后加 `--yes` |
| `CHROME_INSTALLED=no` 或无来源 profile | 安装并登录 Chrome 一次；多 profile 传 `--profile "Profile 1"` |
| 端口未监听 / 启动 30s 超时 | `--detect-only` 确认；端口冲突就换端口并同步下游；profile 损坏则 `--reset` |
| 跳转登录页 / `eval` 返回 `null` | `snapshot -i` 操作登录；核对 storage key，复杂 JS 改用 `eval -b` 或 `--stdin` |
