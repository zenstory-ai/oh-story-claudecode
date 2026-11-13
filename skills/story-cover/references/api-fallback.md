# API 回退生图

只在会话没有内置生图工具或作者明确要求走 API 时使用。`gpt-image-2` 返回 base64，请求体不带 `response_format`。无参考图走文生图，有参考图走图生图。

## 环境变量

| 变量 | 必填 | 默认 | 说明 |
|:-----|:----:|:-----|:-----|
| `GPT_IMAGE_API_KEY` | 是 | — | OpenAI 或兼容代理的 API Key |
| `GPT_IMAGE_BASE_URL` | | `https://api.openai.com/v1` | 用兼容代理时改这个 |
| `GPT_IMAGE_MODEL` | | `gpt-image-2` | 只在测试新模型时覆盖 |
| `GPT_IMAGE_SIZE` | | `1024x1536` | 官方接口竖版用 `1024x1536`（支持 `1024x1024`/`1024x1536`/`1536x1024`/`auto`，勿传非标 `768x1024` 免报 400）；3:4 上传图由入口 Step 5 裁切导出 |
| `BOOK_DIR` | 是 | — | `封面/` 的上一层，按入口「收集信息」定的保存位置 |
| `PROMPT` | 是 | — | 入口按模板拼好的完整提示词 |
| `REF_IMAGE` | | — | 参考图本地路径或 URL；设置后走图生图 |

## 文生图（没有参考图）

```bash
set -euo pipefail
: "${GPT_IMAGE_API_KEY:?请设置 export GPT_IMAGE_API_KEY=你的key}"
: "${PROMPT:?请先 export PROMPT=构建提示词步骤拼好的完整提示词}"
BASE_URL="${GPT_IMAGE_BASE_URL:-https://api.openai.com/v1}"
MODEL="${GPT_IMAGE_MODEL:-gpt-image-2}"
SIZE="${GPT_IMAGE_SIZE:-1024x1536}"
BOOK_DIR="${BOOK_DIR:?请先 export BOOK_DIR=书目录或 ./covers/<书名>}"

mkdir -p "$BOOK_DIR/封面"

# 自增版本号，避免覆盖之前生成的封面
i=1
while [ -f "$BOOK_DIR/封面/封面_v${i}.png" ]; do i=$((i+1)); done
OUT="$BOOK_DIR/封面/封面_v${i}.png"
RESP=$(mktemp)
trap 'rm -f "$RESP"' EXIT

# 用 jq 拼 JSON 体，避免 PROMPT 里的引号/换行/中文把 shell 字符串撑破
BODY=$(jq -n \
  --arg m "$MODEL" \
  --arg p "$PROMPT" \
  --arg s "$SIZE" \
  '{model:$m, prompt:$p, size:$s}')

curl -fsS --max-time 180 --retry 2 --retry-delay 5 \
  "$BASE_URL/images/generations" \
  -H "Authorization: Bearer $GPT_IMAGE_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$BODY" > "$RESP"

# API 出错时早退，避免把 error JSON 当成 base64 写成损坏 PNG
if jq -e '.error' "$RESP" >/dev/null 2>&1; then
  echo "API error:" >&2
  jq '.error' "$RESP" >&2
  exit 1
fi

# `// empty` 让缺失字段输出空串而非 "null"，配合下面的 -s 检查避免写出 3 字节假 PNG
jq -er '.data[0].b64_json // empty' "$RESP" | base64 --decode > "$OUT"
[ -s "$OUT" ] || { echo "empty or malformed output: $OUT" >&2; head -c 300 "$RESP" >&2; exit 1; }

# 落地提示词副本，方便迭代时基于上一次微调
printf '%s\n' "$PROMPT" > "${OUT%.png}.prompt.txt"

file "$OUT"
ls -lt "$BOOK_DIR/封面/"
```

## 图生图（有参考图）

下面的 `/v1/images/edits` 命令通过 `multipart/form-data` 上传本地图片，不加 `Content-Type: application/json`。文本字段用 `--form-string`，图片字段用 `-F image=@path`。

```bash
set -euo pipefail
: "${GPT_IMAGE_API_KEY:?请设置 export GPT_IMAGE_API_KEY=你的key}"
: "${PROMPT:?请先 export PROMPT=构建提示词步骤拼好的完整提示词}"
BASE_URL="${GPT_IMAGE_BASE_URL:-https://api.openai.com/v1}"
MODEL="${GPT_IMAGE_MODEL:-gpt-image-2}"
SIZE="${GPT_IMAGE_SIZE:-1024x1536}"
BOOK_DIR="${BOOK_DIR:?请先 export BOOK_DIR=书目录或 ./covers/<书名>}"
REF_IMAGE="${REF_IMAGE:?请先 export REF_IMAGE=本地路径或 URL}"

mkdir -p "$BOOK_DIR/封面"

# 自增版本号
i=1
while [ -f "$BOOK_DIR/封面/封面_v${i}.png" ]; do i=$((i+1)); done
OUT="$BOOK_DIR/封面/封面_v${i}.png"
RESP=$(mktemp)
REF_TMP=""
trap '[ -n "$REF_TMP" ] && rm -f "$REF_TMP"; rm -f "$RESP"' EXIT

# URL 先下载到临时文件，本地路径直接用。用裸 mktemp 以保证 macOS/Linux 行为一致。
case "$REF_IMAGE" in
  http://*|https://*)
    REF_TMP=$(mktemp)
    curl -fsSL --max-time 60 -o "$REF_TMP" "$REF_IMAGE"
    REF_LOCAL="$REF_TMP"
    ;;
  *)
    [ -f "$REF_IMAGE" ] || { echo "参考图不存在: $REF_IMAGE" >&2; exit 1; }
    REF_LOCAL="$REF_IMAGE"
    ;;
esac

curl -fsS --max-time 240 --retry 2 --retry-delay 5 \
  "$BASE_URL/images/edits" \
  -H "Authorization: Bearer $GPT_IMAGE_API_KEY" \
  --form-string "model=$MODEL" \
  --form-string "size=$SIZE" \
  --form-string "prompt=$PROMPT" \
  -F "image=@$REF_LOCAL" > "$RESP"

if jq -e '.error' "$RESP" >/dev/null 2>&1; then
  echo "API error:" >&2
  jq '.error' "$RESP" >&2
  exit 1
fi

# `// empty` 让缺失字段输出空串而非 "null"，配合 -s 检查避免写出 3 字节假 PNG
jq -er '.data[0].b64_json // empty' "$RESP" | base64 --decode > "$OUT"
[ -s "$OUT" ] || { echo "empty or malformed output: $OUT" >&2; head -c 300 "$RESP" >&2; exit 1; }

printf '%s\n' "$PROMPT"    > "${OUT%.png}.prompt.txt"
printf '%s\n' "$REF_IMAGE" > "${OUT%.png}.ref.txt"

file "$OUT"
ls -lt "$BOOK_DIR/封面/"
```
