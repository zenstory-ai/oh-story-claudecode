---
name: story-cover
version: 1.0.0
description: "小说封面生成。根据书名、作者名自动分析题材风格，调用 GPT-Image-2 生成含标题和署名的专业级网文封面；Codex CLI 优先使用内置 ImageGen，无需单独 API Key。触发方式：/story-cover、/封面、「帮我做个封面」「生成封面图」「做个小说封面」「封面设计」。"
metadata: {"openclaw":{"requires":{"env":["GPT_IMAGE_API_KEY"],"bins":["curl","jq","base64"]},"primaryEnv":"GPT_IMAGE_API_KEY","source":"https://github.com/zenstory-ai/oh-story-claudecode"}}
---
# story-cover：小说封面生成

你是小说封面设计师。根据书名和题材，调用 GPT-Image-2 一次性生成包含书名和作者名的完整封面。

**核心原则：封面是读者的第一印象，一眼传达题材和氛围。**

---

## 生成通路

- **Codex 内置（优先）**：当前 Codex CLI 会话可调用 `$imagegen` / `image_gen` 时，直接生成并落盘；计入 Codex 通用用量，无需 `OPENAI_API_KEY` 或 `GPT_IMAGE_API_KEY`，也不运行 `curl`。`story-cover` 自行调用工具，不让用户另开命令。
- **API 回退**：仅在会话没有内置工具或用户明确指定 API 时使用，需要 `GPT_IMAGE_API_KEY`。工具缺失不等于 Codex 订阅不支持生图；内置调用失败时先报告错误，不静默切换到可能收费的 API。

## 输出参数与 API 回退环境变量

| 变量 | 必填 | 默认 | 说明 |
|:-----|:----:|:-----|:-----|
| `GPT_IMAGE_API_KEY` | API 回退必填 | — | OpenAI 或兼容代理的 API Key；Codex 内置通路不用 |
| `GPT_IMAGE_BASE_URL` | | `https://api.openai.com/v1` | 兼容代理时改这个 |
| `GPT_IMAGE_MODEL` | | `gpt-image-2` | 仅在测试新模型时覆盖 |
| `GPT_IMAGE_SIZE` | | `1024x1536` | API 回退的目标比例提示（番茄 3:4→`768x1024`，默认 2:3→`1024x1536`）。官方 gpt-image-2 认任意 16 倍数尺寸（比例≤3:1），但**很多中转代理会忽略 size、按预设返回约 2:3**（已实测）——平台尺寸不靠它，由「导出平台上传尺寸」步骤兜底 |
| `UPLOAD_SIZE` | | — | 平台固定上传像素（番茄 `600x800`）；设置后由「导出平台上传尺寸」步骤居中裁剪+缩放出上传版（不变形、不依赖出图尺寸） |
| `BOOK_DIR` | ✅ | — | 输出目录，建议 `./covers/<书名>` |
| `REF_IMAGE` | | — | 参考图本地路径或 URL；内置通路先把图片载入会话，API 回退走 `images/edits` 图生图 |

---

## 生成流程

### Step 1：收集信息

必填：书名、作者名（笔名）、目标平台、输出目录 `BOOK_DIR`（建议 `./covers/<书名>`；API 回退用环境变量，内置通路直接使用当前任务值）。问作者时说「封面存在哪？默认 `./covers/<书名>`」，不把变量名当问题抛给作者
选填：参考图 `REF_IMAGE`（本地路径或 URL，设置后切换到图生图）、风格偏好、尺寸

> **书名和笔名是封面必需信息**：缺任一必须先用 AskUserQuestion 问用户补全，不得编造或留空。

**按目标平台定封面尺寸**：番茄上传 600×800 是 **3:4**（不是 2:3），出图比例不对、平台二次裁剪就会切掉书名/笔名。

| 平台 | 上传尺寸 | 比例 | 生成 `GPT_IMAGE_SIZE`（尽量） |
|:-----|:--------|:-----|:-------------------|
| 番茄小说 | 600×800 | 3:4 | `768x1024` |
| 其他平台（默认竖版） | 按平台规格 | 2:3 | `1024x1536` |

