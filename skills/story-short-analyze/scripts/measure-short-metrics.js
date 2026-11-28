#!/usr/bin/env node
/**
 * Deterministic prose & vertical-screen web-feel metrics calculator for story-short-analyze.
 *
 * Zero external dependencies. Computes objective metrics for the 9-item
 * 「量化网感体检表」 and `_meta.json.voice_metrics` so the analyst never guesses.
 *
 * Usage:
 *   node scripts/measure-short-metrics.js [--json] [--markdown] [--paywall-section N] <file-path>
 *
 * Exit: 0 = ok, 1 = file read error, 2 = invalid arguments.
 */

'use strict'

const fs = require('fs')
const path = require('path')

const CHAPTER_HEADING_RE = /^###\s*第[一二三四五六七八九十百千万两〇零0-9]+[章节回](?:[\s\u3000].{0,40})?$/
const NUMERIC_HEADING_RE = /^###\s*\d+\.?$/
const MD_SUBHEADING_RE = /^###\s*[^\s#].{0,40}$/
const PLAIN_CHAPTER_RE = /^第[一二三四五六七八九十百千万两〇零0-9]+[章节回](?:[\s\u3000].{0,30})?$/
const CN_NUMERIC_RE = /^([一二三四五六七八九十百]+)[、.．](?:\s*.{0,30})?$/
const DOT_NUMERIC_RE = /^(\d{1,2})\.$/
const BARE_NUMERIC_RE = /^(\d{1,2})$/
const LEAD_SEP_RE = /^(?:(?:…\s*){2,}|(?:\.\s*){3,}|(?:·\s*){3,}|[—\-]{2,}|0?1\.?)$/
const INLINE_LEAD_END_RE = /(?:…{2,}|\.{3,}|·{3,})$/
const DIVIDER_LINE_RE = /^(?:[—\-]{2,}|(?:…\s*){2,}|(?:\.\s*){3,}|(?:·\s*){3,}|[*_=~]{3,})$/
const STRUCTURAL_LINE_RE = /^#{1,6}(?:\s|\S)|^-{3,}$|^[*_=~]{3,}$/
const POV_HEADER_LINE_RE = /^\s*【[^】]{1,20}(?:视角|番外|后记|尾声)(?:[（(][^）)】]{1,16}[）)])?】\s*$/

