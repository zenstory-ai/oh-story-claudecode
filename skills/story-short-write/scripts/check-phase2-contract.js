#!/usr/bin/env node
/**
 * Phase 2 deterministic contract verifier for story-short-write.
 *
 * This script is intentionally mechanical: it checks whether the two Phase 2
 * artifacts expose the fields and table shape required by the skill. It does
 * not pretend to judge story quality or whether a reference was genuinely
 * understood.
 *
 * Usage: node scripts/check-phase2-contract.js --json [--strict] [project-dir]
 * Exit: 0 = pass (no hard failures; soft warnings allowed unless --strict),
 *       1 = blocking contract failures (or soft warnings under --strict),
 *       2 = invalid invocation.
 */

'use strict'

const fs = require('fs')
const path = require('path')

// 小节大纲按列名找列，不按位置：新旧列名都认，老书的 小节大纲.md 不迁移也能继续写。
// 第一个名字是现行列名（SKILL.md 的小节大纲模板），其余是旧名。
const OUTLINE_COLUMNS = [
  { role: 'stage', names: ['在全篇哪一段', '结构段/五段功能'] },
  { role: 'progress', names: ['这节发生的事', '情节推进', '子事件×3-5'] },
  { role: 'emotion', names: ['情绪'] },
  { role: 'hook', names: ['节尾停在哪', '结尾承接/钩子'] },
  { role: 'words', names: ['目标字数'] },
]
// 可选列：0.10 起小节大纲只要五列，下面这些写了照认、不写不拦（老书的十二列表头照样过）。
const OPTIONAL_COLUMNS = ['主事件', '人物/关系变化', '前因后果', '因果/逻辑链', '读者新获知什么', '伏笔/物件', '这节靠什么推进', '对话改变了什么', '场景形态', '对白作用', '动静', '对话密度']
const OUTLINE_HEADERS = OUTLINE_COLUMNS.map((column) => column.names[0])
const STAGE_NAMES = OUTLINE_COLUMNS[0].names

