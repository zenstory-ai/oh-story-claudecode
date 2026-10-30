---
name: story-cover
version: 1.0.0
description: "小说封面生成与提示词设计。根据书名、作者名和题材构建封面提示词；用户只要提示词时不生图，要求封面图时调用 GPT-Image-2，Codex CLI 优先使用内置 ImageGen。触发方式：/story-cover、/封面、「帮我做个封面」「生成封面图」「封面提示词」「封面设计」。"
metadata: {"openclaw":{"requires":{"env":["GPT_IMAGE_API_KEY"],"bins":["curl","jq","base64"]},"primaryEnv":"GPT_IMAGE_API_KEY","source":"https://github.com/zenstory-ai/oh-story-claudecode"}}
---
# story-cover：小说封面生成

根据书名和题材生成包含书名、笔名的完整封面，让读者一眼看出题材和氛围。

**仅提示词模式**：用户只要提示词，或 `story-publish` 选了仅提示词时，只做 Step 1-3，交付完整提示词，不需要生图工具、API Key 或输出目录；要封面图才继续 Step 4-6。由 `story-publish` 调用时，它传来的已确认书名、简介、笔名、平台和题材不再重问；结束时返回完整提示词原文，生图成功再附图片路径和质量检查结果，失败就说明原因。

---

## 生成通路

- **Codex 内置（优先）**：当前 Codex CLI 会话可调用 `$imagegen` / `image_gen` 时，直接调用工具生成并保存，无需 `OPENAI_API_KEY` 或 `GPT_IMAGE_API_KEY`，不运行 `curl`。
- **API 回退**：仅在会话没有内置工具或用户明确指定 API 时使用，需要 `GPT_IMAGE_API_KEY`；环境变量和命令在 [references/api-fallback.md](references/api-fallback.md)，走这条通路时再读。工具缺失不等于 Codex 订阅不支持生图；内置调用失败时先报告错误，不静默切换到可能收费的 API。

## 生成流程

### Step 1：收集信息

先找当前书：项目根 `.active-book` 指向项目内现有目录时就是当前书；否则从项目根往下最多 4 层找（跳过 `.` 开头的目录、`node_modules`、`拆文库/`、`对标/`），含 `追踪/`、`正文/`、`设定/` 子目录或 `正文.md`、`设定.md` 文件的是书目录，找到多本时请作者选择。有 `正文/` 或 `设定/` 子目录的是长篇，有 `正文.md` 或 `设定.md` 的是短篇。找到后读：

- 长篇：`设定/题材定位.md`「基本信息」的书名、题材类型、目标平台、核心梗；
- 短篇：`设定.md`「基本信息」的标题、目标平台、目标情绪，以及「一句话梗概」「题材招式」。

已有或调用方传入的已确认字段不再问；笔名没有明确提供时才问。没有书目录或缺项时，用宿主可用的提问方式一次问齐缺少的书名、笔名、目标平台。

> **书名和笔名是封面必需信息**：缺任一时先请作者补全，不得编造或留空。

选填：参考图 `REF_IMAGE`（本地路径或 URL）、风格偏好；参考图的用法见 Step 4。

**保存位置**：有书目录时存到 `{书目录}/封面/`，不用问；没有书目录时用 `./covers/{书名}/封面/`。下文 `BOOK_DIR` 指 `封面/` 的上一层。

**按目标平台定比例和上传尺寸**：番茄上传 600×800，比例 **3:4**，出图比例不符时平台再次裁剪可能切掉书名或笔名；其他平台按竖版 2:3 交付，作者给出平台上传像素时按该尺寸导出。各平台的画风关键词见 [references/cover-styles.md](references/cover-styles.md)「平台风格」。

### Step 2：题材判定

在 [references/cover-styles.md](references/cover-styles.md) 的「风格库」里选一个题材：

仅提示词模式没有题材依据时先问作者，不用下面第 2 条的「都市」兜底。

1. 有「题材类型」（长篇）或梗概、题材招式（短篇）时，按内容选风格库中最接近的一节。
2. 没有，或对不上风格库任何一节（如年代、种田、无限流、电竞）时，用书名（必要时简介）对照「题材推断规则」：只命中一个题材就用它；命中多个按该表下方的优先级取一；都没命中先用「都市」。
3. 第 2 条推断出的题材，在 Step 4 给作者看方案时一并说出来，作者可以改。

### Step 3：构建提示词

提示词 = **文字层** + **风格层** + **画面层**。设计指令用英文，书名和笔名保留作者提供的原文。所选题材的字体、标签、色彩、人物、背景、光效都在「风格库」同一节里查。

**文字层**：GPT-Image-2 可直接渲染中文。书名在上方居中，用该题材的书名字体；笔名在下方居中，用该题材的笔名字体。笔名要和书名风格呼应、清晰可读而不抢焦点：