内置通路把目标比例写进提示词；API 回退再 `export GPT_IMAGE_SIZE`（很多代理会忽略、返回约 2:3）。平台有固定上传像素时设置 `UPLOAD_SIZE`（番茄 `600x800`）。**平台尺寸最终由「导出平台上传尺寸」步骤居中裁剪+缩放保证，不依赖实际出图尺寸。** 平台与题材风格见 [references/cover-styles.md](references/cover-styles.md)。

### Step 2：题材判定

扫描书名（必要时简介）中的关键词，对照 [references/cover-styles.md](references/cover-styles.md) 的「题材推断规则」表选定题材。

- 单题材命中 → 直接采用
- 多题材命中 → 按优先级取一：仙侠 > 西幻 > 古言 > 现言 > 都市 > 悬疑 > 科幻 > 历史 > 灵异 > 轻小说
- 零命中 → 默认 `都市`

### Step 3：构建提示词

提示词 = **文字层** + **风格层** + **画面层**，全部用英文编写。

#### 文字层：书名 + 作者名字体设计

在提示词中直接包含中文书名和作者名，GPT-Image-2 可直接渲染。**重点描述字体风格**：

```
Title text '书名' at top center in [书名字体风格].
Author name '作者名' at bottom center in [作者名字体风格].
```

#### 书名字体风格

| 题材 | 描述关键词 |
|:-----|:-----------|
| 玄幻/仙侠 | `bold golden brush calligraphy with metallic glow and sharp strokes` |
| 都市 | `modern bold sans-serif with metallic silver finish` |
| 古言/宫斗 | `elegant golden traditional Kai script with ornate decoration` |
| 现言/甜宠 | `soft rounded handwritten style in white with pink glow` |
| 悬疑/推理 | `distorted bold cracked letters in blood red` |
| 科幻/末世 | `neon glowing futuristic font in electric blue` |
| 西幻 | `metallic embossed fantasy lettering with glow effect` |
| 历史/军事 | `heavy stone-carved seal script in deep red` |
| 灵异/恐怖 | `eerie dripping handwritten font in sickly green` |
| 轻小说 | `colorful cartoon outlined bubbly font` |

#### 作者名字体风格（重点：作者名必须精心设计，不能只是"小字"）

作者名虽小，但是封面专业感的关键。必须指定：**字体 + 颜色 + 装饰元素**，让作者名与书名风格呼应但不抢焦点。

| 题材 | 作者名风格提示词 |
|:-----|:----------------|
| 玄幻/仙侠 | `small refined white serif text with faint golden glow, flanked by delicate cloud-scroll ornaments on both sides, resting on a thin horizontal gold line` |
| 都市 | `small clean white modern text with subtle drop shadow, positioned above a thin silver horizontal divider line` |
| 古言/宫斗 | `small elegant dark red traditional text inside a thin golden rectangular border frame with corner decorations` |
| 现言/甜宠 | `small soft pink-white handwritten text with a tiny heart motif on the left side, light sparkle effect` |
| 悬疑/推理 | `small pale grey text with slight blur effect, almost hidden in the shadows, a thin cracked line underneath` |
| 科幻/末世 | `small crisp white monospace text with subtle cyan scanline overlay, flanked by small geometric brackets` |
| 西幻 | `small bronze medieval script text with aged parchment texture, enclosed in a small decorative shield or banner shape` |
| 历史/军事 | `small dignified white Song typeface text above a double horizontal line in dark red` |
| 灵异/恐怖 | `small faded grey-green text slightly tilted, with a thin dripping ink line above` |
| 轻小说 | `small playful rounded white text with pastel color outline, tiny star decorations on both sides` |

**作者名通用规则**：
- 大小：`small`（不能太大抢书名焦点，也不能太小看不清）
- 位置：`at bottom center`，与画面底部保持适当间距
- 必须有装饰元素：线条/边框/小图标/光效中至少一种
- 颜色与背景形成对比但不刺眼

