#!/usr/bin/env node
// test-outline-copy.mjs — native node:test regression suite for check-outline-copy.js (all 31 cases).

import { describe, test, before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SCRIPT = path.join(REPO_ROOT, "skills/story-long-write/scripts/check-outline-copy.js");

const COPIED = "他握紧那柄旧刀在雨里站了整整一夜没有离开半步";
const OATH = "此誓天地可鉴";
const VOW = "虽死无悔";
const PANEL = "天王级唱功大师级导演能力中国军魂伴奏";

let tmpDir;

before(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "test-outline-copy-"));
});

after(() => {
  if (tmpDir) fs.rmSync(tmpDir, { recursive: true, force: true });
});

function writeFile(relPath, content) {
  const full = path.join(tmpDir, relPath);
  fs.mkdirSync(path.dirname(full), { recursive: true });
  fs.writeFileSync(full, content, "utf8");
  return full;
}

function runDetector(args, nodeArgs = []) {
  const res = spawnSync(process.execPath, [...nodeArgs, SCRIPT, ...args], {
    encoding: "utf8",
  });
  return {
    status: res.status,
    output: `${res.stdout || ""}${res.stderr || ""}`,
  };
}

describe("check-outline-copy.js (31 cases)", () => {
  test("1. anchor-tail: flags unauthorized overlap before anchor", () => {
    const o = writeFile(
      "o1.md",
      `#### 情节细化\n- 点1：${COPIED}，${OATH}。\n- 复沓锚句：\n  点1：${OATH}\n`
    );
    const p = writeFile("p1.md", `${COPIED}，${OATH}。\n`);
    const r = runDetector(["--outline", o, p]);
    assert.equal(r.status, 1, r.output);
    assert.ok(r.output.includes(`22 字「${COPIED}」`), r.output);
    assert.ok(r.output.includes("1 处 6 字为登记原话"), r.output);
  });

  test("2. anchor-head: flags unauthorized overlap after anchor (v0.10 field name)", () => {
    const o = writeFile(
      "o2.md",
      `#### 情节细化\n- 点1：${OATH}，${COPIED}。\n- 原样出现的原话：\n  点1：${OATH}\n`
    );
    const p = writeFile("p2.md", `${OATH}，${COPIED}。\n`);
    const r = runDetector(["--outline", o, p]);
    assert.equal(r.status, 1, r.output);
    assert.ok(r.output.includes(`22 字「${COPIED}」`), r.output);
    assert.ok(r.output.includes("1 处 6 字为登记原话"), r.output);
  });

  test("3. multi-anchor: deducts multiple anchors while reporting middle overlap", () => {
    const o = writeFile(
      "o3.md",
      `#### 情节细化\n- 点1：${OATH}，${COPIED}，${VOW}。\n- 复沓锚句：\n  点1：${OATH}\n  点1：${VOW}\n`
    );
    const p = writeFile("p3.md", `${OATH}，${COPIED}，${VOW}。\n`);
    const r = runDetector(["--outline", o, p]);
    assert.equal(r.status, 1, r.output);
    assert.ok(r.output.includes(`22 字「${COPIED}」`), r.output);
    assert.ok(r.output.includes("10 字为登记原话"), r.output);
  });

  test("4. pure-anchor: exempts exact registered anchor", () => {
    const o = writeFile(
      "o4.md",
      `#### 情节细化\n- 点1：面板弹出，主角确认奖励到手。\n- 复沓锚句：\n  点1：${PANEL}\n`
    );
    const p = writeFile("p4.md", `眼前忽然亮起一行小字。\n${PANEL}\n他抬手把那行字抹掉。\n`);
    const r = runDetector(["--outline", o, p]);
    assert.equal(r.status, 0, r.output);
    assert.ok(r.output.includes("无未授权誊抄"), r.output);
    assert.ok(r.output.includes("1 处 18 字"), r.output);
  });

  test("5. short-story-autodiscover: finds 小节大纲.md beside 正文.md", () => {
    writeFile("短篇/小节大纲.md", `## 第一节\n- 点1：${COPIED}。\n`);
    const p = writeFile("短篇/正文.md", `${COPIED}。\n`);
    const r = runDetector([p]);
    assert.equal(r.status, 1, r.output);
    assert.ok(r.output.includes(`22 字「${COPIED}」`), r.output);
  });

  test("6. long-form-autodiscover: finds 大纲/细纲_第001章.md for 正文/第001章_雨夜.md", () => {
    writeFile("长篇/大纲/细纲_第001章.md", `## 第 1 章\n- 点1：${COPIED}。\n`);
    const p = writeFile("长篇/正文/第001章_雨夜.md", `# 第001章 雨夜\n\n${COPIED}。\n`);
    const r = runDetector([p]);
    assert.equal(r.status, 1, r.output);
    assert.ok(r.output.includes(`22 字「${COPIED}」`), r.output);
  });

  test("7. legacy-no-anchor-field: works without anchor field", () => {
    const o = writeFile("o7.md", `#### 情节细化\n- 点1：${COPIED}，${OATH}。\n`);
    const p = writeFile("p7.md", `${COPIED}，${OATH}。\n`);
    const r = runDetector(["--outline", o, p]);
    assert.equal(r.status, 1, r.output);
    assert.ok(r.output.includes("28 字"), r.output);
    assert.ok(!r.output.includes("为登记原话"), r.output);
  });

  test("8. anchor-field-none: ignores literal '无'", () => {
    const o = writeFile(
      "o8.md",
      `#### 情节细化\n- 点1：${COPIED}。\n- 复沓锚句：无\n- 结尾设定：主角离开。\n`
    );
    const p = writeFile("p8.md", `${COPIED}。\n`);
    const r = runDetector(["--outline", o, p]);
    assert.equal(r.status, 1, r.output);
    assert.ok(r.output.includes(`22 字「${COPIED}」`), r.output);
    assert.ok(!r.output.includes("为登记原话"), r.output);
  });

  test("9. clean: silent exit 0 when no overlap", () => {
    const o = writeFile("o9.md", `#### 情节细化\n- 点1：${COPIED}。\n`);
    const p = writeFile("p9.md", "雨停了，他终于肯回头看一眼身后那扇门。\n");
    const r = runDetector(["--outline", o, p]);
    assert.equal(r.status, 0, r.output);
    assert.equal(r.output, "");
  });

  test("10. missing-outline: skips cleanly when auto-discovery finds no outline", () => {
    const p = writeFile("orphan.md", `${COPIED}。\n`);
    const r = runDetector([p]);
    assert.equal(r.status, 0, r.output);
    assert.ok(r.output.includes("跳过"), r.output);
    assert.ok(r.output.includes(path.resolve(p)), r.output);
    assert.ok(r.output.includes("未自动发现细纲"), r.output);
  });

  test("11-12. multi-prose-batch and later-hit check each chapter independently", () => {
    writeFile("批/大纲/细纲_第005章.md", `## 第 5 章\n- 点1：${COPIED}。\n`);
    writeFile("批/大纲/细纲_第006章.md", `## 第 6 章\n- 点1：${VOW}，主角转身离开。\n`);
    const ch5 = writeFile("批/正文/第005章_雨夜.md", `# 第005章 雨夜\n\n${COPIED}。\n`);
    const ch6 = writeFile(
      "批/正文/第006章_天明.md",
      "# 第006章 天明\n\n雨停了，他终于肯回头看一眼身后那扇门。\n"
    );

    const r11 = runDetector([ch5, ch6]);
    assert.equal(r11.status, 1, r11.output);
    assert.ok(r11.output.includes("第005章_雨夜.md"), r11.output);
    assert.ok(r11.output.includes(`22 字「${COPIED}」`), r11.output);

    const r12 = runDetector([ch6, ch5]);
    assert.equal(r12.status, 1, r12.output);
    assert.ok(r12.output.includes("第005章_雨夜.md"), r12.output);
  });

  test("13-19. CLI error handling: missing files, bad options, directory inputs", () => {
    const o9 = writeFile("o9-err.md", `#### 情节细化\n- 点1：${COPIED}。\n`);
    const p9 = writeFile("p9-err.md", "雨停了。\n");
    const missingOutline = path.join(tmpDir, "不存在的细纲.md");
    const missingProse = path.join(tmpDir, "不存在的正文.md");

    const r13 = runDetector(["--outline", missingOutline, p9]);
    assert.equal(r13.status, 2, r13.output);
    assert.ok(r13.output.includes("无法读取显式细纲"), r13.output);
    assert.ok(r13.output.includes(path.resolve(missingOutline)), r13.output);
    assert.ok(r13.output.includes("不存在"), r13.output);

    const r14 = runDetector(["--outline", o9, missingProse]);
    assert.equal(r14.status, 2, r14.output);
    assert.ok(r14.output.includes("无法读取正文"), r14.output);
    assert.ok(r14.output.includes(path.resolve(missingProse)), r14.output);
    assert.ok(r14.output.includes("不存在"), r14.output);

    const r15 = runDetector(["--outline"]);
    assert.equal(r15.status, 2, r15.output);
    assert.ok(r15.output.includes("--outline 缺少路径"), r15.output);

    const r16 = runDetector(["--unknown", p9]);
    assert.equal(r16.status, 2, r16.output);
    assert.ok(r16.output.includes("未知选项: --unknown"), r16.output);

    const r17 = runDetector(["--outline", o9]);
    assert.equal(r17.status, 2, r17.output);
    assert.ok(r17.output.includes("缺少正文路径"), r17.output);

    const dirOutline = path.join(tmpDir, "目录细纲");
    fs.mkdirSync(dirOutline, { recursive: true });
    const r18 = runDetector(["--outline", dirOutline, p9]);
    assert.equal(r18.status, 2, r18.output);
    assert.ok(r18.output.includes("无法读取显式细纲"), r18.output);
    assert.ok(r18.output.includes(path.resolve(dirOutline)), r18.output);
    assert.ok(r18.output.includes("不是普通文件"), r18.output);

    const dirProse = path.join(tmpDir, "目录正文");
    fs.mkdirSync(dirProse, { recursive: true });
    const r19 = runDetector(["--outline", o9, dirProse]);
    assert.equal(r19.status, 2, r19.output);
    assert.ok(r19.output.includes("无法读取正文"), r19.output);
    assert.ok(r19.output.includes(path.resolve(dirProse)), r19.output);
    assert.ok(r19.output.includes("不是普通文件"), r19.output);
  });

  test("20-23. fault-injection via --require and directory auto-discovery error", () => {
    const explode = writeFile("explode.md", `${COPIED}。\n`);
    const hook20 = writeFile(
      "throw-on-basename.js",
      `const path = require('path')
const originalBasename = path.basename
path.basename = function basename(file, ...args) {
  if (originalBasename.call(this, file, ...args) === 'explode.md') throw new Error('synthetic unexpected failure')
  return originalBasename.call(this, file, ...args)
}
`
    );
    const r20 = runDetector([explode], ["--require", hook20]);
    assert.equal(r20.status, 2, r20.output);
    assert.ok(r20.output.includes("细纲照搬检测异常"), r20.output);
    assert.ok(r20.output.includes("synthetic unexpected failure"), r20.output);

    writeFile("批fault/大纲/细纲_第005章.md", `## 第 5 章\n- 点1：${COPIED}。\n`);
    const ch5 = writeFile("批fault/正文/第005章_雨夜.md", `# 第005章 雨夜\n\n${COPIED}。\n`);

    const hook21 = writeFile(
      "throw-on-readdir.js",
      `const fs = require('fs')
const original = fs.readdirSync
fs.readdirSync = function (dir, ...args) {
  if (String(dir).endsWith('大纲')) {
    const error = new Error(\`EACCES: cannot read \${dir}\`)
    error.code = 'EACCES'
    throw error
  }
  return original.call(this, dir, ...args)
}
`
    );
    const r21 = runDetector([ch5], ["--require", hook21]);
    assert.equal(r21.status, 2, r21.output);
    assert.ok(r21.output.includes("EACCES"), r21.output);
    assert.ok(r21.output.includes("大纲"), r21.output);

    const hook22 = writeFile(
      "throw-on-outline-read.js",
      `const fs = require('fs')
const original = fs.readFileSync
fs.readFileSync = function (file, ...args) {
  if (String(file).endsWith('细纲_第005章.md')) {
    const error = new Error(\`EACCES: cannot read \${file}\`)
    error.code = 'EACCES'
    throw error
  }
  return original.call(this, file, ...args)
}
`
    );
    const r22 = runDetector([ch5], ["--require", hook22]);
    assert.equal(r22.status, 2, r22.output);
    assert.ok(r22.output.includes("EACCES"), r22.output);
    assert.ok(r22.output.includes("细纲_第005章.md"), r22.output);

    fs.mkdirSync(path.join(tmpDir, "非文件细纲/小节大纲.md"), { recursive: true });
    const p23 = writeFile("非文件细纲/正文.md", `${COPIED}。\n`);
    const r23 = runDetector([p23]);
    assert.equal(r23.status, 2, r23.output);
    assert.ok(r23.output.includes("不是普通文件"), r23.output);
  });

  test("24-31. post-write completion sections excluded without hiding real copy", () => {
    const prose = writeFile("completed-prose.md", `${COPIED}。\n`);

    const excluded = [
      ["24. completion-heading", `#### 实际完成情况\n${COPIED}。\n`],
      ["25. completion-field", `- 实际完成情况：${COPIED}。\n- 结尾设定：离开。\n`],
      ["26. completion-bold-field", `- **实际完成情况**：\n  ${COPIED}。\n- 结尾设定：离开。\n`],
      ["27. completion-nested-heading", `#### 实际完成情况\n已完成。\n##### 实际落地\n${COPIED}。\n`],
    ];
    for (const [label, outlineText] of excluded) {
      const o = writeFile("completion.md", outlineText);
      const r = runDetector(["--outline", o, prose]);
      assert.equal(r.status, 0, `${label}: ${r.output}`);
    }

    const flagged = [
      ["28. copy-before-completion", `#### 情节细化\n${COPIED}。\n#### 实际完成情况\n已完成。\n`],
      [
        "29. copy-after-completion-peer-heading",
        `#### 实际完成情况\n##### 实际落地\n已完成。\n#### 后续情节\n${COPIED}。\n`,
      ],
      [
        "30. copy-after-completion-parent-heading",
        `#### 实际完成情况\n##### 实际落地\n已完成。\n## 下一章\n${COPIED}。\n`,
      ],
      [
        "31. copy-after-completion-field",
        `- **实际完成情况**：已完成。\n- 结尾设定：${COPIED}。\n`,
      ],
    ];
    for (const [label, outlineText] of flagged) {
      const o = writeFile("completion.md", outlineText);
      const r = runDetector(["--outline", o, prose]);
      assert.equal(r.status, 1, `${label}: ${r.output}`);
      assert.ok(r.output.includes(`22 字「${COPIED}」`), `${label}: ${r.output}`);
    }
  });
});
