#!/usr/bin/env node
'use strict';

/**
 * 短篇题材包按节切片器（v5 五段标准结构）
 *
 * 用法：
 *   node skills/story-short-write/scripts/slice-genre-pack.js --stage plan|write --genre <题材名或别名> [--json]
 *   node skills/story-short-write/scripts/slice-genre-pack.js --stage plan|write --project <短篇目录> [--json]
 *   node skills/story-short-write/scripts/slice-genre-pack.js --stage plan|write --file <流派包路径> [--json]
 *
 * 约定：
 *   - --stage plan  ：仅输出标题/导语 + 1. 故事线设计 / 2. 常见剧情设计 / 3. 人物设计（供构思与列纲）
 *   - --stage write ：仅输出标题/导语 + 4. 正文技巧 / 5. 案例片段（供正文落稿）
 *   - 若遇未按 v5 五段结构编排的自定义题材包，优雅回退全文（sliced: false），绝不报错中断。
 */

const fs = require('fs');
const path = require('path');

const SKILL_ROOT = path.resolve(__dirname, '..');
const GENRE_DIR = path.join(SKILL_ROOT, 'references', 'genre-styles');

const STAGE_SECTIONS = {
  plan: [1, 2, 3],
  write: [4, 5],
};

function countNws(text) {
  return String(text || '').replace(/\s+/g, '').length;
}

function stripFrontmatter(rawText) {
  return String(rawText || '').replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n*/, '');
}