function cleanCell(value) {
  return value.replace(/\*\*/g, '').replace(/`/g, '').trim()
}

function parseTableLine(line) {
  const trimmed = line.trim()
  if (!trimmed.startsWith('|') || !trimmed.endsWith('|')) return null
  return trimmed.slice(1, -1).split('|').map(cleanCell)
}

function isSeparatorRow(cells) {
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell))
}

function readUtf8(file) {
  try {
    const text = fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '')
    return { ok: text.trim().length > 0, text }
  } catch (error) {
    return { ok: false, text: '', error: error.message }
  }
}

function makeCheck(id, ok, file, evidence, expected, references, repair, severity = 'blocking') {
  return { id, ok, severity, file, evidence, expected, references, repair }
}

function verify(projectDir, options = {}) {
  const strict = Boolean(options && options.strict)
  const project = path.resolve(projectDir)
  const skillRoot = path.resolve(__dirname, '..')
  const primarySettings = path.join(project, '设定.md')
  const altSettings = path.join(project, '题材与大纲.md')
  const settingsName = fs.existsSync(primarySettings)
    ? '设定.md'
    : (fs.existsSync(altSettings) ? '题材与大纲.md' : '设定.md')
  const settingsFile = path.join(project, settingsName)
  const outlineFile = path.join(project, '小节大纲.md')
  const charactersFile = path.join(project, '人物表.md')
  const settingsRead = readUtf8(settingsFile)
  const outlineRead = readUtf8(outlineFile)
  const checks = []

  checks.push(makeCheck(
    'phase2.settings-readable',
    settingsRead.ok,
    settingsName,
    settingsRead.ok ? '文件存在且非空' : (settingsRead.error || '文件为空'),
    '项目目录下存在非空的 设定.md（或 题材与大纲.md）',
    ['SKILL.md'],
    '只补建或补全 设定.md（或 题材与大纲.md），不改动已通过的 小节大纲.md。',
    'blocking'
  ))
  checks.push(makeCheck(
    'phase2.outline-readable',
    outlineRead.ok,
    '小节大纲.md',
    outlineRead.ok ? '文件存在且非空' : (outlineRead.error || '文件为空'),
    '项目目录下存在非空的 小节大纲.md',
    ['SKILL.md'],
    '只补建或补全 小节大纲.md，不改动已通过的 设定.md。',
    'blocking'
  ))
  if (fs.existsSync(charactersFile)) {
    const charactersRead = readUtf8(charactersFile)
    checks.push(makeCheck(
      'phase2.characters-readable',
      charactersRead.ok,
      '人物表.md',
      charactersRead.ok ? '文件存在且非空' : (charactersRead.error || '文件为空'),
      '项目目录下如创建了 人物表.md，文件应可读且非空',
      ['SKILL.md'],
      '补全 人物表.md，或确认人物信息已统一落在 设定.md「人设速写」后删去空文件。',
      'blocking'
    ))
  }

  if (!settingsRead.ok || !outlineRead.ok) return report(project, checks, { strict })

  const settings = settingsRead.text
  const outline = outlineRead.text
  const isImportedSettings = /^#{1,6}[ \t]*(?:已写部分的写法|本书续写基线)/m.test(settings)
  const isImportedPartial = isImportedSettings && /半成品/.test(settings)
  const isImportedOrLegacySettings =
    isImportedSettings || /^#{1,6}[ \t]*Phase 2 设计校验/m.test(settings)

  // 正则保留「红果」仅兼容旧项目已写的设定，新项目引导不再列出
  const platformMatch = settings.match(/目标平台\s*[：:]\s*(知乎(?:盐言|盐选)?|盐[言选]|七猫(?:短篇)?|黑岩|红果|小程序|点众|番茄(?:短篇|短故事)?|未定)/)
  checks.push(makeCheck(
    'phase2.platform-declared',
    Boolean(platformMatch),
    settingsName,
    platformMatch ? `目标平台：${platformMatch[1]}` : '未找到常见平台表内的目标平台字段',
    '建议写明“目标平台：知乎盐言 / 番茄 / 七猫 / 黑岩 / 点众 / 小程序”之一；作者没定平台写“未定”',
    ['SKILL.md'],
    '复核目标平台：若是自选其他平台，确认后可保留；否则补进 设定.md 基本信息。',
    'advisory'
  ))

  // 题材：现行写题材名或流派别名（「题材：追妻火葬场」「题材：宫斗宅斗」，冷门写「题材：冷门：公式名」），
  // 由脚本按文件名与 frontmatter aliases 对到 genre-styles；0.9.x 及更早写文件路径照认。
  const genreLine = settings.match(/^[ \t]*[-*]?[ \t]*(?:题材参考|题材包|题材)[ \t]*[：:][ \t]*([^\n]*)$/m)
  const genreValue = genreLine ? genreLine[1].replace(/`/g, '').trim() : ''
  const genreDir = path.join(skillRoot, 'references', 'genre-styles')
  const genrePacks = fs.existsSync(genreDir)
    ? fs.readdirSync(genreDir)
      .filter((name) => name.endsWith('.md'))
      .sort()
      .map((file) => {
        const name = file.slice(0, -3)
        let aliases = []
        try {
          const text = fs.readFileSync(path.join(genreDir, file), 'utf8')
          const fm = text.match(/^---\r?\n([\s\S]*?)\r?\n---/)
          const aliasLine = fm ? fm[1].match(/^[ \t]*aliases[ \t]*:[ \t]*\[([^\]]*)\][ \t]*$/m) : null
          if (aliasLine) {
            aliases = aliasLine[1]
              .split(',')
              .map((item) => item.trim().replace(/^['"]|['"]$/g, '').trim())
              .filter(Boolean)
          }
        } catch {
          aliases = []
        }
        return { name, aliases }
      })
    : []
  const genreNames = genrePacks.map((pack) => pack.name)
  let genreEvidence = '未找到「题材：」一行'
  let genreOk = false
  const pathMatch = genreValue.match(/references\/(?:genre-styles\/[^\s|]+\.md|genre-writing-formulas\.md)/)
  if (pathMatch) {
    const resolved = path.resolve(skillRoot, pathMatch[0])
    const insideSkill = resolved.startsWith(`${skillRoot}${path.sep}`)
    const isLegacyFormula = pathMatch[0] === 'references/genre-writing-formulas.md'
    genreOk = (insideSkill && fs.existsSync(resolved) && fs.statSync(resolved).isFile()) ||
      (isLegacyFormula && fs.existsSync(path.join(skillRoot, 'SKILL.md')))
    genreEvidence = genreOk ? `题材：${pathMatch[0]}` : `题材对不到文件：${pathMatch[0]}`
  } else if (/^冷门/.test(genreValue)) {
    genreOk = fs.existsSync(path.join(skillRoot, 'SKILL.md'))
    genreEvidence = `题材：${genreValue}（冷门题材公式）`
  } else if (isImportedSettings && genreValue === '[待补充]') {
    genreOk = true
    genreEvidence = '导入短篇题材暂标 [待补充]，待续写构思时选流派包'
  } else if (genreValue) {
    const tokens = genreValue.split(/[\/、,，+＋（(）)\s]+/).map((s) => s.trim()).filter(Boolean)
    const hasBgCue = tokens.some((t) => /^(?:言情|女频|现言|古言|男频|男女)$/.test(t)) ||
      /(?:言情|女频|现言|古言)/.test(genreValue)
    const strictBlTerms = ['双男主', '耽美', 'ABO', '病娇双男主', '双男主追夫']
    const blPack = genrePacks.find((pack) => pack.name === '双男主')
    const blStrictHit = blPack
      ? strictBlTerms.find((term) => genreValue === term || genreValue.startsWith(term) || tokens.includes(term))
      : null
    const blPureLoveHit = !blStrictHit && blPack && !hasBgCue &&
      (genreValue === '纯爱' || tokens.includes('纯爱'))
      ? '纯爱'
      : null
    const blGenderHit = blStrictHit || blPureLoveHit
    if (blGenderHit) {
      genreOk = true
      genreEvidence = blGenderHit === '双男主' ? '题材：双男主' : `题材：双男主（别名：${blGenderHit}）`
    } else if (genreNames.includes(genreValue)) {
      genreOk = true
      genreEvidence = `题材：${genreValue}`
    } else {
      const highConceptTerms = new Set([
        '脑洞设定流', '脑洞', '弹幕', '系统', '攻略系统', '读心术', '读心', '心声',
        '恶毒女配', '穿书女配', '无限流短篇', '无限流', '对照组',
      ])
      const scenePacks = new Set([
        '校园青春暗恋', '仙侠奇幻末世', '年代重生打脸', '宅斗宫斗', '悬疑', '男频都市反杀',
      ])
      const aliasMatches = []
      for (const pack of genrePacks) {
        const candidates = [pack.name, ...pack.aliases]
        for (const alias of candidates) {
          if (pack.name === '双男主' && alias === '纯爱' && hasBgCue) continue
          let rank = 0
          if (genreValue === alias) rank = 3
          else if (genreValue.startsWith(alias)) rank = 2
          else if (tokens.includes(alias)) rank = 1
          if (!rank) continue
          const genderTier = pack.name === '双男主' ? 3 : 0
          const conceptTier = pack.name === '脑洞设定流' && highConceptTerms.has(alias) ? 2 : 0
          const sceneTier = scenePacks.has(pack.name) ? 1 : 0
          const priorityTier = Math.max(genderTier, conceptTier, sceneTier)
          aliasMatches.push({ pack: pack.name, alias, priorityTier, rank, len: alias.length })
        }
      }
      aliasMatches.sort((a, b) =>
        (b.priorityTier - a.priorityTier) ||
        (b.rank - a.rank) ||
        (b.len - a.len) ||
        a.pack.localeCompare(b.pack)
      )
      const matched = aliasMatches[0]
      if (matched) {
        genreOk = true
        genreEvidence = matched.alias === matched.pack
          ? `题材：${matched.pack}`
          : `题材：${matched.pack}（别名：${matched.alias}）`
      } else {
        genreOk = false
        genreEvidence = `题材「${genreValue}」不是现有题材包或别名（${genreNames.join(' / ')}），未命中细分流派请选「通用短篇」`
      }
    }
  }
  checks.push(makeCheck(
    'phase2.genre-reference-declared',
    genreOk,
    settingsName,
    genreEvidence,
    `建议在「构思要点」写「题材：题材包名」（${genreNames.join(' / ')} 之一；未命中细分流派选「通用短篇」）`,
    ['SKILL.md', 'references/genre-styles/*.md'],
    '复核题材名：若确属自定义或复合题材可保留；需要对齐题材包时修正「题材：」一行。',
    'advisory'
  ))

  // 套路：现行写在「### 这篇用的套路」下，一条一行；旧书在设计校验区写「核心招式：a；b」，照认。
  const movesMatch = settings.match(/核心招式\s*[：:]\s*([^\n]+)/)
  let moves = []
  if (movesMatch) {
    moves = movesMatch[1].split(/[；;]|\s\/\s/).map((item) => item.trim()).filter(Boolean)
  } else {
    const section = settings.match(/^#{2,6}[ \t]*这篇用的套路[^\n]*\n([\s\S]*?)(?=^#{1,6}[ \t]|(?![\s\S]))/m)
    if (section) {
      moves = section[1].split(/\r?\n/)
        .map((line) => line.match(/^[ \t]*[-*][ \t]+(.+)$/))
        .filter(Boolean)
        .map((match) => match[1].trim())
        .filter((item) => item && item !== '[待补充]' && !/^参照的结构/.test(item))
    }
  }
  checks.push(makeCheck(
    'phase2.genre-moves-declared',
    moves.length >= 2 && moves.length <= 3,
    settingsName,
    moves.length ? `识别到 ${moves.length} 个套路` : '「这篇用的套路」下没有条目',
    '建议「这篇用的套路」下写 2-3 条，一条一行（旧书的「核心招式：招式一；招式二」照认）',
    ['SKILL.md'],
    '复核套路数量：需要收敛或补足时调到 2-3 条；若篇幅或题材刻意增减，确认后可保留。',
    'advisory'
  ))

  const villainSkipped = /反派(?:设计)?\s*[：:]\s*(?:无|不适用|没有)\s*[（(][^)）]+[)）]/.test(settings)
  const villainFields = ['身份', '动机', '作恶方式', '致命弱点', '报应']
  const missingVillainFields = villainFields.filter((field) => !new RegExp(`(?:^|\\n)\\s*[-*]?\\s*${field}\\s*[：:]`, 'm').test(settings))
  const villainOk = villainSkipped || missingVillainFields.length === 0
  checks.push(makeCheck(
    'phase2.villain-contract',
    villainOk,
    settingsName,
    villainSkipped ? '已明确反派不适用' : (villainOk ? '反派五字段齐全' : `缺字段：${missingVillainFields.join('、')}`),
    '无反派时建议写“反派：没有（原因）”；有反派时建议填写身份、动机、作恶方式、致命弱点、报应',
    ['SKILL.md'],
    '复核反派设定：若有具体反派，补齐缺失字段；若确无反派或已用白话说明，确认后可保留。',
    'advisory'
  ))

  const placeholderFields = ['题材参考', '题材', '核心招式', '反派设计', '反派', '反转类型', '反转位置', '反转在', '付费点', '目标平台', '目标字数']
  const fieldLine = new RegExp(`^[ \\t]*[-*]?[ \\t]*(?:${placeholderFields.join('|')})[ \\t]*[：:]`)
  let inMoves = false
  const placeholderLines = []
  settings.split(/\r?\n/).forEach((text, index) => {
    if (/^#{1,6}[ \t]/.test(text)) inMoves = /这篇用的套路/.test(text)
    const watched = fieldLine.test(text) || (inMoves && /^[ \t]*[-*][ \t]/.test(text))
    if (watched && /\{[^}]*\}/.test(text)) placeholderLines.push({ line: index + 1, text })
  })
  checks.push(makeCheck(
    'phase2.no-template-placeholders',
    placeholderLines.length === 0,
    settingsName,
    placeholderLines.length ? `仍是模板占位符的行：${placeholderLines.map((entry) => entry.line).join('、')}` : '构思要点与套路没有未填写的 {} 占位符',
    '构思要点与「这篇用的套路」写实际设计内容，不保留 {} 模板占位符',
    ['SKILL.md'],
    '只把报告行的占位符替换成本篇的实际设计，不重写其他字段。',
    'blocking'
  ))

  const lines = outline.split(/\r?\n/)
  let headerAt = -1
  let headerCells = null
  for (let index = 0; index < lines.length; index++) {
    const cells = parseTableLine(lines[index])
    if (cells && STAGE_NAMES.includes(cells[0])) {
      headerAt = index
      headerCells = cells
      break
    }
  }
  const column = {}
  const unknownCells = []
  const duplicateRoles = []
  if (headerCells) {
    headerCells.forEach((cell, index) => {
      const spec = OUTLINE_COLUMNS.find((item) => item.names.includes(cell))
      if (spec) {
        if (spec.role in column) duplicateRoles.push(cell)
        else column[spec.role] = index
      } else if (!OPTIONAL_COLUMNS.includes(cell)) {
        unknownCells.push(cell)
      }
    })
  }
  const missingColumns = OUTLINE_COLUMNS.filter((item) => !(item.role in column)).map((item) => item.names[0])
  const legacyHeader = Boolean(headerCells) && headerCells.some((cell) =>
    OUTLINE_COLUMNS.some((item) => item.names.indexOf(cell) > 0))
  const coreHeaderOk = Boolean(headerCells) && missingColumns.length === 0 && duplicateRoles.length === 0
  let headerEvidence = `未找到以“${STAGE_NAMES[0]}”开头的 Markdown 表格`
  if (headerCells) {
    const problems = []
    if (missingColumns.length) problems.push(`缺列：${missingColumns.join('、')}`)
    if (duplicateRoles.length) problems.push(`重复的列：${duplicateRoles.join('、')}`)
    headerEvidence = `表头 ${headerCells.length} 列：${headerCells.join(' | ')}` +
      (problems.length ? `；${problems.join('；')}` : (legacyHeader ? '（旧列名，照认）' : ''))
  }
  checks.push(makeCheck(
    'phase2.outline-header',
    coreHeaderOk,
    '小节大纲.md',
    headerEvidence,
    `表头含这五列：${OUTLINE_HEADERS.join(' | ')}；其余列可选`,
    ['SKILL.md'],
    '只修表头缺失或重复的核心列，不改动各节已经成立的剧情内容。',
    'blocking'
  ))
  checks.push(makeCheck(
    'phase2.outline-custom-columns',
    unknownCells.length === 0,
    '小节大纲.md',
    unknownCells.length ? `自定义/未登记列：${unknownCells.join('、')}` : '表头无未登记的自定义列',
    `标准列为 ${OUTLINE_HEADERS.join(' | ')} 及已知可选列`,
    ['SKILL.md'],
    '复核自定义列：若是有意加的辅助列且每行对齐，可保留；若是写错列名，改回标准列名。',
    'advisory'
  ))

  const rows = []
  if (headerAt >= 0) {
    for (let index = headerAt + 1; index < lines.length; index++) {
      const cells = parseTableLine(lines[index])
      if (!cells) {
        if (rows.length) break
        continue
      }
      if (isSeparatorRow(cells)) continue
      rows.push({ line: index + 1, cells })
    }
  }
  const width = headerCells ? headerCells.length : 0
  const rowShapeFailures = rows.filter((row) => row.cells.length !== width)
  checks.push(makeCheck(
    'phase2.outline-data-rows',
    rows.length > 0 && rowShapeFailures.length === 0,
    '小节大纲.md',
    rows.length === 0 ? '表头下没有数据行' : (rowShapeFailures.length ? `列数错误行：${rowShapeFailures.map((row) => row.line).join('、')}` : `识别到 ${rows.length} 节，列数与表头一致`),
    '表头下至少一行数据，每节的列数与表头一致',
    ['SKILL.md'],
    '只补缺失节或修复报告行的列错位。',
    'blocking'
  ))

  const shapedRows = coreHeaderOk ? rows.filter((item) => item.cells.length === width) : []
  const cell = (row, role) => (role in column ? (row.cells[column[role]] || '') : '')
  const emptyProgress = shapedRows.filter((row) => !cell(row, 'progress').trim()).map((row) => row.line)
  checks.push(makeCheck(
    'phase2.outline-subevents',
    shapedRows.length > 0 && emptyProgress.length === 0,
    '小节大纲.md',
    emptyProgress.length
      ? `「这节发生的事」为空的行：${emptyProgress.join('、')}`
      : (shapedRows.length ? `所有 ${shapedRows.length} 节都写了这节发生的事` : '表头或列数有误，见前两项'),
    '每节写一句这节发生的事，不设数量',
    ['SKILL.md'],
    '只补报告行的「这节发生的事」，不重写其他列或其他节；不要为数量补事件。',
    'blocking'
  ))

  // 「约 1-1.3 万」「1.1万字」这类写法先换成整数再解析。
  const targetLine = (settings.match(/目标字数\s*[：:][^\n]*/) || [''])[0]
    .replace(/(\d+(?:\.\d+)?)\s*((?:[-–—~～]|到|至)\s*)(\d+(?:\.\d+)?)\s*万/g,
      (_, a, sep, b) => `${Math.round(Number(a) * 10000)}${sep}${Math.round(Number(b) * 10000)}`)
    .replace(/(\d+(?:\.\d+)?)\s*万/g, (_, a) => String(Math.round(Number(a) * 10000)))
  const targetMatch = targetLine.match(/目标字数\s*[：:]\s*(?:约\s*)?([\d,，]+)\s*(?:字)?\s*(?:[-–—~～]|到|至)\s*([\d,，]+)\s*字?/) ||
    targetLine.match(/目标字数\s*[：:]\s*(?:约\s*)?([\d,，]+)\s*字?/)
  const toNumber = (value) => Number(String(value).replace(/[,，]/g, ''))
  const targetLow = targetMatch ? toNumber(targetMatch[1]) : null
  const targetHigh = targetMatch && targetMatch[2] !== undefined ? toNumber(targetMatch[2]) : targetLow
  const statedTarget = targetLow
  const rowTargets = shapedRows.map((row) => {
    const match = cell(row, 'words').match(/([\d,，]+)/)
    return match ? Number(match[1].replace(/[,，]/g, '')) : null
  })
  const targetSum = rowTargets.every((value) => Number.isFinite(value))
    ? rowTargets.reduce((sum, value) => sum + value, 0)
    : null
  const isRange = targetHigh !== null && targetHigh !== targetLow
  const targetPendingOnImport = isImportedPartial && /\[待补充\]/.test(targetLine)
  const statedTargetOk = targetPendingOnImport ||
    (statedTarget !== null && statedTarget >= 1000 && targetHigh <= 200000 && targetHigh >= targetLow)
  checks.push(makeCheck(
    'phase2.target-wordcount',
    statedTargetOk,
    settingsName,
    targetPendingOnImport
      ? '导入半成品目标字数暂标 [待补充]，待续写构思确认'
      : (statedTarget === null ? '目标字数未识别或不可解析' : `设定目标：${isRange ? `${targetLow}-${targetHigh}` : statedTarget}`),
    '设定.md 的目标字数为 1000-200000 的正整数或区间（低值 ≤ 高值）',
    ['SKILL.md'],
    '只在 设定.md 基本信息补或修正可解析的目标字数。',
    'blocking'
  ))

  const targetSumOk = statedTargetOk && shapedRows.length > 0 && shapedRows.length === rows.length && targetSum !== null &&
    (isImportedPartial
      ? (targetPendingOnImport || targetSum <= targetHigh * 1.05)
      : (isRange
        ? targetSum >= targetLow && targetSum <= targetHigh
        : Math.abs(targetSum - statedTarget) <= statedTarget * 0.05))
  checks.push(makeCheck(
    'phase2.target-word-sum',
    targetSumOk,
    `${settingsName}、小节大纲.md`,
    isImportedPartial
      ? `导入半成品已写节大纲合计：${targetSum === null ? '有非数字目标字数' : targetSum}（全篇目标：${targetPendingOnImport ? '[待补充]' : (isRange ? `${targetLow}-${targetHigh}` : statedTarget)}）`
      : `设定目标：${statedTarget === null ? '未识别' : (isRange ? `${targetLow}-${targetHigh}` : statedTarget)}；大纲合计：${targetSum === null ? '有非数字目标字数' : targetSum}`,
    '建议大纲每行目标字数可解析，写区间时合计落在区间内，写单值时误差不超过 5%',
    ['SKILL.md'],
    '复核各节目标字数合计：若偏差过大请微调分配，不要用增删剧情绕过数字偏差。',
    'advisory'
  ))

  // 反转位置只核节号在不在大纲范围内；百分比只供核对，不是通过线（0.10 起旧写法里的算式不再核算）。
  const reversalMatch = settings.match(/反转(?:位置|在)\s*[：:]\s*第\s*(\d+)\s*节/)
  const noReversal = /反转类型\s*[：:]\s*无反转/.test(settings) &&
    /反转(?:位置|在)\s*[：:]\s*不适用\s*[（(][^)）]+[)）]/.test(settings)
  let reversalOk = false
  let reversalEvidence = '未找到“反转在：第 X 节（共 Y 节）”'
  if (noReversal) {
    reversalOk = true
    reversalEvidence = '反转类型为无反转，位置已带原因标为不适用'
  } else if (reversalMatch) {
    const reveal = Number(reversalMatch[1])
    reversalOk = reveal >= 1 && reveal <= rows.length
    reversalEvidence = `声明反转在第 ${reveal} 节；大纲识别 ${rows.length} 节`
  }
  checks.push(makeCheck(
    'phase2.reversal-position',
    reversalOk,
    settingsName,
    reversalEvidence,
    '有反转时建议写“反转在：第 X 节（共 Y 节）”，X 在大纲节数之内；无反转时写“反转类型：无反转”和带原因的“反转在：不适用（…）”',
    ['SKILL.md'],
    '复核反转节号是否超出大纲节数；无反转篇若已说明思路，确认后可保留。',
    'advisory'
  ))

  const paywallMatch = settings.match(/付费点\s*[：:]\s*第?\s*(\d+)\s*节(?:末)?/)
  const paywallSection = paywallMatch ? Number(paywallMatch[1]) : null
  const paywallRows = rows
    .map((row, index) => ({ section: index + 1, hook: cell(row, 'hook') }))
    .filter((row) => /付费点/.test(row.hook))
  const paywallOk = paywallSection !== null && paywallRows.length === 1 &&
    paywallRows[0].section === paywallSection
  let paywallEvidence = `${settingsName} 未按“付费点：第 X 节末”声明`
  if (paywallSection !== null && paywallRows.length === 0) {
    paywallEvidence = `${settingsName} 声明第 ${paywallSection} 节末；大纲“节尾停在哪”列未标出付费点`
  } else if (paywallSection !== null && paywallRows.length > 0) {
    paywallEvidence = `${settingsName} 声明第 ${paywallSection} 节末；大纲标在第 ${paywallRows.map((row) => row.section).join('、')} 节`
  }
  checks.push(makeCheck(
    'phase2.paywall-in-both',
    paywallOk,
    `${settingsName}、小节大纲.md`,
    paywallEvidence,
    '有付费断点需求的平台建议在 设定.md 写“付费点：第 X 节末”，并在小节大纲.md 对应节「节尾停在哪」标出',
    ['SKILL.md'],
    '复核付费点：若目标平台需单一付费断点则两边对齐；若是免费/非付费卡点形态，确认后可保留。',
    'advisory'
  ))

  // 导语/冷开场声明（advisory）：导入书与 0.9.x 旧版设定跳过以保持严格向后兼容。
  let leadOk = false
  let leadEvidence = `${settingsName} 未声明导语或冷开场`
  if (isImportedOrLegacySettings) {
    leadOk = true
    leadEvidence = '导入或旧版设定，跳过导语声明检查'
  } else {
    const leadSection = settings.match(/^#{2,6}[ \t]*[^\n]*(?:导语|冷开场)[^\n]*\n([\s\S]*?)(?=^#{1,6}[ \t]|(?![\s\S]))/m)
    const stripHtmlComments = (text) => {
      const src = text || ''
      let out = ''
      let cursor = 0
      while (cursor < src.length) {
        const start = src.indexOf('<!--', cursor)
        if (start === -1) {
          out += src.slice(cursor)
          break
        }
        out += src.slice(cursor, start)
        const end = src.indexOf('-->', start + 4)
        if (end === -1) {
          out += src.slice(start + 4)
          break
        }
        cursor = end + 3
      }
      return out
    }
    const leadBody = leadSection
      ? stripHtmlComments(leadSection[1]).split(/\r?\n/).map((line) => line.trim()).filter((line) => line && !/^\{[^}]*\}$/.test(line) && line !== '[待补充]')
      : []
    const leadField = settings.match(/^[ \t]*[-*]?[ \t]*(?:导语|冷开场)[^：:\n]*[：:][ \t]*([^\n]+)$/m)
    const leadFieldVal = leadField ? leadField[1].trim() : ''
    const hasLeadField = Boolean(leadFieldVal) && !/^\{[^}]*\}$/.test(leadFieldVal) && leadFieldVal !== '[待补充]' && leadFieldVal !== '无'
    if (leadBody.length > 0 || hasLeadField) {
      leadOk = true
      leadEvidence = leadBody.length > 0 ? `${settingsName} 已包含导语/冷开场小节` : `${settingsName} 已声明导语/冷开场字段`
    }
  }
  checks.push(makeCheck(
    'phase2.lead-declared',
    leadOk,
    settingsName,
    leadEvidence,
    '建议在 设定.md 声明导语（150-300 字开门见山卖点与钩子），便于进入正文直接进冲突',
    ['SKILL.md'],
    '复核导语：若本篇走网文短篇开门见山导语，在 设定.md 补一段导语草稿或开篇要点；若刻意省略导语可保留。',
    'advisory'
  ))

  // 付费点位置比例（advisory）：大纲 ≥5 节且声明了付费点时，建议按节数与目标字数累计均落在全文 20%-55% 区间。
  let paywallRatioOk = true
  let paywallRatioEvidence = '未声明付费点或总节数不足 5 节，跳过付费点位置比例检查'
  if (paywallSection !== null && rows.length >= 5) {
    const ratio = paywallSection / rows.length
    const pct = Math.round(ratio * 100)
    const sectionRatioOk = ratio >= 0.20 && ratio <= 0.55
    const hasValidRowTargets = shapedRows.length === rows.length && targetSum !== null && targetSum > 0 &&
      paywallSection >= 1 && paywallSection <= rowTargets.length
    if (hasValidRowTargets) {
      const cumTarget = rowTargets.slice(0, paywallSection).reduce((sum, val) => sum + val, 0)
      const charRatio = cumTarget / targetSum
      const charPct = Math.round(charRatio * 100)
      paywallRatioOk = sectionRatioOk && charRatio >= 0.20 && charRatio <= 0.55
      paywallRatioEvidence = `付费点在第 ${paywallSection} 节 / 共 ${rows.length} 节（按节数 ${pct}%，按目标字数 ${cumTarget}/${targetSum} 约 ${charPct}%）`
    } else {
      paywallRatioOk = sectionRatioOk
      paywallRatioEvidence = `付费点在第 ${paywallSection} 节 / 共 ${rows.length} 节（${pct}%）`
    }
  }
  checks.push(makeCheck(
    'phase2.paywall-position-ratio',
    paywallRatioOk,
    `${settingsName}、小节大纲.md`,
    paywallRatioEvidence,
    '总节数 ≥5 节时，建议付费点按节数与目标字数累计均落在全文 32%–44% 推荐带（宽容区间 20%-55%，通常第 2-4 节末）',
    ['SKILL.md'],
    '复核付费点位置：偏后容易拖慢免费段转折，偏前容易铺垫不足；按平台试读比例微调或确认保留。',
    'advisory'
  ))

  return report(project, checks, { strict })
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
  }
}

