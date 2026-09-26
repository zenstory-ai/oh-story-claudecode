#!/bin/bash
# check-prose-after-write.sh — PostToolUse(Write|Edit|MultiEdit) 正文兜底
# 正文落盘后自动跑「轻量确定性网」，把发现注入提醒——模型无关的兜底层：
# 即使主会话漏跑「确定性收尾」步骤（压缩/弱模型/分心），这些硬信号也保证被抓。
#
# 只兜「硬信号」（漏跑最伤、退化模型自己发现不了的）：截断、生成拒绝语 / AI 自指、
# 工程词漏进正文、紧邻整行复读、毒句式（确定性 AI 句式指纹）、落盘失败/截断。
# 碎句号/长段落/破折号这类 advisory，以及复读全量 / tier2 歧义词，仍由 workflow 收尾
# 步骤的 check-ai-patterns / check-degeneration 全量跑——本 hook 不部署也不依赖那两个
# 检测器，是独立的轻量网（毒句式规则与 check-ai-patterns.js 的同名规则统一规格）。
#
# 覆盖范围：只在 PostToolUse 的 Write|Edit|MultiEdit 上触发。cat>/tee/cp/mv 等用 Bash
# 写正文的路径绕过本 hook（Claude/OpenCode 侧 Bash 只做 pre-guard，无 post-write 兜底）；
# 这类路径由 Codex 的 Stop 回合末 git 改动集扫描兜全。已知边界，非缺陷。
#
# 内容网走 node 共享核 story_hook_core.js（和 OpenCode/ZCode 同一份），只留 bash
# 做事件路由与文件类型判定。node 天生按 UTF-8 写 stdout，免掉旧内嵌 python 的 cp936 体操。
#
# 非阻塞（exit 0，advisory 提醒，不挡写作）；无发现时完全静默（不污染 context）；
# node 不可用时静默放行（兜底不能反过来卡流程）。
set -euo pipefail

source "$(dirname "$0")/lib/common.sh"

# 中文路径上做 bash 通配/basename/case。Windows 中文系统的 GBK 区域会把 UTF-8 字面量按
# 多字节误解码、让每个比较恒假而静默失效（issue #164）。强制 C 区域走字节匹配才稳定。
# node 单独进程按 UTF-8 处理，不受 LC_ALL=C 影响。
export LC_ALL=C

HOOK_INPUT="${CLAUDE_TOOL_INPUT:-}"
if [ -z "$HOOK_INPUT" ] && [ ! -t 0 ]; then
  HOOK_INPUT="$(cat)"
fi
# 故意不 export：Write/Edit 负载里带整章正文，export 会把它塞进本脚本每个子进程的 envp，
# 负载一大 execve 就 E2BIG（Linux 单个环境变量上限 128 KiB，macOS 整体 1 MiB），
# dirname/basename/node 全报「Argument list too long」，兜底网静默停用。改为只在需要负载的
# node 调用处用管道喂 stdin（story_hook_cli.js extract-target 在 HOOK_INPUT 缺省时读 stdin）。

# 探测 node（官方现在推荐原生二进制装 Claude Code，只有 npm 装法才带 Node——native 安装
# 可能无 node。探测不到就静默放行：兜底网降级停用，session-start.sh 会在会话起点提示一次）。
node -e "" >/dev/null 2>&1 || exit 0
CLI="$(dirname "$0")/story_hook_cli.js"
[ -f "$CLI" ] || exit 0

# 抽取目标文件路径（负载走管道喂 node 的 stdin，按 UTF-8 写回路径）。
TARGET="$(printf '%s' "$HOOK_INPUT" | node "$CLI" extract-target 2>/dev/null || true)"
[ -z "$TARGET" ] && exit 0

ROOT=$(project_root)
# 盘符绝对路径归一（对齐 guard-outline-before-prose.sh / plugin.ts，issue #184）。
case "$TARGET" in
  /*) ABS="$TARGET" ;;
  [A-Za-z]:[/\\]*) ABS="${TARGET//\\//}" ;;
  *)  ABS="$ROOT/$TARGET" ;;
esac

BASE="$(basename "$ABS")"
PARENT="$(basename "$(dirname "$ABS")")"

# 只对「正文」文件兜底，绝不碰代码/细纲/设定/大纲等非正文文件：
#   - 短篇：{书}/正文.md，且同目录有 设定.md（真短篇工程信号，排除 docs/正文.md 之类）
#   - 长篇：{书}/正文/第N章*.md（父目录必须是「正文」），且 {书} 有 大纲/追踪/设定（真书结构）
# case 模式锚定首字：细纲_第N章.md（首字「细」）、卷纲_第1卷.md、check-ai-patterns.js、
# 设定.md、大纲.md 等天然都不匹配 `正文.md`/`第*章*.md`，不会被捕获。
IS_PROSE=false
case "$BASE" in
  正文.md)
    [ -f "$(dirname "$ABS")/设定.md" ] && IS_PROSE=true
    ;;
  第*章*.md)
    if [ "$PARENT" = "正文" ]; then
      BOOK="$(dirname "$(dirname "$ABS")")"
      if [ -d "$BOOK/大纲" ] || [ -d "$BOOK/追踪" ] || [ -d "$BOOK/设定" ] || [ -f "$BOOK/设定.md" ]; then
        IS_PROSE=true
      fi
    fi
    ;;
esac
[ "$IS_PROSE" = true ] || exit 0
[ -f "$ABS" ] || exit 0

# 报告用真实换行拼接（NL），不用字面 `\n` 占位：末尾必须 printf '%s' 输出，见文末注释。
NL=$'\n'
OUT=""

# 落盘检测：正文极短（<200 字节）多半是没写完或落盘失败（quota/timeout 中断）。
# 用字节（wc -c）而非字数：LC_ALL=C 下无法按码点数中文，字节阈值已足够判「几乎空」。
BYTES=$(wc -c < "$ABS" 2>/dev/null | tr -d ' ' || echo 0)
case "$BYTES" in ''|*[!0-9]*) BYTES=0 ;; esac
if [ "$BYTES" -lt 200 ]; then
  OUT+="【落盘】正文仅 ${BYTES} 字节，疑似未写完/落盘失败（quota/超时中断？），请核对并补写。${NL}"
fi

# 内容网走 node 共享核，抓截断/拒绝语/AI 自指/工程词 tier1/紧邻复读/毒句式。
# 字数只由 storyctl 的公开命令测量，不在 Adapter 内复制，也不受 Node 降级影响。
NET_MSG="$(node "$CLI" prose-net "$ABS" 2>/dev/null || true)"
[ -n "$NET_MSG" ] && OUT+="【退化/工程词/毒句式】（硬信号：截断/拒绝语/工程词→重写该段；毒句式→就地改写；命中即处理，别留给下一章）${NL}${NET_MSG}${NL}"

[ -z "$OUT" ] && exit 0

# 必须 %s 不能 %b：${OUT} 里嵌的是作者原文切片（截断/复读/工程词摘录）。%b 会把正文里的
# `\n`、`\b`、`\t` 当转义展开，把摘录改写成文件里不存在的内容；`\c`（Windows 路径 C:\code
# 就带）更会直接终止整条 printf，把它后面所有硬信号静默丢掉（exit 0、stderr 空）。
# 本 hook 自己的分隔换行由上面的 ${NL} 真实换行承担，不再依赖 %b 展开。
printf '%s\n' "=== 正文兜底检测（${BASE}）===" "轻量确定性网自动复扫（模型无关，防主会话漏跑收尾）。按类型处理后复扫到净："
printf '%s' "$OUT"
exit 0
