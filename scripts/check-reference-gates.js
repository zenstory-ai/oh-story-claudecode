#!/usr/bin/env node
/**
 * check-reference-gates.js — static guard for the two Reference Gates.
 *
 * The gates are prompt text executed by a model, so there is no runtime entry
 * point to call and no return value to assert. This guard therefore pins the
 * source policy only: the gate stays on the first screen and keeps naming every
 * reference it routes. Gate adherence itself is measured by real writing runs,
 * not here; do not read a pass as evidence that a model obeyed the gate.
 */

'use strict'

const assert = require('assert')
const fs = require('fs')
const path = require('path')

const repoRoot = path.resolve(__dirname, '..')

function readSkill(name) {
  return fs.readFileSync(path.join(repoRoot, `skills/${name}/SKILL.md`), 'utf8')
}

const long = readSkill('story-long-write')
const longLines = long.split(/\r?\n/)
const longGateLine = longLines.findIndex((line) => line.includes('章节 Reference Gate')) + 1
assert(longGateLine > 0 && longGateLine <= 20, `long Reference Gate must stay in first screen, got line ${longGateLine}`)
assert.match(long, /只读本 SKILL\.md 不算完成/)
assert.match(long, /`rg` 检索或局部摘读也不算完整读取/)
for (const reference of [
  'workflow-setup.md', 'workflow-chapter.md', 'workflow-daily.md', 'workflow-revision.md', 'long-format.md',
  'writing-craft.md', 'long-chapter-quality.md', 'long-chapter-hooks.md', 'long-suspense.md',
  'long-reversal.md',
]) {
  assert(long.includes(reference), `long gate must route ${reference}`)
}
assert.match(long, /不得先写正文再补读/)
assert.match(long, /Constraint Lock/)
assert.match(long, /references 只提供技法，不得覆盖这些项目事实/)

const short = readSkill('story-short-write')
const shortLines = short.split(/\r?\n/)
const shortGateLine = shortLines.findIndex((line) => line.includes('阶段 Reference Gate')) + 1
assert(shortGateLine > 0 && shortGateLine <= 20, `short Reference Gate must stay in first screen, got line ${shortGateLine}`)
assert.match(short, /只读本 SKILL\.md 不算完成门禁/)
assert.match(short, /任一必需路径不存在、不可读/)
assert.match(short, /分块直到 EOF；`rg` 检索或局部摘读不算读完/)

// Phase 2 orchestration lives in its stage reference; these are source-policy
// assertions, not evidence that a model loaded it or honored the repair loop.
const shortGate = shortLines.slice(shortGateLine - 1, shortGateLine + 11).join('\n')
assert(shortGate.includes('`references/workflow-design.md`'), 'Phase 2 gate must route workflow-design on the first screen')
const shortDesign = fs.readFileSync(path.join(repoRoot, 'skills/story-short-write/references/workflow-design.md'), 'utf8')
assert.match(shortDesign, /check-phase2-contract\.js --json/)
assert.match(shortDesign, /最多做 2 轮定向 repair/)

process.stdout.write('reference-gates: source policy holds\n')
