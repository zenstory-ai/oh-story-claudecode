#!/usr/bin/env node
/**
 * Deterministic delivery verifier & section counter for story-short-write.
 *
 * Usage:
 *   node scripts/check-delivery-contract.js --json [--strict] \
 *     --min-chars N --max-chars N --sections N [--min-section-chars N] [--check-contract] [project-dir]
 *   node scripts/check-delivery-contract.js --counts [--json] [project-dir-or-file]
 *
 * --check-contract validates only parameters before writing; it is not delivery approval.
 * --counts prints lead and per-section visible char counts without requiring delivery bounds.
 * Exit: 0 = pass (no hard failures; soft warnings allowed unless --strict),
 *       1 = blocking delivery failures (or soft warnings under --strict),
 *       2 = invalid invocation.
 *
 * The verifier only checks user-visible size and shape. It does not score prose,
 * causality, emotion, or any other semantic quality dimension.
 */

'use strict'

const fs = require('fs')
const path = require('path')

const MARKERS = [
  { style: 'numeric-heading', pattern: /^###\s*\d+\.$/ },
  { style: 'chapter-heading', pattern: /^###\s*第[一二三四五六七八九十百千万两〇零0-9]+章(?:[\s\u3000].{1,30})?$/ },
  { style: 'zhihu-numeric', pattern: /^\d+\.$/ },
]

const LEAD_SEP_RE = /^(?:(?:…\s*){2,}|(?:\.\s*){3,}|(?:·\s*){3,}|[—\-]{2,}|0?1\.?)$/
const LEAD_HEADING_RE = /^###\s*导语\s*$/
const INLINE_LEAD_END_RE = /(?:…{2,}|\.{3,}|·{3,})$/
const DIVIDER_LINE_RE = /^(?:[—\-]{2,}|(?:…\s*){2,}|(?:\.\s*){3,}|(?:·\s*){3,}|[*_=~]{3,})$/
const POV_HEADER_LINE_RE = /^\s*【[^】]{1,20}(?:视角|番外|后记|尾声)(?:[（(][^）)】]{1,16}[）)])?】\s*$/

function readBody(file) {
  try {
    const text = fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '')
    return { ok: text.trim().length > 0, text }
  } catch (error) {
    return { ok: false, text: '', error: error.message }
  }
}

function visibleChars(text) {
  return Array.from(text).filter((character) => !/\s/u.test(character)).length
}

function markerFor(line) {
  const trimmed = line.trim()
  return MARKERS.find((entry) => entry.pattern.test(trimmed)) || null
}

function isStructuralNonProse(trimmed) {
  return /^#{1,6}\s/.test(trimmed) || /^-{3,}$/.test(trimmed) || /^[*_]{3,}$/.test(trimmed)
}

function stripHtmlCommentsFromLines(rawLines) {
  const unclosed = new Set()
  for (;;) {
    const out = []
    let open = false
    let openedAt = null
    rawLines.forEach((raw, index) => {
      let text = ''
      let cursor = 0
      while (cursor < raw.length) {
        if (open) {
          const close = raw.indexOf('-->', cursor)
          if (close === -1) {
            cursor = raw.length
            break
          }
          cursor = close + 3
          open = false
          continue
        }
        const start = raw.indexOf('<!--', cursor)
        if (start === -1) {
          text += raw.slice(cursor)
          break
        }
        text += raw.slice(cursor, start)
        cursor = start + 4
        const key = `${index}:${start}`
        if (unclosed.has(key)) continue
        open = true
        openedAt = key
      }
      out.push(text)
    })
    if (!(open && openedAt !== null)) return out
    unclosed.add(openedAt)
  }
}

/**
 * Extract section markers. When chapter-heading markers (`###第N章`) are present,
 * a standalone `1.` inside Section 1 (within the first 600 chars) acts as the
 * Qimao/Heiyan/Dianzhong embedded-lead separator rather than a conflicting marker.
 */
function extractMarkers(lines) {
  const raw = lines
    .map((line, index) => ({ line: index + 1, marker: markerFor(line), text: line.trim() }))
    .filter((entry) => entry.marker)

  const outerStyle = ['chapter-heading', 'numeric-heading'].find(
    (style) => raw.filter((e) => e.marker.style === style).length >= 2
  )
  if (outerStyle) {
    const outerMarkers = raw.filter((e) => e.marker.style === outerStyle)
    const firstChLine = outerMarkers[0].line
    const secondChLine = outerMarkers[1].line
    // Exclude embedded lead separator `1.` inside Section 1, or inner `1.`..`N.` when chapter/numeric headings are outer split
    const nonOuter = raw.filter((e) => e.marker.style !== outerStyle)
    const allInnerZhihu = nonOuter.length > 0 && nonOuter.every((e) => e.marker.style === 'zhihu-numeric')
    if (allInnerZhihu) {
      const onlyLeadSep = nonOuter.length === 1 && nonOuter[0].text === '1.'
        && nonOuter[0].line > firstChLine && nonOuter[0].line < secondChLine
      const innerSeq = nonOuter.every((e, i) => Number(e.text.match(/\d+/)[0]) === i + 1)
      if (onlyLeadSep || innerSeq) return outerMarkers
    }
  }
  return raw
}