function parseGenrePacks(genreDir = GENRE_DIR) {
  if (!fs.existsSync(genreDir)) return [];
  return fs
    .readdirSync(genreDir)
    .filter((name) => name.endsWith('.md'))
    .sort()
    .map((file) => {
      const fullPath = path.join(genreDir, file);
      const name = file.slice(0, -3);
      let aliases = [];
      try {
        const text = fs.readFileSync(fullPath, 'utf8');
        const fm = text.match(/^---\r?\n([\s\S]*?)\r?\n---/);
        const aliasLine = fm ? fm[1].match(/^[ \t]*aliases[ \t]*:[ \t]*\[([^\]]*)\][ \t]*$/m) : null;
        if (aliasLine) {
          aliases = aliasLine[1]
            .split(',')
            .map((item) => item.trim().replace(/^['"]|['"]$/g, '').trim())
            .filter(Boolean);
        }
      } catch {
        aliases = [];
      }
      return { name, file, path: fullPath, aliases };
    });
}

function extractGenreFromProject(projectDir) {
  const candidates = [
    path.join(projectDir, '设定.md'),
    path.join(projectDir, '设定', '题材定位.md'),
  ];
  for (const filePath of candidates) {
    if (!fs.existsSync(filePath)) continue;
    const text = fs.readFileSync(filePath, 'utf8');
    const match = text.match(/^[ \t]*[-*]?[ \t]*(?:题材参考|题材包|题材类型|题材)[ \t]*[：:][ \t]*([^\n]*)$/m);
    if (match && match[1].trim()) {
      return match[1].replace(/`/g, '').trim();
    }
  }
  return '';
}

function resolveShortGenrePack(genreValue, genreDir = GENRE_DIR) {
  const packs = parseGenrePacks(genreDir);
  const fallback = packs.find((p) => p.name === '通用短篇') || packs[0] || null;
  const raw = String(genreValue || '').replace(/`/g, '').trim();

  if (!raw || /^冷门/.test(raw) || raw === '[待补充]') {
    return { pack: fallback, matched_by: raw ? 'fallback_cold' : 'fallback_empty' };
  }

  // 允许直接传相对路径（兼容 0.9.x 写法）
  const pathMatch = raw.match(/references\/genre-styles\/([^\s|]+\.md)/);
  if (pathMatch) {
    const byFile = packs.find((p) => p.file === pathMatch[1]);
    if (byFile) return { pack: byFile, matched_by: 'path' };
  }

  const tokens = raw.split(/[\/、,，+＋（(）)\s]+/).map((s) => s.trim()).filter(Boolean);
  const hasBgCue =
    tokens.some((t) => /^(?:言情|女频|现言|古言|男频|男女)$/.test(t)) ||
    /(?:言情|女频|现言|古言)/.test(raw);

  // 与 check-phase2-contract.js 一致：双男主严判，防「言情纯爱」误路由
  const strictBlTerms = ['双男主', '耽美', 'ABO', '病娇双男主', '双男主追夫'];
  const blPack = packs.find((p) => p.name === '双男主');
  if (blPack) {
    const blStrictHit = strictBlTerms.find((term) => raw === term || raw.startsWith(term) || tokens.includes(term));
    if (blStrictHit) return { pack: blPack, matched_by: `bl_strict:${blStrictHit}` };
    if (!hasBgCue && (raw === '纯爱' || tokens.includes('纯爱'))) {
      return { pack: blPack, matched_by: 'bl_pure_love' };
    }
  }

  // 1. 精确文件名命中
  const exactName = packs.find((p) => p.name === raw || tokens.includes(p.name));
  if (exactName) return { pack: exactName, matched_by: 'exact_name' };

  // 2. 精确别名命中
  for (const pack of packs) {
    if (pack.name === '双男主') continue;
    const hit = pack.aliases.find((alias) => raw === alias || tokens.includes(alias));
    if (hit) return { pack, matched_by: `alias:${hit}` };
  }

  // 3. 子串命中（优先长别名，防短词误碰）
  const candidates = [];
  for (const pack of packs) {
    if (pack.name === '双男主') continue;
    for (const term of [pack.name, ...pack.aliases]) {
      if (term.length >= 2 && (raw.includes(term) || term.includes(raw))) {
        candidates.push({ pack, term, len: term.length });
      }
    }
  }
  candidates.sort((a, b) => b.len - a.len);
  if (candidates.length) {
    return { pack: candidates[0].pack, matched_by: `substr:${candidates[0].term}` };
  }

  return { pack: fallback, matched_by: 'fallback_unmatched' };
}

/**
 * 按 v5 标准二级标题编号截取题材包（跳过代码块内 ##）。
 * 若不含标准 `## 1. 故事线设计`，优雅回退全文并标 sliced: false。
 */
function sliceGenrePack(rawText, wantedNums, options = {}) {
  const { keepHeader = true } = options;
  const body = stripFrontmatter(rawText);
  const fullNws = countNws(body);
  const lines = body.split(/\r?\n/);

  let inFence = false;
  const headings = [];
  for (let i = 0; i < lines.length; i += 1) {
    if (/^\s*```/.test(lines[i])) {
      inFence = !inFence;
      continue;
    }
    if (inFence) continue;
    const m = /^##\s+(\d+)\.\s+(.+?)\s*$/.exec(lines[i]);
    if (m) {
      headings.push({ line: i, num: Number(m[1]), title: m[2] });
    }
  }

  const isV5 = headings.some((h) => h.num === 1 && /故事线设计/.test(h.title));
  if (!isV5) {
    const trimmed = body.trim();
    return {
      sliced: false,
      sections: [],
      full_nws: fullNws,
      slice_nws: countNws(trimmed),
      saved_pct: 0,
      content: trimmed,
    };
  }

  const wantSet = new Set(wantedNums);
  const chunks = [];
  if (keepHeader && headings[0].line > 0) {
    const header = lines.slice(0, headings[0].line).join('\n').trim();
    if (header) chunks.push(header);
  }

  const keptSections = [];
  for (let idx = 0; idx < headings.length; idx += 1) {
    const cur = headings[idx];
    if (!wantSet.has(cur.num)) continue;
    const end = idx + 1 < headings.length ? headings[idx + 1].line : lines.length;
    const secText = lines.slice(cur.line, end).join('\n').trim();
    if (secText) {
      chunks.push(secText);
      keptSections.push(`${cur.num}. ${cur.title}`);
    }
  }

  const content = chunks.join('\n\n').trim();
  const sliceNws = countNws(content);
  const savedPct = fullNws > 0 ? Number((((fullNws - sliceNws) / fullNws) * 100).toFixed(1)) : 0;

  return {
    sliced: true,
    sections: keptSections,
    full_nws: fullNws,
    slice_nws: sliceNws,
    saved_pct: savedPct,
    content,
  };
}

function parseArgs(argv) {
  const opts = { stage: '', genre: '', project: '', file: '', json: false };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--stage' && argv[i + 1]) opts.stage = argv[++i];
    else if (arg.startsWith('--stage=')) opts.stage = arg.slice('--stage='.length);
    else if (arg === '--genre' && argv[i + 1]) opts.genre = argv[++i];
    else if (arg.startsWith('--genre=')) opts.genre = arg.slice('--genre='.length);
    else if (arg === '--project' && argv[i + 1]) opts.project = argv[++i];
    else if (arg.startsWith('--project=')) opts.project = arg.slice('--project='.length);
    else if (arg === '--file' && argv[i + 1]) opts.file = argv[++i];
    else if (arg.startsWith('--file=')) opts.file = arg.slice('--file='.length);
    else if (arg === '--json') opts.json = true;
    else if (arg === '-h' || arg === '--help') opts.help = true;
  }
  return opts;
}

function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help || !STAGE_SECTIONS[opts.stage]) {
    const usage =
      '用法: node slice-genre-pack.js --stage plan|write [--genre <题材> | --project <短篇目录> | --file <路径>] [--json]';
    if (opts.help) {
      console.log(usage);
      process.exit(0);
    }
    console.error(`参数错误：需要 --stage plan 或 --stage write。\n${usage}`);
    process.exit(2);
  }

  let packPath = '';
  let packName = '';
  let matchedBy = 'file';
  let resolvedGenre = opts.genre;

  if (opts.file) {
    packPath = path.resolve(opts.file);
    if (!fs.existsSync(packPath)) {
      console.error(`找不到指定题材包文件：${packPath}`);
      process.exit(2);
    }
    packName = path.basename(packPath, '.md');
  } else {
    if (!resolvedGenre && opts.project) {
      resolvedGenre = extractGenreFromProject(path.resolve(opts.project));
    }
    const resolved = resolveShortGenrePack(resolvedGenre);
    if (!resolved.pack) {
      console.error(`未找到可用短篇题材包目录：${GENRE_DIR}`);
      process.exit(2);
    }
    packPath = resolved.pack.path;
    packName = resolved.pack.name;
    matchedBy = resolved.matched_by;
  }

  const rawText = fs.readFileSync(packPath, 'utf8');
  const sliced = sliceGenrePack(rawText, STAGE_SECTIONS[opts.stage]);

  if (opts.json) {
    console.log(
      JSON.stringify(
        {
          ok: true,
          stage: opts.stage,
          genre_input: resolvedGenre || null,
          pack: packName,
          path: packPath,
          matched_by: matchedBy,
          ...sliced,
        },
        null,
        2
      )
    );
    return;
  }

  const label = opts.stage === 'plan' ? '1–3 节：故事线/常见剧情/人物设计' : '4–5 节：正文技巧/案例片段';
  const header = sliced.sliced
    ? `<!-- genre-pack: ${packName}.md (${label}; ${sliced.slice_nws}/${sliced.full_nws} NWS, -${sliced.saved_pct}%) -->`
    : `<!-- genre-pack: ${packName}.md (non-v5 fallback: full text) -->`;
  console.log(`${header}\n${sliced.content}`);
}

if (require.main === module) {
  main();
}

module.exports = {
  parseGenrePacks,
  extractGenreFromProject,
  resolveShortGenrePack,
  sliceGenrePack,
  STAGE_SECTIONS,
};