#### 风格层：平台风格

平台风格的描述关键词统一来自 [references/cover-styles.md](references/cover-styles.md) 的「平台风格」节，按目标平台直接取对应关键词串使用，不在本文件维护副本以免与参考文件漂移。

#### 画面层：题材 + 构图

从 [references/cover-styles.md](references/cover-styles.md) 读取题材对应的风格标签、色彩、人物、背景描述。

构图变体（首次输出 2-3 个方案）：

| 方案 | 构图 | 适合题材 |
|:-----|:-----|:---------|
| A | 人物特写 + 场景 | 全题材通用 |
| B | 全身像 + 动态姿势 | 玄幻、都市、西幻 |
| C | 纯场景/氛围图 | 悬疑、科幻、历史 |

#### 完整提示词模板

```
Chinese web novel cover design, [平台风格].
Title text '{书名}' at top center in [书名字体风格].
Author name '{作者名}' at bottom center in [作者名字体风格 — 从上表选择].
[题材风格标签]. [人物描述]. [背景描述].
[色彩指令]. [光效指令].
Professional book cover, high detail digital painting, portrait [平台比例：番茄=3:4，默认=2:3] ratio, keep title and author name inside the central safe area away from edges (inner ~85%), no watermark
```

#### 提示词技巧（实测验证）

- 人物描述越具体越好：服饰、姿态、发型、表情、道具每个维度都指定
- 背景分层：前景（人物）→ 中景（场景）→ 远景（氛围）
- 光效是指定光源方向 + 颜色（如 `dramatic golden light from above`）
- 用 `digital painting style` 而非 `photo`，避免真人照片感

### Step 4：生成并保存

#### Codex 内置 ImageGen（优先）

1. 用 Step 3 的完整提示词调用 `image_gen`。比例和安全区写进提示词，不传 `GPT_IMAGE_MODEL`、`GPT_IMAGE_SIZE`、`response_format` 等 API 参数。
2. 有 `REF_IMAGE` 时，本地文件先用图片查看工具载入会话；URL 先下载再载入。说明它是编辑目标还是风格参考，并列出必须保持的内容。
3. 每个构图方案单独调用一次。先创建 `BOOK_DIR/封面/`，再把工具返回的图片复制为 `封面_vN.png`，`N` 自增且不覆盖旧版；保留 `$CODEX_HOME/generated_images/` 原文件，同时保存同名 `.prompt.txt`，有参考图再保存 `.ref.txt`。确认图片可读，并把原图绝对路径交给 Step 5。

#### API 回退

`gpt-image-2` 始终返回 base64，请求体不要带 `response_format`（旧 DALL-E 参数，gpt-image 系列不支持）。`$PROMPT` 为「构建提示词」步骤拼出的完整提示词。

两种调用方式二选一：未设置 `REF_IMAGE` → 走「文生图」；设置了 → 走「图生图」。

#### 文生图（默认）

```bash
set -euo pipefail
: "${GPT_IMAGE_API_KEY:?请设置 export GPT_IMAGE_API_KEY=你的key}"
: "${PROMPT:?请先 export PROMPT=构建提示词步骤拼好的完整提示词}"
BASE_URL="${GPT_IMAGE_BASE_URL:-https://api.openai.com/v1}"
MODEL="${GPT_IMAGE_MODEL:-gpt-image-2}"
SIZE="${GPT_IMAGE_SIZE:-1024x1536}"
BOOK_DIR="${BOOK_DIR:?请先 export BOOK_DIR=./covers/<书名>}"

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

#### 图生图（提供参考图时）

`/v1/images/edits` 走 `multipart/form-data`，**不能** 用 `Content-Type: application/json`。文本字段用 `--form-string`（避免 `@` 被误判为文件引用），图片字段用 `-F image=@path`。

```bash
set -euo pipefail
: "${GPT_IMAGE_API_KEY:?请设置 export GPT_IMAGE_API_KEY=你的key}"
: "${PROMPT:?请先 export PROMPT=构建提示词步骤拼好的完整提示词}"
BASE_URL="${GPT_IMAGE_BASE_URL:-https://api.openai.com/v1}"
MODEL="${GPT_IMAGE_MODEL:-gpt-image-2}"
SIZE="${GPT_IMAGE_SIZE:-1024x1536}"
BOOK_DIR="${BOOK_DIR:?请先 export BOOK_DIR=./covers/<书名>}"
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