function isBareBookTitleLine(trimmed, index) {
  return index <= 2 && /^《[^》]{1,40}》$/.test(trimmed)
}

function detectLead(cleanLines, markers) {
  if (markers.length < 1) {
    return { placement: 'none', chars: 0, separator: null, separatorLine: null, leadText: '', sec1StartIdx: null }
  }
  const preLines = []
  for (let i = 0; i < markers[0].line - 1; i++) {
    const trimmed = cleanLines[i].trim()
    if (!trimmed || isStructuralNonProse(trimmed) || DIVIDER_LINE_RE.test(trimmed)) continue
    if (isBareBookTitleLine(trimmed, i) && preLines.length === 0) continue
    preLines.push(trimmed)
  }
  const preChars = visibleChars(preLines.join('\n'))
  if (preChars > 0) {
    return {
      placement: 'before-first-marker',
      chars: preChars,
      separator: markers[0].text,
      separatorLine: markers[0].line,
      leadText: preLines.join('\n'),
      sec1StartIdx: markers[0].line,
    }
  }

  // Qimao / Heiyan / Dianzhong: lead embedded at top of Section 1 before standalone `……` / `......` / `······` / `——` / `1.` / `1`,
  // OR ending a lead paragraph with inline `……` / `...` / `···` followed by Section 1 prose.
  const sec1End = markers.length >= 2 ? markers[1].line - 1 : cleanLines.length
  const hasLaterProse = (afterIdx) => {
    for (let j = afterIdx + 1; j < sec1End; j++) {
      const t = cleanLines[j].trim()
      if (t && !isStructuralNonProse(t) && !DIVIDER_LINE_RE.test(t)) return true
    }
    return false
  }
  let embeddedChars = 0
  let seenProse = false
  const embeddedLines = []
  for (let i = markers[0].line; i < sec1End; i++) {
    const trimmed = cleanLines[i].trim()
    if (!trimmed || isStructuralNonProse(trimmed)) continue
    if (seenProse && LEAD_SEP_RE.test(trimmed)) {
      return {
        placement: 'ch1-top-embedded',
        chars: embeddedChars,
        separator: trimmed,
        separatorLine: i + 1,
        leadText: embeddedLines.join('\n'),
        sec1StartIdx: i + 1,
      }
    }
    if (DIVIDER_LINE_RE.test(trimmed)) continue
    seenProse = true
    const inlineEnd = trimmed.match(INLINE_LEAD_END_RE)
    embeddedLines.push(trimmed)
    embeddedChars += visibleChars(trimmed)
    if (inlineEnd && embeddedChars > 0 && embeddedChars <= 600 && hasLaterProse(i)) {
      return {
        placement: 'ch1-top-embedded',
        chars: embeddedChars,
        separator: inlineEnd[0],
        separatorLine: null,
        leadText: embeddedLines.join('\n'),
        sec1StartIdx: i + 1,
      }
    }
    if (embeddedChars > 650) break
  }

  return { placement: 'none', chars: 0, separator: null, separatorLine: null, leadText: '', sec1StartIdx: null }
}

/**
 * Detect verbatim rewind between the lead and the first 400 visible chars of Section 1.
 * Strips whitespace & punctuation so quote/comma tweaks don't hide copy-paste repetition.
 */
function findLeadRewind(leadText, sec1HeadText, minRun = 12) {
  const leadNorm = Array.from(String(leadText || '').replace(/[^\p{L}\p{N}]+/gu, ''))
  const secNorm = Array.from(String(sec1HeadText || '').replace(/[^\p{L}\p{N}]+/gu, ''))
  if (leadNorm.length < minRun || secNorm.length < minRun) return null
  const leadStr = leadNorm.join('')
  const secStr = secNorm.join('')
  // Build index of minRun-grams in secStr for O(N) lookup, then extend matches greedily.
  const indexMap = new Map()
  for (let j = 0; j <= secNorm.length - minRun; j++) {
    const gram = secStr.slice(j, j + minRun)
    if (!indexMap.has(gram)) indexMap.set(gram, [])
    indexMap.get(gram).push(j)
  }
  let bestLen = 0
  let bestStart = -1
  for (let i = 0; i <= leadNorm.length - minRun; i++) {
    const gram = leadStr.slice(i, i + minRun)
    const hits = indexMap.get(gram)
    if (!hits) continue
    for (const j of hits) {
      let k = minRun
      while (i + k < leadNorm.length && j + k < secNorm.length && leadNorm[i + k] === secNorm[j + k]) {
        k++
      }
      if (k > bestLen) {
        bestLen = k
        bestStart = i
      }
    }
  }
  if (bestLen < minRun) return null
  const excerpt = leadNorm.slice(bestStart, Math.min(bestStart + bestLen, bestStart + 30)).join('')
  return { length: bestLen, excerpt }
}

