#!/usr/bin/env node
"use strict";
/**
 * Register inspiration atoms from EM mechanism cards, then validate/query the index.
 *
 * 三层灵感库的机械层。原子灵感（IA）不再生成独立文件：每个 IA 是
 * `灵感索引.csv` 里的一行登记，机制全文只在 `拆文库/{书}/剧情/情绪模块.md`
 * 的 EM 卡一处维护，需要时按 ID 回查。NM/CBA 卡内禁止路径引用，
 * 来源只记 `书名/EM-xxx` 式裸 ID；路径解析统一走索引。
 */

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const COLUMNS = [
  "item_id",
  "layer",
  "title",
  "source_book",
  "path",
  "source_ids",
  "novel_count",
  "atom_count",
  "grade",
  "tags",
  "status",
];
const LAYERS = { "原子灵感": "IA-", "单小说灵感合并": "NM-", "跨书灵感聚合": "CBA-" };
const TAG_AXES = new Set(["题材", "读者需求", "情绪", "关系动作", "剧情功能", "节奏位置", "适用阶段", "风险"]);
const REQUIRED_CBA_AXES = new Set(["题材", "读者需求", "情绪", "剧情功能", "适用阶段", "风险"]);
const CORE_QUERY_AXES = new Set(["题材", "读者需求", "情绪", "剧情功能", "适用阶段"]);
// EM 完整卡必须具备的五个灵感映射字段（缺失＝Stage 3 卡片质量问题，报错回拆文侧修复）
const EM_REQUIRED_FIELDS = ["读者想看什么", "情绪链", "戏剧单元", "可替换项", "不可照搬"];
// 专名泄漏扫描范围：排除「不可照搬」——该字段的职责就是点名原书专名
const EM_LEAK_SCAN_FIELDS = ["读者想看什么", "情绪链", "戏剧单元", "可替换项"];
const EM_HEADER_RE = /^###\s+[*_]*(EM-[0-9]{2,})(?![0-9])[*_]*\s*(?:[·\-—：:｜|]\s*)?(.*?)[\s*_]*$/;
// 以 EM 编号开头、却不是 `### EM-xxx` 的标题行：下一张卡会被静默并进上一张
const EM_MISPLACED_HEADER_RE = /^#{1,6}\s+[*_【\[]*EM-[0-9]/;
const EM_TABLE_SEPARATOR_RE = /^:?-+:?$/;
const EM_INDEX_ID_RE = /(EM-[0-9]{2,})/;
// 字段行的两种体裁：表格 `| 字段 | 值 |` 与粗体列表 `- **字段**：值`（前导 `- ` 可省）
const EM_BOLD_FIELD_RE = /^[-*]?\s*\*{2,3}([^*]+?)(?:[:：]\*{2,3}|\*{2,3}\s*[:：])\s*(.*)$/;
// 同义字段名归一；表头行的首列词不作为字段
const EM_FIELD_ALIASES = { "不可照搬项": "不可照搬", "可替换项目": "可替换项" };
const EM_TABLE_HEADER_KEYS = new Set(["字段", "维度", "---", ""]);
const CARD_PATH_RE = /\]\(|\.md\)|原子灵感\/|单小说灵感合并\/|跨书灵感聚合\/|拆文库\//;
const EM_ARROW_RE = /→|⟶|->/;

function cmpStr(a, b) {
  return a < b ? -1 : a > b ? 1 : 0;
}

function isDir(dirPath) {
  try {
    return fs.statSync(dirPath).isDirectory();
  } catch {
    return false;
  }
}

function isFile(filePath) {
  try {
    return fs.statSync(filePath).isFile();
  } catch {
    return false;
  }
}

function resolveReal(targetPath) {
  try {
    return fs.realpathSync(targetPath);
  } catch {
    return path.resolve(targetPath);
  }
}

function decodeUtf8Strict(raw) {
  const start = raw.length >= 3 && raw[0] === 0xef && raw[1] === 0xbb && raw[2] === 0xbf ? 3 : 0;
  return new TextDecoder("utf-8", { fatal: true }).decode(raw.subarray(start));
}