function report(project, checks, options = {}) {
  const strict = Boolean(options && options.strict)
  const hardFailures = checks.filter((check) => !check.ok && check.severity === 'blocking')
  const softWarnings = checks.filter((check) => !check.ok && check.severity === 'advisory')
  const findings = [...hardFailures, ...softWarnings]
  const failures = strict ? findings : hardFailures
  return {
    schema_version: 1,
    verifier: 'story-short-write.phase2-contract',
    project,
    strict,
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

const USAGE = '用法: node scripts/check-phase2-contract.js --json [--strict] [project-dir]\n'

function main(argv) {
  if (argv.includes('--help') || argv.includes('-h')) {
    process.stdout.write(USAGE)
    return 0
  }
  let strict = false
  const args = []
  for (const arg of argv) {
    if (arg === '--json') continue
    if (arg === '--strict') { strict = true; continue }
    args.push(arg)
  }
  if (args.length > 1 || args.some((arg) => arg.startsWith('--'))) {
    process.stderr.write(USAGE)
    return 2
  }
  const result = verify(args[0] || '.', { strict })
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`)
  return result.ok ? 0 : 1
}

if (require.main === module) process.exitCode = main(process.argv.slice(2))

module.exports = { OUTLINE_HEADERS, OPTIONAL_COLUMNS, verify }