function countNarrationEmDashes(bodyLines) {
  const speechRe = /(?:“[^”\n]*”|「[^」\n]*」|『[^』\n]*』|"[^"\n]*"|【[^】\n]*】)/g
  let count = 0
  for (const { line } of bodyLines) {
    if (DIVIDER_LINE_RE.test(line)) continue
    const narration = line.replace(speechRe, '')
    const matches = narration.match(/(?<!—)——(?!—)/g)
    if (matches) count += matches.length
  }
  return count
}

function detectPaywallSection(project) {
  for (const name of ['设定.md', '题材与大纲.md']) {
    const file = path.join(project, name)
    if (!fs.existsSync(file)) continue
    try {
      const text = fs.readFileSync(file, 'utf8')
      const match = text.match(/付费点\s*[：:]\s*第?\s*(\d+)\s*节/)
      if (match) return { section: Number(match[1]), source: name }
    } catch {
      // ignore unreadable optional file
    }
  }
  const outlineFile = path.join(project, '小节大纲.md')
  if (fs.existsSync(outlineFile)) {
    try {
      const lines = fs.readFileSync(outlineFile, 'utf8').split(/\r?\n/)
      let inTable = false
      let rowIndex = 0
      const hits = []
      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed.startsWith('|') || !trimmed.endsWith('|')) {
          if (inTable && rowIndex > 0) break
          continue
        }
        const cells = trimmed.slice(1, -1).split('|').map((c) => c.trim())
        if (!inTable) {
          if (cells[0] === '在全篇哪一段' || cells[0] === '结构段/五段功能') inTable = true
          continue
        }
        if (cells.every((c) => /^:?-{3,}:?$/.test(c))) continue
        rowIndex++
        if (/付费点/.test(trimmed)) hits.push(rowIndex)
      }
      if (hits.length === 1) return { section: hits[0], source: '小节大纲.md' }
    } catch {
      // ignore unreadable optional file
    }
  }
  return { section: null, source: null }
}

function detectTargetChars(project) {
  if (!project) return null
  for (const name of ['设定.md', '题材与大纲.md']) {
    const file = path.join(project, name)
    if (!fs.existsSync(file)) continue
    try {
      const text = fs.readFileSync(file, 'utf8')
      const match = text.match(/目标字数\s*[：:]\s*(\d+)(?:\s*[-–—~～]\s*(\d+))?/)
      if (match) {
        const low = Number(match[1])
        const high = match[2] ? Number(match[2]) : low
        if (low >= 1000 && high >= low) return Math.round((low + high) / 2)
      }
    } catch {
      // ignore unreadable optional file
    }
  }
  return null
}

function collectBodyLines(cleanLines, markers, lead) {
  const excludedLines = new Set(markers.map((entry) => entry.line - 1))
  if (lead.placement === 'ch1-top-embedded' && lead.separatorLine) {
    excludedLines.add(lead.separatorLine - 1)
  }
  return cleanLines
    .map((line, index) => ({ line: line.trim(), index }))
    .filter(({ line, index }) => (
      line !== ''
      && !excludedLines.has(index)
      && !isStructuralNonProse(line)
      && !DIVIDER_LINE_RE.test(line)
      && !isBareBookTitleLine(line, index)
    ))
}

function analyzeDialogue(bodyLines) {
  let quotedChars = 0
  let bracketChars = 0
  let dialogueSpans = 0
  let longDialogue45 = 0
  const speechRe = /(“[^”\n]*”|「[^」\n]*」|『[^』\n]*』|"[^"\n]*")|(【[^】\n]*】)/g
  for (const { line } of bodyLines) {
    const isPovHeader = POV_HEADER_LINE_RE.test(line)
    let m
    speechRe.lastIndex = 0
    while ((m = speechRe.exec(line)) !== null) {
      if (m[1]) {
        const len = visibleChars(m[1].slice(1, -1))
        quotedChars += len
        dialogueSpans++
        if (len >= 45) longDialogue45++
      } else if (m[2] && !isPovHeader) {
        bracketChars += visibleChars(m[2].slice(1, -1))
      }
    }
  }
  return {
    quotedChars,
    bracketChars,
    speechChars: quotedChars + bracketChars,
    dialogueSpans,
    longDialogue45,
    longDialogue45Ratio: dialogueSpans === 0 ? 0 : Number((longDialogue45 / dialogueSpans).toFixed(4)),
  }
}

function computeMedian(lengths) {
  if (lengths.length === 0) return 0
  const sorted = [...lengths].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  const median = sorted.length % 2 === 1 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
  return Number(median.toFixed(1))
}

