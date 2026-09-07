#!/bin/bash
# session-start.sh — 显示项目状态和写作上下文摘要
# 设计原则：无可用信息时完全静默，不输出任何内容，避免污染 context
set -euo pipefail

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
# 注入串用真实换行拼接（NL），不用字面 `\n` 占位：输出端必须 printf '%s'，见文末注释。
NL=$'\n'
OUTPUT=""
HAS_CONTENT=false

# 先做最小 preflight，再 source；否则 lib 缺失时无法输出可修复提示。
if [ ! -f "$HOOK_DIR/lib/common.sh" ] || [ ! -f "$HOOK_DIR/lib/sentinel.sh" ]; then
  printf '%s\n' "[WARN] story hook 函数库缺失。重新运行 /story-setup 恢复 .claude/hooks/lib/。"
  exit 0
fi

# 加载公共函数库
source "$HOOK_DIR/lib/common.sh"
source "$HOOK_DIR/lib/sentinel.sh"

# 字节稳定区域：本 hook 经 discover_active_book 处理中文书名/路径。Windows 中文系统若导出
# GBK 区域设置，locale 敏感操作会按多字节错解 UTF-8。强制 C 区域走字节处理才稳（issue #164
# 同类）。本 hook 无内嵌 python，可直接 export。
export LC_ALL=C

ROOT=$(project_root)

# story-setup 部署后的一次性重启确认。custom agents 只在会话启动时被注册成
# subagent_type；story-setup 部署完会留下 .claude/.agents-pending-restart 标记。
# 走到这里说明已是新会话、agents 已随会话重新加载——确认并清除标记（一次性）。
if [ -f "$ROOT/.claude/.agents-pending-restart" ]; then
  OUTPUT+="[INFO] story-setup 刚部署/更新了 agents，本会话已重新加载——story-architect、narrative-writer 等 custom agent 现已注册可用。${NL}"
  OUTPUT+="  若写作 skill 仍提示 spawn 失败 / 降级 solo，说明你还在部署时的旧会话里，请再新开一个 Claude Code 会话。${NL}${NL}"
  HAS_CONTENT=true
  rm -f "$ROOT/.claude/.agents-pending-restart" 2>/dev/null || true
fi

