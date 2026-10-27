#!/bin/sh
### story-hooks: BEGIN ###
# story project commit validation
# Managed by story-setup -- do not edit this block manually
# Checks for hardcoded character attributes in story files (advisory only, never blocks)
#
# 本块按 SKILL.md 的部署规则会被原样插进用户已有的 .git/hooks/pre-commit，块自身不带
# shebang、跟着宿主解释器跑。宿主 shebang 常见 #!/bin/sh（git 自带样例、lefthook、husky 都是），
# Debian/Ubuntu 下 /bin/sh 就是 dash。所以整块只用 POSIX sh 语法：不用 set -o pipefail、
# read -r -d ''、进程替换 `< <(...)`、$'\n'——dash 下第一项报错、后两项直接是语法错误，
# 会让此后每次 git commit 都失败（退 1、不产生提交），与本块「advisory only, never blocks」
# 的契约正好相反。文件自身的 shebang 也用 /bin/sh：create 模式下整文件被拷成 hook，
# 无 /bin/bash 的宿主（Alpine/busybox、NixOS）上 git 会直接 fatal 而不是跳过。
# 收尾的 `|| true` 是最后一道保险：宿主开着 set -e 时也绝不会因为本块挡掉提交。
(
set -eu
# LC_ALL=C：模式里的全角「　」「：」是多字节 UTF-8，GBK 区域下 grep 会判无效序列
# 退 2，! 取反后对每个设定文件误报缺字段。强制 C 区域按字节匹配（同
# validate-story-commit.sh，issue #164 约定：LC_ALL=C + 交替代替字符组）。
export LC_ALL=C
ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
WARNINGS=""
# POSIX sh 没有 $'\n'，换行常量只能这么写。
NL='
'

# 暂存的 md 列表一次性取回：POSIX sh 无 read -d ''，接不了 -z 的 NUL 流，改用换行分隔
# （只有文件名自带换行才会错行，极罕见且仅影响 advisory 文案）。也不能写成
# `git … | while`：管道会把 while 放进子 shell，攒好的 WARNINGS 出不来。先存变量，
# 再用 here-doc 喂 while，循环仍跑在当前 shell 里。
STAGED=$(git -c core.quotepath=false diff --cached --relative --name-only --diff-filter=ACM -- . 2>/dev/null || true)

while IFS= read -r file; do
  [ -n "$file" ] || continue
  case "$file" in
    *.md) ;;
    *) continue ;;
  esac

  FULL_PATH="$ROOT/$file"
  [ -f "$FULL_PATH" ] || continue

  # 匹配语义与警告文案对齐 JS core（story_hook_core.js stagedMarkdownWarnings）：冒号/空白用
  # 交替而非含全角字符的方括号字符组（C/GBK 区域下字符组会被拆成单字节、漏匹配）；name 字段
  # grep -i 大小写不敏感。
  case "$file" in
    正文.md|*/正文.md|正文/*|*/正文/*)
      case "${file##*/}" in *_原稿_*) continue ;; esac
      HARDCODED=$(grep -nE "(身高|体重|年龄)([[:space:]]|　)*(：|:)([[:space:]]|　)*[0-9]+" "$FULL_PATH" 2>/dev/null || true)
      if [ -n "$HARDCODED" ]; then
        WARNINGS="$WARNINGS$NL⚠ $file: 正文硬编码角色属性，应引用设定文件：$NL$HARDCODED"
      fi
      ;;
  esac

  # 只查角色卡：设定/ 下还住着 关系.md、题材定位.md、文风.md、世界观/*、势力/* 这类项目级
  # 设定件，它们本来就没有 名字/姓名 字段，整棵目录一刀切会每次提交刷一屏假警告、把上面的
  # 硬编码真警告埋掉（判定口径同 validate-story-commit.sh）。
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
  if [ "$IS_CHARACTER_SHEET" = true ] &&
    ! grep -qiE "^([[:space:]]|　)*(名字|姓名|名称|name)([[:space:]]|　)*(：|:)" "$FULL_PATH" 2>/dev/null; then
    WARNINGS="$WARNINGS$NL⚠ $file: 设定文件缺少 name/名字 必填字段。"
  fi
done <<STORY_STAGED_EOF
$STAGED
STORY_STAGED_EOF

if [ -n "$WARNINGS" ]; then
  echo "=== Story Commit Warnings（advisory only）==="
  # printf '%s' 而非 '%b'/echo -e：$WARNINGS 里嵌着 grep -n 抓出的作者正文原文，
  # 里面的 `\c`（Windows 路径 C:\code 就带）会终止输出、把后面的警告全吞掉。
  printf '%s\n' "$WARNINGS"
  echo "=== End Warnings ==="
fi

) || true
### story-hooks: END ###