function countSections(text, projectDir = null) {
  const lines = text.replace(/\r\n?/g, '\n').replace(/\n+$/, '\n').split('\n')
  const cleanLines = stripHtmlCommentsFromLines(lines)
  const markers = extractMarkers(lines)
  const lead = detectLead(cleanLines, markers)
  const bodyLines = collectBodyLines(cleanLines, markers, lead)

  const sections = markers.map((entry, index) => {
    const end = index + 1 < markers.length ? markers[index + 1].line - 1 : cleanLines.length
    const chars = visibleChars(cleanLines.slice(entry.line, end).join('\n'))
    return { section: index + 1, marker: entry.text, chars }
  })

  const paraLengths = bodyLines.map(({ line }) => visibleChars(line)).filter((len) => len > 0)
  const bodyChars = paraLengths.reduce((sum, len) => sum + len, 0)
  const medianParaChars = computeMedian(paraLengths)
  const dialogue = analyzeDialogue(bodyLines)

  const paywallInfo = projectDir ? detectPaywallSection(projectDir) : { section: null, source: null }
  const targetChars = projectDir ? detectTargetChars(projectDir) : null
  let paywallPreviewRatio = null
  if (paywallInfo.section !== null && paywallInfo.section >= 1 && paywallInfo.section <= markers.length && bodyChars > 0) {
    const endLineIdx = paywallInfo.section < markers.length ? markers[paywallInfo.section].line - 1 : cleanLines.length
    const cumBodyChars = bodyLines
      .filter(({ index }) => index < endLineIdx)
      .reduce((sum, { line }) => sum + visibleChars(line), 0)
    const denom = (targetChars && bodyChars < targetChars * 0.85) ? targetChars : bodyChars
    paywallPreviewRatio = Number((cumBodyChars / denom).toFixed(4))
  }

  const totalChars = visibleChars(text)
  const preMarkerLeadChars = lead.placement === 'before-first-marker' ? lead.chars : 0
  return {
    total_chars: totalChars,
    raw_visible_chars: totalChars,
    body_chars: bodyChars,
    lead_chars: lead.chars,
    lead_placement: lead.placement,
    pre_marker_lead_chars: preMarkerLeadChars,
    median_para_chars: medianParaChars,
    long_dialogue_45_ratio: dialogue.longDialogue45Ratio,
    paywall_preview_ratio: paywallPreviewRatio,
    section_count: sections.length,
    sections,
  }
}

function makeCheck(id, ok, evidence, expected, repair, severity = 'blocking') {
  return {
    id,
    ok,
    severity,
    file: '正文.md',
    evidence,
    expected,
    references: ['SKILL.md'],
    repair,
  }
}

