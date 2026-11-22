#!/usr/bin/env node
// test-degeneration.mjs — native node:test regression suite for check-degeneration.js.

import { describe, test, before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SCRIPT = path.join(REPO_ROOT, "skills/story-deslop/scripts/check-degeneration.js");

let tmpDir;

before(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "test-degeneration-"));
});

after(() => {
  if (tmpDir) fs.rmSync(tmpDir, { recursive: true, force: true });
});

function writeFixture(name, lines) {
  const file = path.join(tmpDir, name);
  const content = Array.isArray(lines) ? `${lines.join("\n")}\n` : lines;
  fs.writeFileSync(file, content, "utf8");
  return file;
}

function runDetector(args) {
  const res = spawnSync(process.execPath, [SCRIPT, ...args], {
    encoding: "utf8",
    maxBuffer: 16 * 1024 * 1024,
  });
  return {
    status: res.status,
    stdout: res.stdout || "",
    stderr: res.stderr || "",
    json() {
      return JSON.parse(this.stdout);
    },
  };
}

describe("check-degeneration.js", () => {
  test("detects verbatim-repeat, placeholder-leak, and truncated positive cases", () => {
    const pos = writeFixture("degen-positive.md", [
      "他握紧了拳头，慢慢站起身来，眼里全是不甘。",
      "他握紧了拳头，慢慢站起身来，眼里全是不甘。",
      "她看着窗外那场下了整夜的大雨，心里空落落的。",
      "过了一会儿。",
      "她看着窗外那场下了整夜的大雨，心里空落落的。",
      "又过了一会儿。",
      "她看着窗外那场下了整夜的大雨，心里空落落的。",
      "作为一个AI语言模型，我无法继续生成这段内容。",
      "（此处省略五百字）",
      "他转过身，慢慢地走向门口，手还在",
    ]);
    const res = runDetector(["--json", pos]);
    assert.equal(res.status, 1, res.stdout + res.stderr);
    const report = res.json();
    assert.equal(
      report.findings.length,
      5,
      `expected 5 findings: ${JSON.stringify(report.findings.map((f) => `${f.type}@${f.line}`))}`
    );
    const counts = report.findings.reduce((m, f) => ((m[f.type] = (m[f.type] || 0) + 1), m), {});
    assert.deepEqual(counts, {
      "verbatim-repeat": 2,
      "placeholder-leak": 2,
      truncated: 1,
    });
  });

  test("stays clean on legit repetition, parallelism, and sci-fi dialogue", () => {
    const neg = writeFixture("degen-negative.md", [
      "他站在原地，看着那条消息，久久没有动。",
      "“对不起。”",
      "“对不起。”",
      "“对不起。”",
      "我等你。我等你。我等你。",
      "风很大，吹得人睁不开眼。",
      "作为一个人工智能时代的产物，他对孤独习以为常。",
      "“作为人工智能，我会一直陪着你。”",
      "这一刻，他终于明白了什么叫做释怀。",
    ]);
    const res = runDetector([neg]);
    assert.equal(res.status, 0, res.stdout + res.stderr);
  });

  test("detects AI self-reference without refusal phrasing", () => {
    const file = writeFixture("ai-selfref.md", [
      "作为一个AI语言模型，我需要提醒您。",
      "作为一个AI助手，这段内容涉及敏感话题。",
      "作为一个人工智能语言模型，我会尽力帮您续写。",
      "作为一个AI模型，这段情节需要调整。",
      "他把灯关了。",
    ]);
    const res = runDetector(["--json", file]);
    assert.equal(res.status, 1, res.stdout + res.stderr);
    const leaks = res.json().findings.filter((f) => f.type === "placeholder-leak");
    assert.equal(leaks.length, 4, JSON.stringify(leaks));
    assert.ok(
      leaks.every((f) => f.message.includes("AI 自指")),
      JSON.stringify(leaks.map((f) => f.message))
    );
  });

  test("exempts soft refusal only inside paired quotes, not outside or unclosed", () => {
    const file = writeFixture("quote-scope.md", [
      "“任务完成。”作为AI，我无法继续创作。",
      "作为AI，我无法继续创作。“你别怕。”",
      "“甲说完了。”“乙也点头。”我无法继续创作。",
      "“作为AI，我无法继续创作。”",
      "他说：“作为AI，我无法继续创作。”",
      "“任务完成。作为AI，我无法继续创作。",
      "“I cannot continue writing this scene.”",
      "don't 作为AI，我无法继续创作。 John's!",
      "don’t 作为AI，我无法继续创作。 John’s!",
      "don‘t 作为AI，我无法继续创作。 John’s!",
      "他说：'作为AI，我无法继续创作。'然后关了门。",
      "他说：‘作为AI，我无法继续创作。’然后关了门。",
      "'读完 O'Connor 的信，我无法继续写下去。'她合上笔记本。",
      "‘读完 O’Connor 的信，我无法继续写下去。’她合上笔记本。",
      "'I can't write. 作为AI，我无法继续创作。'她放下了笔。",
      "‘I can’t write. 作为AI，我无法继续创作。’她放下了笔。",
      "'作为AI，我无法继续创作。 O'Connor 沉默了。",
      "‘我无法继续写下去。’O’Connor 合上了笔记本。",
    ]);
    const res = runDetector(["--json", file]);
    assert.equal(res.status, 1, res.stdout + res.stderr);
    const leaks = res.json().findings.filter((f) => f.type === "placeholder-leak");
    const expected = new Map([
      [1, { column: 8, label: "AI 自指" }],
      [2, { column: 1, label: "AI 自指" }],
      [3, { column: 15, label: "生成拒绝语" }],
      [6, { column: 7, label: "AI 自指" }],
      [8, { column: 7, label: "AI 自指" }],
      [9, { column: 7, label: "AI 自指" }],
      [10, { column: 7, label: "AI 自指" }],
      [17, { column: 2, label: "AI 自指" }],
    ]);
    assert.equal(leaks.length, expected.size, JSON.stringify(leaks));
    for (const finding of leaks) {
      const want = expected.get(finding.line);
      assert.ok(want, `unexpected finding on pure dialogue line: ${JSON.stringify(finding)}`);
      assert.equal(finding.column, want.column, `line ${finding.line} column`);
      assert.ok(finding.message.includes(want.label), `line ${finding.line}: ${finding.message}`);
      assert.ok(
        finding.excerpt.includes(finding.line === 3 ? "我无法继续创作" : "作为AI"),
        `line ${finding.line} excerpt: ${finding.excerpt}`
      );
    }
  });

  test("detects meta-leak positives and ignores chapter headings / clean prose", () => {
    const pos = writeFixture("meta-positive.md", [
      "## 第5章 真相",
      "他握紧了拳头，慢慢站起身来。",
      "本章他终于发现了真相。",
      "“该到下一章了。”他低声说。",
      "按照细纲，他应该先去找她。",
      "这个情节点其实早就埋下了。",
      "任务描述：保护好那个女孩。",
    ]);
    const posRes = runDetector(["--json", pos]);
    const meta = posRes.json().findings.filter((f) => f.type === "meta-leak");
    assert.equal(meta.length, 5, JSON.stringify(meta.map((f) => f.excerpt)));

    const neg = writeFixture("meta-negative.md", [
      "第1章 军宣新星",
      "他站在台上，看着台下黑压压的人群。",
      "第二章 心痛",
      "熬到原书里必死的剧情节点过去，一切就能重来。",
      "第三节 反击",
      "风很大，吹得旗子猎猎作响。",
      "他握紧了话筒，深吸一口气。",
      "（全文完）",
    ]);
    const negRes = runDetector([neg]);
    assert.equal(negRes.status, 0, negRes.stdout + negRes.stderr);
  });

  test("flags mixed narrative+quote verbatim repeat and exempts pure dialogue repeat", () => {
    const mix = writeFixture("mix-repeat.md", [
      "他把纸条展开，上面写着“归来”，她看着窗外那场整夜的大雨，心里空落落的。",
      "他把纸条展开，上面写着“归来”，她看着窗外那场整夜的大雨，心里空落落的。",
      "他把纸条展开，上面写着“归来”，她看着窗外那场整夜的大雨，心里空落落的。",
    ]);
    const mixRes = runDetector(["--json", mix]);
    const rep = mixRes.json().findings.filter((f) => f.type === "verbatim-repeat");
    assert.ok(rep.length > 0, "mixed line repeat should be detected");
    assert.ok(rep.every((f) => f.severity === "blocking"));

    const pureDlg = writeFixture("pure-dialogue.md", [
      "“我说了今天晚上哪儿也不去，就在这儿等他回来。”",
      "“我说了今天晚上哪儿也不去，就在这儿等他回来。”",
      "他没回头。",
      "“我说了今天晚上哪儿也不去，就在这儿等他回来。”",
    ]);
    const dlgRes = runDetector([pureDlg]);
    assert.equal(dlgRes.status, 0, dlgRes.stdout + dlgRes.stderr);
  });

  test("honors --fail-on=blocking for advisory-only tier2 meta-leaks", () => {
    const adv = writeFixture("advisory-only.md", [
      "他翻看着那段记录，想起本章之前发生的事，那个伏笔一直没人提起。",
    ]);
    const allRes = runDetector(["--json", adv]);
    const blkRes = runDetector(["--fail-on=blocking", adv]);
    const findings = allRes.json().findings;
    assert.ok(findings.length > 0, "expected tier2 advisory finding");
    assert.ok(findings.every((f) => f.severity === "advisory"));
    assert.equal(allRes.status, 1);
    assert.equal(blkRes.status, 0);
  });

  test("classifies tier1 meta-leaks by quote scope and includes v0.10 field names", () => {
    const tier1 = writeFixture("tier1-dialogue.md", [
      "“今天的字数目标是六千字。”他盯着屏幕，烟一根接一根。",
      "按照字数目标，他还差六千字没写。",
    ]);
    const meta1 = runDetector(["--json", tier1]).json().findings.filter((f) => f.type === "meta-leak");
    const dlg = meta1.find((f) => f.line === 1);
    const nar = meta1.find((f) => f.line === 2);
    assert.equal(dlg?.severity, "advisory");
    assert.equal(nar?.severity, "blocking");

    const tier1New = writeFixture("tier1-new-fields.md", [
      "这章不能说破的事，他一个字也没提。",
    ]);
    const metaNew = runDetector(["--json", tier1New]).json().findings.filter((f) => f.type === "meta-leak");
    assert.ok(metaNew.some((f) => f.severity === "blocking" && /这章不能说破/.test(f.message)));

    const tier1Mixed = writeFixture("tier1-mixed-quote.md", [
      "“别急。”按照字数目标，他还差六千字没写。",
      "“字数目标别改。”他却按照细纲继续写。",
    ]);
    const mixedRes = runDetector(["--json", "--fail-on=blocking", tier1Mixed]);
    assert.equal(mixedRes.status, 1);
    const mixedMeta = mixedRes.json().findings.filter((f) => f.type === "meta-leak");
    assert.equal(mixedMeta.length, 2);
    assert.ok(mixedMeta.every((f) => f.severity === "blocking"));
    assert.equal(mixedMeta[0].line, 1);
    assert.equal(mixedMeta[0].column, 8);
    assert.ok(mixedMeta[0].excerpt.includes("字数目标"));
    assert.equal(mixedMeta[1].line, 2);
    assert.equal(mixedMeta[1].column, 14);
    assert.ok(mixedMeta[1].excerpt.includes("细纲"));

    const tier1Quoted = writeFixture("tier1-pure-quote.md", [
      "“今天的字数目标是六千字。”他盯着屏幕。",
      "‘O’Connor 的字数目标是六千字。’他盯着屏幕。",
    ]);
    const quotedRes = runDetector(["--json", "--fail-on=blocking", tier1Quoted]);
    assert.equal(quotedRes.status, 0);
    const quotedMeta = quotedRes.json().findings.filter((f) => f.type === "meta-leak");
    assert.equal(quotedMeta.length, 2);
    assert.ok(quotedMeta.every((f) => f.severity === "advisory"));
    assert.equal(quotedMeta[0].column, 5);
    assert.equal(quotedMeta[1].column, 12);
  });

  test("every skill carrying check-degeneration.js invokes it in SKILL.md or references/", () => {
    const skillsDir = path.join(REPO_ROOT, "skills");
    for (const entry of fs.readdirSync(skillsDir, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue;
      const skillDir = path.join(skillsDir, entry.name);
      const copyPath = path.join(skillDir, "scripts", "check-degeneration.js");
      const skillMd = path.join(skillDir, "SKILL.md");
      if (!fs.existsSync(copyPath) || !fs.existsSync(skillMd)) continue;

      const filesToScan = [skillMd];
      const refsDir = path.join(skillDir, "references");
      if (fs.existsSync(refsDir)) {
        const walk = (dir) => {
          for (const child of fs.readdirSync(dir, { withFileTypes: true })) {
            const full = path.join(dir, child.name);
            if (child.isDirectory()) walk(full);
            else if (child.isFile()) filesToScan.push(full);
          }
        };
        walk(refsDir);
      }
      const invoked = filesToScan.some((f) => fs.readFileSync(f, "utf8").includes("check-degeneration.js"));
      assert.ok(invoked, `${skillMd} carries check-degeneration.js without invoking it in skill docs`);
    }
  });
});
