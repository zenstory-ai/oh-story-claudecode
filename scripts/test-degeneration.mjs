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

  test("flags 主角/男主/女主/反派 as tier2 advisory (never tier1 blocking) and exempts 穿书/原书 context + 女主播/三天前文创部", () => {
    // 非穿书语境下，主角/男主/女主/反派仍为 tier2 advisory（绝不 blocking）
    const plain = writeFixture("plain-tier2.md", [
      "他冷笑一声，打算先把主角除掉。",
      "推开门后，她决定离男主远一点。",
      "冷脸女主此刻正站在走廊尽头。",
      "这一世，她绝不替反派背锅。",
    ]);
    const allRes = runDetector(["--json", plain]);
    const blkRes = runDetector(["--json", "--fail-on=blocking", plain]);
    assert.equal(allRes.status, 1);
    assert.equal(blkRes.status, 0, "主角/男主/女主/反派 must NEVER block");
    const meta = allRes.json().findings.filter((f) => f.type === "meta-leak");
    assert.equal(meta.length, 4, JSON.stringify(meta));
    assert.ok(meta.every((f) => f.severity === "advisory"));

    // 穿书/快穿/原书/弹幕语境下豁免 男主/女主/读者/第X章，避免高分女频误报
    const chuanshu = writeFixture("chuanshu-tier2.md", [
      "穿书进来第一天，她决定离男主远一点。",
      "原书女主此刻正站在走廊尽头，连读者都猜不出后续。",
      "按原剧情第三章的走向，今晚就会退婚。",
    ]);
    const csMeta = runDetector(["--json", chuanshu]).json().findings.filter((f) => f.type === "meta-leak");
    assert.equal(csMeta.length, 0, `穿书语境应豁免男主/女主/读者/第X章: ${JSON.stringify(csMeta)}`);

    // 女主播/男主播/三天前文创部 等复合词与跨词边界绝不误报
    const boundaries = writeFixture("meta-word-boundaries.md", [
      "女主播把话筒推远，男主播、女主持和男主唱紧跟着上台，男主厨在后台端菜。",
      "三天前文创部绕过风控，把此前文件和目前文物清单一起递了上去。",
    ]);
    const bMeta = runDetector(["--json", boundaries]).json().findings.filter((f) => f.type === "meta-leak");
    assert.equal(bMeta.length, 0, `女主播/三天前文创部不应误报: ${JSON.stringify(bMeta)}`);

    // 正文残留 [待补充] 与零宽字符 \u200b 必须阻断
    const zwspAndTodo = writeFixture("zwsp-and-todo.md", [
      "这里写着 [待补充]，忘了替换正文。",
      "他把细\u200b纲忘在了桌面上。",
    ]);
    const zRes = runDetector(["--json", "--fail-on=blocking", zwspAndTodo]);
    assert.equal(zRes.status, 1);
    const zTypes = zRes.json().findings.map((f) => f.type);
    assert.ok(zTypes.includes("placeholder-leak"), JSON.stringify(zTypes));
    assert.ok(zTypes.includes("meta-leak"), JSON.stringify(zTypes));

    // 【】弹幕/心声/系统播报里的「主角/男主/女主/反派」跳过 tier2，叙述层非豁免词照常提示
    const danmu = writeFixture("danmu-tier2.md", [
      "【快跑啊！原书女主和反派马上就要联手坑男主了！】",
      "她端起茶盏，心想下一章还得继续演，没出声。",
    ]);
    const danmuRes = runDetector(["--json", danmu]);
    const danmuMeta = danmuRes.json().findings.filter((f) => f.type === "meta-leak");
    assert.equal(danmuMeta.length, 1, JSON.stringify(danmuMeta));
    assert.equal(danmuMeta[0].line, 2);
    assert.equal(danmuMeta[0].severity, "advisory");
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

  test("detects markdown-leak (blocking), near-repeat (advisory), and ASCII period endings", () => {
    const mdLeak = writeFixture("markdown-leak.md", [
      "## **第1章** 标题允许粗体",
      "***",
      "正文里突然冒出**第一变。**这种粗体残留。",
      "他推门走进雨夜。",
    ]);
    const mdRes = runDetector(["--json", "--fail-on=blocking", mdLeak]);
    assert.equal(mdRes.status, 1);
    const leaks = mdRes.json().findings.filter((f) => f.type === "markdown-leak");
    assert.equal(leaks.length, 1, JSON.stringify(leaks));
    assert.equal(leaks[0].line, 3);
    assert.equal(leaks[0].severity, "blocking");

    const nearRep = writeFixture("near-repeat.md", [
      "三婶抹着眼泪一把拉住罗成衣袖，非要借他那八万块钱救救急。",
      "院子里的老黄狗叫了两声，屋檐滴着冷水。",
      "罗成没松口，低头翻起了手机里的转账记录。",
      "三婶抹着眼泪一把拉住罗成衣袖，非要借他那八万块钱救救急。",
    ]);
    const nrAll = runDetector(["--json", nearRep]);
    const nrBlk = runDetector(["--json", "--fail-on=blocking", nearRep]);
    assert.equal(nrAll.status, 1);
    assert.equal(nrBlk.status, 0, "near-repeat must be advisory only");
    const nr = nrAll.json().findings.filter((f) => f.type === "near-repeat");
    assert.equal(nr.length, 1, JSON.stringify(nr));
    assert.equal(nr[0].line, 4);

    const asciiDot = writeFixture("ascii-dot.md", [
      '他盯着屏幕沉默半晌，只回了一句".....".',
    ]);
    assert.equal(runDetector([asciiDot]).status, 0, "ASCII period ending should align with story_hook_core");
  });

  test("Wave 5 Track 5C-Core: truncated closing braces, meta-leak FP cut, placeholder bracket names, censored-pinyin-leak, author-meta-header", () => {
    // 1) P0 R227: WeChat brace }, system panel 】, signoff （完）, book title 》 must NOT trigger truncated
    for (const [name, tail] of [
      ["wechat-brace", "池元：{无论多晚，我都等您。}"],
      ["panel-bracket", "【任务完成】"],
      ["signoff-paren", "他转身离去。\n（完）"],
      ["book-guillemet", "桌上摊着一本《山海录》"],
    ]) {
      const f = writeFixture(`trunc-ok-${name}.md`, [tail]);
      const res = runDetector(["--json", f]);
      assert.equal(
        res.json().findings.filter((x) => x.type === "truncated").length,
        0,
        `${name} must not trigger truncated: ${res.stdout}`
      );
    }

    // 2) P1 Wave 4A + R180: meta-leak skips bare chapter headings, quoted & everyday 主角/反派, and 系统/穿书 context
    const metaClean = writeFixture("meta-wave5-clean.md", [
      "",
      "第89章 难道这是。。夫妻相？",
      "“……热搜稿，记得换个主角重写。”经纪人敲了敲桌面。",
      "“你可是今晚的主角。”司仪笑着递上话筒。",
      "她是全场众星捧月的主角，也是今天的主角，妥妥的古装大女主。",
      "她学着短剧反派女二的表情翻了个白眼，往后文远侯府才不会被牵连。",
    ]);
    assert.equal(
      runDetector(["--json", metaClean]).json().findings.filter((x) => x.type === "meta-leak").length,
      0,
      "bare chapter heading + quoted/everyday 主角/反派 must be exempt"
    );

    const sysCtx = writeFixture("meta-sys-ctx.md", [
      "系统叮了一声，弹出救赎任务。",
      "他扫了一眼站在阶下的主角和反派，转身回了偏殿。",
    ]);
    assert.equal(
      runDetector(["--json", sysCtx]).json().findings.filter((x) => x.type === "meta-leak").length,
      0,
      "系统/救赎任务 context must exempt 主角 and 反派"
    );

    // 3) P2 Wave 4A: placeholder-leak must not false-positive on normal parenthesized names or 略微/略显
    const phClean = writeFixture("placeholder-bracket-clean.md", [
      "照片上的两人（程煜时）夫妻相十足。",
      "她（略显尴尬）地收回手，又（略微点头）示意对方坐下。",
    ]);
    assert.equal(
      runDetector(["--json", phClean]).json().findings.filter((x) => x.type === "placeholder-leak").length,
      0
    );
    const phHit = writeFixture("placeholder-bracket-hit.md", [
      "两人打得难解难分（此处省略五百字）最终落幕。",
      "后面细节（略）不再赘述。",
    ]);
    assert.equal(
      runDetector(["--json", "--fail-on=blocking", phHit]).json().findings.filter((x) => x.type === "placeholder-leak").length,
      2
    );

    // 4) P1 Wave 3D FN-2: censored-pinyin-leak (review_required) catches censorship pinyin, 0 FP on normal English/units
    const pinyinPos = writeFixture("pinyin-pos.md", [
      "他咬牙把身ti打磨到极限。",
      "醉意上头，他低头亲wen了她额角。",
      "刀背重重砸在对方大tui上，胸kou一阵发闷。",
      "黑影冷笑，竟想直接杀si证人。",
    ]);
    const pBlk = runDetector(["--json", "--fail-on=blocking", pinyinPos]);
    const pRev = runDetector(["--json", "--fail-on=review_required", pinyinPos]);
    assert.equal(pBlk.status, 0, "censored-pinyin-leak is review_required, not blocking");
    assert.equal(pRev.status, 1, "censored-pinyin-leak must fail --fail-on=review_required");
    const pHits = pRev.json().findings.filter((x) => x.type === "censored-pinyin-leak");
    assert.equal(pHits.length, 4, JSON.stringify(pHits));
    assert.ok(pHits.every((x) => x.severity === "review_required"));

    const pinyinClean = writeFixture("pinyin-clean-english.md", [
      "VIP包厢里，CEO拿着PDF和A4纸核对AI与DNA检测报告。",
      "他在APP上连着5G刷iPhone，顺手用NPC账号PK掉Lv5的BOSS，HP和MP刚回满，OK！",
      "刀口长3cm，伤口距胸口两寸，他打boss从不看攻略。",
    ]);
    assert.equal(
      runDetector(["--json", pinyinClean]).json().findings.filter((x) => x.type === "censored-pinyin-leak").length,
      0,
      "normal English/abbreviations/units must have 0 censored-pinyin-leak FP"
    );

    // 5) P1 Wave 3D FN-1: author-meta-header (review_required, first 500 chars only)
    const headerPos = writeFixture("author-header-pos.md", [
      "帅哥美女们，这里是大脑寄存处。",
      "作者说：本书又名《逆袭》，介意者慎入，求五星好评求催更！",
      "夜雨砸在青石板上，他推开了客栈木门。",
    ]);
    const hBlk = runDetector(["--json", "--fail-on=blocking", headerPos]);
    const hRev = runDetector(["--json", "--fail-on=review_required", headerPos]);
    assert.equal(hBlk.status, 0, "author-meta-header is review_required, not blocking");
    assert.equal(hRev.status, 1, "author-meta-header must fail --fail-on=review_required");
    assert.equal(hRev.json().findings.filter((x) => x.type === "author-meta-header").length, 2);

    // 6) Full-width ］ and half-width ] closing brackets (WeChat/danmu box endings) must not flag truncated
    for (const [idx, line] of [
      "手机屏幕亮起一条微信：［今晚九点老地方见］",
      "系统提示：[主线任务已触发]",
    ].entries()) {
      const f = writeFixture(`bracket-end-${idx}.md`, ["他低头看向屏幕。", line]);
      const brRes = runDetector(["--json", f]);
      assert.equal(
        brRes.json().findings.filter((x) => x.type === "truncated").length,
        0,
        `closing bracket should not trigger truncated: ${line}`
      );
    }

    const latePad = "雨夜里的青砖小巷安静得只能听见屋檐滴水声，他紧了紧衣领穿过石桥往城南粮栈走去。".repeat(16);
    const headerLate = writeFixture("author-header-late.md", [
      latePad,
      "他在路边茶摊听见说书人随口喊了一句求五星好评。",
    ]);
    assert.equal(
      runDetector(["--json", headerLate]).json().findings.filter((x) => x.type === "author-meta-header").length,
      0,
      "author-meta-header must only scan first 500 visible chars"
    );

    // Space-separated --fail-on and --help documenting review_required
    const helpRes = runDetector(["--help"]);
    assert.equal(helpRes.status, 0);
    assert.match(helpRes.stdout, /--fail-on=blocking\|review_required\|all/);
    const pinyinOnly = writeFixture("space-fail-on-pinyin.md", [
      "## 第1章 夜路",
      "",
      "他咬牙把身ti打磨到极限，推门走入雨夜。",
    ]);
    assert.equal(runDetector(["--fail-on", "blocking", pinyinOnly]).status, 0);
    assert.equal(runDetector(["--fail-on", "review_required", pinyinOnly]).status, 1);
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