function verify(projectDir, contract, options = {}) {
  const strict = Boolean(options && options.strict)
  const project = path.resolve(projectDir)
  const bodyFile = path.join(project, '正文.md')
  const bodyRead = readBody(bodyFile)
  const checks = []

  checks.push(makeCheck(
    'delivery.body-readable',
    bodyRead.ok,
    bodyRead.ok ? '正文.md 存在且非空' : (bodyRead.error || '正文.md 为空'),
    '项目目录下存在非空的 正文.md',
    '只补建或恢复 正文.md；不要改动设定与大纲。',
    'blocking'
  ))
  if (!bodyRead.ok) return report(project, contract, checks, { strict })

  const lines = bodyRead.text.replace(/\r\n?/g, '\n').replace(/\n+$/, '\n').split('\n')

  const placeholderLines = []
  lines.forEach((line, index) => {
    if (/\{[^}\n]*\}/.test(line)) placeholderLines.push(index + 1)
  })
  checks.push(makeCheck(
    'delivery.no-template-placeholders',
    placeholderLines.length === 0,
    placeholderLines.length ? `正文含未填写的 {} 占位符（行：${placeholderLines.join('、')}）` : '正文无未填写的 {} 占位符',
    '正文不得保留未填写的 {} 模板占位符',
    '只替换报告行中未填写的 {} 占位符，不改其余正文。',
    'blocking'
  ))

  const cleanLines = stripHtmlCommentsFromLines(lines)
  const markers = extractMarkers(lines)
  const leadInfo = detectLead(cleanLines, markers)
  const bodyLines = collectBodyLines(cleanLines, markers, leadInfo)
  const paraLengths = bodyLines.map(({ line }) => visibleChars(line)).filter((len) => len > 0)
  const bodyChars = paraLengths.reduce((sum, len) => sum + len, 0)

  const actual = visibleChars(bodyRead.text)
  const hardFloorChars = Math.ceil(contract.minChars * 0.5)
  const catastrophicUnderLength = actual < contract.minChars * 0.5
  const inRange = actual >= contract.minChars && actual <= contract.maxChars
  checks.push({
    ...makeCheck(
      'delivery.visible-chars',
      inRange,
      `非空白 Unicode 字符：${actual}（raw_visible_chars=${actual}，纯正文 body_chars=${bodyChars}）` + (catastrophicUnderLength ? `（不足下限 50%：${hardFloorChars}）` : ''),
      `用户要求 ${contract.minChars}-${contract.maxChars} 个非空白字符（硬底线 ≥ ${hardFloorChars}）`,
      catastrophicUnderLength
        ? '正文严重不足目标下限的一半，需补全缺失情节与场次后再交付。'
        : (actual < contract.minChars
          ? '复核字数：若需达标，只扩写既有情节点的行动、后果或对话，不新增支线；若确属合理收束可向作者说明。'
          : '复核字数：若需压缩，只删重复解释、复述和无功能过场，不删关键证据或结算。'),
      catastrophicUnderLength ? 'blocking' : 'advisory'
    ),
    actual_chars: actual,
    hard_floor_chars: hardFloorChars,
  })

  const sectionCounts = markers.map((entry, index) => {
    const end = index + 1 < markers.length ? markers[index + 1].line - 1 : cleanLines.length
    const count = visibleChars(cleanLines.slice(entry.line, end).join('\n'))
    return { section: index + 1, marker: entry.text, chars: count }
  })

  checks.push(makeCheck(
    'delivery.section-count',
    markers.length === contract.sections,
    `识别到 ${markers.length} 个小节标记：${markers.map((entry) => entry.text).join('、') || '无'}`,
    `建议正文为 ${contract.sections} 节`,
    '复核节数：若是漏标或多标小节标记则修正；若是创作中合理合节/分节且序号连贯，确认后可保留。',
    'advisory'
  ))

  if (contract.minSectionChars != null) {
    for (const [index, entry] of markers.entries()) {
      const count = sectionCounts[index].chars
      checks.push({
        ...makeCheck(
          'delivery.section-min-chars',
          count >= contract.minSectionChars,
          `${entry.text} 正文非空白 Unicode 字符：${count}`,
          `建议每节正文至少 ${contract.minSectionChars} 个非空白字符（不含小节标记）`,
          `复核第 ${index + 1} 节篇幅：若写得太赶，补足既有情节点的行动、后果或对话；若是有意快节奏短节，确认后可保留。`,
          'advisory'
        ),
        section: index + 1,
        actual_chars: count,
      })
    }
  }
  const styles = new Set(markers.map((entry) => entry.marker.style))
  checks.push(makeCheck(
    'delivery.section-style',
    markers.length > 0 && styles.size === 1,
    markers.length ? `小节标记样式：${Array.from(styles).join('、')}` : '没有可识别的小节标记',
    '建议全文统一使用 SKILL.md 允许的一种小节标记（###1. / ###第N章 / 1.）',
    '复核小节标记样式：一般应全文统一，只调整标记行，不改正文内容。',
    'advisory'
  ))

  const numericSequence = markers.map((entry) => {
    const match = entry.text.match(/\d+/)
    return match ? Number(match[0]) : null
  })
  const sequenceOk = markers.length > 0 && (
    numericSequence.every((number) => number !== null)
      ? numericSequence.every((number, index) => number === index + 1)
      : new Set(markers.map((entry) => entry.text)).size === markers.length
  )
  checks.push(makeCheck(
    'delivery.section-sequence',
    sequenceOk,
    `小节序列：${markers.map((entry) => entry.text).join('、') || '无'}`,
    '数字小节从 1 连续递增；中文章名不得重复',
    '只修正小节标记编号，不改正文内容。',
    'blocking'
  ))

  const markerLines = new Set(markers.map((entry) => entry.line - 1))
  const blankAllowedNeighbors = new Set(markerLines)
  lines.forEach((line, index) => {
    const trimmed = line.trim()
    if (LEAD_HEADING_RE.test(trimmed) || POV_HEADER_LINE_RE.test(trimmed)) {
      blankAllowedNeighbors.add(index)
    }
  })
  const invalidBlankLines = []
  for (let index = 0; index < lines.length; index++) {
    if (lines[index].trim() !== '') continue
    const isEdge = index === 0 || index === lines.length - 1
    const touchesAllowed = blankAllowedNeighbors.has(index - 1) || blankAllowedNeighbors.has(index + 1)
    if (!isEdge && !touchesAllowed) invalidBlankLines.push(index + 1)
  }
  checks.push(makeCheck(
    'delivery.blank-lines',
    invalidBlankLines.length === 0,
    invalidBlankLines.length ? `正文段落间空行：${invalidBlankLines.join('、')}` : '正文段落间无空行',
    '建议只允许文件边缘、小节标记、### 导语 或【XX视角】切镜标头相邻处出现空行，正文段落之间紧密单换行',
    '复核报告行的段间空行：按目标平台格式需要时删去多余空行，若平台或场景转场有意留白可保留。',
    'advisory'
  ))

  // 短篇竖屏结构健康度（全部仅 advisory，不设硬阻断）。
  let paraRhythmOk = true
  let paraRhythmEvidence = '正文无内容段落'
  if (paraLengths.length > 0) {
    const median = computeMedian(paraLengths)
    const over80Count = paraLengths.filter((len) => len > 80).length
    const over80Ratio = over80Count / paraLengths.length
    paraRhythmOk = median <= 30 && over80Ratio <= 0.03
    paraRhythmEvidence = `共 ${paraLengths.length} 段，段长中位 ${median} 字，>80 字段落 ${over80Count} 段（${(over80Ratio * 100).toFixed(1)}%）`
  }
  checks.push(makeCheck(
    'delivery.short-para-rhythm',
    paraRhythmOk,
    paraRhythmEvidence,
    '建议短篇段落中位 ≤30 字且 >80 字长段占比 ≤3%，贴合手机竖屏阅读节奏',
    '复核超长段落：把多动作/多信息混杂的长段按镜头或一句一段拆开；刻意长推理/古言抒情段可保留。',
    'advisory'
  ))

  let dialogueOk = true
  let dialogueEvidence = '正文不足 200 字，跳过对话占比检查'
  let longDialogueOk = true
  let longDialogueEvidence = '正文不足 200 字，跳过长对白占比检查'
  if (bodyChars >= 200) {
    const dial = analyzeDialogue(bodyLines)
    const dialogueRatio = dial.speechChars / bodyChars
    dialogueOk = dialogueRatio >= 0.15
    dialogueEvidence = dial.bracketChars > 0
      ? `引号内对话 ${dial.quotedChars} 字 +【】心声/弹幕 ${dial.bracketChars} 字（共 ${dial.speechChars} / ${bodyChars} 字，${(dialogueRatio * 100).toFixed(1)}%）`
      : `引号内对话 ${dial.quotedChars} / ${bodyChars} 字（${(dialogueRatio * 100).toFixed(1)}%）`
    if (dial.dialogueSpans >= 5) {
      longDialogueOk = dial.longDialogue45Ratio <= 0.35
      longDialogueEvidence = `长对白（≥45字）${dial.longDialogue45} / ${dial.dialogueSpans} 句（${(dial.longDialogue45Ratio * 100).toFixed(1)}%）`
    } else {
      longDialogueEvidence = `对话不足 5 句（${dial.dialogueSpans} 句），跳过长对白占比检查`
    }
  }
  checks.push(makeCheck(
    'delivery.short-dialogue-share',
    dialogueOk,
    dialogueEvidence,
    '建议常规短篇对话/心声弹幕占比 25%-35%（第一人称悬疑/吐槽独白流允许 15%-22%，软检底线 ≥15%）',
    '复核对话占比：常规题材若偏低且中段大段旁白转述冲突，改成当面对质或短促台词交锋；第一人称悬疑/吐槽独白流允许 15%-22%，更低时确认是否有意为之。',
    'advisory'
  ))
  checks.push(makeCheck(
    'delivery.short-long-dialogue',
    longDialogueOk,
    longDialogueEvidence,
    '建议短篇单句 ≥45 字长对白占比 ≤35%，避免人物一口气念诉状或白皮书式长演讲',
    '复核长对白：将超过 45 字的演讲式台词拆成一问一答短打，或在中间插入动作、打断与表情反应。',
    'advisory'
  ))

  let emDashOk = true
  let emDashEvidence = '正文不足 200 字，跳过旁白破折号检查'
  if (bodyChars >= 200) {
    const narrationEmDash = countNarrationEmDashes(bodyLines)
    const per10k = (narrationEmDash / bodyChars) * 10000
    emDashOk = narrationEmDash <= 2 || per10k <= 2
    emDashEvidence = `叙述旁白破折号「——」${narrationEmDash} 处（约 ${per10k.toFixed(1)} 处/万字）`
  }
  checks.push(makeCheck(
    'delivery.short-em-dash',
    emDashOk,
    emDashEvidence,
    '建议短篇叙述旁白破折号「——」≤2 处/万字（实测真人短篇中位 0 处/万字；对话打断不计）',
    '复核旁白破折号：将解释补充型「——」拆成两句短段或直接删去冗余解释，仅保留必要停顿。',
    'advisory'
  ))

  let leadOk = true
  let leadEvidence = '节数不足 2 节或无正文内容，跳过导语检查'
  if (markers.length >= 2 && bodyChars > 0) {
    const leadChars = leadInfo.chars
    leadOk = leadChars > 0 && leadChars <= 500
    if (leadChars === 0) {
      leadEvidence = '首个小节标记前缺少导语（0 字）'
    } else if (leadInfo.placement === 'ch1-top-embedded') {
      leadEvidence = `首节开头内嵌导语 ${leadChars} 字（分隔符：${leadInfo.separator}）`
    } else {
      leadEvidence = `首个小节标记前导语 ${leadChars} 字`
    }
  }
  checks.push(makeCheck(
    'delivery.short-lead-present',
    leadOk,
    leadEvidence,
    '建议多节短篇设置 1-500 字冷开场导语（知乎置于首节标记前；七猫/黑岩/点众可内嵌于首节开头至……/1.前）',
    '复核导语：若投稿平台需要冷开场导语，在首个小节标记前或首节开头补 150-300 字导语（或压短过长导语）；刻意直入第 1 节可保留。',
    'advisory'
  ))

  // 导语与第 1 节首 400 字零倒带复述检测（advisory，不阻断正常承接）。
  let rewindOk = true
  let rewindEvidence = '无导语或第 1 节正文，跳过导语倒带检查'
  if (leadInfo.chars > 0 && leadInfo.sec1StartIdx !== null && markers.length >= 1) {
    const sec1End = markers.length >= 2 ? markers[1].line - 1 : cleanLines.length
    const sec1HeadLines = []
    let collected = 0
    for (let i = leadInfo.sec1StartIdx; i < sec1End && collected < 400; i++) {
      const trimmed = cleanLines[i].trim()
      if (!trimmed || isStructuralNonProse(trimmed) || DIVIDER_LINE_RE.test(trimmed)) continue
      sec1HeadLines.push(trimmed)
      collected += visibleChars(trimmed)
    }
    const sec1HeadText = Array.from(sec1HeadLines.join('\n')).slice(0, 480).join('')
    const rewind = findLeadRewind(leadInfo.leadText, sec1HeadText, 12)
    if (rewind) {
      rewindOk = false
      rewindEvidence = `导语与第 1 节首 400 字存在 ${rewind.length} 字连续原句倒带复述（「${rewind.excerpt}」）`
    } else {
      rewindEvidence = '导语与第 1 节首 400 字零连续原句倒带'
    }
  }
  checks.push(makeCheck(
    'delivery.short-lead-rewind',
    rewindOk,
    rewindEvidence,
    '建议导语与第 1 节首 400 字零秒续接，避免连续 ≥12 字原句倒带复述',
    '删去第 1 节开头复述导语的原句，改用刀口微距接拍、冷吐槽撕局、赌注扩容或微细节秒验零秒续接。',
    'advisory'
  ))

  // 实际付费卡点累计正文占比（纯 advisory，不阻断正常交付）。
  const paywallInfo = detectPaywallSection(project)
  let paywallRatioOk = true
  let paywallRatioEvidence = '未声明付费卡点节，跳过实际付费点字数占比检查'
  if (paywallInfo.section !== null && markers.length >= 2 && bodyChars > 0) {
    if (paywallInfo.section < 1 || paywallInfo.section > markers.length) {
      paywallRatioOk = false
      paywallRatioEvidence = `${paywallInfo.source} 声明付费点在第 ${paywallInfo.section} 节，但正文仅识别到 ${markers.length} 节`
    } else {
      const endLineIdx = paywallInfo.section < markers.length ? markers[paywallInfo.section].line - 1 : cleanLines.length
      const cumBodyChars = bodyLines
        .filter(({ index }) => index < endLineIdx)
        .reduce((sum, { line }) => sum + visibleChars(line), 0)
      const ratio = Number((cumBodyChars / bodyChars).toFixed(4))
      paywallRatioOk = ratio >= 0.30 && ratio <= 0.45
      paywallRatioEvidence = `${paywallInfo.source} 声明付费点第 ${paywallInfo.section} 节末：实际累计正文 ${cumBodyChars} / ${bodyChars} 字（${(ratio * 100).toFixed(1)}%）`
    }
  }
  checks.push(makeCheck(
    'delivery.short-paywall-ratio',
    paywallRatioOk,
    paywallRatioEvidence,
    '建议付费卡点节末累计实际正文落在全文 30%–45% 区间（知乎盐言中位约 38%）',
    '复核免费段篇幅：偏高时压缩前段铺垫或前移卡点，偏低时补足前段赌注；若属意难平/死人文学蓄压轨可确认保留。',
    'advisory'
  ))

  return report(project, contract, checks, {
    strict,
    sectionCounts,
    leadChars: leadInfo.chars,
    leadPlacement: leadInfo.placement,
    totalChars: actual,
    bodyChars,
    rawVisibleChars: actual,
  })
}

