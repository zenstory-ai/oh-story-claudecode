#!/bin/bash
# validate-story-commit.sh — 在 git commit 时检查格式问题（WARNING only, no BLOCKING）
set -euo pipefail

source "$(dirname "$0")/lib/common.sh"

HOOK_INPUT="${CLAUDE_TOOL_INPUT:-}"
if [ -z "$HOOK_INPUT" ] && [ ! -t 0 ]; then
  HOOK_INPUT="$(cat)"
fi
# 故意不 export：export 会把负载塞进本脚本每个子进程的 envp（git/grep/basename 全算上），
# 负载一大 execve 就 E2BIG（Linux 单个环境变量上限 128 KiB）。只在真正读它的那一次 node 调用上
# 做单命令赋值（is-git-commit 只认 HOOK_INPUT 环境变量，不读 stdin），把暴露面收到一处。
# 本 hook 挂 Bash 工具，负载只是命令串，实际都很小；收紧是为了对齐另两个 hook 的同一约定。

is_git_commit_command() {
  # 走 node 共享核 isGitCommitCommand：命令优先取 STORY_COMMIT_COMMAND，缺省从 HOOK_INPUT
  # 挖 command/cmd/script。js 分词语义，与 OpenCode/ZCode 一致；对「引号内分隔符」这类边界
  # 与旧 python shlex 有已文档化、仅 advisory 的差异（不影响本 hook 的 exit 0 非阻塞语义）。
  # node 探测不到就当「非 commit」，让下方静默放行（兜底不反噬提交流程；native 安装可能
  # 无 node，此时 commit 格式提示停用，session-start.sh 会在会话起点提示一次）。
  node -e "" >/dev/null 2>&1 || return 1
  local CLI; CLI="$(dirname "$0")/story_hook_cli.js"
  [ -f "$CLI" ] || return 1
  HOOK_INPUT="$HOOK_INPUT" node "$CLI" is-git-commit >/dev/null 2>&1
}

# PreToolUse matcher 可能过宽或目标 CLI 不支持 if 字段；脚本必须内部自检。
# 没有明确 git commit 命令时完全静默退出，避免 echo/grep 等命令误触发。
if ! is_git_commit_command; then
  exit 0
fi

# 后续 case + grep 在中文路径/正文内容上做匹配。Windows 中文系统若导出 GBK 区域设置，
# grep 按 GBK 多字节解码 UTF-8 内容会乱。强制 C 区域走字节匹配才稳定（issue #164 同类）。
# 放在 is_git_commit_command（node 共享核）之后，避免影响其输入解码。
export LC_ALL=C

ROOT=$(project_root)
GIT_ROOT=$(git -C "$ROOT" rev-parse --show-toplevel 2>/dev/null || printf '%s\n' "$ROOT")
# 警告串用真实换行拼接（NL），不用字面 `\n` 占位：输出端必须 printf '%s'，见文末注释。
NL=$'\n'
WARNINGS=""