function readUtf8SigLines(filePath) {
  return decodeUtf8Strict(fs.readFileSync(filePath)).replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

function atomicWriteText(filePath, text) {
  const dir = path.dirname(filePath);
  fs.mkdirSync(dir, { recursive: true });
  const base = path.basename(filePath);
  const tmp = path.join(dir, `.${base}.${process.pid}.${crypto.randomBytes(6).toString("hex")}.tmp`);
  let fd = null;
  try {
    fd = fs.openSync(tmp, "wx");
    const buf = Buffer.from(text, "utf8");
    fs.writeSync(fd, buf, 0, buf.length, 0);
    fs.fsyncSync(fd);
    fs.closeSync(fd);
    fd = null;
    fs.renameSync(tmp, filePath);
  } catch (err) {
    if (fd !== null) {
      try { fs.closeSync(fd); } catch {}
    }
    try { fs.unlinkSync(tmp); } catch {}
    throw err;
  }
}

function csvEscape(value) {
  const str = value === null || value === undefined ? "" : String(value);
  if (/[",\n\r]/.test(str)) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return str;
}

function csvText(rows) {
  const lines = [COLUMNS.map(csvEscape).join(",")];
  for (const row of rows) {
    lines.push(COLUMNS.map((col) => csvEscape(row[col] ?? "")).join(","));
  }
  return "\uFEFF" + lines.join("\n") + "\n";
}

function parseCsvRecords(text) {
  const clean = text.startsWith("\uFEFF") ? text.slice(1) : text;
  const records = [];
  let row = [];
  let field = "";
  let inQuotes = false;
  let hadQuotes = false;
  let lineNum = 1;
  let i = 0;
  const len = clean.length;

  while (i < len) {
    const ch = clean[i];
    if (inQuotes) {
      if (ch === '"') {
        if (i + 1 < len && clean[i + 1] === '"') {
          field += '"';
          i += 2;
        } else {
          inQuotes = false;
          i += 1;
        }
      } else if (ch === "\r") {
        if (i + 1 < len && clean[i + 1] === "\n") {
          field += "\r\n";
          i += 2;
        } else {
          field += "\r";
          i += 1;
        }
        lineNum += 1;
      } else if (ch === "\n") {
        field += "\n";
        i += 1;
        lineNum += 1;
      } else {
        field += ch;
        i += 1;
      }
    } else if (ch === '"' && field === "") {
      inQuotes = true;
      hadQuotes = true;
      i += 1;
    } else if (ch === ",") {
      row.push(field);
      field = "";
      hadQuotes = false;
      i += 1;
    } else if (ch === "\r" || ch === "\n") {
      if (row.length > 0 || field !== "" || hadQuotes) {
        row.push(field);
        records.push({ fields: row, lineNum });
        row = [];
        field = "";
        hadQuotes = false;
      }
      if (ch === "\r" && i + 1 < len && clean[i + 1] === "\n") {
        i += 2;
      } else {
        i += 1;
      }
      lineNum += 1;
    } else {
      field += ch;
      i += 1;
    }
  }
  if (inQuotes) {
    throw new Error("csv_unterminated_quote");
  }
  if (field !== "" || row.length > 0 || hadQuotes) {
    row.push(field);
    records.push({ fields: row, lineNum });
  }
  return records;
}

function normalizeEmField(key) {
  const cleaned = key.trim().replace(/^\*+|\*+$/g, "").trim();
  return Object.prototype.hasOwnProperty.call(EM_FIELD_ALIASES, cleaned) ? EM_FIELD_ALIASES[cleaned] : cleaned;
}

function parseEmModule(moduleText) {
  const lines = moduleText.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
  const cards = [];
  const indexEntries = [];
  const problems = [];
  let current = null;
  let pendingField = null;
  let inIndexSection = false;

  for (const line of lines) {
    const stripped = line.trim();
    const header = EM_HEADER_RE.exec(stripped);
    if (header) {
      current = { em_id: header[1], title: header[2] };
      cards.push(current);
      inIndexSection = false;
      pendingField = null;
      continue;
    }
    if (EM_MISPLACED_HEADER_RE.test(stripped)) {
      problems.push(`em_header_unrecognized:${stripped.slice(0, 40)}——EM 卡标题须写成 \`### EM-xxx 名称\``);
      current = null;
      pendingField = null;
      continue;
    }
    if (stripped.startsWith("## ")) {
      inIndexSection = stripped.includes("其他机制索引");
      current = null;
      pendingField = null;
      continue;
    }
    if (current !== null && stripped.startsWith("|")) {
      pendingField = null;
      const cells = stripped.replace(/^\|+|\|+$/g, "").split("|").map((cell) => cell.trim());
      if (cells.length >= 2) {
        const key = normalizeEmField(cells[0]);
        if (!EM_TABLE_HEADER_KEYS.has(key) && !EM_TABLE_SEPARATOR_RE.test(key)) {
          if (EM_REQUIRED_FIELDS.includes(key) && Object.prototype.hasOwnProperty.call(current, key)) {
            problems.push(`${current.em_id}:em_field_duplicate:${key}`);
          }
          current[key] = cells[1];
        }
      }
      continue;
    }
    if (current !== null) {
      if (pendingField !== null && stripped && (line[0] === " " || line[0] === "\t")) {
        const appended = stripped.replace(/^[-*]+/, "").trim();
        current[pendingField] = current[pendingField] ? `${current[pendingField]}；${appended}` : appended;
        continue;
      }
      const bold = EM_BOLD_FIELD_RE.exec(stripped);
      if (bold) {
        const key = normalizeEmField(bold[1]);
        const value = bold[2].trim();
        if (EM_REQUIRED_FIELDS.includes(key) && Object.prototype.hasOwnProperty.call(current, key)) {
          problems.push(`${current.em_id}:em_field_duplicate:${key}`);
        }
        current[key] = value;
        pendingField = value ? null : key;
        continue;
      }
      if (pendingField !== null && stripped.startsWith("#")) {
        pendingField = null;
        continue;
      }
      if (pendingField !== null && stripped) {
        const appended = stripped.replace(/^[-*]+/, "").trim();
        if (appended) {
          current[pendingField] = current[pendingField] ? `${current[pendingField]}；${appended}` : appended;
        }
        continue;
      }
    }
    if (inIndexSection && stripped) {
      const match = EM_INDEX_ID_RE.exec(stripped);
      if (match) {
        const parts = stripped
          .replace(/^[|｜ ]+|[|｜ ]+$/g, "")
          .split(/[|｜]/)
          .map((part) => part.trim())
          .filter(Boolean);
        let name = parts.length >= 2 && parts[0] === match[1] ? parts[1] : (parts.length ? parts[0] : match[1]);
        if (name === match[1] && parts.length >= 2) {
          name = parts[1];
        }
        indexEntries.push([match[1], name]);
      }
    }
  }
  return [cards, indexEntries, problems];
}

function resolveWorkspace(root, explicit = null) {
  if (explicit !== null && explicit !== undefined) {
    if (isDir(path.join(explicit, "拆文库"))) {
      return explicit;
    }
    throw new Error(`workspace_invalid:${explicit} 下没有 拆文库/`);
  }
  let candidate = resolveReal(root);
  for (let i = 0; i < 6; i += 1) {
    if (isDir(path.join(candidate, "拆文库"))) {
      return candidate;
    }
    const parent = path.dirname(candidate);
    if (parent === candidate) break;
    candidate = parent;
  }
  throw new Error("workspace_not_located:从 --root 向上未找到含 拆文库/ 的目录——用 --workspace 显式指定");
}

function replaceableAntipatternHits(value, names) {
  const hits = new Set();
  for (const segment of value.split(/[；;，,、｜|]/)) {
    if (!EM_ARROW_RE.test(segment)) continue;
    const left = segment.split(EM_ARROW_RE)[0];
    for (const name of names) {
      if (left.includes(name)) hits.add(name);
    }
  }
  return Array.from(hits).sort(cmpStr);
}

function walkMdFiles(dirPath) {
  const results = [];
  if (!isDir(dirPath)) return results;
  const walk = (current) => {
    let entries;
    try {
      entries = fs.readdirSync(current, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) {
        walk(full);
      } else if (entry.name.endsWith(".md")) {
        results.push(full);
      }
    }
  };
  walk(dirPath);
  return results;
}

function characterNames(workspace, book) {
  const roleDir = path.join(workspace, "拆文库", book, "角色");
  const names = new Set();
  const skip = new Set(["角色关系", "README", "readme", "索引", "目录"]);
  if (isDir(roleDir)) {
    for (const entry of walkMdFiles(roleDir)) {
      const rawStem = path.basename(entry, ".md");
      const stem = rawStem.replace(/^\d+[-_.、\s]*/, "");
      if ([...stem].length >= 2 && !skip.has(stem)) {
        names.add(stem);
      }
    }
  }
  return names;
}

function loadNumberedRows(root) {
  const errors = [];
  const indexPath = path.join(root, "灵感索引.csv");
  try {
    const text = decodeUtf8Strict(fs.readFileSync(indexPath));
    const records = parseCsvRecords(text);
    const fieldnames = records.length ? records[0].fields : [];
    const rows = [];
    for (let i = 1; i < records.length; i += 1) {
      const rec = records[i];
      if (rec.fields.length !== fieldnames.length) {
        errors.push(`line_${rec.lineNum}:column_count_mismatch`);
        continue;
      }
      const row = {};
      for (let j = 0; j < fieldnames.length; j += 1) {
        row[fieldnames[j]] = rec.fields[j];
      }
      rows.push([rec.lineNum, row]);
    }
    if (fieldnames.length !== COLUMNS.length || fieldnames.some((col, idx) => col !== COLUMNS[idx])) {
      errors.push("index_header_mismatch");
    }
    return [rows, errors];
  } catch (err) {
    return [[], [`index_unreadable:${err.message}`]];
  }
}

function loadRows(root) {
  const [numbered, errors] = loadNumberedRows(root);
  return [numbered.map(([, row]) => row), errors];
}

class RegisterError extends Error {
  constructor(errors, warnings = []) {
    super(errors.join("\n"));
    this.errors = errors;
    this.warnings = warnings || [];
  }
}

function iaRow(book, emId, title, grade) {
  return {
    item_id: emId.replace("EM-", "IA-"),
    layer: "原子灵感",
    title: title.trim(),
    source_book: book,
    path: "",
    source_ids: emId,
    novel_count: "1",
    atom_count: "1",
    grade,
    tags: "",
    status: "active",
  };
}

function analyzeModule(root, modulePath, book, workspace = null) {
  const errors = [];
  const warnings = [];
  if (!book || book === "." || book === ".." || book.includes("/") || book.includes("\\")) {
    throw new RegisterError([`book_name_invalid:${JSON.stringify(book)}——--book 只写书名本身`]);
  }
  let ws;
  try {
    ws = resolveWorkspace(root, workspace);
  } catch (err) {
    throw new RegisterError([err.message]);
  }
  let moduleText;
  try {
    moduleText = readUtf8SigLines(modulePath);
  } catch (err) {
    throw new RegisterError([`emotion_module_unreadable:${err.message}`]);
  }
  const [cards, indexEntries, problems] = parseEmModule(moduleText);
  if (!cards.length && !indexEntries.length) {
    throw new RegisterError(["emotion_module_has_no_em_cards"]);
  }
  errors.push(...problems);

  const bookDir = path.join(ws, "拆文库", book);
  if (!isDir(bookDir)) {
    errors.push(`book_dir_not_found:拆文库/${book}——工作区 ${ws} 下没有这本书，泄漏门无法取角色名单`);
  } else {
    const rel = path.relative(resolveReal(bookDir), resolveReal(modulePath));
    if (!rel || rel === ".." || rel.startsWith(`..${path.sep}`) || path.isAbsolute(rel)) {
      errors.push(`module_book_mismatch:${modulePath} 不在 拆文库/${book}/ 下——--book 与 --module 必须是同一本书`);
    }
  }
  const names = characterNames(ws, book);
  if (!names.size && isDir(bookDir)) {
    warnings.push(`character_roster_missing:拆文库/${book}/角色/ 不存在或为空——泄漏门本次没有名单可查，请人工确认卡内无专名`);
  }

  const sortedNames = Array.from(names).sort(cmpStr);
  const seen = new Set();
  const atomRows = [];
  const cardIdSet = new Set(cards.map((c) => c.em_id));

  for (const card of cards) {
    const emId = card.em_id;
    if (seen.has(emId)) {
      errors.push(`em_id_duplicate:${emId}`);
      continue;
    }
    seen.add(emId);
    let cardErrors = 0;
    if (!card.title.trim()) {
      errors.push(`${emId}:em_title_missing——EM 卡标题须写成 \`### ${emId} 名称\``);
      cardErrors += 1;
    }
    const absent = EM_REQUIRED_FIELDS.filter((field) => !Object.prototype.hasOwnProperty.call(card, field));
    const empty = EM_REQUIRED_FIELDS.filter(
      (field) => Object.prototype.hasOwnProperty.call(card, field) && !card[field].trim()
    );
    if (absent.length) {
      errors.push(`${emId}:em_fields_missing:${absent.join("|")}——请回 story-long-analyze Stage 3 补全该模块卡`);
      cardErrors += 1;
    }
    if (empty.length) {
      errors.push(`${emId}:em_field_value_empty:${empty.join("|")}——字段在但值为空；多行值须紧跟字段名行（支持列表/段落）`);
      cardErrors += 1;
    }

    const fieldTexts = { "标题": card.title || "" };
    for (const field of EM_LEAK_SCAN_FIELDS) {
      fieldTexts[field] = card[field] || "";
    }
    const hitLocations = {};
    for (const name of sortedNames) {
      const locs = Object.entries(fieldTexts)
        .filter(([, text]) => text.includes(name))
        .map(([field]) => field);
      if (locs.length) {
        hitLocations[name] = locs;
      }
    }
    const antipattern = replaceableAntipatternHits(card["可替换项"] || "", names);
    const nonPortable = card["不可照搬"] || "";
    for (const name of antipattern) {
      errors.push(`${emId}:replaceable_antipattern:${name}——「专名→任意X」把专名写进抽象字段，改写成「功能位→任意X」`);
      cardErrors += 1;
    }
    for (const [name, locations] of Object.entries(hitLocations)) {
      if (antipattern.includes(name)) continue;
      if (nonPortable.includes(name)) {
        errors.push(`${emId}:source_specific_name_in_mechanism:${name}@${locations.join("|")}——本卡「不可照搬」已点名该专名却仍在抽象字段使用，请回 Stage 3 去专名后重试`);
        cardErrors += 1;
      } else {
        warnings.push(`${emId}:leak_suspect:${name}@${locations.join("|")}——角色卡名与通用职能词无法机械区分，请人工复核；确认是专名请回 Stage 3 修卡`);
      }
    }
    if (cardErrors === 0) {
      atomRows.push(iaRow(book, emId, card.title, "full"));
    }
  }

  for (const [emId, title] of indexEntries) {
    if (seen.has(emId)) continue;
    seen.add(emId);
    for (const name of sortedNames) {
      if (title.includes(name)) {
        warnings.push(`${emId}:leak_suspect:${name}@索引标题——请人工复核；确认是专名请回 Stage 3 修索引条目`);
      }
    }
    atomRows.push(iaRow(book, emId, title, "index"));
  }

  return {
    book,
    cards_full: cards.length,
    cards_index: indexEntries.filter(([emId]) => !cardIdSet.has(emId)).length,
    character_roster: names.size,
    errors,
    warnings,
    atom_rows: atomRows,
  };
}

function checkAtoms(root, modulePath, book, workspace = null) {
  let report;
  try {
    report = analyzeModule(root, modulePath, book, workspace);
  } catch (err) {
    if (err instanceof RegisterError) {
      return { ok: false, book, errors: err.errors, warnings: err.warnings };
    }
    throw err;
  }
  const { atom_rows: _ignored, ...rest } = report;
  return { ...rest, ok: rest.errors.length === 0 };
}

function registerAtoms(root, modulePath, book, workspace = null) {
  const report = analyzeModule(root, modulePath, book, workspace);
  if (report.errors.length) {
    throw new RegisterError(report.errors, report.warnings);
  }
  const atomRows = report.atom_rows;
  const indexPath = path.join(root, "灵感索引.csv");
  const [existing, errors] = isFile(indexPath) ? loadRows(root) : [[], []];
  if (errors.length) {
    throw new RegisterError(errors, report.warnings);
  }
  const preserved = existing.filter((row) => !(row.layer === "原子灵感" && row.source_book === book));
  const layerOrder = { "原子灵感": 0, "单小说灵感合并": 1, "跨书灵感聚合": 2 };
  const combined = [...preserved, ...atomRows];
  combined.sort((a, b) => {
    const la = Object.prototype.hasOwnProperty.call(layerOrder, a.layer) ? layerOrder[a.layer] : 9;
    const lb = Object.prototype.hasOwnProperty.call(layerOrder, b.layer) ? layerOrder[b.layer] : 9;
    if (la !== lb) return la - lb;
    const bc = cmpStr(a.source_book || "", b.source_book || "");
    if (bc !== 0) return bc;
    return cmpStr(a.item_id || "", b.item_id || "");
  });
  atomicWriteText(indexPath, csvText(combined));
  return {
    ok: true,
    book,
    atoms_full: atomRows.filter((row) => row.grade === "full").length,
    atoms_index: atomRows.filter((row) => row.grade === "index").length,
    index_writes: 1,
    character_roster: report.character_roster,
    warnings: report.warnings,
  };
}

function parseTags(raw) {
  const result = {};
  const errors = [];
  if (!raw || !raw.trim()) {
    return [result, errors];
  }
  for (const part of raw.split("；")) {
    if (!part.trim()) continue;
    const eqIdx = part.indexOf("=");
    if (eqIdx === -1) {
      errors.push(`tag_missing_equals:${part}`);
      continue;
    }
    const axis = part.slice(0, eqIdx).trim();
    const values = part.slice(eqIdx + 1).trim();
    if (!TAG_AXES.has(axis)) {
      errors.push(`tag_axis_unknown:${axis}`);
      continue;
    }
    const parsed = new Set(values.split("|").map((v) => v.trim()).filter(Boolean));
    if (!parsed.size) {
      errors.push(`tag_value_empty:${axis}`);
      continue;
    }
    if (!Object.prototype.hasOwnProperty.call(result, axis)) {
      result[axis] = new Set();
    }
    for (const v of parsed) result[axis].add(v);
  }
  return [result, errors];
}

function positiveInt(raw) {
  if (typeof raw !== "string" && typeof raw !== "number") return null;
  const trimmed = String(raw).trim();
  if (!/^-?\d+$/.test(trimmed)) return null;
  const value = parseInt(trimmed, 10);
  return value >= 1 ? value : null;
}

function sourceIds(raw) {
  return String(raw || "").split(/[|；]/).map((item) => item.trim()).filter(Boolean);
}

function loadBookEmIds(workspace, sourceBook) {
  const modulePath = path.join(workspace, "拆文库", sourceBook, "剧情", "情绪模块.md");
  let moduleText;
  try {
    moduleText = readUtf8SigLines(modulePath);
  } catch {
    return [new Set(), "emotion_module_unreadable"];
  }
  const [cards, indexEntries] = parseEmModule(moduleText);
  const ids = new Set();
  for (const card of cards) ids.add(card.em_id);
  for (const [emId] of indexEntries) ids.add(emId);
  return [ids, null];
}

function loadVocabulary(root) {
  const vocabPath = path.join(root, "标签词表.md");
  if (!isFile(vocabPath)) return null;
  let text;
  try {
    text = readUtf8SigLines(vocabPath);
  } catch {
    return null;
  }
  const vocabulary = {};
  let currentAxis = null;
  for (const line of text.split("\n")) {
    const stripped = line.trim();
    if (stripped.startsWith("## ")) {
      const axis = stripped.slice(3).trim();
      currentAxis = TAG_AXES.has(axis) ? axis : null;
      if (currentAxis !== null && !Object.prototype.hasOwnProperty.call(vocabulary, currentAxis)) {
        vocabulary[currentAxis] = [];
      }
      continue;
    }
    if (currentAxis !== null && (stripped.startsWith("- ") || stripped.startsWith("* "))) {
      const value = stripped.slice(2).split("（")[0].split("(")[0].trim();
      if (value && !vocabulary[currentAxis].includes(value)) {
        vocabulary[currentAxis].push(value);
      }
    }
  }
  return vocabulary;
}

function vocabularyErrors(vocabulary) {
  const missing = Array.from(REQUIRED_CBA_AXES)
    .filter((axis) => !Object.prototype.hasOwnProperty.call(vocabulary, axis))
    .sort(cmpStr);
  return missing.map((axis) => `vocabulary_axis_missing:${axis}`);
}

function validate(root, workspace = null) {
  const [numbered, errors] = loadNumberedRows(root);
  const rows = numbered.map(([, row]) => row);
  let ws = null;
  let workspaceError = "";
  try {
    ws = resolveWorkspace(root, workspace);
  } catch (err) {
    workspaceError = err.message;
  }
  const vocabulary = loadVocabulary(root);
  if (vocabulary !== null) {
    errors.push(...vocabularyErrors(vocabulary));
  }
  const seen = new Set();
  const iaByBook = new Map();
  const nmByBook = new Map();
  const activeSingleBookCba = new Map();

  for (const [number, row] of numbered) {
    const itemId = (row.item_id || "").trim();
    const layer = (row.layer || "").trim();
    const book = (row.source_book || "").trim();
    const prefix = LAYERS[layer];
    if (!prefix) {
      errors.push(`line_${number}:layer_invalid`);
      continue;
    }
    const uniqueKey = `${layer}\0${layer !== "跨书灵感聚合" ? book : ""}\0${itemId}`;
    if (!itemId.startsWith(prefix) || seen.has(uniqueKey)) {
      errors.push(`line_${number}:item_id_invalid_or_duplicate`);
    }
    seen.add(uniqueKey);

    let cardText = "";
    if (layer === "原子灵感") {
      if (!iaByBook.has(book)) iaByBook.set(book, new Map());
      iaByBook.get(book).set(itemId, row);
      if ((row.path || "").trim()) {
        errors.push(`line_${number}:ia_must_not_have_card_file`);
      }
      const grade = (row.grade || "").trim();
      if (grade !== "full" && grade !== "index") {
        errors.push(`line_${number}:ia_grade_invalid`);
      }
    } else {
      if (layer === "单小说灵感合并") {
        if (!nmByBook.has(book)) nmByBook.set(book, new Map());
        nmByBook.get(book).set(itemId, row);
      }
      const relative = (row.path || "").trim().replace(/\\/g, "/");
      if (!relative.startsWith(`${layer}/`) || relative.split("/").includes("..")) {
        errors.push(`line_${number}:path_outside_layer`);
      } else if (!isFile(path.join(root, relative))) {
        errors.push(`line_${number}:path_missing`);
      } else {
        try {
          cardText = decodeUtf8Strict(fs.readFileSync(path.join(root, relative)));
        } catch {
          cardText = "";
        }
      }
      if (cardText && CARD_PATH_RE.test(cardText)) {
        errors.push(`line_${number}:path_reference_in_card——卡内只允许裸 ID，路径按 ID 查灵感索引.csv`);
      }
      if ((row.grade || "").trim()) {
        errors.push(`line_${number}:grade_reserved_for_ia`);
      }
    }

    const [tags, tagErrors] = parseTags(row.tags || "");
    for (const err of tagErrors) {
      errors.push(`line_${number}:${err}`);
    }
    if (layer === "跨书灵感聚合") {
      const missingAxes = Array.from(REQUIRED_CBA_AXES)
        .filter((axis) => !Object.prototype.hasOwnProperty.call(tags, axis))
        .sort(cmpStr);
      if (missingAxes.length) {
        errors.push(`line_${number}:cba_tags_missing:${missingAxes.join("|")}`);
      }
      if (vocabulary !== null) {
        for (const axis of Object.keys(tags).sort(cmpStr)) {
          if (!Object.prototype.hasOwnProperty.call(vocabulary, axis)) continue;
          const allowed = new Set(vocabulary[axis]);
          const extras = Array.from(tags[axis]).filter((v) => !allowed.has(v)).sort(cmpStr);
          for (const value of extras) {
            errors.push(`line_${number}:tag_value_not_in_vocabulary:${axis}=${value}——先对照 标签词表.md：同义就用表内值，确属新维度先受控扩表`);
          }
        }
      }
      const novelCount = positiveInt(row.novel_count || "");
      if (novelCount === null) {
        errors.push(`line_${number}:novel_count_invalid`);
      }
      if (positiveInt(row.atom_count || "") === null) {
        errors.push(`line_${number}:atom_count_invalid`);
      }
      if (!(row.source_ids || "").trim()) {
        errors.push(`line_${number}:source_ids_missing`);
      }
      if (novelCount === 1 && !cardText.includes("单书假设")) {
        errors.push(`line_${number}:single_book_hypothesis_marker_missing`);
      }
      if (novelCount !== null && novelCount >= 2 && !cardText.includes("跨书重复验证")) {
        errors.push(`line_${number}:cross_book_validation_marker_missing`);
      }
    } else if (Object.keys(tags).length > 0) {
      errors.push(`line_${number}:tags_reserved_for_cba`);
    }
  }

  for (const [book, atoms] of iaByBook.entries()) {
    let emIds = new Set();
    let moduleError = null;
    if (ws === null) {
      errors.push(`book_${book}:${workspaceError}`);
      moduleError = "workspace_not_located";
    } else {
      [emIds, moduleError] = loadBookEmIds(ws, book);
      if (moduleError) {
        errors.push(`book_${book}:${moduleError}`);
      }
    }
    const registered = new Set();
    for (const [itemId, row] of atoms.entries()) {
      const refs = sourceIds(row.source_ids || "");
      if (refs.length !== 1 || !refs[0].startsWith("EM-")) {
        errors.push(`${book}/${itemId}:ia_source_em_invalid`);
        continue;
      }
      if (refs[0].replace("EM-", "IA-") !== itemId) {
        errors.push(`${book}/${itemId}:ia_id_must_mirror_em_id`);
      }
      registered.add(refs[0]);
      if (positiveInt(row.novel_count || "") !== 1 || positiveInt(row.atom_count || "") !== 1) {
        errors.push(`${book}/${itemId}:ia_counts_must_equal_one`);
      }
    }
    if (!moduleError) {
      const missing = Array.from(emIds).filter((id) => !registered.has(id)).sort(cmpStr);
      const extra = Array.from(registered).filter((id) => !emIds.has(id)).sort(cmpStr);
      if (missing.length || extra.length) {
        errors.push(`book_${book}:ia_em_set_mismatch:missing=${JSON.stringify(missing)}:extra=${JSON.stringify(extra)}`);
      }
    }
  }

  for (const [book, merges] of nmByBook.entries()) {
    const atoms = iaByBook.get(book) || new Map();
    const atomEm = new Set(Array.from(atoms.values()).map((r) => (r.source_ids || "").trim()));
    for (const [itemId, row] of merges.entries()) {
      const refs = sourceIds(row.source_ids || "");
      if (refs.length < 2) {
        errors.push(`${book}/${itemId}:nm_requires_at_least_two_sources`);
        continue;
      }
      const refSet = new Set(refs);
      const unknown = Array.from(refSet).filter((r) => !atomEm.has(r)).sort(cmpStr);
      if (unknown.length) {
        errors.push(`${book}/${itemId}:nm_source_em_missing:${JSON.stringify(unknown)}`);
      }
      if (positiveInt(row.novel_count || "") !== 1) {
        errors.push(`${book}/${itemId}:nm_novel_count_must_equal_one`);
      }
      const overlapCount = Array.from(refSet).filter((r) => atomEm.has(r)).length;
      if (positiveInt(row.atom_count || "") !== overlapCount) {
        errors.push(`${book}/${itemId}:nm_atom_count_mismatch`);
      }
    }
  }

  for (const row of rows) {
    if (row.layer !== "跨书灵感聚合") continue;
    const cbaId = (row.item_id || "").trim();
    const expanded = new Set();
    const unknownRefs = [];
    for (const rawRef of sourceIds(row.source_ids || "")) {
      const slashIdx = rawRef.lastIndexOf("/");
      if (slashIdx === -1) {
        unknownRefs.push(rawRef);
        continue;
      }
      const book = rawRef.slice(0, slashIdx);
      const ref = rawRef.slice(slashIdx + 1);
      const bookNm = nmByBook.get(book);
      const bookIa = iaByBook.get(book);
      if (ref.startsWith("NM-") && bookNm && bookNm.has(ref)) {
        for (const emRef of sourceIds(bookNm.get(ref).source_ids || "")) {
          expanded.add(`${book}\0${emRef}`);
        }
      } else if (ref.startsWith("EM-") && bookIa && bookIa.has(ref.replace("EM-", "IA-"))) {
        expanded.add(`${book}\0${ref}`);
      } else {
        unknownRefs.push(rawRef);
      }
    }
    if (unknownRefs.length) {
      errors.push(`${cbaId}:cba_source_missing:${JSON.stringify([...unknownRefs].sort(cmpStr))}`);
    }
    if (!expanded.size) {
      errors.push(`${cbaId}:cba_requires_sources`);
      continue;
    }
    const novels = new Set(Array.from(expanded).map((key) => key.split("\0")[0]));
    if (novels.size === 1 && (row.status || "").trim() === "active") {
      const only = Array.from(novels)[0];
      activeSingleBookCba.set(only, (activeSingleBookCba.get(only) || 0) + 1);
    }
    if (positiveInt(row.novel_count || "") !== novels.size) {
      errors.push(`${cbaId}:cba_novel_count_mismatch`);
    }
    if (positiveInt(row.atom_count || "") !== expanded.size) {
      errors.push(`${cbaId}:cba_atom_count_mismatch`);
    }
  }
  for (const book of Array.from(activeSingleBookCba.keys()).sort(cmpStr)) {
    const count = activeSingleBookCba.get(book);
    if (count > 3) {
      errors.push(`book_${book}:active_single_book_cba_limit_exceeded:${count}`);
    }
  }
  return errors;
}

function coverage(root) {
  const [rows, errors] = loadRows(root);
  if (errors.length) {
    throw new Error(errors.join(";"));
  }
  const iaByBook = new Map();
  const nmMembers = new Map();
  for (const row of rows) {
    const book = (row.source_book || "").trim();
    if (row.layer === "原子灵感" && (row.status || "").trim() === "active") {
      if (!iaByBook.has(book)) iaByBook.set(book, new Set());
      for (const ref of sourceIds(row.source_ids || "")) {
        iaByBook.get(book).add(ref);
      }
    } else if (row.layer === "单小说灵感合并") {
      nmMembers.set(`${book}\0${(row.item_id || "").trim()}`, new Set(sourceIds(row.source_ids || "")));
    }
  }
  const covered = new Set();
  const singleBookHypotheses = [];
  for (const row of rows) {
    if (row.layer !== "跨书灵感聚合" || (row.status || "").trim() !== "active") continue;
    if (positiveInt(row.novel_count || "") === 1) {
      singleBookHypotheses.push((row.item_id || "").trim());
    }
    for (const rawRef of sourceIds(row.source_ids || "")) {
      const slashIdx = rawRef.lastIndexOf("/");
      if (slashIdx === -1) continue;
      const book = rawRef.slice(0, slashIdx);
      const ref = rawRef.slice(slashIdx + 1);
      if (ref.startsWith("NM-")) {
        const members = nmMembers.get(`${book}\0${ref}`) || new Set();
        for (const emRef of members) covered.add(`${book}\0${emRef}`);
      } else {
        covered.add(`${book}\0${ref}`);
      }
    }
  }
  const books = {};
  let uncoveredTotal = 0;
  for (const book of Array.from(iaByBook.keys()).sort(cmpStr)) {
    const atoms = iaByBook.get(book);
    const uncovered = Array.from(atoms).filter((em) => !covered.has(`${book}\0${em}`)).sort(cmpStr);
    uncoveredTotal += uncovered.length;
    books[book] = {
      atoms: atoms.size,
      covered: atoms.size - uncovered.length,
      uncovered,
    };
  }
  return {
    ok: true,
    books,
    uncovered_total: uncoveredTotal,
    single_book_hypotheses: singleBookHypotheses.sort(cmpStr),
  };
}

function requestedTags(values) {
  const [tags, errors] = parseTags(values.join("；"));
  if (errors.length) {
    throw new Error(errors.join(";"));
  }
  return tags;
}

function query(root, values, limit) {
  const [rows, errors] = loadRows(root);
  if (errors.length) {
    throw new Error(errors.join(";"));
  }
  const wanted = requestedTags(values);
  const axisValues = {};
  for (const axis of Object.keys(wanted)) {
    axisValues[axis] = new Set();
  }
  const matches = [];
  for (const row of rows) {
    if (row.layer !== "跨书灵感聚合" || row.status !== "active") continue;
    const [tags, tagErrors] = parseTags(row.tags || "");
    if (tagErrors.length) continue;
    for (const axis of Object.keys(axisValues)) {
      const found = tags[axis];
      if (found) {
        for (const v of found) axisValues[axis].add(v);
      }
    }
    let score = 0;
    const matched = [];
    let coreMatch = false;
    for (const [axis, wantedValues] of Object.entries(wanted)) {
      const rowValues = tags[axis] || new Set();
      const overlap = Array.from(wantedValues).filter((v) => rowValues.has(v)).sort(cmpStr);
      if (overlap.length) {
        score += (CORE_QUERY_AXES.has(axis) ? 2 : 1) * overlap.length;
        for (const v of overlap) matched.push(`${axis}=${v}`);
        if (CORE_QUERY_AXES.has(axis)) coreMatch = true;
      }
    }
    if (score <= 0 || !coreMatch) continue;
    matches.push({
      item_id: row.item_id,
      title: row.title,
      path: row.path,
      score,
      matched_tags: matched,
      novel_count: positiveInt(row.novel_count || "") || 0,
      atom_count: positiveInt(row.atom_count || "") || 0,
    });
  }
  matches.sort((a, b) => {
    if (a.score !== b.score) return b.score - a.score;
    if (a.novel_count !== b.novel_count) return b.novel_count - a.novel_count;
    if (a.atom_count !== b.atom_count) return b.atom_count - a.atom_count;
    return cmpStr(a.item_id, b.item_id);
  });
  const unmatched = [];
  for (const axis of Object.keys(wanted).sort(cmpStr)) {
    const missingVals = Array.from(wanted[axis]).filter((v) => !axisValues[axis].has(v)).sort(cmpStr);
    for (const value of missingVals) {
      unmatched.push(`${axis}=${value}`);
    }
  }
  const axisInventory = {};
  for (const axis of Object.keys(axisValues).sort(cmpStr)) {
    axisInventory[axis] = Array.from(axisValues[axis]).sort(cmpStr);
  }
  const cappedLimit = Math.max(3, Math.min(limit, 8));
  return {
    matches: matches.slice(0, cappedLimit),
    unmatched_tags: unmatched,
    axis_inventory: axisInventory,
    vocabulary_loaded: loadVocabulary(root) !== null,
  };
}

function resolve(root, refs) {
  const [rows, errors] = loadRows(root);
  if (errors.length) {
    throw new Error(errors.join(";"));
  }
  const byKey = new Map();
  for (const row of rows) {
    const book = row.layer !== "跨书灵感聚合" ? (row.source_book || "").trim() : "";
    byKey.set(`${book}\0${(row.item_id || "").trim()}`, row);
  }
  const resolved = [];
  const missing = [];
  for (const rawRef of refs) {
    const slashIdx = rawRef.lastIndexOf("/");
    const book = slashIdx !== -1 ? rawRef.slice(0, slashIdx) : "";
    const ref = slashIdx !== -1 ? rawRef.slice(slashIdx + 1) : rawRef;
    const item = ref.startsWith("EM-") ? ref.replace("EM-", "IA-") : ref;
    const row = byKey.get(`${item.startsWith("CBA-") ? "" : book}\0${item}`);
    if (!row) {
      missing.push(rawRef);
      continue;
    }
    const location = row.layer === "原子灵感"
      ? `拆文库/${book}/剧情/情绪模块.md#${row.source_ids || ""}`
      : (row.path || "");
    resolved.push({
      ref: rawRef,
      item_id: row.item_id || "",
      title: row.title || "",
      location,
    });
  }
  return { ok: missing.length === 0, resolved, missing };
}

function printHelp() {
  process.stdout.write(
    "usage: inspiration_index.js {register-atoms,check-atoms,validate,coverage,query,resolve} ...\n"
  );
}

function parseArgs(argv) {
  if (!argv.length) {
    throw new Error("command is required (choose from: register-atoms, check-atoms, validate, coverage, query, resolve)");
  }
  if (argv[0] === "-h" || argv[0] === "--help") {
    printHelp();
    return { help: true };
  }
  const command = argv[0];
  const rest = argv.slice(1);
  if (!["register-atoms", "check-atoms", "validate", "coverage", "query", "resolve"].includes(command)) {
    throw new Error(`unknown_command:${command}`);
  }
  const args = {
    command,
    root: null,
    module: null,
    book: null,
    workspace: null,
    tag: [],
    limit: 6,
    ref: [],
  };
  for (let i = 0; i < rest.length; i += 1) {
    const tok = rest[i];
    if (tok === "-h" || tok === "--help") {
      printHelp();
      return { help: true };
    }
    let flag = tok;
    let inlineVal = null;
    const eqIdx = tok.indexOf("=");
    if (tok.startsWith("--") && eqIdx !== -1) {
      flag = tok.slice(0, eqIdx);
      inlineVal = tok.slice(eqIdx + 1);
    }
    const nextVal = () => {
      if (inlineVal !== null) return inlineVal;
      if (i + 1 >= rest.length) throw new Error(`missing_argument:${flag}`);
      i += 1;
      return rest[i];
    };
    if (flag === "--root") args.root = nextVal();
    else if (flag === "--module" && (command === "register-atoms" || command === "check-atoms")) args.module = nextVal();
    else if (flag === "--book" && (command === "register-atoms" || command === "check-atoms")) args.book = nextVal();
    else if (flag === "--workspace" && (command === "register-atoms" || command === "check-atoms" || command === "validate")) args.workspace = nextVal();
    else if (flag === "--tag" && command === "query") args.tag.push(nextVal());
    else if (flag === "--limit" && command === "query") {
      const raw = nextVal();
      if (!/^-?\d+$/.test(raw.trim())) throw new Error(`invalid_int:${raw}`);
      args.limit = parseInt(raw.trim(), 10);
    } else if (flag === "--ref" && command === "resolve") args.ref.push(nextVal());
    else throw new Error(`unknown_argument:${tok}`);
  }
  if (!args.root) throw new Error("--root is required");
  if ((command === "register-atoms" || command === "check-atoms") && (!args.module || args.book === null)) {
    throw new Error("--module and --book are required");
  }
  if (command === "resolve" && !args.ref.length) {
    throw new Error("--ref is required");
  }
  return args;
}

function run(args) {
  if (args.command === "register-atoms") {
    try {
      const payload = registerAtoms(args.root, args.module, args.book.trim(), args.workspace);
      process.stdout.write(JSON.stringify(payload) + "\n");
      return 0;
    } catch (err) {
      const errors = err instanceof RegisterError ? err.errors : [err.message || String(err)];
      const warnings = err instanceof RegisterError ? err.warnings : [];
      process.stdout.write(JSON.stringify({ ok: false, errors, warnings }) + "\n");
      return 2;
    }
  }
  if (args.command === "check-atoms") {
    const report = checkAtoms(args.root, args.module, args.book.trim(), args.workspace);
    process.stdout.write(JSON.stringify(report) + "\n");
    return report.ok ? 0 : 1;
  }
  if (args.command === "validate") {
    const errors = validate(args.root, args.workspace);
    process.stdout.write(JSON.stringify({ ok: errors.length === 0, errors }) + "\n");
    return errors.length === 0 ? 0 : 1;
  }
  if (args.command === "coverage") {
    try {
      const payload = coverage(args.root);
      process.stdout.write(JSON.stringify(payload) + "\n");
      return 0;
    } catch (err) {
      process.stdout.write(JSON.stringify({ ok: false, error: err.message || String(err) }) + "\n");
      return 2;
    }
  }
  if (args.command === "resolve") {
    try {
      const payload = resolve(args.root, args.ref);
      process.stdout.write(JSON.stringify(payload) + "\n");
      return payload.ok ? 0 : 1;
    } catch (err) {
      process.stdout.write(JSON.stringify({ ok: false, error: err.message || String(err) }) + "\n");
      return 2;
    }
  }
  try {
    const payload = query(args.root, args.tag, args.limit);
    process.stdout.write(JSON.stringify({ ok: true, ...payload }) + "\n");
    return 0;
  } catch (err) {
    process.stdout.write(JSON.stringify({ ok: false, error: err.message || String(err) }) + "\n");
    return 2;
  }
}

function main(argv = process.argv.slice(2)) {
  let args;
  try {
    args = parseArgs(argv);
    if (args.help) return 0;
  } catch (err) {
    process.stderr.write(`error: ${err.message}\n`);
    return 2;
  }
  try {
    return run(args);
  } catch (err) {
    const message = `io_error:${err.message || String(err)}`;
    process.stdout.write(JSON.stringify({ ok: false, error: message, errors: [message] }) + "\n");
    return 2;
  }
}

module.exports = {
  COLUMNS,
  LAYERS,
  TAG_AXES,
  REQUIRED_CBA_AXES,
  CORE_QUERY_AXES,
  EM_REQUIRED_FIELDS,
  EM_LEAK_SCAN_FIELDS,
  RegisterError,
  atomic_write_text: atomicWriteText,
  csv_text: csvText,
  normalize_em_field: normalizeEmField,
  parse_em_module: parseEmModule,
  resolve_workspace: resolveWorkspace,
  replaceable_antipattern_hits: replaceableAntipatternHits,
  character_names: characterNames,
  load_numbered_rows: loadNumberedRows,
  load_rows: loadRows,
  analyze_module: analyzeModule,
  check_atoms: checkAtoms,
  register_atoms: registerAtoms,
  parse_tags: parseTags,
  positive_int: positiveInt,
  source_ids: sourceIds,
  load_book_em_ids: loadBookEmIds,
  validate,
  load_vocabulary: loadVocabulary,
  vocabulary_errors: vocabularyErrors,
  coverage,
  requested_tags: requestedTags,
  query,
  resolve,
  main,
};

if (require.main === module) {
  process.exitCode = main();
}