function toScopeItem(item) {
  return {
    id: item.id,
    severity: item.severity,
    file: item.file,
    evidence: item.evidence,
    expected: item.expected,
    references: item.references,
    repair: item.repair,
    ...(item.section === undefined ? {} : { section: item.section, actual_chars: item.actual_chars }),
    ...(item.section === undefined && item.actual_chars !== undefined ? { actual_chars: item.actual_chars } : {}),
  }
}

function report(project, contract, checks, options = {}) {
  const strict = Boolean(options && options.strict)
  const hardFailures = checks.filter((check) => !check.ok && check.severity === 'blocking')
  const softWarnings = checks.filter((check) => !check.ok && check.severity === 'advisory')
  const findings = [...hardFailures, ...softWarnings]
  const failures = strict ? findings : hardFailures
  return {
    schema_version: 1,
    verifier: 'story-short-write.delivery-contract',
    scope: 'delivery',
    project,
    strict,
    contract: {
      metric: 'non_whitespace_unicode_chars_v1',
      min_chars: contract.minChars,
      max_chars: contract.maxChars,
      sections: contract.sections,
      min_section_chars: contract.minSectionChars ?? null,
    },
    ...(options.sectionCounts ? {
      total_chars: options.totalChars ?? 0,
      raw_visible_chars: options.rawVisibleChars ?? 0,
      body_chars: options.bodyChars ?? 0,
      lead_chars: options.leadChars ?? 0,
      lead_placement: options.leadPlacement ?? 'none',
      section_counts: options.sectionCounts,
    } : {}),
    ok: failures.length === 0,
    status: failures.length > 0 ? 'fail' : (softWarnings.length > 0 ? 'warn' : 'pass'),
    checks,
    hard_failures: hardFailures,
    soft_warnings: softWarnings,
    findings,
    failures,
    advisories: softWarnings,
    repair_scope: failures.map(toScopeItem),
    review_scope: softWarnings.map(toScopeItem),
  }
}