# 部署自检：.story-deployed 存在但 hooks 文件被误删时发出警告
# story_hook_cli.js/story_hook_core.js 是承重的 node 共享核——被删时 check-prose-after-write/
# validate-story-commit/detect-story-gaps 全部静默退化，必须列入名单。
if sentinel_exists "$ROOT/.story-deployed"; then
  MISSING_HOOKS=""
  for hook in session-start.sh session-end.sh detect-story-gaps.sh pre-compact.sh post-compact.sh validate-story-commit.sh guard-outline-before-prose.sh check-prose-after-write.sh story_hook_cli.js story_hook_core.js lib/common.sh lib/sentinel.sh; do
    if [ ! -f "$ROOT/.claude/hooks/$hook" ]; then
      MISSING_HOOKS+="$hook "
    fi
  done
  if [ -n "$MISSING_HOOKS" ]; then
    OUTPUT+="[WARN] .story-deployed 存在但缺少 hook：$MISSING_HOOKS${NL}"
    OUTPUT+="  修复：重新运行 /story-setup 恢复缺失的 hook。${NL}${NL}"
    HAS_CONTENT=true
  fi

  # node 运行时检测：正文兜底网/commit 格式提示/连续性检查走 node 共享核（#243）。官方现在
  # 推荐原生二进制装 Claude Code，只有 npm 装法才带 Node——native 安装可能无 node，上述三项
  # 会静默降级停用（大纲拦截守卫有纯 bash 兜底，仍生效）。会话起点提示一次，避免误以为兜底仍在。
  if ! node -e "" >/dev/null 2>&1; then
    OUTPUT+="[WARN] 检测不到 node 运行时：正文兜底网/commit 格式提示/连续性检查已停用（大纲拦截仍有纯 bash 兜底）。${NL}"
    OUTPUT+="  修复：安装 Node.js（https://nodejs.org，或 nvm / brew install node）后新开会话即可恢复。${NL}${NL}"
    HAS_CONTENT=true
  fi

  AGENTS_VERSION=$(read_sentinel_field agents_version "$ROOT/.story-deployed")
  case "$AGENTS_VERSION" in
    ''|*[!0-9]*)
      OUTPUT+="[WARN] .story-deployed 缺少数字 agents_version。重新运行 /story-setup。${NL}${NL}"
      HAS_CONTENT=true
      ;;
    *)
      if [ "$AGENTS_VERSION" -lt 29 ]; then
        OUTPUT+="[WARN] story-setup agents_version=$AGENTS_VERSION 低于 v29。重新运行 /story-setup 刷新 hooks、agents 和 references（部署后需新开会话）。${NL}${NL}"
        HAS_CONTENT=true
      elif [ "$AGENTS_VERSION" -gt 29 ]; then
        OUTPUT+="[WARN] story-setup agents_version=$AGENTS_VERSION 高于本 hook 支持的 v29。不要降级覆盖；请先更新 oh-story-claudecode。${NL}${NL}"
        HAS_CONTENT=true
      fi
      ;;
  esac

  # agents_version（上面）是唯一的运行时过期权威，只在部署物行为变化时才 bump；
  # setup_skill_version 是 skill 内容锚点，按内容节奏独立变化，这里只做存在性检查、
  # 不参与版本比较——否则内容改动会误报"需要重新部署"。
  for field in setup_skill_version target_cli resolver_strategy references_dir; do
    if [ -z "$(read_sentinel_field "$field" "$ROOT/.story-deployed")" ]; then
      OUTPUT+="[WARN] .story-deployed 缺少 $field 字段。重新运行 /story-setup 刷新部署元信息。${NL}${NL}"
      HAS_CONTENT=true
    fi
  done

  # 多端部署时 references_dir 是逗号分隔的多条路径，逐条查；整串当一个路径查会必然查不到，
  # 每次开会话都误报「参考资料包缺失」。
  REFERENCES_DIR=$(read_sentinel_field references_dir "$ROOT/.story-deployed")
  if [ -n "$REFERENCES_DIR" ]; then
    MISSING_REFS=""
    OLD_IFS=$IFS
    IFS=','
    for REF_ENTRY in $REFERENCES_DIR; do
      REF_ENTRY=$(printf '%s' "$REF_ENTRY" | LC_ALL=C sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
      [ -n "$REF_ENTRY" ] || continue
      REFERENCES_PATH=$(resolve_project_path "$REF_ENTRY")
      if [ ! -d "$REFERENCES_PATH" ] || ! find "$REFERENCES_PATH" -maxdepth 1 -type f -name "*.md" -print -quit 2>/dev/null | grep -q .; then
        MISSING_REFS="${MISSING_REFS}${MISSING_REFS:+, }${REF_ENTRY}"
      fi
    done
    IFS=$OLD_IFS
    if [ -n "$MISSING_REFS" ]; then
      OUTPUT+="[WARN] story-setup 参考资料包缺失或为空：${MISSING_REFS}。重新运行 /story-setup；若重跑后仍报这条，是 skill 包本身没装全，按你的安装方式重装 oh-story-claudecode（npx skills add 或 marketplace 面板）再部署。${NL}${NL}"
      HAS_CONTENT=true
    fi
  fi
else
  OUTPUT+="[WARN] 写作环境未部署。运行 /story-setup 初始化。${NL}${NL}"
  HAS_CONTENT=true
fi

# 显示分支和最近 commit（仅在有 git 历史时）
BRANCH=$(git -C "$ROOT" branch --show-current 2>/dev/null || echo "")
if [ -n "$BRANCH" ]; then
  OUTPUT+="=== 写作进度 ===${NL}"
  OUTPUT+="分支：$BRANCH${NL}"
  RECENT=$(git -C "$ROOT" log --oneline -5 2>/dev/null || true)
  if [ -n "$RECENT" ]; then
    OUTPUT+="$RECENT${NL}"
  fi
  OUTPUT+="${NL}"
  HAS_CONTENT=true
fi

# 上下文.md 摘要（只看当前位置部分；新模板前 7 行是标题与说明，取 18 行才覆盖到 ## 当前位置 整块（≤8 字段 + 注释行））
BOOK_DIR=$(discover_active_book)
if [ -n "$BOOK_DIR" ] && [ -f "$BOOK_DIR/追踪/上下文.md" ]; then
  OUTPUT+="--- 当前位置 ---${NL}"
  # `2>/dev/null || true` 不能省：[ -f ] 对「存在但读不到」也为真，此时 head 退非零，
  # set -e 会就地终止脚本——OUTPUT 到文末才 flush，上面所有 [WARN] 会连同 stderr 一起丢光。
  SNAPSHOT=$(head -18 "$BOOK_DIR/追踪/上下文.md" 2>/dev/null || true)
  OUTPUT+="${SNAPSHOT}${NL}---${NL}${NL}"
  HAS_CONTENT=true
fi

# 未完成拆文（阈值 > 0 才报告）
if [ -d "$ROOT/拆文库" ]; then
  # 同上：子目录不可读时 find 退 1，pipefail 把它变成整条管道的退出码，set -e 就在这里
  # 终止脚本、一个字节都不输出。`|| true` + 数字兜底保证只是这一项降级、其余提示照常送达。
  # 只数「最终状态」不是 completed 的那些：裸数 _progress.md 会把拆完的书永久报成未完成。
  PROGRESS_COUNT=$(discover_incomplete_analyses "$ROOT" | wc -l | tr -d ' ' || true)
  case "$PROGRESS_COUNT" in ''|*[!0-9]*) PROGRESS_COUNT=0 ;; esac
  if [ "$PROGRESS_COUNT" -gt 0 ]; then
    OUTPUT+="[INFO] 拆文库/ 中有 $PROGRESS_COUNT 个未完成拆文。运行 /story-long-analyze 或 /story-short-analyze。${NL}"
    HAS_CONTENT=true
  fi