# 获取即将 commit 的文件列表（使用 -z null 分隔避免空格路径问题）
while IFS= read -r -d '' file; do
  # 跳过非 md 文件
  case "$file" in
    *.md) ;;
    *) continue ;;
  esac

  FULL_PATH="$ROOT/$file"
  if [ ! -f "$FULL_PATH" ]; then
    FULL_PATH="$GIT_ROOT/$file"
  fi

  # 检查正文文件是否包含硬编码的情节值
  # 匹配语义与警告文案对齐 JS core（story_hook_core.js stagedMarkdownWarnings，跨 CLI 的
  # 权威实现；py↔js 由 scripts/test-prose-net-parity.sh Part E 锁 parity）。
  # 冒号/空白都用交替而不是把全角字符塞进方括号字符组：含全角字符的字符组在 C 区域会被
  # 拆成单字节、漏匹配；(：|:) 同时命中全角「：」和半角「:」，([[:space:]]|　) 在 LC_ALL=C 下
  # 也认全角空格 U+3000（否则全角空格分隔的写法会漏检/误判）。
  case "$file" in
    正文.md|*/正文.md|正文/*|*/正文/*)
      HARDCODED=$(grep -nE "(身高|体重|年龄)([[:space:]]|　)*(：|:)([[:space:]]|　)*[0-9]+" "$FULL_PATH" 2>/dev/null || true)
      if [ -n "$HARDCODED" ]; then
        WARNINGS="$WARNINGS${NL}⚠ $file: 正文硬编码角色属性，应引用设定文件：${NL}$HARDCODED"
      fi
      ;;
  esac

  # 检查角色卡的必填字段（结构化匹配：key:value 格式）。grep -i 对齐 JS core 的 /i：
  # 大小写不敏感命中 name/NAME/Name（LC_ALL=C 下 -i 只折叠 ASCII，中文字节不受影响）。
  #
  # 只查角色卡：设定/ 下还住着一批项目级设定件——artifact-protocols.md 规定的 关系.md
  # （正文是「# 角色关系图」）、题材定位.md（「# 题材定位」），以及 文风.md、题材正文提示卡.md、
  # 世界观/*、势力/* 等，它们本来就没有 名字/姓名 字段。整棵 设定/ 一刀切会让每次碰设定的提交
  # 都刷一屏假警告，把同框的「正文硬编码角色属性」真警告埋掉。判定：设定/角色|人物 子目录内的
  # 文件 + 设定/ 直属的扁平角色卡（角色.md/主角.md/配角.md/反派.md 等自定义命名）才查；
  # 其余子目录与已知项目级文件跳过。
  # 四端同口径：本脚本（Claude）、OpenCode 的 .git/hooks/pre-commit、JS core 的
  # isCharacterSheetPath / stagedMarkdownWarnings、codex 的 _is_character_sheet_path /
  # staged_markdown_warnings 已全部收窄到同一判定。改任一端都要四端一起改，否则
  # 同一次提交在不同 CLI 上会给出不同警告（parity 测试 Part E 锁 py↔js 两端）。
  # 别为了「对齐权威实现」把这段改回去——那会把假警告一起改回来。
  IS_CHARACTER_SHEET=false
  case "$file" in
    设定/角色/*|*/设定/角色/*|设定/人物/*|*/设定/人物/*)
      IS_CHARACTER_SHEET=true
      ;;
    设定/*/*|*/设定/*/*)
      # 世界观/势力/报告/原理/人物关系 等非角色子目录：整目录跳过
      ;;
    设定/*|*/设定/*)
      case "${file##*/}" in
        关系.md|题材定位.md|题材正文提示卡.md|文风.md|世界规则.md|世界观.md|金手指.md|背景设定.md) ;;
        *) IS_CHARACTER_SHEET=true ;;
      esac
      ;;
  esac
  if [ "$IS_CHARACTER_SHEET" = true ] \
    && ! grep -qiE "^([[:space:]]|　)*(名字|姓名|名称|name)([[:space:]]|　)*(：|:)" "$FULL_PATH" 2>/dev/null; then
    WARNINGS="$WARNINGS${NL}⚠ $file: 设定文件缺少 name/名字 必填字段。"
  fi
done < <(git -C "$ROOT" -c core.quotepath=false diff --cached --relative --name-only --diff-filter=ACM -z -- . 2>/dev/null || true)

if [ -n "$WARNINGS" ]; then
  echo "=== Story Commit Warnings（advisory only）==="
  # 必须 %s 不能 %b：$WARNINGS 里嵌着 grep -n 抓出的作者正文原文。%b 会把正文里的 `\n`、`\b`
  # 当转义展开，`\c`（Windows 路径 C:\code 就带）更会直接终止 printf，把后面所有文件的警告
  # 连同收尾框线一起吞掉。分隔换行由上面拼接时的 ${NL} 真实换行承担。
  printf '%s\n' "$WARNINGS"
  echo "=== End Warnings ==="
fi

# Always exit 0 — 写作流程不能被 hook 卡住
exit 0