function parsePositiveInteger(value) {
  if (!/^[1-9]\d*$/.test(value || '')) return null
  const number = Number(value)
  return Number.isSafeInteger(number) ? number : null
}

function parseArgs(argv) {
  const values = {}
  const positional = []
  let strict = false
  let counts = false
  let json = false
  for (let index = 0; index < argv.length; index++) {
    const arg = argv[index]
    if (arg === '--json') { json = true; continue }
    if (arg === '--check-contract') continue
    if (arg === '--strict') { strict = true; continue }
    if (arg === '--counts') { counts = true; continue }
    if (['--min-chars', '--max-chars', '--sections', '--min-section-chars'].includes(arg)) {
      if (index + 1 >= argv.length || argv[index + 1].startsWith('--')) return null
      values[arg] = parsePositiveInteger(argv[++index])
      if (values[arg] === null) return null
      continue
    }
    if (arg.startsWith('--')) return null
    positional.push(arg)
  }
  if (positional.length > 1) return null
  if (counts) {
    return {
      mode: 'counts',
      json,
      target: positional[0] || '.',
    }
  }
  if (!values['--min-chars'] || !values['--max-chars'] || !values['--sections']) return null
  if (values['--min-chars'] > values['--max-chars']) return null
  // The shortest allowed markers are 1., 2., ...; they count even without a body floor.
  const sections = values['--sections']
  let minimum = sections * ((values['--min-section-chars'] ?? 0) + 1)
  for (let start = 1; start <= sections; start *= 10) minimum += sections - start + 1
  if (minimum > values['--max-chars']) return null
  return {
    mode: 'verify',
    json,
    project: positional[0] || '.',
    strict,
    contract: {
      minChars: values['--min-chars'],
      maxChars: values['--max-chars'],
      sections: values['--sections'],
      minSectionChars: values['--min-section-chars'] ?? null,
    },
  }
}