function visibleChars(text) {
  return Array.from(String(text || '')).filter((ch) => !/\s/u.test(ch)).length
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

function normalizeText(raw) {
  return String(raw || '')
    .replace(/^\uFEFF/, '')
    .replace(/\r\n?/g, '\n')
    .replace(/<br\s*\/?>/gi, '\n')
}

function isSequentialNumeric(candidates) {
  if (candidates.length < 2) return false
  let prev = 0
  let hits = 0
  for (const item of candidates) {
    if (item.num === prev + 1) {
      hits++
      prev = item.num
    } else if (item.num > prev && item.num <= prev + 2) {
      prev = item.num
    }
  }
  return hits >= Math.max(1, Math.floor(candidates.length * 0.6))
}

function detectSections(cleanLines) {
  const groups = {
    'chapter-heading': [],
    'numeric-heading': [],
    'md-subheading': [],
    'plain-chapter': [],
    'cn-numeric': [],
    'dot-numeric': [],
    'bare-numeric': [],
  }

  cleanLines.forEach((raw, index) => {
    const s = raw.trim()
    if (!s) return
    if (CHAPTER_HEADING_RE.test(s)) {
      groups['chapter-heading'].push({ line: index + 1, marker: s, style: 'chapter-heading' })
    } else if (NUMERIC_HEADING_RE.test(s)) {
      groups['numeric-heading'].push({ line: index + 1, marker: s, style: 'numeric-heading' })
    } else if (MD_SUBHEADING_RE.test(s)) {
      groups['md-subheading'].push({ line: index + 1, marker: s, style: 'md-subheading' })
    } else if (PLAIN_CHAPTER_RE.test(s)) {
      groups['plain-chapter'].push({ line: index + 1, marker: s, style: 'plain-chapter' })
    } else if (CN_NUMERIC_RE.test(s)) {
      groups['cn-numeric'].push({ line: index + 1, marker: s, style: 'cn-numeric' })
    } else {
      const dm = s.match(DOT_NUMERIC_RE)
      if (dm) {
        groups['dot-numeric'].push({ line: index + 1, marker: s, style: 'zhihu-numeric', num: Number(dm[1]) })
      } else {
        const bm = s.match(BARE_NUMERIC_RE)
        if (bm && Number(bm[1]) >= 1 && Number(bm[1]) <= 60) {
          groups['bare-numeric'].push({ line: index + 1, marker: s, style: 'bare-numeric', num: Number(bm[1]) })
        }
      }
    }
  })

  const validDot = isSequentialNumeric(groups['dot-numeric']) ? groups['dot-numeric'] : []
  const validBare = isSequentialNumeric(groups['bare-numeric']) ? groups['bare-numeric'] : []
  const innerNumeric = validDot.length >= validBare.length ? validDot : validBare

  let primary = []
  let style = 'none'
  let dualNumbering = { detected: false, outer_count: 0, inner_count: 0 }

  if (groups['chapter-heading'].length >= 2) {
    primary = groups['chapter-heading']
    style = 'chapter-heading'
    if (innerNumeric.length >= 2) {
      dualNumbering = {
        detected: true,
        outer_count: primary.length,
        inner_count: innerNumeric.length,
      }
    }
  } else if (groups['numeric-heading'].length >= 2) {
    primary = groups['numeric-heading']
    style = 'numeric-heading'
  } else if (groups['md-subheading'].length >= 2) {
    primary = groups['md-subheading']
    style = 'md-subheading'
    if (innerNumeric.length >= 2) {
      dualNumbering = {
        detected: true,
        outer_count: primary.length,
        inner_count: innerNumeric.length,
      }
    }
  } else if (groups['plain-chapter'].length >= 2) {
    primary = groups['plain-chapter']
    style = 'plain-chapter'
    if (innerNumeric.length >= 2) {
      dualNumbering = {
        detected: true,
        outer_count: primary.length,
        inner_count: innerNumeric.length,
      }
    }
  } else if (groups['cn-numeric'].length >= 2) {
    primary = groups['cn-numeric']
    style = 'cn-numeric'
  } else if (innerNumeric.length >= 2) {
    primary = innerNumeric
    style = innerNumeric[0].style
  } else if (groups['chapter-heading'].length === 1) {
    primary = groups['chapter-heading']
    style = 'chapter-heading'
  } else if (groups['numeric-heading'].length === 1) {
    primary = groups['numeric-heading']
    style = 'numeric-heading'
  } else if (groups['md-subheading'].length === 1) {
    primary = groups['md-subheading']
    style = 'md-subheading'
  } else if (groups['plain-chapter'].length === 1) {
    primary = groups['plain-chapter']
    style = 'plain-chapter'
  }

  return { markers: primary, style, dualNumbering, innerNumeric }
}

function isProseLine(trimmed, markerLineSet) {
  if (!trimmed) return false
  if (STRUCTURAL_LINE_RE.test(trimmed)) return false
  if (DIVIDER_LINE_RE.test(trimmed)) return false
  if (markerLineSet && markerLineSet.has(trimmed)) return false
  return true
}

function detectLead(cleanLines, markers) {
  const scanEmbedded = (startIdx, endIdx) => {
    const hasLaterProse = (afterIdx) => {
      for (let j = afterIdx + 1; j < endIdx; j++) {
        const t = cleanLines[j].trim()
        if (t && !STRUCTURAL_LINE_RE.test(t) && !DIVIDER_LINE_RE.test(t)) return true
      }
      return false
    }
    let chars = 0
    let seenProse = false
    for (let i = startIdx; i < endIdx; i++) {
      const s = cleanLines[i].trim()
      if (!s) continue
      if (STRUCTURAL_LINE_RE.test(s)) continue
      if (seenProse && LEAD_SEP_RE.test(s)) {
        if (chars > 0 && chars <= 600) {
          return {
            placement: 'ch1-top-embedded',
            chars,
            separator: s,
            separator_line: i + 1,
          }
        }
        return null
      }
      if (DIVIDER_LINE_RE.test(s)) continue
      seenProse = true
      const inlineEnd = s.match(INLINE_LEAD_END_RE)
      chars += visibleChars(s)
      if (inlineEnd && chars > 0 && chars <= 600 && hasLaterProse(i)) {
        return {
          placement: 'ch1-top-embedded',
          chars,
          separator: inlineEnd[0],
          separator_line: null,
        }
      }
      if (chars > 650) break
    }
    return null
  }

  if (markers.length >= 1) {
    // 1) Check before first section marker (Zhihu style)
    const preLines = []
    for (let i = 0; i < markers[0].line - 1; i++) {
      const s = cleanLines[i].trim()
      if (!s || STRUCTURAL_LINE_RE.test(s) || DIVIDER_LINE_RE.test(s)) continue
      // Skip bare book title line like 《书名》 on line 1 when followed by nothing else
      if (/^《[^》]{1,40}》$/.test(s) && preLines.length === 0) continue
      preLines.push(s)
    }
    const preChars = visibleChars(preLines.join('\n'))
    if (preChars > 0) {
      return {
        placement: 'before-first-marker',
        chars: preChars,
        separator: markers[0].marker,
        separator_line: markers[0].line,
      }
    }

    // 2) Check Ch1-top embedded lead before …… / ...... / —— / 1. / 1 (Qimao / Heiyan / Dianzhong)
    const sec1End = markers.length >= 2 ? markers[1].line - 1 : cleanLines.length
    const embedded = scanEmbedded(markers[0].line, sec1End)
    if (embedded) return embedded
  } else {
    const embedded = scanEmbedded(0, cleanLines.length)
    if (embedded) return embedded
  }

  return { placement: 'none', chars: 0, separator: null, separator_line: null }
}

function isSingleSentencePara(line) {
  // Count sentence-ending punctuation (plus any immediately trailing closing quotes/brackets)
  // that is still followed by non-closing prose content.
  const cleaned = line.trim()
  if (!cleaned) return false
  const matches = cleaned.match(/[。！？!?]+[”’」』"'）】]*(?=[^\s”’」』"'）】])/g)
  return !matches || matches.length === 0
}

const ONOMATOPOEIA_EM_DASH_RE = /^[砰咚轰哐啪嘭呼呜嗡吱嘎叮铛滋哗噼啪哗啦咔嚓]+——[！？。]?$/

function countNarrationEmDashes(proseLines) {
  const speechRe = /(?:“[^”\n]*”|「[^」\n]*」|『[^』\n]*』|"[^"\n]*"|【[^】\n]*】)/g
  let count = 0
  for (const line of proseLines) {
    if (DIVIDER_LINE_RE.test(line)) continue
    if (ONOMATOPOEIA_EM_DASH_RE.test(line.trim())) continue
    const narration = line.replace(speechRe, '')
    const matches = narration.match(/(?<!—)——(?!—)/g)
    if (matches) count += matches.length
  }
  return count
}

function measureShortMetrics(rawText, filePath = null, options = {}) {
  const paywallSection = options && options.paywallSection !== undefined ? options.paywallSection : null
  const normalized = normalizeText(rawText)
  const rawLines = normalized.split('\n')
  const cleanLines = stripHtmlCommentsFromLines(rawLines)

  const { markers, style, dualNumbering, innerNumeric } = detectSections(cleanLines)
  const lead = detectLead(cleanLines, markers)

  const markerLineIndices = new Set(markers.map((m) => m.line - 1))
  // If dual numbering exists (e.g. Heiyan ###第1章 + inner 1. 2.), also exclude inner numeric marker lines from prose stats
  if (dualNumbering.detected) {
    for (const m of innerNumeric) markerLineIndices.add(m.line - 1)
  }
  if (lead.separator_line && lead.placement === 'ch1-top-embedded') {
    markerLineIndices.add(lead.separator_line - 1)
  }

  // Per-section char counts (excluding section marker line itself and divider lines)
  const sections = markers.map((entry, idx) => {
    const start = entry.line
    const end = idx + 1 < markers.length ? markers[idx + 1].line - 1 : cleanLines.length
    let chars = 0
    for (let i = start; i < end; i++) {
      if (markerLineIndices.has(i)) continue
      const s = cleanLines[i].trim()
      if (!s || STRUCTURAL_LINE_RE.test(s) || DIVIDER_LINE_RE.test(s)) continue
      chars += visibleChars(s)
    }
    return { index: idx + 1, marker: entry.marker, line: entry.line, chars }
  })

  const firstSectionChars = sections.length > 0 ? sections[0].chars : null
  const subsequentSections = sections.slice(1)
  const subsequentAvgChars = subsequentSections.length > 0
    ? Math.round(subsequentSections.reduce((sum, s) => sum + s.chars, 0) / subsequentSections.length)
    : null

  // Collect prose paragraphs (retain original line index so paywall cumulative cutoff matches check-delivery-contract.js)
  const proseEntries = []
  cleanLines.forEach((raw, idx) => {
    if (markerLineIndices.has(idx)) return
    const s = raw.trim()
    if (!s || STRUCTURAL_LINE_RE.test(s) || DIVIDER_LINE_RE.test(s)) return
    if (idx <= 2 && /^《[^》]{1,40}》$/.test(s)) return
    proseEntries.push({ idx, line: s })
  })
  const proseLines = proseEntries.map((entry) => entry.line)

  const rawVisibleChars = visibleChars(normalized)
  const paraLengths = proseLines.map((line) => visibleChars(line)).filter((n) => n > 0)
  const bodyChars = paraLengths.reduce((sum, n) => sum + n, 0)

  const sortedLengths = [...paraLengths].sort((a, b) => a - b)
  const mid = Math.floor(sortedLengths.length / 2)
  const medianParaChars = sortedLengths.length === 0
    ? 0
    : (sortedLengths.length % 2 === 1
      ? sortedLengths[mid]
      : Number(((sortedLengths[mid - 1] + sortedLengths[mid]) / 2).toFixed(1)))
  const meanParaChars = paraLengths.length === 0 ? 0 : Number((bodyChars / paraLengths.length).toFixed(1))
  const maxParaChars = sortedLengths.length === 0 ? 0 : sortedLengths[sortedLengths.length - 1]
  const shortPara30Count = paraLengths.filter((n) => n <= 30).length
  const shortPara30Ratio = paraLengths.length === 0 ? 0 : Number((shortPara30Count / paraLengths.length).toFixed(4))
  const longPara80Count = paraLengths.filter((n) => n > 80).length
  const longPara80Ratio = paraLengths.length === 0 ? 0 : Number((longPara80Count / paraLengths.length).toFixed(4))

  const singleSentenceCount = proseLines.filter(isSingleSentencePara).length
  const singleSentenceRate = proseLines.length === 0 ? 0 : Number((singleSentenceCount / proseLines.length).toFixed(4))

  // Dialogue & quote style & first dialogue char offset
  const speechRe = /(“[^”\n]*”|「[^」\n]*」|『[^』\n]*』|"[^"\n]*")|(【[^】\n]*】)/g
  let quotedChars = 0
  let bracketChars = 0
  let dialogueSpans = 0
  let shortDialogue15 = 0
  let longDialogue45 = 0
  let curlyCount = 0
  let cornerCount = 0
  let cornerShortCount = 0
  let straightCount = 0
  let firstDialogueChar = null
  let runningChars = 0

  for (const line of proseLines) {
    const isPovHeader = POV_HEADER_LINE_RE.test(line)
    speechRe.lastIndex = 0
    let m
    while ((m = speechRe.exec(line)) !== null) {
      if (m[1]) {
        const span = m[1]
        const inner = span.slice(1, -1)
        const len = visibleChars(inner)
        if (firstDialogueChar === null && len > 0) {
          firstDialogueChar = runningChars + visibleChars(line.slice(0, m.index)) + 1
        }
        quotedChars += len
        dialogueSpans++
        if (len <= 15) shortDialogue15++
        if (len >= 45) longDialogue45++
        if (span.startsWith('“')) curlyCount++
        else if (span.startsWith('「') || span.startsWith('『')) {
          cornerCount++
          if (len <= 10) cornerShortCount++
        } else if (span.startsWith('"')) straightCount++
      } else if (m[2] && !isPovHeader) {
        bracketChars += visibleChars(m[2].slice(1, -1))
      }
    }
    runningChars += visibleChars(line)
  }

  const speechChars = quotedChars + bracketChars
  const dialogueRatio = bodyChars === 0 ? 0 : Number((speechChars / bodyChars).toFixed(4))
  const shortDialogue15Ratio = dialogueSpans === 0 ? 0 : Number((shortDialogue15 / dialogueSpans).toFixed(4))
  const longDialogue45Ratio = dialogueSpans === 0 ? 0 : Number((longDialogue45 / dialogueSpans).toFixed(4))

  let quoteStyle = 'none'
  // Occasional short corner-bracket titles/captions (e.g. 「东方小贝多芬」) inside curly-quote prose
  // should not flip quote_style to `mixed` when curly quotes dominate.
  const effectiveCornerCount = curlyCount >= 3 && cornerCount - cornerShortCount === 0 && cornerShortCount <= 2
    ? 0
    : cornerCount
  const totalQuotes = curlyCount + effectiveCornerCount + straightCount
  if (totalQuotes > 0) {
    if (curlyCount / totalQuotes >= 0.85) quoteStyle = 'curly (“”)'
    else if (effectiveCornerCount / totalQuotes >= 0.85) quoteStyle = 'corner (「」)'
    else if (straightCount / totalQuotes >= 0.85) quoteStyle = 'straight ("")'
    else quoteStyle = 'mixed'
  }

  // POV detection (outside quoted dialogue)
  let narrationChars = 0
  let firstPersonCount = 0
  let thirdPersonCount = 0
  for (const line of proseLines) {
    const narration = line.replace(speechRe, '')
    narrationChars += visibleChars(narration)
    firstPersonCount += (narration.match(/我/g) || []).length
    thirdPersonCount += (narration.match(/[他她]/g) || []).length
  }
  const firstPersonPerK = narrationChars === 0 ? 0 : Number(((firstPersonCount / narrationChars) * 1000).toFixed(2))
  const pov = firstPersonPerK >= 6 || (firstPersonCount >= 10 && firstPersonCount >= thirdPersonCount * 0.6)
    ? '第一人称「我」'
    : '第三人称'

  // Punctuation density (exclude 【】 danmu/bracket exclamations from body narration/dialogue rate)
  const fullProse = proseLines.join('\n')
  const bracketSpans = fullProse.match(/【[^】\n]*】/g) || []
  const bracketExclamationCount = bracketSpans.reduce((sum, s) => sum + ((s.match(/[！!]/g) || []).length), 0)
  const proseWithoutBrackets = fullProse.replace(/【[^】\n]*】/g, '')
  const exclamationCount = (proseWithoutBrackets.match(/[！!]/g) || []).length
  const questionCount = (fullProse.match(/[？?]/g) || []).length
  const ellipsisCount = (fullProse.match(/……|\.{6}|\.{3,}/g) || []).length
  const emDashNarrationCount = countNarrationEmDashes(proseLines)

  const perK = (n) => (bodyChars === 0 ? 0 : Number(((n / bodyChars) * 1000).toFixed(2)))
  const per10k = (n) => (bodyChars === 0 ? 0 : Number(((n / bodyChars) * 10000).toFixed(2)))

  let paywall = null
  let paywallCharRatio = null
  if (paywallSection !== null) {
    const valid = Number.isInteger(paywallSection) && paywallSection >= 1 && paywallSection <= markers.length
    if (valid && bodyChars > 0) {
      const endLineIdx = paywallSection < markers.length ? markers[paywallSection].line - 1 : cleanLines.length
      const cumChars = proseEntries
        .filter(({ idx }) => idx < endLineIdx)
        .reduce((sum, { line }) => sum + visibleChars(line), 0)
      paywallCharRatio = Number((cumChars / bodyChars).toFixed(4))
      paywall = {
        section: paywallSection,
        valid: true,
        cumulative_chars: cumChars,
        char_ratio: paywallCharRatio,
      }
    } else {
      paywall = {
        section: paywallSection,
        valid: false,
        cumulative_chars: null,
        char_ratio: null,
      }
    }
  }

  return {
    schema_version: 1,
    file: filePath ? path.resolve(filePath) : null,
    total_chars: bodyChars,
    raw_visible_chars: rawVisibleChars,
    section_count: sections.length,
    section_style: style,
    dual_numbering: dualNumbering,
    first_section_chars: firstSectionChars,
    subsequent_avg_chars: subsequentAvgChars,
    sections,
    ...(paywall ? { paywall, paywall_char_ratio: paywallCharRatio } : {}),
    lead: {
      placement: lead.placement,
      chars: lead.chars,
      separator: lead.separator,
    },
    paragraphs: {
      count: paraLengths.length,
      median_chars: medianParaChars,
      mean_chars: meanParaChars,
      max_chars: maxParaChars,
      short_30_count: shortPara30Count,
      short_30_ratio: shortPara30Ratio,
      over_80_count: longPara80Count,
      over_80_ratio: longPara80Ratio,
      single_sentence_rate: singleSentenceRate,
    },
    dialogue: {
      quoted_chars: quotedChars,
      bracket_chars: bracketChars,
      speech_chars: speechChars,
      ratio: dialogueRatio,
      spans: dialogueSpans,
      short_15_ratio: shortDialogue15Ratio,
      long_45_ratio: longDialogue45Ratio,
      quote_style: quoteStyle,
      first_dialogue_char: firstDialogueChar,
    },
    pov: {
      label: pov,
      first_person_narration_count: firstPersonCount,
      first_person_per_k: firstPersonPerK,
    },
    punctuation: {
      exclamation_count: exclamationCount,
      bracket_exclamation_count: bracketExclamationCount,
      question_count: questionCount,
      exclamation_per_k: perK(exclamationCount),
      question_per_k: perK(questionCount),
      exclaim_question_per_k: perK(exclamationCount + questionCount),
      em_dash_narration_count: emDashNarrationCount,
      em_dash_narration_per_10k: per10k(emDashNarrationCount),
      ellipsis_count: ellipsisCount,
      ellipsis_per_k: perK(ellipsisCount),
    },
    voice_metrics_skeleton: {
      median_para_chars: Math.round(medianParaChars),
      single_sentence_para_rate: singleSentenceRate,
      dialogue_ratio: dialogueRatio,
      first_dialogue_char: firstDialogueChar,
      hook_rate: null,
      ending_type: null,
    },
  }
}

function pct(ratio) {
  return `${(ratio * 100).toFixed(1)}%`
}

function formatMarkdownTable(m) {
  const secSummary = m.section_count > 0
    ? `共 ${m.section_count} 节（第1节 ${m.first_section_chars} 字 / 后续均 ${m.subsequent_avg_chars ?? '-'} 字）`
    : '无显式分节标记'
  const dualNote = m.dual_numbering.detected
    ? `含双编号（外层 ${m.dual_numbering.outer_count} / 内层 ${m.dual_numbering.inner_count}）`
    : (m.section_count > 1 && m.first_section_chars > (m.subsequent_avg_chars || 0) * 1.15 ? '首节偏长' : '体量均衡')
  const leadNote = m.lead.placement === 'before-first-marker'
    ? `首节前独立导语 ${m.lead.chars} 字`
    : (m.lead.placement === 'ch1-top-embedded'
      ? `首节开头内嵌导语 ${m.lead.chars} 字（分隔符：${m.lead.separator}）`
      : '未检出独立导语分隔符')
  const firstDial = m.dialogue.first_dialogue_char !== null ? `第 ${m.dialogue.first_dialogue_char} 字` : '无引号对话'
  const paywallCell = m.paywall && m.paywall.valid && m.paywall_char_ratio !== null
    ? `第 ${m.paywall.section} 节末（实测累计正文 ${m.paywall.cumulative_chars} 字，占 ${pct(m.paywall_char_ratio)}）`
    : '{付费断点位置}'

  const lines = [
    '#### 量化网感体检表',
    '',
    '| 指标 | 实测值 | 简注 |',
    '|------|--------|------|',
    `| 总字数 | ${m.total_chars} 字 | 不含节号与独立分隔符（含节号 ${m.raw_visible_chars} 字）；${leadNote} |`,
    `| 节数与体量 | ${secSummary} | ${dualNote} |`,
    `| 段长中位 | ${m.paragraphs.median_chars} 字（≤30 字段占 ${pct(m.paragraphs.short_30_ratio)}，>80 字段占 ${pct(m.paragraphs.over_80_ratio)}，最长 ${m.paragraphs.max_chars} 字） | 竖屏短段度 |`,
    `| 单句成段率 | ${pct(m.paragraphs.single_sentence_rate)} | 共 ${m.paragraphs.count} 段 |`,
    `| 对话占比 | ${pct(m.dialogue.ratio)}（≤15字短对白占 ${pct(m.dialogue.short_15_ratio)}，引号：${m.dialogue.quote_style}） | ${m.dialogue.bracket_chars > 0 ? `含【】心声/弹幕 ${m.dialogue.bracket_chars} 字` : '纯引号对白'} |`,
    `| 叙述人称 | ${m.pov.label} | 叙述「我」${m.pov.first_person_per_k}/千字 |`,
    `| 首冲突位置 | {语义定位，如导语首句/第1节前段}（首对话${firstDial}） | 标点：「！+？」${m.punctuation.exclaim_question_per_k}/千字，旁白「——」${m.punctuation.em_dash_narration_count} 处（${m.punctuation.em_dash_narration_per_10k}/万字） |`,
    `| 非末节节尾卡点率 | {待分析师统计}%（{M}/{N-1} 节带硬钩子） | ${paywallCell} |`,
    '| 收尾类型 | {明账清算 / 火葬场追悔 / HE发糖 / 细思极恐留白 / 克制回甘 / 开放式} | {是否写足实质代价或首尾呼应} |',
  ]
  return lines.join('\n')
}

const USAGE = '用法: node scripts/measure-short-metrics.js [--json] [--markdown] [--paywall-section N] <原文路径>\n'

function parsePositiveInt(val) {
  if (!/^[1-9]\d*$/.test(String(val || ''))) return null
  const num = Number(val)
  return Number.isSafeInteger(num) ? num : null
}

function main(argv) {
  if (argv.includes('--help') || argv.includes('-h')) {
    process.stdout.write(USAGE)
    return 0
  }
  let wantJson = false
  let wantMd = false
  let paywallSection = null
  const positional = []
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i]
    if (arg === '--json') wantJson = true
    else if (arg === '--markdown') wantMd = true
    else if (arg === '--paywall-section') {
      if (i + 1 >= argv.length) {
        process.stderr.write(`--paywall-section 缺少正整数参数\n${USAGE}`)
        return 2
      }
      paywallSection = parsePositiveInt(argv[++i])
      if (paywallSection === null) {
        process.stderr.write(`--paywall-section 须为正整数\n${USAGE}`)
        return 2
      }
    } else if (arg.startsWith('--paywall-section=')) {
      paywallSection = parsePositiveInt(arg.slice('--paywall-section='.length))
      if (paywallSection === null) {
        process.stderr.write(`--paywall-section 须为正整数\n${USAGE}`)
        return 2
      }
    } else if (arg.startsWith('--')) {
      process.stderr.write(`未知参数: ${arg}\n${USAGE}`)
      return 2
    } else {
      positional.push(arg)
    }
  }
  if (positional.length !== 1) {
    process.stderr.write(`需要且仅需要 1 个原文文件路径。\n${USAGE}`)
    return 2
  }
  const target = path.resolve(positional[0])
  if (!fs.existsSync(target) || !fs.statSync(target).isFile()) {
    process.stderr.write(`文件不存在或不可读: ${target}\n`)
    return 1
  }
  const text = fs.readFileSync(target, 'utf8')
  const metrics = measureShortMetrics(text, target, { paywallSection })

  if (wantJson && !wantMd) {
    process.stdout.write(`${JSON.stringify(metrics, null, 2)}\n`)
  } else if (wantMd && !wantJson) {
    process.stdout.write(`${formatMarkdownTable(metrics)}\n`)
  } else {
    process.stdout.write(`${formatMarkdownTable(metrics)}\n\n\`\`\`json\n${JSON.stringify(metrics, null, 2)}\n\`\`\`\n`)
  }
  return 0
}

if (require.main === module) {
  process.exitCode = main(process.argv.slice(2))
}

module.exports = {
  visibleChars,
  detectSections,
  detectLead,
  isSingleSentencePara,
  countNarrationEmDashes,
  measureShortMetrics,
  formatMarkdownTable,
}
