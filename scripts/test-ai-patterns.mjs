#!/usr/bin/env node
// test-ai-patterns.mjs — native node:test regression suite for check-ai-patterns.js.

import { describe, test, before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SCRIPT = path.join(REPO_ROOT, "skills/story-deslop/scripts/check-ai-patterns.js");

let tmpDir;

before(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "test-ai-patterns-"));
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
    maxBuffer: 32 * 1024 * 1024,
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

describe("check-ai-patterns.js", () => {
  test("not-is-comparison: detects genuine flips and ignores conjunctions, either-or, tags, frontmatter, fences", () => {
    const file = writeFixture("fixture.md", [
      "---",
      "title: 不是A，而是B",
      "---",
      "是不是这里不该报。",
      "他不是冷漠，而是绝望。",
      "她不是害怕，是累了。",
      "他不是笨是太急。",
      "他不是冷漠；是绝望。",
      "它不是普通的粥！",
      "是药。",
      "她不是不想走，也不是不敢走。",
      "他不是讨厌你，只是累了。",
      "他不是走了，可是没人发现。",
      "他不是不愿意，于是答应了。",
      "她不是生气，倒是有点担心。",
      "他不是哭就是闹。",
      "这事不是真的就是假的。",
      "这不是你的东西，是吗？",
      "他不是傻子。是吗？",
      "他不是傻子，是吧。",
      "不是这样，是嘛。",
      "他不是第一次来。",
      "",
      "是的，他还记得门口那盏灯。",
      "他不是没听见。是啊，他只是没回头。",
      "他不是不想答应，是呢，话到嘴边又咽回去。",
      "```",
      "他不是冷漠，而是绝望。",
      "```",
      "~~~md",
      "他不是普通表达，而是代码示例。",
      "~~~",
    ]);
    const res = runDetector(["--json", file]);
    assert.equal(res.status, 1, res.stdout + res.stderr);
    const excerpts = res.json().findings.map((f) => f.excerpt);
    const expected = [
      "不是冷漠，而是绝望",
      "不是害怕，是累了",
      "不是笨是太急",
      "不是冷漠；是绝望",
      "不是普通的粥！ 是药",
    ];
    assert.equal(excerpts.length, expected.length, JSON.stringify(excerpts));
    for (const item of expected) {
      assert.ok(excerpts.includes(item), `missing ${item} in ${JSON.stringify(excerpts)}`);
    }
  });

  test("prose patterns: period-stutter, em-dash, long-paragraph, mixed/pure quotes, headings, --fail-on", () => {
    const longPara =
      "他沿着长廊一直往里走，" +
      "走过一道又一道紧闭的木门，".repeat(16) +
      "终于在尽头停下，盯着那点暗红看了很久。";
    const f2 = writeFixture("fixture-prose.md", [
      "他站起来。",
      "他走过去。",
      "门开了。",
      "风进来。",
      "他停住。",
      "心一沉。",
      "她借着月光看清了桌上那张纸的边角——那是一张旧纸。",
      longPara,
    ]);
    const r2 = runDetector(["--json", f2]);
    assert.equal(r2.status, 1);
    const findings2 = r2.json().findings;
    assert.equal(findings2.length, 3, JSON.stringify(findings2));
    const counts = findings2.reduce((m, f) => ((m[f.type] = (m[f.type] || 0) + 1), m), {});
    assert.deepEqual(counts, { "period-stutter": 1, "em-dash": 1, "long-paragraph": 1 });
    assert.equal(findings2.find((f) => f.type === "period-stutter").line, 1);

    const f3 = writeFixture("fixture-mixed-quote.md", [
      "他站起。他看见“门”。风进来。他回头。灯灭了。心一沉。",
    ]);
    const st3 = runDetector(["--json", f3]).json().findings.filter((f) => f.type === "period-stutter");
    assert.equal(st3.length, 1);
    assert.equal(st3[0].severity, "advisory");

    const f4 = writeFixture("fixture-pure-dialogue.md", [
      "“走。”",
      "“快。”",
      "“跑。”",
      "“停。”",
      "“看。”",
      "“听。”",
    ]);
    assert.equal(runDetector([f4]).status, 0);

    const f5 = writeFixture("fixture-heading.md", `## ${"长".repeat(230)}\n`);
    assert.equal(runDetector([f5]).status, 0);

    const f6 = writeFixture(
      "fixture-advisory.md",
      `他沿着长廊一直往里走，${"走过一道又一道紧闭的木门，".repeat(16)}终于在尽头停下。\n`
    );
    const r6All = runDetector(["--json", f6]);
    const r6Blk = runDetector(["--fail-on=blocking", f6]);
    assert.equal(r6All.status, 1);
    assert.equal(r6Blk.status, 0);
    assert.ok(r6All.json().findings.length > 0);
    assert.ok(r6All.json().findings.every((f) => f.severity === "advisory"));

    const f7 = writeFixture("fixture-blocking.md", ["她停住——没说话。"]);
    const r7Json = runDetector(["--json", f7]);
    const r7Blk = runDetector(["--fail-on=blocking", f7]);
    const r7Rev = runDetector(["--fail-on=review_required", f7]);
    assert.equal(r7Json.json().findings.find((f) => f.type === "em-dash")?.severity, "review_required");
    assert.equal(r7Json.json().review_required, 1);
    assert.equal(r7Json.json().blocking, 0);
    assert.equal(r7Blk.status, 0);
    assert.equal(r7Rev.status, 1);

    const f7q = writeFixture("fixture-quoted-em-dash.md", [
      "“钥匙在——”他没说完。",
      '「等等——」『别动——』"快走——"',
      "【警告——权限不足】",
      "“话还没说完——",
    ]);
    const r7q = runDetector(["--json", "--fail-on=review_required", f7q]);
    assert.equal(r7q.status, 0);
    assert.equal(r7q.json().findings.filter((f) => f.type === "em-dash").length, 0);
  });

  test("issue #205: cross-blank-line not-is, >=3 escalation, dialogue exemption, unclosed quote", () => {
    const f8 = writeFixture("fixture-cross-para.md", [
      "中年男人消失了。",
      "",
      "不是被拖走。",
      "",
      "是整个人像被橡皮擦抹掉，全没了。",
    ]);
    const r8 = runDetector(["--json", f8]);
    const ni8 = r8.json().findings.filter((f) => f.type === "not-is-comparison");
    assert.equal(ni8.length, 1);
    assert.equal(ni8[0].line, 3);
    assert.equal(ni8[0].severity, "advisory");
    assert.equal(ni8[0].review, "semantic");
    assert.equal(runDetector(["--fail-on=blocking", f8]).status, 0);
    assert.equal(runDetector(["--fail-on=review_required", f8]).status, 0);

    const f8b = writeFixture("fixture-notis-blocking.md", [
      "不是退让，而是试探。",
      "这不是巧合，而是预谋。",
      "是硬功夫，不是花架子撑出来的。",
    ]);
    const r8b = runDetector(["--json", f8b]);
    const hits8b = r8b
      .json()
      .findings.filter((f) => f.type === "not-is-comparison" || f.type === "reverse-not-is");
    assert.equal(hits8b.length, 3);
    assert.ok(hits8b.every((f) => f.severity === "review_required" && f.review === "mechanical"));
    assert.equal(r8b.json().review_required, 3);
    assert.equal(runDetector(["--fail-on=blocking", f8b]).status, 0);
    assert.equal(runDetector(["--fail-on=review_required", f8b]).status, 1);

    const f9 = writeFixture("fixture-dialogue-notis.md", [
      "“你们看见了啊，不是我要闹，是物业非法限制人身自由。”",
    ]);
    assert.equal(runDetector([f9]).status, 0);

    const f10 = writeFixture("fixture-narration-notis.md", [
      "他冷笑一声。这不是巧合，是有人安排的。",
    ]);
    assert.equal(
      runDetector(["--json", f10]).json().findings.filter((f) => f.type === "not-is-comparison").length,
      1
    );

    const fUnclosed = writeFixture("fixture-unclosed-quote-notis.md", [
      "她终于开口：“我不想再提这件事。",
      "他没接话。",
      "他不是不明白，是懒得解释。",
      "她低头，“算了。”",
    ]);
    const niU = runDetector(["--json", fUnclosed])
      .json()
      .findings.filter((f) => f.type === "not-is-comparison");
    assert.equal(niU.length, 1);
    assert.equal(niU[0].line, 3);
  });

  test("micro-action-tic: dense positive, normal negative, short-tail positive", () => {
    const f11 = writeFixture("fixture-micro-tic.md", [
      "父亲的手停了一下。绳在铁环上松了半圈。",
      "他把绳拉紧，在秆子上勒了一道印。",
      "他拍了两下，手背上沾了叶子。",
      "母亲切了一阵，停了。锅铲刮了一下锅底。",
      "他把线头绕了一下，又攥了一下石头。",
    ]);
    const mt11 = runDetector(["--json", f11]).json().findings.filter((f) => f.type === "micro-action-tic");
    assert.equal(mt11.length, 1);
    assert.equal(mt11[0].severity, "advisory");
    assert.equal(runDetector(["--fail-on=blocking", f11]).status, 0);

    const f12 = writeFixture("fixture-micro-tic-normal.md", [
      "他回到家的时候，父亲正在院子里绑架子车上的绳子，车斗里堆着几捆刚掰下来的玉米秆。",
      "他说要去北京谈观测站的事，父亲的手停了一下，然后把绳子重新拉紧，没有接话。",
      "“你等我一下，我去把鸡圈门修完了一下午也就过去了。”父亲蹲在鸡圈边上，头也没抬。",
      "傍晚收拾行李的时候，他把断渠捡回来的那块石头看了一眼，装进了外套口袋里。",
      "母亲在厨房里切菜，刀落在案板上的声音比平时快了不少，他站在门口听了一会儿才进去。",
    ]);
    assert.equal(
      runDetector(["--json", f12]).json().findings.filter((f) => f.type === "micro-action-tic").length,
      0
    );

    const f13 = writeFixture("fixture-micro-tic-short-tail.md", [
      "他扯了下嘴角，没接那句话。母亲把碗推过去，他看了眼，又挪开。",
      "院门响了声，父亲停了下，手里的绳子绕了圈，重新压住秆子。",
      "她扫了眼桌上的信封，笑了声，指尖在信纸边缘顿了下。",
      "屋里静了会，锅盖颤了下，水汽贴着墙慢慢往上爬。",
    ]);
    const mt13 = runDetector(["--json", f13]).json().findings.filter((f) => f.type === "micro-action-tic");
    assert.equal(mt13.length, 1);
    assert.ok(mt13[0].excerpt.includes("了下") && mt13[0].excerpt.includes("了眼"));
  });

  test("stock-reaction-tic: positive, variants, normal negative", () => {
    const f = writeFixture("fixture-stock-reaction.md", [
      "指尖在窗台上轻轻叩了一下。",
      "她望向窗外别处，指尖却在袖口里攥紧了一下。",
      "徐管事的语气平静得像在念一份货单。",
      "他扶着栏杆的那只手，指节泛白。",
      "指尖在窗棂上轻轻叩了一下。",
    ]);
    const sr = runDetector(["--json", f]).json().findings.filter((x) => x.type === "stock-reaction-tic");
    assert.equal(sr.length, 1);
    assert.equal(sr[0].severity, "advisory");
    assert.ok(sr[0].excerpt.includes("指尖在窗台") && sr[0].excerpt.includes("语气平静得像在念"));
    assert.equal(runDetector(["--fail-on=blocking", f]).status, 0);

    const fv = writeFixture("fixture-stock-reaction-variants.md", [
      "胸口像被什么东西轻轻撞了一下。",
      "他喉结滚了滚，没接话。",
      "她的声音也放轻了。",
      "老人的眼圈一下就红了。",
    ]);
    const srv = runDetector(["--json", fv]).json().findings.filter((x) => x.type === "stock-reaction-tic");
    assert.equal(srv.length, 1);
    assert.ok(srv[0].excerpt.includes("胸口像被") && srv[0].excerpt.includes("声音也放轻"));

    const fn = writeFixture("fixture-stock-reaction-normal.md", [
      "他握扳手的手指发白，钢丝割开虎口，血顺着扳手滴进齿轮；机器仍旧卡着。",
      "她在引用栏抄下“指节泛白”，随后删掉，改回谈判破裂后的实际结果。",
      "门外的人催了第二遍，他把缺页的合同递回去，拒绝签字。",
    ]);
    assert.equal(
      runDetector(["--json", fn]).json().findings.filter((x) => x.type === "stock-reaction-tic").length,
      0
    );
  });

  test("abstract-summary-tic, action-list-tic, cliche-density-tic, metaphor-density-tic", () => {
    const pad16 = Array.from(
      { length: 16 },
      () => "院子里的灯还亮着，母亲把晒好的被子抱进屋里，他在门口帮着把竹竿收回来，又把水缸的盖子盖好。"
    );
    const f14 = writeFixture("fixture-abstract-summary.md", [
      "从这一刻开始，所有安排都被推到台前。",
      "命运像早已布好的棋局，把他推向那扇门。",
      "他生出前所未有的决意。",
      "属于他的反击，才刚刚开始。",
      ...pad16,
    ]);
    const ast = runDetector(["--json", f14]).json().findings.filter((x) => x.type === "abstract-summary-tic");
    assert.equal(ast.length, 1);
    assert.equal(ast[0].severity, "advisory");
    assert.ok(ast[0].excerpt.includes("从这一刻开始") && ast[0].excerpt.includes("才刚刚开始"));
    assert.equal(runDetector(["--fail-on=blocking", f14]).status, 0);

    const f15 = writeFixture("fixture-abstract-summary-normal.md", [
      "她把旧棋盘从柜子里搬出来，棋子少了两枚，只能用纽扣代替。",
      "父亲说：“从这一刻开始，你要自己记账。”她点点头，把账本翻到空白页。",
      "院外的雨停了，屋檐还在滴水，她先把潮掉的纸拿到窗边晾开。",
    ]);
    assert.equal(
      runDetector(["--json", f15]).json().findings.filter((x) => x.type === "abstract-summary-tic").length,
      0
    );

    const fAl = writeFixture("fixture-action-list.md", [
      "她伸手拿起桌上的杯子，取过旁边的药瓶，拧开瓶盖，倒出两片药，端起水杯，仰头咽下去，放下杯子，推开椅子，转身走到门口。",
    ]);
    const al = runDetector(["--json", fAl]).json().findings.filter((x) => x.type === "action-list-tic");
    assert.equal(al.length, 1);
    assert.equal(al[0].severity, "advisory");
    assert.ok(al[0].message.includes("监控摄像头式动作清单"));
    assert.equal(runDetector(["--fail-on=blocking", fAl]).status, 0);

    const fAlNorm = writeFixture("fixture-action-list-normal.md", [
      "她把药瓶攥在手里。门外又喊了一遍名字，椅子腿在地砖上拖出刺耳的一声。",
      "她站起来，又坐回去，半天才把水杯推远。",
    ]);
    assert.equal(
      runDetector(["--json", fAlNorm]).json().findings.filter((x) => x.type === "action-list-tic").length,
      0
    );

    const f16 = writeFixture("fixture-cliche-density.md", [
      "夜色静静笼罩着城市，远处霓虹隐约闪烁。",
      "林澈心中涌起一股说不清的情绪，仿佛某种预兆正在缓缓靠近。",
      "苏晚眼中闪过一丝复杂的神色，嘴角勾起一抹若有若无的笑意。",
      "她语气不容置疑，声音里透着不易察觉的冷意。",
      "林澈深吸一口气，淡淡开口，语气平静无波。",
      "苏晚指节泛白，目光锐利，沉默在两人之间蔓延。",
    ]);
    const cd = runDetector(["--json", f16]).json().findings.filter((x) => x.type === "cliche-density-tic");
    assert.equal(cd.length, 1);
    assert.equal(cd[0].severity, "advisory");
    assert.ok(cd[0].excerpt.includes("仿佛") && cd[0].excerpt.includes("眼中闪过"));
    assert.equal(runDetector(["--fail-on=blocking", f16]).status, 0);

    const f17 = writeFixture("fixture-cliche-density-normal.md", [
      "她在旧本子上抄了一句“仿佛某种预兆”，旁边画了个叉，提醒自己别这么写。",
      "窗外的雨把纸箱泡软了，林澈把最上面的文件抽出来，摊在暖气片旁边。",
      "苏晚说话声音不大，办公室太空，反而显得每个字都落得很清楚。",
    ]);
    assert.equal(
      runDetector(["--json", f17]).json().findings.filter((x) => x.type === "cliche-density-tic").length,
      0
    );

    const fMeta = writeFixture("fixture-metaphor-density.md", [
      "门口的雨还没停。路灯像泡在脏水里的眼珠，光晕晃得人心里发毛。",
      "保安室的玻璃好像蒙了一层油，谁的脸贴上去都发灰。",
      "人群挤在台阶下，仿佛一团被水浇透的纸。",
      "周砚的声音像是老旧电梯里的报站声，卡在喉咙口。",
      "公告牌上的红字如同钉子，一颗一颗往墙上扎。",
      "孩子的哭声像从楼缝里漏出来的风，细得让人背后发凉。",
      "胸牌亮起来，像一块透明的旧手机屏。",
    ]);
    const md = runDetector(["--json", fMeta]).json().findings.filter((x) => x.type === "metaphor-density-tic");
    assert.equal(md.length, 1);
    assert.equal(md[0].severity, "advisory");
    assert.ok(md[0].excerpt.includes("路灯像") && md[0].excerpt.includes("玻璃好像"));
    assert.equal(runDetector(["--fail-on=blocking", fMeta]).status, 0);

    const fMetaNorm = writeFixture("fixture-metaphor-density-normal.md", [
      "群头像换成了黑底白字，周砚盯着看了两秒。",
      "她在本子上写下“像水一样”四个字，又拿红笔划掉。",
      "雨声从棚顶漏下来，像有人在慢慢倒豆子。",
      "他把收据塞进口袋，转身去敲 3 单元的门。",
    ]);
    assert.equal(
      runDetector(["--json", fMetaNorm]).json().findings.filter((x) => x.type === "metaphor-density-tic")
        .length,
      0
    );
  });

  test("reasoning-chain-tic and system-notice-formality-tic", () => {
    const f18 = writeFixture("fixture-reasoning-chain.md", [
      "周砚站在门岗亭前，看着群消息一行行跳出来。他知道眼下最重要的任务是稳住人群，避免恐慌继续扩大。他也明白，如果业主继续围在北门，公共区域秩序会很快失控。这意味着每一句广播都必须谨慎，因为错误指令可能带来新的死亡。",
      "",
      "真正的问题在于，他没有完整规则，却必须在规则惩罚之前做出判断。在这种情况下，任何安慰都可能变成误导，任何沉默也可能被理解成默认。他需要先确认谁还在外面，再确认哪些楼栋还能进门。只有这样，他才有可能把混乱压回可控范围。",
      "",
      "周砚看着胸牌上的蓝光，心里不断分析当前局面。系统给出的任务是让所有存活业主回家，限制条件是零点之前，风险来源是红线之外和错误指令。按照这个逻辑，他应该先减少移动中的人，再建立单元门口的临时秩序，最后逐个核对门牌。",
      "",
      "他清楚自己只是实习物业，但现在系统把责任交给了他。也就是说，他必须承担一个原本不该由他承担的结果。他需要保持冷静，需要筛选信息，需要判断每个人的风险等级。想到这里，他终于意识到，今晚考验的是信息不足时的决策能力，也是他能不能承担公共秩序的开始。",
    ]);
    const rc = runDetector(["--json", f18]).json().findings.filter((x) => x.type === "reasoning-chain-tic");
    assert.equal(rc.length, 1);
    assert.equal(rc[0].severity, "advisory");
    assert.ok(rc[0].excerpt.includes("他知道") && rc[0].excerpt.includes("这意味着"));
    assert.equal(runDetector(["--fail-on=blocking", f18]).status, 0);

    const f19 = writeFixture("fixture-reasoning-chain-normal.md", [
      "周砚站在门岗亭前，群消息还在往上跳。",
      "",
      "“周砚你说话！”",
      "",
      "“北门到底怎么回事？”",
      "",
      "他把广播键按住，又松开。门口还有十几个人没走，抱猫粮的女人蹲在地上，手一直在抖；遛狗的大爷把狗绳缠在腕子上，眼睛盯着红线外那串钥匙。",
      "",
      "周砚翻开物业值班表，用指甲在纸上划了三下。北门，三号楼，儿童区。他先把还在外面的名字圈出来，又拿笔把能看见的楼栋写在旁边。",
      "",
      "他在本子边上写了一句“这意味着责任”，又立刻划掉，换成三号楼三个门牌号。",
      "",
      "“所有人离北门十米。”他说，“三号楼业主先回单元门口，不进电梯。家里有人没回来的，把门牌号发群里，不要刷屏。”",
    ]);
    assert.equal(
      runDetector(["--json", f19]).json().findings.filter((x) => x.type === "reasoning-chain-tic").length,
      0
    );

    const f20 = writeFixture("fixture-reasoning-chain-domain-words.md", [
      "门口的规则牌被风刮歪了，周砚伸手扶正。责任区三个字露在雨水里，下面贴着旧表格，风险提示已经掉了一角。",
      "",
      "保安把秩序线往前挪了半米，绳子蹭过地砖，留下两道泥印。周砚拿起笔，在登记本上补了一行责任人，又把规则牌下面的钉子按回去。",
      "",
      "三号楼的人还堵在门口。有人指着风险提示骂，有人拽着秩序线不放。周砚没解释，只把扩音器递给老保安，自己弯腰去捡掉在水里的门禁卡。",
      "",
      "雨越下越大，纸上的责任栏洇开了，规则两个字糊成一团。秩序线那头，小孩把伞举歪，鞋尖踩进水坑里。",
    ]);
    assert.equal(
      runDetector(["--json", f20]).json().findings.filter((x) => x.type === "reasoning-chain-tic").length,
      0
    );

    const f20b = writeFixture("fixture-reasoning-chain-negated.md", [
      "周砚不知道规则后面还有什么，也不明白责任到底怎么分。他还不清楚风险来自哪一条线，不需要判断结果，也不需要确认谁承担。",
      "",
      "门岗亭里的旧表格被雨水洇开，任务栏、条件栏、责任栏糊在一起。老保安问他要不要广播，他摇头，只把那张纸夹回文件夹里。",
      "",
      "他不知道三号楼的人为什么还不走，也不明白秩序线怎么突然松了半截。孩子的伞骨翻起来，鞋尖踩进水坑，门禁卡贴在地砖上。",
      "",
      "周砚不清楚这些规则是不是还算数，也不需要分析每个人的风险来源。他把扩音器放回桌上，先去把北门的雨棚往外拽了一点。",
    ]);
    assert.equal(
      runDetector(["--json", f20b]).json().findings.filter((x) => x.type === "reasoning-chain-tic").length,
      0
    );

    const f21 = writeFixture("fixture-notice-formality.md", [
      "【夜间不得离开本区域。】",
      "",
      "【零点前，所有人员必须返回登记住所。】",
      "",
      "【管理人员必须维持公共区域秩序。公共区域失控，管理人员承担优先惩罚。】",
      "",
      "【本公告不可撤回，不可转发，不可截图。】",
      "",
      "【当前区域：一号楼。】",
      "",
      "【当前安全等级：0。】",
      "",
      "【当前公共区域秩序：混乱。】",
      "",
      "【第一夜任务：务必在零点前，使所有人员返回登记住所。】",
      "",
      "【任务失败：管理人员优先承担惩罚。】",
      "",
      "【提示：管理人员发言将被视为公共秩序指令。错误指令造成的死亡，同样计入管理人员责任。】",
    ]);
    const nf = runDetector(["--json", f21])
      .json()
      .findings.filter((x) => x.type === "system-notice-formality-tic");
    assert.equal(nf.length, 1);
    assert.equal(nf[0].severity, "advisory");
    assert.ok(nf[0].excerpt.includes("不得") && nf[0].excerpt.includes("必须"));
    assert.equal(runDetector(["--fail-on=blocking", f21]).status, 0);

    const f22 = writeFixture("fixture-notice-natural.md", [
      "【夜间不能离开本区域。】",
      "",
      "【零点之前，所有人员都要返回登记住所。】",
      "",
      "【管理人员要维护好公共区域的秩序。公共区域出现混乱的时候，管理人员要先受到处罚。】",
      "",
      "【本公告不能撤回，不能转发，不能截图。】",
      "",
      "【现在的区域是一号楼。】",
      "",
      "【目前的安全等级为0。】",
      "",
      "【目前公共区域的秩序很乱。】",
      "",
      "【夜间任务是在零点之前让所有人员返回登记住所。】",
      "",
      "【任务失败后，管理人员先承担惩罚。】",
      "",
      "【提示：管理人员发出的指令就是公共秩序指令。造成死亡的错误指令也要算在管理人员的责任之内。】",
    ]);
    assert.equal(
      runDetector(["--json", f22]).json().findings.filter((x) => x.type === "system-notice-formality-tic")
        .length,
      0
    );
  });

  test("overcompressed-prose-tic and density-rule quote exemptions", () => {
    const rep = (n, s) => Array.from({ length: n }, () => s).join("\n\n") + "\n";

    const f23 = writeFixture(
      "fixture-overcompressed-prose.md",
      rep(60, "周砚抬头。") + rep(40, "灰雾贴住红线外侧，北门灯光晃成一团冷斑，脚步声压回门岗亭前。")
    );
    const oc = runDetector(["--json", f23]).json().findings.filter((x) => x.type === "overcompressed-prose-tic");
    assert.equal(oc.length, 1);
    assert.equal(oc[0].severity, "advisory");
    assert.equal(runDetector(["--fail-on=blocking", f23]).status, 0);

    const f24 = writeFixture(
      "fixture-overcompressed-prose-natural.md",
      rep(40, "周砚抬头。") +
        rep(40, "灰雾还贴在红线外面，北门的灯光已经晃成了一团冷斑，脚步声也被压回了门岗亭前。")
    );
    assert.equal(
      runDetector(["--json", f24]).json().findings.filter((x) => x.type === "overcompressed-prose-tic").length,
      0
    );

    const f25 = writeFixture(
      "fixture-overcompressed-prose-fast-natural.md",
      rep(60, "他就停了一秒。") + rep(40, "雨还在门口落着，灯光也被水汽糊住了，大家都往后退了一点。")
    );
    assert.equal(
      runDetector(["--json", f25]).json().findings.filter((x) => x.type === "overcompressed-prose-tic").length,
      0
    );

    const f26 = writeFixture(
      "fixture-overcompressed-prose-repaired-beats.md",
      rep(50, "周砚抬头时，北门外那条马路已经看不见了。更怪的是声音也跟着没了，业主群里刷屏的问号停了三秒。")
    );
    assert.equal(
      runDetector(["--json", f26]).json().findings.filter((x) => x.type === "overcompressed-prose-tic").length,
      0
    );

    const say = (lines) => lines.map((line) => `他说：“${line}”`);
    const repeat = (n, line) => Array.from({ length: n }, () => line);
    const quoteCases = [
      [
        "micro-action-tic",
        say([
          "父亲的手停了一下。绳在铁环上松了半圈。",
          "他把绳拉紧，在秆子上勒了一道印。",
          "他拍了两下，手背上沾了叶子。",
          "母亲切了一阵，停了。锅铲刮了一下锅底。",
          "他把线头绕了一下，又攥了一下石头。",
        ]),
      ],
      [
        "stock-reaction-tic",
        say([
          "指尖在窗台上轻轻叩了一下。",
          "她望向窗外别处，指尖却在袖口里攥紧了一下。",
          "徐管事的语气平静得像在念一份货单。",
          "他扶着栏杆的那只手，指节泛白。",
          "指尖在窗棂上轻轻叩了一下。",
        ]),
      ],
      [
        "abstract-summary-tic",
        say([
          "从这一刻开始，所有安排都被推到台前。",
          "命运像早已布好的棋局，把他推向那扇门。",
          "他生出前所未有的决意。",
          "属于他的反击，才刚刚开始。",
        ]),
      ],
      [
        "action-list-tic",
        say([
          "她伸手拿起桌上的杯子，取过旁边的药瓶，拧开瓶盖，倒出两片药，端起水杯，仰头咽下去，放下杯子，推开椅子，转身走到门口。",
        ]),
      ],
      [
        "cliche-density-tic",
        say([
          "夜色静静笼罩着城市，远处霓虹隐约闪烁。",
          "林澈心中涌起一股说不清的情绪，仿佛某种预兆正在缓缓靠近。",
          "苏晚眼中闪过一丝复杂的神色，嘴角勾起一抹若有若无的笑意。",
          "她语气不容置疑，声音里透着不易察觉的冷意。",
          "林澈深吸一口气，淡淡开口，语气平静无波。",
          "苏晚指节泛白，目光锐利，沉默在两人之间蔓延。",
        ]),
      ],
      [
        "metaphor-density-tic",
        say([
          "门口的雨还没停。路灯像泡在脏水里的眼珠，光晕晃得人心里发毛。",
          "保安室的玻璃好像蒙了一层油，谁的脸贴上去都发灰。",
          "人群挤在台阶下，仿佛一团被水浇透的纸。",
          "周砚的声音像是老旧电梯里的报站声，卡在喉咙口。",
          "公告牌上的红字如同钉子，一颗一颗往墙上扎。",
          "孩子的哭声像从楼缝里漏出来的风，细得让人背后发凉。",
          "胸牌亮起来，像一块透明的旧手机屏。",
        ]),
      ],
      [
        "reasoning-chain-tic",
        say([
          "他知道眼下最重要的任务是稳住人群，避免恐慌继续扩大。他也明白，如果业主继续围在北门，公共区域秩序会很快失控。这意味着每一句广播都必须谨慎，因为错误指令可能带来新的死亡。",
          "真正的问题在于，他没有完整规则，却必须在规则惩罚之前做出判断。在这种情况下，任何安慰都可能变成误导，任何沉默也可能被理解成默认。他需要先确认谁还在外面，再确认哪些楼栋还能进门。只有这样，他才有可能把混乱压回可控范围。",
          "他清楚自己只是实习物业，但现在系统把责任交给了他。也就是说，他必须承担一个原本不该由他承担的结果。他需要保持冷静，需要筛选信息，需要判断每个人的风险等级。想到这里，他终于意识到，今晚考验的是信息不足时的决策能力。",
        ]),
      ],
      [
        "overcompressed-prose-tic",
        say([
          ...repeat(60, "周砚抬头。"),
          ...repeat(40, "灰雾贴住红线外侧，北门灯光晃成一团冷斑，脚步声压回门岗亭前。"),
        ]),
      ],
      ["ellipsis-density-tic", say(repeat(8, "他站在门口……风吹了进来……灯灭了。"))],
    ];
    for (const [type, lines] of quoteCases) {
      const f = writeFixture(`fixture-quoted-${type}.md`, `${lines.join("\n\n")}\n`);
      const hits = runDetector(["--json", f]).json().findings.filter((x) => x.type === type);
      assert.equal(hits.length, 0, `${type} should ignore quoted prose: ${JSON.stringify(hits)}`);
    }
  });

  test("low-connective-density-tic: positive, quoted streams, all quote pairs, long sentences", () => {
    const f27 = writeFixture(
      "fixture-low-connective-density.md",
      Array.from({ length: 50 }, () => "周砚抬头。红点跳高。北门灯冷。手机黑屏。脚步停住。").join("\n\n") + "\n"
    );
    const lc = runDetector(["--json", f27]).json().findings.filter((x) => x.type === "low-connective-density-tic");
    assert.equal(lc.length, 1);
    assert.equal(lc[0].severity, "advisory");
    assert.ok(lc[0].message.includes("别机械注水"));
    assert.equal(runDetector(["--fail-on=blocking", f27]).status, 0);

    const f27b = writeFixture(
      "fixture-low-connective-quoted-stream.md",
      Array.from({ length: 80 }, () => "“红点跳高。北门灯冷。手机黑屏。脚步停住。”").join("\n\n") +
        "\n\n周砚把群消息往上翻。门岗亭里只剩下空调声，他没有马上开口。\n"
    );
    assert.equal(
      runDetector(["--json", f27b]).json().findings.filter((x) => x.type === "low-connective-density-tic").length,
      0
    );

    const allPairs =
      '「红点[跳高]*。北门灯冷+。手机黑屏?。」『红点[跳高]*。北门灯冷+。手机黑屏?。』【红点[跳高]*。北门灯冷+。手机黑屏?。】“红点[跳高]*。北门灯冷+。手机黑屏?。”‘红点[跳高]*。北门灯冷+。手机黑屏?。’"红点[跳高]*。北门灯冷+。手机黑屏?。"\'红点[跳高]*。北门灯冷+。手机黑屏?。\'';
    const f27c = writeFixture(
      "fixture-low-connective-all-quote-pairs.md",
      Array.from({ length: 35 }, () => allPairs).join("\n\n") +
        "\n\n周砚把群消息往上翻。门岗亭里只剩下空调声，他没有马上开口。\n"
    );
    assert.equal(
      runDetector(["--json", f27c]).json().findings.filter((x) => x.type === "low-connective-density-tic").length,
      0
    );

    const f28 = writeFixture(
      "fixture-low-connective-long-sentences.md",
      Array.from(
        { length: 30 },
        () => "周砚把红点截图发回群里，北门冷灯贴着灰雾晃成一片，脚步声压在门岗亭前不动。"
      ).join("\n\n") + "\n"
    );
    assert.equal(
      runDetector(["--json", f28]).json().findings.filter((x) => x.type === "low-connective-density-tic").length,
      0
    );
  });

  test("field-caught patterns A-E: voice-contrast, negation-parade, formulaic-parallelism, reverse-not-is, trailer-ending, quote-emphasis-tic, trailer-summary", () => {
    const fVoice = writeFixture("fixture-voice-contrast.md", [
      "声音不高，第一句却稳稳压住了整个大厅。",
      "“他声音不大，却带着火气。”旁边的人小声嘀咕。",
      "她的声音不大，台下前排听得清楚。",
    ]);
    const vc1 = runDetector(["--json", fVoice]).json().findings.filter((x) => x.type === "voice-contrast");
    assert.equal(vc1.length, 1);
    assert.equal(vc1[0].line, 1);
    assert.equal(vc1[0].severity, "advisory");
    assert.equal(vc1[0].review, "semantic");
    assert.ok(!vc1[0].excerpt.includes("火气"));
    assert.equal(runDetector(["--fail-on=review_required", fVoice]).status, 0);

    fs.appendFileSync(fVoice, "他声音不大，却让整条走廊安静下来。\n", "utf8");
    const vc2 = runDetector(["--json", fVoice]).json().findings.filter((x) => x.type === "voice-contrast");
    assert.equal(vc2.length, 2);
    assert.ok(vc2.every((f) => f.severity === "review_required" && f.review === "mechanical"));
    assert.equal(runDetector(["--fail-on=blocking", fVoice]).status, 0);
    assert.equal(runDetector(["--fail-on=review_required", fVoice]).status, 1);

    const fParade = writeFixture("fixture-negation-parade.md", [
      "没有伴奏，没有和声，没有提词器。",
      "他没炫技，没有那种一张嘴就飙高音的架势。他只是唱，把每个字放平。",
      "“没有饭，没有水，我们怎么过夜？”有人喊。",
      "他没有回头。巷子里没有灯，他摸着墙走。",
      "船沉没在雾里，没人回头，江面上就只有几块浮木。",
      "他的话被淹没在掌声里，没多久，台上就只有他一个人。",
      "雨下了没多久，没等她撑伞，巷子里就只有水声。",
      "他没等她开口，没等她反应，只是转身走了。",
    ]);
    const np = runDetector(["--json", fParade]).json().findings.filter((x) => x.type === "negation-parade");
    assert.deepEqual(np.map((f) => f.line), [1, 2, 8]);
    assert.ok(np.every((f) => f.severity === "review_required"));

    const fCh21 = writeFixture("fixture-ch21-ai-flavor-gap.md", [
      "至于拍不拍，怎么拍，等他把话说完再决定。",
      "不带摄像机，不带采访灯。",
      "“不带摄像机，不带采访灯。”",
      "不是嚎啕大哭。",
      "",
      "也不是扯着嗓子喊不舍。",
      "",
      "只是一个人走远了，留在原地的人还站着。",
      "不是生就是死。",
      "至于拍摄方案怎么定，等人到了再说。",
      "“不放辣，不放葱。”",
      "他不带伞。她不带包。",
      "不是她不想回家。",
      "也不是母亲不肯原谅她。",
      "只是末班车已经开走了。",
    ]);
    const rCh21 = runDetector(["--json", fCh21]).json();
    assert.equal(rCh21.findings.filter((x) => x.type === "negation-parade").length, 0);
    const fp = rCh21.findings.filter((x) => x.type === "formulaic-parallelism");
    assert.deepEqual(fp.map((f) => f.line), [1, 2, 3, 4, 13]);
    assert.ok(fp.every((f) => f.severity === "advisory"));
    assert.equal(rCh21.findings.filter((f) => f.line >= 9 && f.line <= 12).length, 0);
    assert.equal(runDetector(["--fail-on=blocking", fCh21]).status, 0);

    const fRev = writeFixture("fixture-reverse-not-is.md", [
      "气息拉满不断，是真嗓子，不是修音修出来的。",
      "“是我先来的，不是他。”她把票拍在窗口上。",
      "反正就是这样，不是谁都能改的。",
      "他也是这两年才学会的，不是天生就懂。",
      "是啊，不是谁都有这个耐心。",
      "他问是不是弄错了，不是他报的名。",
      "他是走了，不是吗？",
    ]);
    const rn = runDetector(["--json", fRev]).json().findings.filter((x) => x.type === "reverse-not-is");
    assert.equal(rn.length, 1);
    assert.equal(rn[0].line, 1);
    assert.equal(rn[0].severity, "advisory");
    assert.equal(rn[0].review, "semantic");
    assert.ok(rn[0].excerpt.includes("是真嗓子"));

    const fTrailer = writeFixture("fixture-trailer-ending.md", [
      "他把口琴收进兜里。没人知道他练了多久。",
      ...Array.from(
        { length: 16 },
        () => "院子里的灯还亮着，母亲把晒好的被子抱进屋里，他在门口帮着把竹竿收回来，又把水缸的盖子盖好。"
      ),
      "“没人知道下一场在哪儿。”老赵嘟囔着收拾谱架。",
      "钟声再度响起，比赛正式拉开序幕。",
      "没人知道，这才刚刚开头。",
      "一场从县城炸向省台的接力，正朝着他，缓缓压了过去。",
    ]);
    const te = runDetector(["--json", fTrailer]).json().findings.filter((x) => x.type === "trailer-ending");
    assert.equal(te.length, 3);
    assert.ok(te.every((f) => f.severity === "review_required"));
    assert.ok(!te.some((f) => f.line === 1));
    assert.ok(!te.some((f) => f.excerpt.includes("下一场") || f.excerpt.includes("拉开序幕")));
    const teExcerpts = te.map((f) => f.excerpt).join(" | ");
    for (const marker of ["没人知道", "这才刚刚开头", "压了过去"]) {
      assert.ok(teExcerpts.includes(marker), teExcerpts);
    }
    assert.equal(runDetector(["--fail-on=blocking", fTrailer]).status, 0);
    assert.equal(runDetector(["--fail-on=review_required", fTrailer]).status, 1);

    const fUnaware = writeFixture("fixture-trailer-unaware.md", [
      "她不知道该说什么，只好低头收拾行李。",
      "她不知道的是，这一去，她的命运就此改变了。",
    ]);
    const teU = runDetector(["--json", fUnaware]).json().findings.filter((x) => x.type === "trailer-ending");
    assert.equal(teU.length, 1);
    assert.equal(teU[0].line, 2);
    assert.equal(teU[0].excerpt, "她不知道的是");
    assert.equal(teU[0].severity, "advisory");

    const fQe = writeFixture("fixture-quote-emphasis.md", [
      "他是被请来“把关”的，来之前心里还揣着句现成的话。",
      "这段“掉马神演”，正被一帧一帧拍下、剪好、甩上网。",
      "没人出声，几千人像被那朵“花”钉在了座位上。",
      "她说“好”，转身就走。",
      "他笑道“行”，也没多留。",
      "只听“唰”的一声，帘子拉上了。",
      "杯盖“啪”地一下弹开。",
      '"..."',
      "“——”",
      "“嗯。”",
      "“叮咚~”“叮咚~”“叮咚~”",
      "他念了一遍“静”，又写下“定”。",
    ]);
    const qe = runDetector(["--json", fQe]).json().findings.filter((x) => x.type === "quote-emphasis-tic");
    assert.equal(qe.length, 1);
    assert.equal(qe[0].severity, "advisory");
    assert.ok(qe[0].message.includes("3 处"));
    assert.ok(qe[0].excerpt.includes("把关"));
    assert.equal(runDetector(["--fail-on=blocking", fQe]).status, 0);

    const fQeNorm = writeFixture("fixture-quote-emphasis-normal.md", [
      "凌晨十二点十分，番城旅游官网出现苏阳的照片，手里的海报变成了“我在番城”。",
      "他是被请来“把关”的，来之前心里还揣着句现成的话。",
    ]);
    assert.equal(
      runDetector(["--json", fQeNorm]).json().findings.filter((x) => x.type === "quote-emphasis-tic").length,
      0
    );

    const fTs = writeFixture("fixture-trailer-summary.md", [
      "她把账单摊在桌上，指腹压出一道白痕，纸边被汗浸软了一角。",
      "他端起杯子又放下，杯底磕在桌面上响了一声。",
      "这一切都结束了。这一夜注定无眠。",
    ]);
    const ts = runDetector(["--json", fTs]).json().findings.filter((x) => x.type === "trailer-summary");
    assert.equal(ts.length, 2);
    assert.ok(ts.every((f) => f.severity === "review_required"));
    assert.equal(runDetector(["--fail-on=blocking", fTs]).status, 0);
    assert.equal(runDetector(["--fail-on=review_required", fTs]).status, 1);

    const fTsNorm = writeFixture("fixture-trailer-summary-normal.md", [
      "就这样，一年的时间过去了，账本从抽屉挪进了保险柜。",
      "就这样，主仆二人都自责了一番，才结束了这个话题。",
      "就这样，四点多钟，季政委宣布这次相亲联谊会圆满落幕。",
      "等这一切结束了，我们就能过上平静幸福的生活了。",
      "尽管兽绝神木似乎将这一切都说明得非常清楚，但结果与所想并不一样。",
      "就在他认为这一切都结束了的时候，门又被推开了。",
      "世间的这一刻，所有人都接受了命中注定的结局！",
      "加上装备的碾压，这一战的结果是注定的。",
      "他捏着那张纸，不知道这一切意味着什么。",
      "她盯着屏幕，不明白这一切都说明了什么。",
      "那一刻我终于明白，母亲当年为什么总在夜里哭。",
      "我猛地抬头，死死盯着手机，终于明白，为何女儿这半年总躲着我。",
      "我抓起外套就往门口走，反手带上了那扇门。",
    ]);
    assert.equal(
      runDetector(["--json", fTsNorm]).json().findings.filter((x) => x.type === "trailer-summary").length,
      0
    );
  });

  test("HTML comments skipped cleanly; unclosed comment does not hide blocking patterns", () => {
    const fHtml = writeFixture("fixture-html-comment.md", [
      "# 第3章 夜路",
      "<!-- 去味:跳过 -->",
      "<!-- 去味：跳过 -->",
      "他推门出去，雨还在下。",
      "她把伞递给他。<!-- 作者注：这里--以后再改 -->他没接。",
      "<!--",
      "多行注释里的破折号——不算，声音不大，却不算。",
      "-->",
      "他回头看了一眼——门已经关了。",
    ]);
    const rHtml = runDetector(["--json", "--fail-on=review_required", fHtml]);
    assert.equal(rHtml.status, 1);
    const findings = rHtml.json().findings;
    assert.equal(
      findings.filter((f) => [2, 3, 6, 7, 8].includes(f.line) || (f.line === 5 && f.type === "em-dash")).length,
      0
    );
    const dashes = findings.filter((f) => f.type === "em-dash");
    assert.equal(dashes.length, 1);
    assert.equal(dashes[0].line, 9);
    assert.equal(dashes[0].column, 8);
    assert.equal(dashes[0].severity, "review_required");

    const fMarker = writeFixture("fixture-marker-only.md", [
      "# 第3章 夜路",
      "<!-- 去味:跳过 -->",
      "",
      "他推门出去，雨还在下。",
      "她把伞递给他，他没接。",
    ]);
    assert.equal(runDetector(["--json", "--fail-on=review_required", fMarker]).status, 0);

    const fUnclosed = writeFixture("fixture-unclosed-comment.md", [
      "# 第1章",
      "<!-- 作者备注",
      "这不是夸奖，而是命令。",
      "声音不大，却带着狠劲。",
      "她声音不高，却把话钉死了。",
      "他把门带上。",
    ]);
    const rU = runDetector(["--json", "--fail-on=review_required", fUnclosed]);
    assert.equal(rU.status, 1);
    const types = rU.json().findings.map((f) => `${f.line}:${f.type}`);
    for (const want of ["3:not-is-comparison", "4:voice-contrast", "5:voice-contrast"]) {
      assert.ok(types.includes(want), `missing ${want} in ${JSON.stringify(types)}`);
    }
    assert.equal(rU.json().findings.filter((f) => f.line === 2).length, 0);
  });

  test("review classification contract: --list-review-classes matches source and runtime findings", () => {
    const listRes = runDetector(["--list-review-classes"]);
    assert.equal(listRes.status, 0);
    const table = listRes.json();
    const source = fs.readFileSync(SCRIPT, "utf8");
    const emitted = new Set([...source.matchAll(/\btype: '([a-z-]+)'/g)].map((m) => m[1]));
    assert.ok(emitted.size >= 20, `too few emitted types: ${[...emitted]}`);
    const classified = new Set(Object.keys(table));
    assert.deepEqual([...emitted].filter((t) => !classified.has(t)), []);
    assert.deepEqual([...classified].filter((t) => !emitted.has(t)), []);
    for (const [type, cls] of Object.entries(table)) {
      assert.ok(cls === "semantic" || cls === "mechanical", `${type}: ${cls}`);
    }
    for (const t of [
      "stock-reaction-tic",
      "formulaic-parallelism",
      "reasoning-chain-tic",
      "abstract-summary-tic",
      "ellipsis-density-tic",
    ]) {
      assert.equal(table[t], "semantic");
    }
    for (const t of ["em-dash", "cliche-density-tic", "not-is-comparison"]) {
      assert.equal(table[t], "mechanical");
    }

    const fRev = writeFixture("fixture-review.md", [
      "他不是冷漠，而是绝望。",
      "这不是巧合，而是预谋。",
      "声音不高，第一句却稳稳压住了整个大厅。",
      "没有伴奏，没有和声，没有提词器。",
      "是真嗓子，不是修音修出来的。",
      "他回头看了一眼——门已经关了。",
      "她指尖微微一颤。",
      "他指节泛白，攥紧了拳头。",
      "她眼眶发红。",
      "他喉结滚了滚。",
      "她抿了下唇。",
      "一。二。三。四。五。六。七。",
      "没人知道，这才刚刚开头。",
    ]);
    const findings = runDetector(["--json", fRev]).json().findings;
    assert.ok(findings.length >= 6);
    const types = new Set(findings.map((f) => f.type));
    for (const need of ["not-is-comparison", "em-dash", "stock-reaction-tic", "trailer-ending"]) {
      assert.ok(types.has(need), `missing ${need}`);
    }
    for (const f of findings) {
      for (const key of ["file", "line", "column", "type", "severity", "message", "excerpt"]) {
        assert.ok(key in f, `missing ${key}`);
      }
      assert.ok(f.review === "semantic" || f.review === "mechanical");
      if (f.severity === "blocking" || f.severity === "review_required") assert.equal(f.review, "mechanical");
    }
  });

  test("negation-pair-tic, issue #540 slow-prop & calculation, corpus edges", () => {
    const fNeg = writeFixture("fixture-negation-pair.md", [
      "他没说让她住，也没说不让，自己进里间去了。",
      "她没碰那排蒜，也没叫他。",
      "外公没抬头，她也没吭声。",
      '"你不去，我也不去。"她笑着说。',
    ]);
    const np = runDetector(["--json", fNeg]).json().findings.filter((x) => x.type === "negation-pair-tic");
    assert.equal(np.length, 1);
    assert.equal(np[0].severity, "advisory");
    assert.equal(np[0].review, "semantic");

    writeFixture("fixture-negation-pair.md", [
      "他没说话，转身出门去了。",
      '"你不去，我也不去。"她说。',
      '"没钱，也没票。"他说。',
    ]);
    assert.equal(
      runDetector(["--json", fNeg]).json().findings.filter((x) => x.type === "negation-pair-tic").length,
      0
    );

    const fSlow = writeFixture("fixture-slow-stock-reaction.md", [
      "她手指慢慢拢住桌上的药包，一句话也没接。",
      "沈砚指腹摩挲着粗瓷杯沿，听管事把账念完。",
      "她视线落在借据末尾的红印上停了半秒，还是没伸手。",
      "掌柜手往袖口里一缩，笑脸倒没变。",
    ]);
    const sr = runDetector(["--json", fSlow]).json().findings.filter((x) => x.type === "stock-reaction-tic");
    assert.equal(sr.length, 1);
    assert.equal(sr[0].severity, "advisory");
    assert.equal(sr[0].review, "semantic");
    assert.ok(sr[0].message.includes("直白情绪") || sr[0].message.includes("利害判断"));

    const fCalc = writeFixture("fixture-character-calculation.md", [
      "林澈知道二叔开出的条件看着体面，其实把铺子亏空的风险全推到了东院头上。他也明白这会儿当众掀桌讨不到好结果，老太太最烦小辈拿家里的规矩说事，闹大了反而正中二房下怀。",
      "",
      "他心里清楚，眼下这局面谁先接管账房谁就背锅，与其争那个虚名，不如先把南城货栈的钥匙留在手里。只要银钱出入还在自己眼皮底下，二叔就算拿了大印也翻不出浪来，这笔责任犯不着替别人扛。",
    ]);
    assert.equal(
      runDetector(["--json", fCalc]).json().findings.filter((x) => x.type === "reasoning-chain-tic").length,
      0
    );

    const fEdge = writeFixture("fixture-reasoning-corpus-edges.md", [
      "她失明以后可以通过别人呼吸的轻重判断来人是谁，也知道谁在敷衍自己。想到这里，她清楚今晚不能回家，只有这样才能避开前夫那边的耳目。",
      "",
      "识海里的同化规则一圈圈散开，他明白这道规则能吞掉血肉与金铁，也知道接下试炼任务的条件有多苛刻。在这种情况下，他先试着熟悉新规则的边界，把剩余的规则碎片一点点收进掌心。",
    ]);
    assert.equal(
      runDetector(["--json", fEdge]).json().findings.filter((x) => x.type === "reasoning-chain-tic").length,
      0
    );
  });

  test("ellipsis-density-tic, unclosed-quote dash parity, >64KB pipe flush, and short-story length scaling", () => {
    const fEll = writeFixture("fixture-ellipsis-density.md", [
      "雨一直下……门外的脚步声越来越近……他握着门把没动。",
      "走廊里的灯闪了一下……又暗下去……连呼吸声都听不见了。",
      "风从窗缝灌进来……桌上的纸翻了一页……落在地砖上。",
      "“你……你别过来……”她低声喊，【警告……信号中断……】",
    ]);
    const rEll = runDetector(["--json", "--fail-on=blocking", fEll]);
    assert.equal(rEll.status, 0);
    const ed = rEll.json().findings.filter((x) => x.type === "ellipsis-density-tic");
    assert.equal(ed.length, 1);
    assert.equal(ed[0].severity, "advisory");
    assert.equal(ed[0].review, "semantic");
    assert.ok(ed[0].message.includes("6 处"));

    const fEllSparse = writeFixture("fixture-ellipsis-sparse.md", [
      "他站在院门口，看着远处的山影发了很久的呆……直到母亲喊他进屋吃饭才转身。",
      "“我……我今天先把账结了……”父亲放下碗，没再多说一句话。",
    ]);
    assert.equal(
      runDetector(["--json", fEllSparse]).json().findings.filter((x) => x.type === "ellipsis-density-tic").length,
      0
    );

    const fLarge = writeFixture(
      "fixture-large-pipe.md",
      Array.from({ length: 650 }, (_, i) => `第${i}段：他回头看了一眼——门已经关了。`).join("\n\n") + "\n"
    );
    const rLarge = runDetector(["--json", "--fail-on=review_required", fLarge]);
    assert.equal(rLarge.status, 1);
    assert.ok(rLarge.json().findings.length >= 650, `large pipe JSON truncated: ${rLarge.json().findings.length}`);
    assert.ok(rLarge.json().review_required >= 650);

    const fUnclosedDash = writeFixture("fixture-unclosed-dash.md", [
      "他猛地抬头：“你敢——",
      '"等等——',
      "他——猛地抬头：“你敢——",
    ]);
    const dashes = runDetector(["--json", fUnclosedDash]).json().findings.filter((x) => x.type === "em-dash");
    assert.equal(dashes.length, 1);
    assert.equal(dashes[0].line, 3);
    assert.equal(dashes[0].column, 2);

    const pad = Array.from(
      { length: 230 },
      (_, i) => `###${i + 1}.\n雨夜里的便利店还亮着灯，收银台后的风扇转个不停，我低头核对着账本上的数字。`
    ).join("\n\n");
    const threeHits = [
      "他不是来接我的，而是来拿那份转让协议的。",
      "那不是愧疚，而是怕事情闹大收不了场。",
      "我不是心软，而是要等银行流水彻底到账。",
    ].join("\n\n");
    const sixHits = [
      threeHits,
      "她不是不知情，而是从头到尾都在帮他瞒着。",
      "这不是意外，而是提前三个月就布好的局。",
      "他们不是来道歉的，而是来探我手里还有多少底牌的。",
    ].join("\n\n");
    const fShortSparse = writeFixture("fixture-short-sparse.md", `${pad}\n\n${threeHits}\n`);
    const fShortDense = writeFixture("fixture-short-dense.md", `${pad}\n\n${sixHits}\n`);

    const rSparse = runDetector(["--json", "--fail-on=review_required", fShortSparse]);
    assert.equal(rSparse.status, 0);
    const sparseHits = rSparse.json().findings.filter((x) => x.type === "not-is-comparison");
    assert.equal(sparseHits.length, 3);
    assert.ok(sparseHits.every((f) => f.severity === "advisory"));

    const rDense = runDetector(["--json", "--fail-on=review_required", fShortDense]);
    assert.equal(rDense.status, 1);
    assert.equal(runDetector(["--json", "--fail-on=blocking", fShortDense]).status, 0);
  });
});