### Step 5：导出平台上传尺寸（平台有固定像素时）

平台有固定上传像素（番茄 600×800）时，把原图**居中裁剪+缩放**成上传尺寸——不论出图是 2:3 还是 3:4 都裁成平台精确像素，不变形，避免平台再裁切掉书名/笔名。原图保留、另存 `_上传` 版；`SRC` 和 `TARGET` 直接使用前序步骤的任务值，不依赖跨 shell 的临时变量：

```bash
SRC='<Step 4 生成的原图绝对路径>'
TARGET='<Step 1 确定的平台上传尺寸；无则留空>'
[ -f "$SRC" ] || { echo "封面原图不存在: $SRC" >&2; exit 1; }
if [ -n "$TARGET" ] && [ -f "$SRC" ]; then
  UP="${SRC%.png}_上传.png"; W="${TARGET%x*}"; H="${TARGET#*x}"
  if command -v magick >/dev/null 2>&1; then M=magick
  elif command -v convert >/dev/null 2>&1; then M=convert; else M=""; fi
  if [ -n "$M" ]; then
    "$M" "$SRC" -resize "${W}x${H}^" -gravity center -extent "${W}x${H}" "$UP"  # 缩放填满后居中裁
  elif command -v sips >/dev/null 2>&1; then
    cp "$SRC" "$UP"
    sw=$(sips -g pixelWidth "$UP" | awk '/pixelWidth/{print $NF}')
    sh=$(sips -g pixelHeight "$UP" | awk '/pixelHeight/{print $NF}')
    if [ $((sw*H)) -ge $((sh*W)) ]; then sips --resampleHeight "$H" "$UP" >/dev/null
    else sips --resampleWidth "$W" "$UP" >/dev/null; fi
    sips -c "$H" "$W" "$UP" >/dev/null   # sips -c 是 高 宽，居中裁
  else
    echo "无 magick/convert/sips，跳过；手动把 $SRC 居中裁剪+缩放到 $TARGET 再上传" >&2
  fi
  [ -f "$UP" ] && file "$UP"
fi
```

> 书名/笔名已在提示词里留中心安全区，居中裁剪不会切到。

### Step 6：质量检查 + 迭代

| 检查项 | 标准 |
|:-------|:-----|
| 文字渲染 | 书名清晰可辨，字体风格匹配题材 |
| 题材匹配 | 视觉风格与书名题材一致 |
| 构图合理 | 主体突出，文字不遮挡核心画面 |
| 平台适配 | 符合目标平台的封面风格调性 |
| 平台尺寸 | 比例与平台一致；缩放到上传尺寸后书名、笔名完整可见、未被裁切 |

不满意时调整方向：更换构图、调整色调、换字体风格、换平台风格。

交付时这样告诉作者；命令、环境变量和接口报错不贴给作者，失败时用一句话说原因和办法（如「生图接口没配好，需要先设置 API Key」）：

<!-- author-report -->
```md
封面做好了：`{封面图路径}`{；{平台}上传版（{上传尺寸}）：`{上传版路径}`}
这版的思路：{构图 + 色调 + 书名字体，一句话}
想调的话可以说：{2-3 个具体方向，如「换成人物特写」「书名改成毛笔字」}
```

---

## 参考资料

| 文件 | 何时加载 |
|:-----|:---------|
| [references/cover-styles.md](references/cover-styles.md) | 题材→视觉风格映射、平台风格详情、提示词模板 |

---

## 语言

- 跟随用户的语言回复，用户用什么语言就用什么语言回复
- 中文回复遵循《中文文案排版指北》
