#!/usr/bin/env node
/**
 * check-outline-copy.js — 细纲照搬检测
 *
 * 治的病：细纲把情节点写成成品散文句，正文只剩誊抄，质量被锁死在细纲水平。
 * 实测正文与细纲连续重合最高 13.5%、单段最长 40 字，且重合段落多为叙述而非台词
 * ——即全章最好的那几句在细纲阶段就写完了。
 *
 * 判定：正文与同章细纲连续重合 > 阈值（默认 15 字）即报出
 * ——细纲只锁功能与结果，句子一律在正文现场写。
 *
 * 词面相同不等于不良照搬：系统面板、任务要求、固定专名本就该保持一致。因此本脚本
 * 只提供证据（位置与片段），是否重写由 agent 读上下文语义判断，同 check-ai-patterns.js
 * 的 advisory 轨——但每条都要有结论，不允许只报不改，也不为归零机械改写。
 * 判定保留的只由主会话补进细纲锚句：子代理不改大纲细纲（见 narrative-writer「不自行改纲」），
 * 否则子代理误判的重合会被自己写进白名单，主会话复扫时不再报出，第二层复核失明。
 *
 * 免报：细纲「复沓锚句」字段下列出的原话允许逐字落地——誓言、系统面板、
 * 旧案原话等写细纲时判定必须原文出现的部分，逐行一条。只扣除锚句自身的精确区间，
 * 前后剩余片段照常按阈值判定，避免紧挨锚句的照搬被顺带赦免。
 * 豁免量单独统计并在报告末尾列出，滥用锚句绕过检测时一眼可见。
 *
 * 由 narrative-writer 落盘后自查、主会话收尾复扫时调用（两侧同一份实现，口径一致）。
 * 不进 hook：正文兜底 hook 的共享核是四端共用的，不为单项检测扩面。
 *
 * 用法：
 *   node check-outline-copy.js <正文路径...>                    # 自动找同章细纲；短篇找同目录小节大纲
 *   node check-outline-copy.js --outline <细纲路径> <正文路径...> # 指定细纲
 *
 * 位置参数一律按正文处理，与 check-ai-patterns.js 的 `<file...>` 口径一致：
 * 收尾复扫用 `正文/第XXX章_*.md` 这类通配传多章时，多出来的正文不能被当成细纲吞掉
 * ——那会让首个文件比错对象、其余文件根本不检，静默退 0 报「干净」。
 *
 * 退出码：0 = 干净或未自动发现细纲而跳过；1 = 有重合待复核；
 * 2 = 参数错误、输入不可读（含已发现的细纲）或非预期异常。
 * 干净时静默；自动发现不到细纲时明确报告跳过，避免与「已检查且干净」混淆。
 */

'use strict'
const fs = require('fs')
const path = require('path')

const MIN_RUN = 16 // 判定阈值：连续重合 >15 字，即 >=16
const REPORT_TOP = 8 // 最多列出的片段数

function readTextFile(p) {
  try {
    const stat = fs.statSync(p)
    if (!stat.isFile()) return { ok: false, reason: '不是普通文件' }
    return { ok: true, text: fs.readFileSync(p, 'utf8').replace(/^﻿/, '') }
  } catch (error) {
    if (error && error.code === 'ENOENT') return { ok: false, reason: '不存在' }
    if (error && error.code) return { ok: false, reason: `无法读取（${error.code}）` }
    return { ok: false, reason: `无法读取：${error instanceof Error ? error.message : String(error)}` }
  }
}

function reportInputError(kind, file, reason) {
  process.stderr.write(`错误: 无法读取${kind} "${file}"：${reason}。\n`)
}

function reportUsageError(message) {
  process.stderr.write(`错误: ${message}。\n`)
  process.stderr.write('用法: node check-outline-copy.js [--outline <细纲路径>] <正文路径...>\n')
  return 2
}

/** 只留汉字——剥掉标点/加粗/【】后比对，防止细纲标注造成假阴性 */
function hanOnly(s) {
  return s.replace(/[^一-鿿]/g, '')
}

/**
 * 抽出细纲「复沓锚句」字段下的原话，一行一条。
 * 只认这一个字段，不扫情节点序列——锚句集中在固定区块，情节点保持只写「要发生什么」。
 * 区块终止于行首无缩进的下一个字段（`- xxx`）或下一个小节标题，因此条目本身
 * 用 `1.` 编号、缩进 `-` 列表或纯文本都能正确提取，不必额外标记。
 */
