#!/usr/bin/env node
// check-doc-budget.mjs — 热路径文档预算守卫（防 skill / agent 模板无声膨胀）
//
// 度量：去掉所有空白后的字符数。中英文都算，改标点/换行/缩进不影响读数。
// 路径（paths）按「一个角色的一次调用」登记：
//   files      无条件读取；写成 `文件#小节标题` 只计该小节（到下一个同级或更高级标题为止，代码围栏里的 # 不算）。
//   generated  由脚本拼出的任务包：以 `--project <临时目录> <args>` 运行脚本，读它输出 JSON 的 brief 文件，去掉仓库根路径后计字。
//   branches   条件读取，默认互斥：每条分支 = 基础 + 本分支文件，各自对照自己的 budget。
//   stacking   会在同一次调用里叠加的分支：slots 里每个槽至多取一条分支，枚举全部组合取最坏的一组对照 stacking.budget。
//   path_ceiling.limit 是每次调用的硬上限（v0.8.2 起 35000）；豁免只列在 path_ceiling.exempt 并写明原因。

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
let repoRoot = path.resolve(SCRIPT_DIR, "..");
let manifestPath = path.join(SCRIPT_DIR, "doc-budget.json");

const argv = process.argv.slice(2);
for (let i = 0; i < argv.length; i++) {
  const arg = argv[i];
  if (arg === "--root") {
    if (i + 1 >= argv.length) {
      console.log("FAIL: --root 缺少路径");
      process.exit(2);
    }
    repoRoot = path.resolve(argv[++i]);
  } else if (arg === "--manifest") {
    if (i + 1 >= argv.length) {
      console.log("FAIL: --manifest 缺少路径");
      process.exit(2);
    }
    manifestPath = path.resolve(argv[++i]);
  } else if (arg === "-h" || arg === "--help") {
    console.log("Usage: node scripts/check-doc-budget.mjs [--root DIR] [--manifest FILE]");
    process.exit(0);
  } else {
    console.log(`FAIL: 未知参数：${arg}`);
    process.exit(2);
  }
}

if (!fs.existsSync(manifestPath) || !fs.statSync(manifestPath).isFile()) {
  console.log(`FAIL: 预算清单缺失：${manifestPath}`);
  process.exit(1);
}

const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));

const fail = [];
const note = [];
const strip = (text) => text.replace(/\s/g, "").length;