- 大小用 `small`；位置 `at bottom center`，与画面底部留出间距；
- 必须带一种装饰：线条、边框、小图标或光效；
- 颜色与背景形成对比但不刺眼。

**风格层**：目标平台在「平台风格」表里有对应时，取它的关键词串；没有对应（如黑岩、红果、小程序）时省掉这一层，只靠题材风格。

**画面层**：题材的风格标签、人物、背景、色彩、光效，加上一种构图（见「构图变体」）。

完整提示词模板（唯一一份，示例和改版都按它拼）：

```
Chinese web novel cover design, [平台风格].
Title text '{书名}' at top center in [书名字体].
Author name '{笔名}' at bottom center in [笔名字体].
[题材风格标签]. [构图关键词]. [人物描述]. [背景描述].
[色彩指令]. [光效指令].
Professional book cover, high detail digital painting, portrait [平台比例：番茄=3:4，默认=2:3] ratio, keep title and author name inside the central safe area away from edges (inner ~85%), no watermark
```

仅提示词模式在这里交付 1-3 个完整提示词方案后结束；还没确认的画面细节写成可选方向，不当成小说里的事实。

写法要点：
- 人物描述写清服饰、姿态、发型、表情、道具，不要只写 `a man`；
- 背景分三层：前景人物或道具，中景场景，远景氛围；
- 光效写清光源方向和颜色，如 `dramatic golden light from above`；
- 用 `digital painting style`，不用 `photo`，避免真人照片感。

### Step 4：选方案并生成

先从「构图变体」里挑 2-3 种适合本题材的构图，每种用一句话描述画面（构图、主色、书名字体），连同 Step 2 定的题材一起给作者挑。作者选定后只生成那一张；作者说「都出」时每个方案单独生成一次。

#### Codex 内置 ImageGen（优先）

1. 用 Step 3 的完整提示词调用 `image_gen`。比例和安全区写进提示词，不传 `GPT_IMAGE_MODEL`、`GPT_IMAGE_SIZE`、`response_format` 等 API 参数。
2. 有 `REF_IMAGE` 时，本地文件先用图片查看工具载入会话；URL 先下载再载入。说明它是编辑目标还是风格参考，并列出必须保持的内容。
3. 先创建 `BOOK_DIR/封面/`，再把工具返回的图片复制为 `封面_vN.png`，`N` 自增且不覆盖旧版；保留 `$CODEX_HOME/generated_images/` 原文件，同时保存同名 `.prompt.txt`，有参考图再保存 `.ref.txt`。确认图片可读，并把原图绝对路径交给 Step 5。

#### API 回退

读 [references/api-fallback.md](references/api-fallback.md)，按其中的环境变量和命令生成；没有参考图走文生图，有参考图走图生图。生成后把原图绝对路径交给 Step 5。

### Step 5：导出平台上传尺寸（平台有固定像素时）

平台有固定上传像素（番茄 600×800）时，把原图**居中裁剪+缩放**到精确尺寸，保持画面比例，原图保留并另存 `_上传` 版。`SRC` 填 Step 4 的原图绝对路径，`TARGET` 填 Step 1 的上传尺寸，不依赖上一段 shell 的临时变量：

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

> 提示词中的中心安全区用于减少裁切风险；导出后仍按 Step 6 检查书名和笔名是否完整。

### Step 6：质量检查 + 迭代

| 检查项 | 标准 |
|:-------|:-----|
| 文字渲染 | 书名、笔名清晰可辨，字体风格匹配题材 |
| 题材匹配 | 视觉风格与本书题材一致 |
| 构图合理 | 主体突出，文字不遮挡核心画面 |
| 平台适配 | 符合目标平台的封面风格 |
| 平台尺寸 | 比例与平台一致；缩放到上传尺寸后书名、笔名完整可见、未被裁切 |

未达标或作者希望调整时，可更换构图、色调、字体或平台风格，改完重新生成一张。

交付时这样告诉作者；命令、环境变量和接口报错不贴给作者，失败时用一句话说原因和办法（如「生图接口没配好，需要先设置 API Key」）：

<!-- author-report -->
```md
封面做好了：`{封面图路径}`{；{平台}上传版（{上传尺寸}）：`{上传版路径}`}
这版的思路：{构图 + 色调 + 书名字体，一句话}
想调的话可以说：{2-3 个具体方向，如「换成人物特写」「书名改成毛笔字」}
```

---

## 参考资料

| 文件 | 何时读 |
|:-----|:---------|
| [references/cover-styles.md](references/cover-styles.md) | Step 1 定平台风格、Step 2 定题材、Step 3 查字体和画面时 |
| [references/api-fallback.md](references/api-fallback.md) | Step 4 走 API 回退时 |