function extractAnchors(outline) {
  const m = outline.match(/复沓锚句[^：:\n]*[：:]([\s\S]*?)(?=\n[-*+]\s|\n#{1,6}\s|$)/)
  if (!m) return []
  return m[1]
    .split("\n")
    // 去掉列表符号与「点N：」这类落点前缀，只留原话本身
    .map((line) => line.replace(/^\s*[-*+]?\s*(?:\d+[.、)]\s*)?(?:点\s*\d+\s*[：:])?/, ""))
    .map((line) => hanOnly(line))
    .filter((a) => a.length >= 2)
}

/**
 * 在片段里定位锚句的精确出现区间，挖掉后返回剩余子段与豁免字数。
 * 不能只判「片段包含锚句」就整段放行——贪心扫描求的是最长延伸，锚句嵌在中间时
 * 会连同紧挨着它的未授权重合一起赦免。
 */
function splitByAnchors(frag, anchors) {
  // 片段完全落在某条锚句内：整段豁免（抄了锚句的一部分，仍在授权范围）
  if (anchors.some((a) => a.includes(frag))) return { rest: [], anchoredLen: frag.length }

  const spans = []
  for (const a of anchors) {
    for (let from = 0; from + a.length <= frag.length; ) {
      const at = frag.indexOf(a, from)
      if (at < 0) break
      spans.push([at, at + a.length])
      from = at + 1 // 同一锚句重复出现要逐次记录
    }
  }
  if (!spans.length) return { rest: [frag], anchoredLen: 0 }

  spans.sort((x, y) => x[0] - y[0])
  const merged = [spans[0]] // 多锚句重叠/相邻时并成一段，避免重复计数
  for (const [s, e] of spans.slice(1)) {
    const last = merged[merged.length - 1]
    if (s <= last[1]) last[1] = Math.max(last[1], e)
    else merged.push([s, e])
  }

  const rest = []
  let cursor = 0
  let anchoredLen = 0
  for (const [s, e] of merged) {
    if (s > cursor) rest.push(frag.slice(cursor, s))
    anchoredLen += e - s
    cursor = e
  }
  if (cursor < frag.length) rest.push(frag.slice(cursor))
  return { rest, anchoredLen }
}

/** 定位同章细纲：遍历 大纲/ 按章号正则匹配，支持带后缀的文件名 */
function findOutline(proseFile) {
  const base = path.basename(proseFile)
  // 短篇没有章号：正文.md 与 小节大纲.md 在同目录平铺
  if (base === '正文.md') {
    const sibling = path.join(path.dirname(proseFile), '小节大纲.md')
    return fs.existsSync(sibling) ? sibling : null
  }
  const m = base.match(/^第\s*0*(\d+)\s*章/)
  if (!m) return null
  const chapter = m[1]
  const dir = path.join(path.dirname(path.dirname(proseFile)), '大纲')
  try {
    for (const file of fs.readdirSync(dir)) {
      const fm = file.match(/^细纲_第0*(\d+)章.*\.md$/)
      if (fm && fm[1] === chapter) return path.join(dir, file)
    }
  } catch (error) {
    if (error.code !== 'ENOENT') throw error
  }
  return null
}

function main() {
  const proseFiles = []
  let explicitOutline = null
  const argv = process.argv.slice(2)
  let positionalOnly = false
  for (let k = 0; k < argv.length; k++) {
    const arg = argv[k]
    if (!positionalOnly && arg === '--') {
      positionalOnly = true
    } else if (!positionalOnly && arg === '--outline') {
      if (explicitOutline !== null) return reportUsageError('--outline 不能重复指定')
      const value = argv[k + 1]
      if (!value || value.startsWith('--')) return reportUsageError('--outline 缺少路径')
      explicitOutline = value
      k++
    } else if (!positionalOnly && arg.startsWith('--')) {
      return reportUsageError(`未知选项: ${arg}`)
    } else {
      proseFiles.push(arg)
    }
  }
  if (!proseFiles.length) return reportUsageError('缺少正文路径')

  // 逐个文件独立判定；输入错误优先于重合发现
  let status = 0
  for (const proseFile of proseFiles) {
    status = Math.max(status, checkOne(proseFile, explicitOutline))
  }
  return status
}

function checkOne(proseFile, explicitOutline) {
  const proseResult = readTextFile(proseFile)
  if (!proseResult.ok) {
    reportInputError('正文', proseFile, proseResult.reason)
    return 2
  }
  const prose = proseResult.text

  const outlineFile = explicitOutline || findOutline(proseFile)
  if (!outlineFile) {
    process.stdout.write(`细纲照搬检测：跳过 "${proseFile}"（未自动发现细纲）。\n`)
    return 0
  }
  const outlineResult = readTextFile(outlineFile)
  if (!outlineResult.ok) {
    reportInputError(explicitOutline ? '显式细纲' : '自动发现的细纲', outlineFile, outlineResult.reason)
    return 2
  }
  const outline = outlineResult.text

  // 正文去掉标题行后比对
  const P = hanOnly(prose.replace(/^#.*$/gm, ''))
  const O = hanOnly(outline)
  if (P.length < MIN_RUN || O.length < MIN_RUN) return 0

  // 复沓锚句列出的原话允许逐字落地，命中后计入豁免、不判誊抄
  const anchors = extractAnchors(outline)

  // 贪心扫描：每个起点二分求「仍是细纲子串」的最长延伸，命中区间不重叠
  const hits = []
  let copied = 0
  let anchored = 0
  let anchoredCount = 0
  let i = 0
  while (i < P.length) {
    let best = 0
    if (i + MIN_RUN <= P.length && O.includes(P.substr(i, MIN_RUN))) {
      best = MIN_RUN
      let lo = MIN_RUN
      let hi = Math.min(P.length - i, 200)
      while (lo <= hi) {
        const mid = (lo + hi) >> 1
        if (O.includes(P.substr(i, mid))) {
          best = mid
          lo = mid + 1
        } else hi = mid - 1
      }
    }
    if (best) {
      const frag = P.substr(i, best)
      const { rest, anchoredLen } = splitByAnchors(frag, anchors)
      if (anchoredLen) {
        anchored += anchoredLen
        anchoredCount++
      }
      // 挖掉锚句后的剩余子段仍是细纲子串，只需按阈值重判
      for (const seg of rest) {
        if (seg.length >= MIN_RUN) {
          hits.push({ frag: seg, len: seg.length })
          copied += seg.length
        }
      }
      i += best
    } else i++
  }
  if (!hits.length) {
    // 全部命中都是锚句豁免：静默放行，但把豁免量报出来供人工复核滥用
    if (anchoredCount) {
      process.stdout.write(
        `细纲照搬检测（${path.basename(proseFile)}）：无未授权誊抄；` +
          `另有 ${anchoredCount} 处 ${anchored} 字为复沓锚句的逐字落地。\n`
      )
    }
    return 0
  }

  const rate = ((copied * 100) / P.length).toFixed(1)
  const out = [
    `=== 细纲照搬检测（${path.basename(proseFile)}）===`,
    `正文 ${P.length} 字，与 ${path.basename(outlineFile)} 连续重合 >${MIN_RUN - 1} 字的片段 ${hits.length} 处，共 ${copied} 字（${rate}%）。`,
    `逐条对照原文判断：确属把细纲叙述搬进正文就重写——细纲只锁功能与结果，句子在正文现场写；系统面板、誓词、案卷原话、固定专名等功能性重合可保留。每条都要有结论，不为归零机械改写。保留项由主会话补进细纲「复沓锚句」——子代理只重写正文或标 \`[需复核]\` 交回，不改大纲细纲。`,
  ]
  hits
    .sort((a, b) => b.len - a.len)
    .slice(0, REPORT_TOP)
    .forEach((h) => out.push(`  · ${h.len} 字「${h.frag}」`))
  if (hits.length > REPORT_TOP) out.push(`  · …另有 ${hits.length - REPORT_TOP} 处`)
  if (anchoredCount) out.push(`（另有 ${anchoredCount} 处 ${anchored} 字为复沓锚句的逐字落地，不计入誊抄）`)
  process.stdout.write(out.join('\n') + '\n')
  return 1
}

try {
  process.exit(main())
} catch (error) {
  const message = error instanceof Error ? error.message : String(error)
  process.stderr.write(`错误: 细纲照搬检测异常：${message}。\n`)
  process.exit(2)
}
