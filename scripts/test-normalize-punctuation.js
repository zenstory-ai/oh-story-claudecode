#!/usr/bin/env node
"use strict";

const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

const repoRoot = path.resolve(__dirname, "..");
const normalizer = path.join(
  repoRoot,
  "skills/story-deslop/scripts/normalize-punctuation.js"
);
const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "normalize-punctuation-"));

function run(args) {
  return spawnSync(process.execPath, [normalizer, ...args], {
    cwd: repoRoot,
    encoding: "utf8",
  });
}

try {
  for (const [name, bytes] of [
    ["gbk", Buffer.from("c4e3bac32d2dcac0bde7", "hex")],
    ["utf16le", Buffer.concat([Buffer.from([0xff, 0xfe]), Buffer.from("正文--继续", "utf16le")])],
    ["truncated-utf8", Buffer.concat([Buffer.from("正文--"), Buffer.from([0xe4, 0xb8])])],
  ]) {
    const file = path.join(tmpDir, `${name}.md`);
    fs.writeFileSync(file, bytes);
    for (const args of [["--check", file], [file]]) {
      const result = run(args);
      assert.strictEqual(result.status, 2, `${name}: ${result.stdout}${result.stderr}`);
      assert.match(result.stderr, /utf-8/i);
      assert.deepStrictEqual(fs.readFileSync(file), bytes, `${name}: invalid bytes must remain untouched`);
    }
  }

  const bom = path.join(tmpDir, "bom.md");
  fs.writeFileSync(bom, "\ufeff# 正文\r\n原文�--继续。\r\n", "utf8");
  assert.strictEqual(run([bom]).status, 0);
  assert.deepStrictEqual(fs.readFileSync(bom), Buffer.from("\ufeff# 正文\r\n原文�，继续。\r\n"));

  const prose = path.join(tmpDir, "prose.md");
  const original = [
    "---",
    "title: fixture",
    "---",
    "# 标题",
    "他说……答案就是这样——真的。",
    "10--20",
    "---",
    "```text",
    "围栏内……与---必须保留",
    "```",
    "「引号……保留样式」",
    "",
  ].join("\r\n");
  fs.writeFileSync(prose, original, "utf8");

  const check = run(["--check", prose]);
  assert.strictEqual(check.status, 1, check.stderr);
  assert.match(check.stdout, /ellipsis/);
  assert.match(check.stdout, /em-dash/);
  assert.match(check.stdout, /double-hyphen/);
  assert.match(check.stdout, /markdown-divider/);
  assert.strictEqual(fs.readFileSync(prose, "utf8"), original, "--check must not write");

  const write = run([prose]);
  assert.strictEqual(write.status, 0, write.stderr);
  const normalized = fs.readFileSync(prose, "utf8");
  assert(normalized.includes("title: fixture\r\n---"), "frontmatter must remain intact");
  assert(normalized.includes("围栏内……与---必须保留"), "fenced text must remain intact");
  assert(normalized.includes("10到20"), "numeric ranges must use 到");
  assert(normalized.includes("「引号，保留样式」"), "default mode must keep quote style");
  assert(!normalized.split("\r\n").includes("---", 3), "body divider must be removed");
  assert(normalized.includes("\r\n"), "CRLF input must keep CRLF output");
  const normalizedProse = normalized
    .replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n/, "")
    .replace(/```[\s\S]*?```/g, "");
  assert(!/(?:……|——|--)/m.test(normalizedProse));

  const second = run([prose]);
  assert.strictEqual(second.status, 0, second.stderr);
  assert.match(second.stdout, /Changed files: 0/);
  assert.strictEqual(fs.readFileSync(prose, "utf8"), normalized, "normalization must be idempotent");

  // 混合行尾：一处孤立 CRLF 不得把全文行尾翻成 CRLF；没有标点问题就必须一个字节都不动，
  // 否则 --check 报零问题、写入模式却改出整篇 diff，两种模式对不上。
  const mixedEol = path.join(tmpDir, "mixed-eol.md");
  const mixedOriginal = "他站在原地。\r\n风很大。\n雨停了。\n";
  fs.writeFileSync(mixedEol, mixedOriginal, "utf8");
  const mixedCheck = run(["--check", mixedEol]);
  assert.strictEqual(mixedCheck.status, 0, mixedCheck.stdout + mixedCheck.stderr);
  const mixedWrite = run([mixedEol]);
  assert.strictEqual(mixedWrite.status, 0, mixedWrite.stderr);
  assert.match(mixedWrite.stdout, /Changed files: 0/);
  assert.strictEqual(
    fs.readFileSync(mixedEol, "utf8"),
    mixedOriginal,
    "mixed line endings must survive a clean pass byte-for-byte"
  );

  // 混合行尾 + 真标点问题：只改标点，逐行行尾保持原样。
  const mixedDirty = path.join(tmpDir, "mixed-eol-dirty.md");
  fs.writeFileSync(mixedDirty, "他说……真的。\r\n风很大——雨停了。\n", "utf8");
  assert.strictEqual(run([mixedDirty]).status, 0);
  assert.strictEqual(
    fs.readFileSync(mixedDirty, "utf8"),
    "他说，真的。\r\n风很大，雨停了。\n",
    "per-line endings must be preserved while punctuation is normalized"
  );

  // HTML 注释里的 `--` 不是停顿标点：`<!-- 去味:跳过 -->` 豁免标记必须原样留在正文里，
  // 被改成 `<! 去味:跳过 ，>` 就不再是注释，会当可见文本泄进成稿。
  const marker = path.join(tmpDir, "marker.md");
  const markerOriginal = [
    "# 第12章 雨夜",
    "<!-- 去味:跳过 -->",
    "他握紧了拳头，慢慢站起身。",
    "<!--",
    "跨行注释里的---与……也照旧",
    "-->",
    "正文……继续。<!-- 行内备注 -->",
    "",
  ].join("\n");
  fs.writeFileSync(marker, markerOriginal, "utf8");
  const markerCheck = run(["--check", marker]);
  assert.strictEqual(markerCheck.status, 1, markerCheck.stderr);
  assert.doesNotMatch(markerCheck.stdout, /double-hyphen/, "HTML 注释不得报 double-hyphen");
  assert.doesNotMatch(markerCheck.stdout, /markdown-divider/, "注释内的 --- 不是正文分隔线");
  assert.strictEqual(run([marker]).status, 0);
  const markerNormalized = fs.readFileSync(marker, "utf8");
  assert(markerNormalized.includes("<!-- 去味:跳过 -->"), "去味豁免标记必须原样保留");
  assert(markerNormalized.includes("跨行注释里的---与……也照旧"), "跨行注释内容必须原样保留");
  assert(markerNormalized.includes("<!-- 行内备注 -->"), "行内注释必须原样保留");
  assert(markerNormalized.includes("正文，继续。"), "注释外的正文仍要归一化");

  // 未闭合注释不是“从这里到 EOF 都合法豁免”：必须具名报错，后续正文仍参与检查/归一化。
  // 否则一个误写的 `<!--` 会让整篇的 `……` / `---` 在 --check 下静默 exit 0。
  const unclosedComment = path.join(tmpDir, "unclosed-comment.md");
  fs.writeFileSync(
    unclosedComment,
    "# 第13章\n<!-- 临时备注\n正文……继续。\n---\n",
    "utf8"
  );
  const unclosedCheck = run(["--check", unclosedComment]);
  assert.strictEqual(unclosedCheck.status, 1, unclosedCheck.stdout + unclosedCheck.stderr);
  assert.match(unclosedCheck.stdout, /html-comment-unclosed/);
  assert.match(unclosedCheck.stdout, /ellipsis|markdown-divider/);
  assert.strictEqual(run([unclosedComment]).status, 0);
  const unclosedNormalized = fs.readFileSync(unclosedComment, "utf8");
  assert(unclosedNormalized.includes("<!-- 临时备注"), "未闭合注释起始符不应被改坏");
  assert(unclosedNormalized.includes("正文，继续。"), "未闭合注释后的正文仍须归一化");
  assert(!unclosedNormalized.includes("\n---\n"), "未闭合注释后的正文分隔线仍须移除");

  // 删空停顿符会把两侧的半角点/连字符粘成新的 `...`/`--`；一遍必须清干净，
  // 否则成稿留着本该删掉的 ASCII 省略号，事后重跑同一步又会改动已定稿的正文。
  const merge = path.join(tmpDir, "merge.md");
  fs.writeFileSync(merge, "他.……..说\n-…...……-2.（！）\n", "utf8");
  assert.strictEqual(run([merge]).status, 0);
  assert.strictEqual(fs.readFileSync(merge, "utf8"), "他，说\n2.（！）\n");
  const mergeRecheck = run(["--check", merge]);
  assert.strictEqual(mergeRecheck.status, 0, "一遍归一化后 --check 必须已清零: " + mergeRecheck.stdout);
  assert.match(run([merge]).stdout, /Changed files: 0/);

  const fences = path.join(tmpDir, "fences.md");
  const fencedOriginal = [
    "~~~markdown",
    "tilde 围栏内……必须保留",
    "```",
    "不同标记不能关闭——仍须保留",
    "~~",
    "更短的波浪线不能关闭--仍须保留",
    "~~~",
    "波浪线围栏外……必须归一化",
    "````markdown",
    "```javascript",
    "四反引号围栏内……必须保留",
    "```",
    "较短的反引号不能关闭——仍须保留",
    "````",
    "反引号围栏外……必须归一化",
    "",
  ].join("\n");
  fs.writeFileSync(fences, fencedOriginal, "utf8");

  const fencedWrite = run([fences]);
  assert.strictEqual(fencedWrite.status, 0, fencedWrite.stderr);
  const fencedNormalized = fs.readFileSync(fences, "utf8");
  assert(fencedNormalized.includes("tilde 围栏内……必须保留"));
  assert(fencedNormalized.includes("不同标记不能关闭——仍须保留"));
  assert(fencedNormalized.includes("更短的波浪线不能关闭--仍须保留"));
  assert(fencedNormalized.includes("四反引号围栏内……必须保留"));
  assert(fencedNormalized.includes("较短的反引号不能关闭——仍须保留"));
  assert(fencedNormalized.includes("波浪线围栏外，必须归一化"));
  assert(fencedNormalized.includes("反引号围栏外，必须归一化"));

  const ascii = path.join(tmpDir, "ascii.md");
  fs.writeFileSync(ascii, "「甲」与“乙”\n", "utf8");
  assert.strictEqual(run(["--quote-mode=ascii", ascii]).status, 0);
  assert.strictEqual(fs.readFileSync(ascii, "utf8"), '"甲"与"乙"\n');

  const yan = path.join(tmpDir, "yan.md");
  fs.writeFileSync(yan, '"甲"和“乙”\n', "utf8");
  assert.strictEqual(run(["--quote-mode", "yan", yan]).status, 0);
  assert.strictEqual(fs.readFileSync(yan, "utf8"), "「甲」和「乙」\n");

  const missing = run([path.join(tmpDir, "missing.md")]);
  assert.strictEqual(missing.status, 2);
  assert.match(missing.stderr, /unable to read/);

  console.log("OK: punctuation normalizer check/write, robust fences, CRLF, quote modes, and errors");
} finally {
  fs.rmSync(tmpDir, { recursive: true, force: true });
}