// 取「文件#小节」：从标题行到下一个同级或更高级标题（跳过代码围栏里的行）。
const sectionOf = (text, anchor) => {
  const lines = text.split("\n");
  let fence = false;
  let start = -1;
  let level = 0;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^\s*(```|~~~)/.test(line)) {
      fence = !fence;
      continue;
    }
    if (fence) continue;
    const m = line.match(/^(#{1,6})\s+(.*)$/);
    if (!m) continue;
    if (start >= 0 && m[1].length <= level) return lines.slice(start, i).join("\n");
    if (start < 0 && m[2].trim().startsWith(anchor)) {
      start = i;
      level = m[1].length;
    }
  }
  return start >= 0 ? lines.slice(start).join("\n") : null;
};

// 读数：null = 文件不存在；undefined = 小节找不到（两种都报错，不静默当 0）。
const cache = new Map();
const weigh = (entry) => {
  if (cache.has(entry)) return cache.get(entry);
  const hash = entry.indexOf("#");
  const rel = hash >= 0 ? entry.slice(0, hash) : entry;
  const abs = path.join(repoRoot, rel);
  let value = null;
  if (fs.existsSync(abs)) {
    const text = fs.readFileSync(abs, "utf8");
    if (hash < 0) value = strip(text);
    else {
      const body = sectionOf(text, entry.slice(hash + 1));
      value = body === null ? undefined : strip(body);
    }
  }
  cache.set(entry, value);
  return value;
};

let python = null;
const findPython = () => {
  if (python) return python;
  for (const [cmd, pre] of [
    ["python3", []],
    ["python", []],
    ["py", ["-3"]],
  ]) {
    const probe = spawnSync(cmd, [...pre, "--version"], { encoding: "utf8", windowsHide: true });
    if (probe.status === 0) {
      python = [cmd, pre];
      return python;
    }
  }
  return null;
};

// 由脚本拼出的任务包：跑一次拿 chars；拼包失败或输出不认得都报错。
const generatedWeight = (gen) => {
  const key = `gen:${gen.script} ${(gen.args || []).join(" ")}`;
  if (cache.has(key)) return cache.get(key);
  let value;
  const isNode = gen.script.endsWith(".js") || gen.script.endsWith(".mjs");
  const py = isNode ? null : findPython();
  const script = path.join(repoRoot, gen.script);
  if (!isNode && !py) value = { error: "找不到 Python 3（依次试 python3、python、py -3）" };
  else if (!fs.existsSync(script)) value = { error: `拼包脚本不存在：${gen.script}` };
  else {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "doc-budget-"));
    const [cmd, pre] = isNode ? [process.execPath, []] : py;
    const run = spawnSync(cmd, [...pre, script, "--project", tmp, ...(gen.args || [])], {
      encoding: "utf8",
      windowsHide: true,
    });
    const last = (run.stdout || "").trim().split("\n").pop() || "";
    let chars = null;
    try {
      const out = JSON.parse(last);
      chars = out.chars;
      // 包里写的是参考文件绝对路径，长度随机器上的仓库位置变；按去掉仓库根后的文本计量，各机器结果一致。
      if (Number.isInteger(chars) && out.brief && fs.existsSync(out.brief)) {
        chars = strip(fs.readFileSync(out.brief, "utf8").split(repoRoot + path.sep).join(""));
      }
    } catch {
      chars = null;
    }
    fs.rmSync(tmp, { recursive: true, force: true });
    value =
      run.status === 0 && Number.isInteger(chars)
        ? chars
        : {
            error: `拼包脚本 ${gen.script} ${(gen.args || []).join(" ")} 没给出 chars（退出码 ${run.status}）：${(run.stderr || last).trim().slice(0, 200)}`,
          };
  }
  cache.set(key, value);
  return value;
};

console.log("热路径文档预算");
console.log("".padEnd(78, "-"));
console.log("  用量 /   预算  余量  文件");

for (const entry of manifest.files) {
  const used = weigh(entry.path);
  if (used === null || used === undefined) {
    fail.push(`预算登记的文件不存在：${entry.path}（改名/删除后请同步 doc-budget.json）`);
    continue;
  }
  const left = entry.budget - used;
  const mark = left < 0 ? "OVER" : "ok";
  console.log(
    `  ${String(used).padStart(6)} / ${String(entry.budget).padStart(6)} ${String(left).padStart(6)}  ${entry.path}  [${mark}]`
  );
  if (left < 0) {
    fail.push(`${entry.path} 超预算 ${-left} 字（${used} > ${entry.budget}）：${entry.why}`);
  } else if (left >= Math.ceil(entry.budget * 0.05)) {
    note.push(
      `${entry.path} 比预算低 ${left} 字，可把 budget 降到 ${Math.ceil(used / 100) * 100} 锁住这次精简`
    );
  }
}

console.log("");
console.log("已登记路径合计（不含项目资料与未登记条件项）");
console.log("".padEnd(78, "-"));

const ceiling = manifest.path_ceiling || null;
if (ceiling && !(Number.isFinite(ceiling.limit) && ceiling.limit > 0)) {
  fail.push(
    `path_ceiling.limit 缺失或不是正数（现为 ${JSON.stringify(ceiling.limit)}）——拼错会让硬上限静默失效`
  );
}
const ceilingOn = ceiling && Number.isFinite(ceiling.limit) && ceiling.limit > 0;
const exemptGroups = new Set((ceiling && ceiling.exempt) || []);

// 一次调用读到的东西：同一文件只算一次；整份已读时它的小节不再另算。
const total = (entries, generated, label) => {
  const set = [...new Set(entries)];
  const whole = new Set(set.filter((e) => !e.includes("#")));
  let sum = 0;
  let broken = false;
  for (const entry of set) {
    const hash = entry.indexOf("#");
    if (hash >= 0 && whole.has(entry.slice(0, hash))) continue;
    const used = weigh(entry);
    if (used === null) {
      fail.push(`路径「${label}」登记的文件不存在：${entry.split("#")[0]}`);
      broken = true;
      continue;
    }
    if (used === undefined) {
      fail.push(`路径「${label}」登记的小节找不到：${entry}`);
      broken = true;
      continue;
    }
    sum += used;
  }
  for (const gen of generated) {
    const used = generatedWeight(gen);
    if (typeof used !== "number") {
      fail.push(`路径「${label}」：${used.error}`);
      broken = true;
      continue;
    }
    sum += used;
  }
  return broken ? null : sum;
};

const checkPath = (label, budget, entries, generated, group) => {
  const sum = total(entries, generated, label);
  if (sum === null) return;
  const left = budget - sum;
  const exempt = ceilingOn && exemptGroups.has(group);
  console.log(
    `  ${String(sum).padStart(6)} / ${String(budget).padStart(6)} ${String(left).padStart(6)}  ${label}  [${left < 0 ? "OVER" : "ok"}${exempt ? "，上限豁免" : ""}]`
  );
  if (left < 0) {
    fail.push(`路径「${label}」超预算 ${-left} 字（${sum} > ${budget}）`);
  }
  if (ceilingOn && !exempt && (sum > ceiling.limit || budget > ceiling.limit)) {
    fail.push(
      `路径「${label}」超过硬上限 ${ceiling.limit} 字（实际 ${sum}，预算 ${budget}）：${ceiling.why}`
    );
  }
};

const AGENT_DIR = "skills/story-setup/references/templates/agents";
const preloads = (rel) => {
  const abs = path.join(repoRoot, rel);
  if (!fs.existsSync(abs)) return null;
  const head = fs.readFileSync(abs, "utf8").split(/^---\s*$/m)[1] || "";
  const inline = head.match(/^skills:[ \t]*\[([^\]]*)\]/m);
  if (inline) return inline[1].split(",").map((s) => s.trim()).filter(Boolean);
  const block = head.match(/^skills:[ \t]*\r?\n((?:[ \t]+-[^\n]*\n?)+)/m);
  if (block) return block[1].split("\n").map((s) => s.replace(/^[ \t]+-[ \t]*/, "").trim()).filter(Boolean);
  if (/^skills:/m.test(head)) {
    fail.push(`${rel} 的 skills 预加载写法认不出，改成 skills: [a, b] 或逐行 - a`);
  }
  return [];
};

const MAX_COMBOS = 4096;
const agentPaths = new Set();
for (const group of manifest.paths || []) {
  let files = group.files || [];
  const generated = group.generated || [];
  if (group.agent) {
    agentPaths.add(group.agent);
    const skills = preloads(group.agent);
    if (skills === null) {
      fail.push(`路径「${group.label}」登记的 agent 不存在：${group.agent}`);
      continue;
    }
    files = [group.agent, ...files, ...skills.map((name) => `skills/${name}/SKILL.md`)];
  }
  if (group.branches) {
    for (const branch of group.branches) {
      checkPath(
        `${group.label}（${branch.label}）`,
        branch.budget,
        [...files, ...branch.files],
        generated,
        group.label
      );
    }
  } else {
    checkPath(group.label, group.budget, files, generated, group.label);
  }
  if (!group.stacking) continue;

  const byLabel = new Map((group.branches || []).map((b) => [b.label, b]));
  const slots = group.stacking.slots || [];
  const seen = new Set();
  let bad = false;
  for (const slot of slots) {
    for (const name of slot) {
      if (!byLabel.has(name)) {
        fail.push(`路径「${group.label}」stacking 列了不存在的分支：${name}`);
        bad = true;
      }
      if (seen.has(name)) {
        fail.push(
          `路径「${group.label}」stacking 里分支「${name}」出现在两个槽里（一个槽内互斥，同一分支只能属于一个槽）`
        );
        bad = true;
      }
      seen.add(name);
    }
  }
  if (!Number.isFinite(group.stacking.budget)) {
    fail.push(`路径「${group.label}」stacking 缺 budget`);
    bad = true;
  }
  const combos = slots.reduce((n, slot) => n * (slot.length + 1), 1);
  if (combos > MAX_COMBOS) {
    fail.push(`路径「${group.label}」stacking 组合数 ${combos} 超过 ${MAX_COMBOS}，拆小槽位`);
    bad = true;
  }
  if (bad || slots.length === 0) continue;

  let worst = null;
  const walk = (i, chosen) => {
    if (i === slots.length) {
      const sum = total(
        [...files, ...chosen.flatMap((name) => byLabel.get(name).files)],
        generated,
        group.label
      );
      if (
        sum !== null &&
        (worst === null ||
          sum > worst.sum ||
          (sum === worst.sum && chosen.length > worst.chosen.length))
      ) {
        worst = { sum, chosen: [...chosen] };
      }
      return;
    }
    walk(i + 1, chosen);
    for (const name of slots[i]) walk(i + 1, [...chosen, name]);
  };
  walk(0, []);
  if (worst === null) continue;

  const label = `${group.label}（最坏叠加：${worst.chosen.join("＋") || "无"}）`;
  const left = group.stacking.budget - worst.sum;
  const exempt = ceilingOn && exemptGroups.has(group.label);
  console.log(
    `  ${String(worst.sum).padStart(6)} / ${String(group.stacking.budget).padStart(6)} ${String(left).padStart(6)}  ${label}  [${left < 0 ? "OVER" : "ok"}${exempt ? "，上限豁免" : ""}]`
  );
  if (left < 0) {
    fail.push(`路径「${label}」超预算 ${-left} 字（${worst.sum} > ${group.stacking.budget}）`);
  }
  if (ceilingOn && !exempt && (worst.sum > ceiling.limit || group.stacking.budget > ceiling.limit)) {
    fail.push(
      `路径「${label}」超过硬上限 ${ceiling.limit} 字（实际 ${worst.sum}，预算 ${group.stacking.budget}）：${ceiling.why}`
    );
  }
}

const agentDir = path.join(repoRoot, AGENT_DIR);
if (ceiling) {
  const labels = new Set((manifest.paths || []).map((g) => g.label));
  for (const name of exemptGroups) {
    if (!labels.has(name)) fail.push(`path_ceiling.exempt 列了不存在的路径：${name}`);
  }
}
if (fs.existsSync(agentDir)) {
  for (const name of fs.readdirSync(agentDir).filter((n) => n.endsWith(".md")).sort()) {
    const rel = `${AGENT_DIR}/${name}`;
    const skills = preloads(rel) || [];
    if (skills.length && !agentPaths.has(rel)) {
      fail.push(
        `${rel} 预加载了 ${skills.join("、")}，但没有登记 agent 路径——预加载内容进该 agent 每次调用，须计入预算`
      );
    }
  }
}

if (note.length) {
  console.log("");
  console.log("提示（不阻断）：");
  for (const n of note) console.log(`  - ${n}`);
}

if (fail.length) {
  console.log("");
  console.log("FAIL: 热路径文档超预算");
  for (const f of fail) console.log(`  - ${f}`);
  console.log("");
  console.log("处理顺序：① 先找同一文件里能删的旧文本（重复指令、已被脚本确定性拦住的规则、");
  console.log("设计理由旁白、只在极少数场景才用得上的分支），删等量再提交；");
  console.log("② 路径超了先看是不是本不该同时发生的读取挤在一次调用里：少见时刻的规则搬进按时刻读的 reference，");
  console.log("或调整流程让它们不再同时发生；会叠加的条件读取登记进 stacking，别当成互斥分支；");
  console.log("③ 确实是必须加的新规则，就在 scripts/doc-budget.json 调高 budget，并在 PR 里写清为什么这段值得每个用户每次会话都付。");
  if (ceilingOn) {
    console.log(`每次调用的硬上限是 ${ceiling.limit} 字（path_ceiling.limit），预算不能调过它；`);
    console.log("确需超限的路径只能列进 path_ceiling.exempt，并在 why 里写明原因。");
  }
  process.exit(1);
}

console.log("");
console.log("Result: 热路径文档预算检查通过");