const USAGE = '用法: node scripts/check-delivery-contract.js --json [--strict] --min-chars N --max-chars N --sections N [--min-section-chars N] [--check-contract] [project-dir]\n      node scripts/check-delivery-contract.js --counts [--json] [project-dir-or-file]\n说明: --check-contract 仅在写前校验参数契约（body_verified=false），终稿验收请去掉 --check-contract 运行。\n'

function runCounts(target, asJson) {
  const resolved = path.resolve(target)
  const filePath = (fs.existsSync(resolved) && fs.statSync(resolved).isFile())
    ? resolved
    : path.join(resolved, '正文.md')
  const bodyRead = readBody(filePath)
  if (!bodyRead.ok) {
    const msg = bodyRead.error || '正文.md 为空'
    if (asJson) {
      process.stdout.write(`${JSON.stringify({ ok: false, file: filePath, error: msg }, null, 2)}\n`)
    } else {
      process.stderr.write(`读取失败: ${msg}\n`)
    }
    return 1
  }
  const projectDir = (fs.existsSync(resolved) && fs.statSync(resolved).isFile())
    ? path.dirname(resolved)
    : resolved
  const result = countSections(bodyRead.text, projectDir)
  if (asJson) {
    process.stdout.write(`${JSON.stringify({ ok: true, file: filePath, ...result }, null, 2)}\n`)
  } else {
    if (result.lead_chars > 0) {
      const label = result.lead_placement === 'ch1-top-embedded' ? '导语(首节内嵌)' : '导语'
      process.stdout.write(`${label} ${result.lead_chars}\n`)
    }
    for (const sec of result.sections) {
      process.stdout.write(`${sec.marker} ${sec.chars}\n`)
    }
    process.stdout.write(`总计 ${result.total_chars}\n`)
  }
  return 0
}

function main(argv) {
  if (argv.includes('--help') || argv.includes('-h')) {
    process.stdout.write(USAGE)
    return 0
  }
  const parsed = parseArgs(argv)
  if (!parsed) {
    process.stderr.write(`参数缺失或范围不可同时满足。${USAGE}`)
    return 2
  }
  if (parsed.mode === 'counts') {
    return runCounts(parsed.target, parsed.json)
  }
  const result = argv.includes('--check-contract')
    ? {
      ...report(path.resolve(parsed.project), parsed.contract, [], { strict: parsed.strict }),
      scope: 'parameters-only',
      body_verified: false,
      note: '--check-contract 仅校验参数契约，未扫描 正文.md；终稿验收请去掉 --check-contract 运行。',
    }
    : { ...verify(parsed.project, parsed.contract, { strict: parsed.strict }), body_verified: true }
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`)
  return result.ok ? 0 : 1
}

if (require.main === module) process.exitCode = main(process.argv.slice(2))

module.exports = {
  markerFor,
  visibleChars,
  extractMarkers,
  detectLead,
  findLeadRewind,
  countNarrationEmDashes,
  countSections,
  verify,
}