fi

# 版本更新检查（被动提醒：每 24h 至多一次，全程静默兜底，失败绝不影响会话；关掉：export STORY_NO_UPDATE_CHECK=1）
story_update_check() {
  [ -n "${STORY_NO_UPDATE_CHECK:-}" ] && return 0
  command -v curl >/dev/null 2>&1 || return 0
  local vfile=""
  [ -f "$ROOT/.claude/skills/story/VERSION" ] && vfile="$ROOT/.claude/skills/story/VERSION"
  [ -z "$vfile" ] && [ -f "$HOME/.claude/skills/story/VERSION" ] && vfile="$HOME/.claude/skills/story/VERSION"
  [ -n "$vfile" ] || return 0
  local cur; cur=$(tr -dc '0-9.' < "$vfile" 2>/dev/null) || return 0
  [ -n "$cur" ] || return 0
  local cache="${HOME:-$ROOT}/.claude/.story-update-cache"
  local now; now=$(date +%s 2>/dev/null) || return 0
  local last=0 latest=""
  if [ -f "$cache" ]; then
    last=$(sed -n '1p' "$cache" 2>/dev/null || echo 0)
    latest=$(sed -n '2p' "$cache" 2>/dev/null || echo "")
  fi
  case "$last" in ''|*[!0-9]*) last=0;; esac
  local checked=0
  if [ "$((now - last))" -ge 86400 ]; then
    checked=1
    latest=$(curl -fsS --max-time 5 "https://api.github.com/repos/zenstory-ai/oh-story-claudecode/releases/latest" 2>/dev/null \
      | grep -o '"tag_name"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | grep -o '[0-9][0-9.]*' | head -1) || latest=""
    # 成功失败都写时间戳：失败时 latest 留空当负缓存，否则取不到 GitHub 的环境每次开会话
    # 都要白等 5 秒 curl，且永远等不到提醒。
    printf '%s\n%s\n' "$now" "$latest" > "$cache" 2>/dev/null || true
  fi
  # 提示本身也要节流：缓存里的 latest 会一直有值，若不看 checked，同一个版本每开一次会话
  # 就提醒一次，与「每 24h 至多一次」的承诺不符（原实现只节流了网络请求）。
  [ "$checked" -eq 1 ] || return 0
  [ -n "$latest" ] || return 0
  if [ "$latest" != "$cur" ] && [ "$(printf '%s\n%s\n' "$cur" "$latest" | sort -t. -k1,1n -k2,2n -k3,3n | tail -1)" = "$latest" ]; then
    OUTPUT+="[INFO] 网文工具箱有新版本 v${latest}（当前 v${cur}）。更新：npx skills add zenstory-ai/oh-story-claudecode -y -g 后重跑 /story-setup；或对 /story 说“检查更新”。关掉提醒：export STORY_NO_UPDATE_CHECK=1${NL}"
    HAS_CONTENT=true
  fi
}
story_update_check || true

# 仅在有实际内容时输出，否则完全静默
# 必须 %s 不能 %b：$OUTPUT 里嵌着 追踪/上下文.md 的原文摘要和 git log 的 commit 标题。%b 会把
# 其中的 `\b`、`\n` 当转义展开（把备份路径 D:\backup\novel 改写成不存在的路径，还往 context
# 里塞裸 0x08），`\c`（commit 标题里的 C:\code 就带）更会直接终止 printf，把后面的 --- 收尾、
# 拆文 [INFO]、新版本 [INFO] 全部静默丢掉。分隔换行由上面拼接时的 ${NL} 真实换行承担。
if [ "$HAS_CONTENT" = true ]; then
  printf '%s' "$OUTPUT"
fi
