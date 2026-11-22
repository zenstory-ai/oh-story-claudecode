#!/usr/bin/env node
"use strict"

import test from "node:test"
import assert from "node:assert/strict"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import childProcess, { execFileSync, spawnSync } from "node:child_process"
import { createRequire, syncBuiltinESMExports } from "node:module"
import { fileURLToPath } from "node:url"

const require = createRequire(import.meta.url)
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const CORE_PATH = path.join(REPO_ROOT, "skills/story-setup/references/templates/hooks/story_hook_core.js")
const CONTRACT_PATH = path.join(REPO_ROOT, "scripts/current-contract.json")
const DETECTOR_PATH = path.join(REPO_ROOT, "skills/story-long-write/scripts/check-ai-patterns.js")
const STORYCTL_PATH = path.join(REPO_ROOT, "skills/story-long-write/scripts/storyctl.js")
const TRACKING_PATH = path.join(REPO_ROOT, "skills/story-long-write/scripts/tracking_commit.js")

const core = require(CORE_PATH)

function mkTmp(prefix) {
  return fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), prefix)))
}

function write(file, content) {
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, content, "utf8")
}

function writeCleanState(book, lastCommitted = 0, revision = 0, ctxRev = revision) {
  write(
    path.join(book, "追踪", "_tracking-state.json"),
    JSON.stringify({ schema_version: 4, state_revision: revision, last_committed_chapter: lastCommitted }) + "\n"
  )
  write(path.join(book, "追踪", "上下文.md"), `> 状态修订：${ctxRev}\n`)
}

test("proseNetFindings covers hard signals, quotes, apostrophes, toxic rules, comments, and exemption markers", () => {
  const fixtures = {
    clean: "江晨睁开眼天还没亮。\n他要快要狠要赢这是唯一的活路。\n「作为AI管家，我劝你别白费力气。」\n他握紧拳头走向门口。",
    truncate: "江晨握紧拳头慢慢走向门口。\n江晨冲过去一拳砸在",
    truncate_astral: "他继续往前走。\n开头😀😀😀😀😀😀😀😀😀😀😀😀😀X",
    refuse: "夜色压下来。\n作为AI我无法继续创作这部分内容。",
    refuse_after_quote: "“任务完成。”作为AI，我无法继续创作。",
    refuse_before_quote: "作为AI，我无法继续创作。“你别怕。”",
    refuse_after_multiple_quotes: "“甲说完了。”“乙也点头。”我无法继续创作。",
    refuse_quoted_ok: "“作为AI，我无法继续创作。”",
    refuse_quoted_with_prefix_ok: "他说：“作为AI，我无法继续创作。”",
    refuse_english_quoted_ok: "“I cannot continue writing this scene.”",
    refuse_unclosed_quote: "“任务完成。作为AI，我无法继续创作。",
    refuse_apostrophe_contractions: "don't 作为AI，我无法继续创作。 John's!",
    refuse_curly_apostrophe_contractions: "don’t 作为AI，我无法继续创作。 John’s!",
    refuse_mixed_curly_apostrophe_contractions: "don‘t 作为AI，我无法继续创作。 John’s!",
    refuse_single_quoted_ok: "他说：'作为AI，我无法继续创作。'然后关了门。",
    refuse_curly_single_quoted_ok: "他说：‘作为AI，我无法继续创作。’然后关了门。",
    refuse_name_in_single_quote_ok: "'读完 O'Connor 的信，我无法继续写下去。'她合上笔记本。",
    refuse_name_in_curly_quote_ok: "‘读完 O’Connor 的信，我无法继续写下去。’她合上笔记本。",
    refuse_contraction_in_single_quote_ok: "'I can't write. 作为AI，我无法继续创作。'她放下了笔。",
    refuse_contraction_in_curly_quote_ok: "‘I can’t write. 作为AI，我无法继续创作。’她放下了笔。",
    refuse_unclosed_apostrophe: "'作为AI，我无法继续创作。 O'Connor 沉默了。",
    refuse_quote_before_name_ok: "‘我无法继续写下去。’O’Connor 合上了笔记本。",
    ai_selfref_model: "夜色压下来。\n作为一个AI语言模型，我需要提醒您接下来的情节包含暴力描写。",
    ai_selfref_assistant: "他推门进来。\n作为一个AI助手，这段内容涉及敏感话题。",
    ai_selfref_era_ok: "作为一个人工智能时代的产物，他对孤独习以为常。\n他把灯关了。",
    terminal_banner_ok: "他抬起手按在光屏上。\n【叮！任务完成，奖励已发放】",
    terminal_ascii_quote_ok: "他站起来推开门。\n他说：\"我回来了。\"",
    terminal_signoff_ok: "她推开门走进阳光里。\n（全文完）",
    terminal_signoff_dash_ok: "她推开门走进阳光里。\n-完-",
    juqing_jiedian_ok: "他深吸一口气。\n熬到必死的剧情节点过去，他就自由了。",
    toxic_quote_codename_ok: "他把烟头按进烟灰缸。\n这一战注定是「血屠」的开端，没人料到后来会那样。",
    engword: "街灯一盏盏亮起。\n按照本章细纲的情节点他该出场了。",
    repeat: "他握紧拳头一步步走过去缓缓逼近。\n他握紧拳头一步步走过去缓缓逼近。\n他终于停下了。",
    repeat_seven_ok: "一二三四五六七\n一二三四五六七\n他停下了。",
    repeat_eight: "一二三四五六七八\n一二三四五六七八\n他停下了。",
    repeat_astral_seven_ok: "😀😀😀😀😀😀😀\n😀😀😀😀😀😀😀\n他停下了。",
    repeat_astral_eight: "😀😀😀😀😀😀😀😀\n😀😀😀😀😀😀😀😀\n他停下了。",
    placeholder: "他打开门。\n（此处省略三百字打斗描写）他赢了。",
    english_ai: "他说。\nI cannot continue writing this scene for you.",
    parallel: "要么生，要么死。\n要么战，要么逃。\n要么赢，要么输。\n他做出了选择。",
    danmaku: "前方高能！\n前方高能！预警。\n这一段我哭了。\n作者加更！",
    toxic_single_voice_ok: "他开口了。\n声音不高，第一句却稳稳压住了整个大厅。",
    toxic_single_negation_ok: "没有伴奏，没有和声，没有提词器。\n台下静了三秒。",
    toxic_two_notis_ok: "不是没有想过退路，而是根本没有退路。\n是真嗓子，不是修音修出来的。\n他把门关上了。",
    toxic_single_trailer_ok: "他放下麦克风朝台下鞠了一躬。\n没人知道他去了哪里。",
    toxic_voice: "他开口了。\n声音不高，第一句却稳稳压住了整个大厅。\n她声音不大，却让后排的人都听清了。",
    toxic_negation: "没有伴奏，没有和声，没有提词器。\n没有灯光，没有掌声，没有退路。\n台下静了三秒。",
    toxic_cross_negation: "不是嚎啕大哭。\n\n也不是扯着嗓子喊不舍。\n\n只是一个人走远了，留在原地的人还站着。",
    toxic_cross_negation_dialogue_ok: "“不是嚎啕大哭。”\n\n“也不是扯着嗓子喊不舍。”\n\n“只是舍不得。”",
    toxic_reverse_notis: "是真嗓子，不是修音修出来的。\n是硬功夫，不是花架子撑出来的。\n是实打实的底气，不是装出来的。\n他清了清嗓子接着唱。",
    toxic_forward_notis: "不是没有想过退路，而是根本没有退路。\n不是不敢开口，而是懒得废话。\n不是输不起，而是没必要让。\n他把门关上了。",
    toxic_trailer: "他放下麦克风朝台下鞠了一躬。\n没人知道，这才刚刚开头。",
    toxic_trailer_summary: "他放下麦克风朝台下鞠了一躬。\n这一切都结束了。",
    toxic_trailer_summary_fate: "她把账单折好塞回包里。\n这一夜注定无人入眠。",
    toxic_trailer_summary_sozhe: "他把钥匙交了出去。\n就这样，一切都结束了。",
    toxic_trailer_summary_new_chapter: "他收拾好行李。\n新的篇章就此开始。",
    toxic_trailer_summary_fate_gear: "他握紧了那枚铜钱。\n命运的齿轮开始转动。",
    toxic_trailer_shubuzhi: "他笑着把门关上。\n殊不知门外早有人等着。\n没人知道后面会发生什么。",
    toxic_trailer_imminent: "城门缓缓合拢。\n一场大战即将来临。\n没人知道后面会发生什么。",
    toxic_trailer_pressing: "他站在城头往下看。\n黑压压的军阵正朝着城门压过去。\n没人知道后面会发生什么。",
    toxic_trailer_alternatives: "他走了。\n谁也不知道他去了哪里。\n谁也没想到会是他。\n这才刚刚开始。\n一场好戏拉开序幕。\n大戏终于拉开帷幕。\n好戏即将开始。\n风暴即将降临。\n潮水正向着堤岸涌来。\n敌军正朝着营地逼了过来。\n骑兵正朝着山口袭过去。\n这一天注定要被记住。\n这一切都说明了问题。\n这一切意味着新生。\n就这样，全部收场。\n就这样，一切都落幕。\n新的旅程就此展开。\n崭新的篇章正在展开。\n新的人生从此开始。",
    toxic_bare_realize_ok: "那一刻我终于明白，母亲当年为什么总在夜里哭。\n我抓起外套就往门口走。",
    toxic_summary_subclause_ok: "等这一切结束了，我们就能过上平静幸福的生活了。\n他把门带上了。",
    toxic_summary_idiom_ok: "世间的这一刻，所有人都接受了命中注定的结局！\n他转身走了。",
    toxic_dialogue_ok: "「没人知道。」\n他笑了笑接着往前走。",
    toxic_eitheror_ok: "不是生就是死，他认了。\n他推门走了进去。",
    toxic_affirm_ok: "是啊，不是他的错。\n他把灯关了。",
    toxic_shibushi_ok: "他问自己是不是听错了，是不是灯光太晃。\n他揉了揉眼睛。",
    toxic_question_ok: "是不是他干的，不是我干的。\n他说不清。",
    toxic_rhetorical_ok: "是挺好的一件事，不是吗。\n他点了点头。",
    toxic_curtain_ok: "钟声再度响起，比赛正式拉开序幕。\n他站上了台。",
    toxic_quote_mid_ok: "她的声音不大好听，被人截成“名场面”，但她不在乎。\n台下没有掌声，没有“安可”声，只有此起彼伏的咳嗽。",
    toxic_multi_tail_ok: "是他的错，不是我的错，不是吗。\n他点了点头。",
    toxic_exempt_marker_ok: "# 第1章\n<!-- 去味:跳过 -->\n没有伴奏，没有和声，没有提词器。没有灯光，没有掌声，没有退路。",
    toxic_exempt_fullwidth_ok: "# 第1章\n<!-- 去味：跳过 -->\n没有伴奏，没有和声，没有提词器。没有灯光，没有掌声，没有退路。",
    toxic_exempt_spaced_ok: "# 第1章\n<!--去味 ： 跳过\t-->\n没有伴奏，没有和声，没有提词器。没有灯光，没有掌声，没有退路。",
    toxic_exempt_bare_blocked: "# 第1章\n去味:跳过\n没有伴奏，没有和声，没有提词器。没有灯光，没有掌声，没有退路。",
    toxic_exempt_other_nets: "# 第1章\n<!-- 去味:跳过 -->\n没有伴奏，没有和声，没有提词器。没有灯光，没有掌声，没有退路。\n按照本章细纲的情节点他该出场了。",
    toxic_comment_ok: "他推开门。\n\n<!-- 备注：声音不大，却让人心里一紧。声音不高，却压住了整间屋子。 -->\n他走了进去。",
    toxic_comment_multiline_ok: "他推开门。\n<!-- 备注\n声音不高，却稳稳压住了整个大厅。\n声音不大，却让全场安静下来。\n-->\n他走了进去。",
    toxic_comment_inline: "他推开门。<!-- 备注 -->声音不高，却稳稳压住了整个大厅。声音不大，却让全场安静下来。",
    toxic_comment_unclosed: "他推开门。\n<!-- 备注没闭合\n声音不高，却稳稳压住了整个大厅。声音不大，却让全场安静下来。",
    toxic_comment_unclosed_after_closed: "<!-- 备注 -->\n他推开门。\n<!-- 没闭合 <!-- 也没闭合\n声音不高，却稳稳压住了整个大厅。声音不大，却让全场安静下来。",
    toxic_astral_window_ok: "没人知道他练了多少年。也没人知道他去了哪里。\n" + Array.from({ length: 30 }, (_, i) => `“第${i + 1}排😀😀😀😀😀😀😀😀😀😀”`).join("\n"),
    toxic_trailer_window_ok: "没人知道他练了多少年。也没人知道他去了哪里。\n" + "江晨把这段视频剪了又剪从凌晨剪到天亮每一帧都抠得死死的。".repeat(22) + "\n他把琴盖合上，起了身。",
  }

  const results = Object.fromEntries(Object.entries(fixtures).map(([k, v]) => [k, core.proseNetFindings(v)]))

  const silentKeys = [
    "clean", "refuse_quoted_ok", "refuse_quoted_with_prefix_ok", "refuse_english_quoted_ok",
    "refuse_single_quoted_ok", "refuse_curly_single_quoted_ok", "refuse_name_in_single_quote_ok",
    "refuse_name_in_curly_quote_ok", "refuse_contraction_in_single_quote_ok",
    "refuse_contraction_in_curly_quote_ok", "refuse_quote_before_name_ok",
    "ai_selfref_era_ok", "terminal_banner_ok", "terminal_ascii_quote_ok",
    "terminal_signoff_ok", "terminal_signoff_dash_ok", "juqing_jiedian_ok",
    "toxic_quote_codename_ok", "repeat_seven_ok", "repeat_astral_seven_ok",
    "parallel", "danmaku", "toxic_single_voice_ok", "toxic_single_negation_ok",
    "toxic_two_notis_ok", "toxic_single_trailer_ok", "toxic_cross_negation",
    "toxic_cross_negation_dialogue_ok", "toxic_bare_realize_ok", "toxic_summary_subclause_ok",
    "toxic_summary_idiom_ok", "toxic_dialogue_ok", "toxic_eitheror_ok", "toxic_affirm_ok",
    "toxic_shibushi_ok", "toxic_question_ok", "toxic_rhetorical_ok", "toxic_curtain_ok",
    "toxic_quote_mid_ok", "toxic_multi_tail_ok", "toxic_exempt_marker_ok",
    "toxic_exempt_fullwidth_ok", "toxic_exempt_spaced_ok", "toxic_comment_ok",
    "toxic_comment_multiline_ok", "toxic_astral_window_ok", "toxic_trailer_window_ok",
  ]
  for (const key of silentKeys) {
    assert.deepEqual(results[key], [], `expected ${key} to be silent`)
  }

  assert.match(results.refuse[0], /^第2行 元信息泄漏（AI 自指）/)
  assert.match(results.refuse_after_quote[0], /^第1行 元信息泄漏（AI 自指）/)
  assert.match(results.refuse_before_quote[0], /^第1行 元信息泄漏（AI 自指）/)
  assert.match(results.refuse_after_multiple_quotes[0], /^第1行 元信息泄漏（生成拒绝语）/)
  assert.match(results.refuse_unclosed_quote[0], /^第1行 元信息泄漏（AI 自指）/)
  assert.match(results.refuse_apostrophe_contractions[0], /^第1行 元信息泄漏（AI 自指）/)
  assert.match(results.refuse_curly_apostrophe_contractions[0], /^第1行 元信息泄漏（AI 自指）/)
  assert.match(results.refuse_mixed_curly_apostrophe_contractions[0], /^第1行 元信息泄漏（AI 自指）/)
  assert.match(results.refuse_unclosed_apostrophe[0], /^第1行 元信息泄漏（AI 自指）/)
  assert.match(results.ai_selfref_model[0], /^第2行 元信息泄漏（AI 自指）/)
  assert.match(results.ai_selfref_assistant[0], /^第2行 元信息泄漏（AI 自指）/)
  assert.match(results.english_ai[0], /^第2行 元信息泄漏（英文 AI 腔）/)
  assert.match(results.engword[0], /^第2行 工程词泄漏/)
  assert.match(results.placeholder[0], /^第2行 占位符/)
  assert.match(results.repeat[0], /^第2行 紧邻复读/)
  assert.match(results.repeat_eight[0], /^第2行 紧邻复读/)
  assert.match(results.repeat_astral_eight[0], /^第2行 紧邻复读/)
  assert.match(results.truncate[0], /^第2行 疑似截断/)
  assert.match(results.truncate_astral[0], /^第2行 疑似截断/)
  assert.ok(!results.truncate_astral[0].includes("\uFFFD"), "astral slice must not split surrogate pairs")

  assert.match(results.toxic_voice[0], /^第2行 毒句式\[voice-contrast\]/)
  assert.match(results.toxic_negation[0], /^第1行 毒句式\[negation-parade\]/)
  assert.match(results.toxic_reverse_notis[0], /^第1行 毒句式\[reverse-not-is\]/)
  assert.match(results.toxic_forward_notis[0], /^第1行 毒句式\[not-is-comparison\]/)
  assert.match(results.toxic_trailer[0], /^第2行 毒句式\[trailer-ending\]/)
  assert.match(results.toxic_trailer_summary[0], /^第2行 毒句式\[trailer-summary\]/)
  assert.match(results.toxic_trailer_summary_fate[0], /^第2行 毒句式\[trailer-summary\]/)
  assert.match(results.toxic_trailer_summary_sozhe[0], /^第2行 毒句式\[trailer-summary\]/)
  assert.match(results.toxic_trailer_summary_new_chapter[0], /^第2行 毒句式\[trailer-summary\]/)
  assert.match(results.toxic_trailer_summary_fate_gear[0], /^第2行 毒句式\[trailer-summary\]/)
  assert.match(results.toxic_trailer_shubuzhi[0], /^第2行 毒句式\[trailer-ending\]/)
  assert.match(results.toxic_trailer_imminent[0], /^第2行 毒句式\[trailer-ending\]/)
  assert.match(results.toxic_trailer_pressing[0], /^第2行 毒句式\[trailer-ending\]/)
  assert.equal(results.toxic_trailer_alternatives.filter((l) => l.includes("毒句式[trailer-ending]")).length, 10)
  assert.equal(results.toxic_trailer_alternatives.filter((l) => l.includes("毒句式[trailer-summary]")).length, 8)
  assert.ok(results.toxic_exempt_bare_blocked.some((l) => l.includes("毒句式")))
  assert.match(results.toxic_exempt_other_nets[0], /^第4行 工程词泄漏/)
  assert.ok(!results.toxic_exempt_other_nets.some((l) => l.includes("毒句式")))
  assert.match(results.toxic_comment_inline[0], /^第1行 毒句式\[voice-contrast\]/)
  assert.match(results.toxic_comment_unclosed[0], /^第3行 毒句式\[voice-contrast\]/)
  assert.match(results.toxic_comment_unclosed_after_closed[0], /^第4行 毒句式\[voice-contrast\]/)

  // HTML comment masking matches check-ai-patterns.js on every comment fixture
  const tmp = mkTmp("hook-core-comments-")
  try {
    for (const key of [
      "toxic_comment_ok",
      "toxic_comment_multiline_ok",
      "toxic_comment_inline",
      "toxic_comment_unclosed",
      "toxic_comment_unclosed_after_closed",
    ]) {
      const f = path.join(tmp, `${key}.md`)
      fs.writeFileSync(f, fixtures[key], "utf8")
      const det = spawnSync(process.execPath, [DETECTOR_PATH, "--json", f], { encoding: "utf8" })
      const detHit = (det.stdout || "").includes('"voice-contrast"')
      const hookHit = results[key].some((l) => l.includes("voice-contrast"))
      assert.equal(hookHit, detHit, `${key} hook vs check-ai-patterns.js mismatch`)
    }
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true })
  }
})

test("cross-file parity with check-ai-patterns.js across all 6 toxic prose rules, exclusions, and scale", () => {
  const TOXIC_RULES = [
    "voice-contrast",
    "negation-parade",
    "not-is-comparison",
    "reverse-not-is",
    "trailer-ending",
    "trailer-summary",
  ]
  // ~9,000 CJK chars (scale = floor((9000 + 2250) / 4500) = 2)
  const longPad = "江晨沿着河岸走过石桥，风吹得衣摆猎猎作响，他把账本折好塞进怀里继续赶路。\n".repeat(260)

  const cases = {
    // 1. voice-contrast (threshold 2 * scale)
    vc_block: {
      text: "他开口了。\n声音不高，第一句却稳稳压住了整个大厅。\n她声音不大，却让后排的人都听清了。\n",
      expectedRules: ["voice-contrast"],
    },
    vc_below: {
      text: "他开口了。\n声音不高，第一句却稳稳压住了整个大厅。\n台下静了三秒。\n",
      expectedRules: [],
    },
    vc_quoted_ok: {
      text: "他说：「声音不高，第一句却稳稳压住了整个大厅。」\n她回道：「声音不大，却让后排的人都听清了。」\n",
      expectedRules: [],
    },
    vc_scale2_below: {
      text: `${longPad}声音不高，第一句却稳稳压住了整个大厅。\n她声音不大，却让后排的人都听清了。\n`,
      expectedRules: [],
    },
    vc_scale2_block: {
      text:
        `${longPad}` +
        "声音不高，第一句却稳稳压住了整个大厅。\n" +
        "她声音不大，却让后排的人都听清了。\n" +
        "他声音并不响亮，偏偏字字清楚。\n" +
        "老者声音不高，但整个院子都静了。\n",
      expectedRules: ["voice-contrast"],
    },

    // 2. negation-parade (threshold 2 * scale)
    np_block: {
      text: "没有伴奏，没有和声，没有提词器。\n没有灯光，没有掌声，没有退路。\n台下静了三秒。\n",
      expectedRules: ["negation-parade"],
    },
    np_below: {
      text: "没有伴奏，没有和声，没有提词器。\n台下静了三秒。\n",
      expectedRules: [],
    },
    np_scale2_below: {
      text: `${longPad}没有伴奏，没有和声，没有提词器。\n没有灯光，没有掌声，没有退路。\n`,
      expectedRules: [],
    },
    np_scale2_block: {
      text:
        `${longPad}` +
        "没有伴奏，没有和声，没有提词器。\n" +
        "没有灯光，没有掌声，没有退路。\n" +
        "没有废话，没有铺垫，没有客套。\n" +
        "没有退路，没有援军，没有侥幸。\n",
      expectedRules: ["negation-parade"],
    },

    // 3. not-is-comparison (combined with reverse-not-is, threshold 3 * scale)
    ni_block: {
      text:
        "不是没有想过退路，而是根本没有退路。\n" +
        "不是不敢开口，而是懒得废话。\n" +
        "不是输不起，而是没必要让。\n" +
        "他把门关上了。\n",
      expectedRules: ["not-is-comparison"],
    },
    ni_below: {
      text: "不是没有想过退路，而是根本没有退路。\n不是不敢开口，而是懒得废话。\n他把门关上了。\n",
      expectedRules: [],
    },
    ni_exclusions_ok: {
      text:
        "不是生就是死，他认了。\n" +
        "他问自己是不是听错了，是不是灯光太晃。\n" +
        "不是没有想过退路，是吗。\n" +
        "不是不愿意去，是的，他太累了。\n" +
        "他推门走了进去。\n",
      expectedRules: [],
    },
    ni_scale2_below: {
      text:
        `${longPad}` +
        "不是没有想过退路，而是根本没有退路。\n" +
        "不是不敢开口，而是懒得废话。\n" +
        "不是输不起，而是没必要让。\n",
      expectedRules: [],
    },
    ni_scale2_block: {
      text:
        `${longPad}` +
        "不是没有想过退路，而是根本没有退路。\n" +
        "不是不敢开口，而是懒得废话。\n" +
        "不是输不起，而是没必要让。\n" +
        "不是听不懂，而是装糊涂。\n" +
        "不是没机会，而是等时机。\n" +
        "不是怕吃亏，而是算清楚了。\n",
      expectedRules: ["not-is-comparison"],
    },

    // 4. reverse-not-is (combined with not-is-comparison, threshold 3 * scale)
    rni_block: {
      text:
        "是真嗓子，不是修音修出来的。\n" +
        "他稳稳吸了口气。\n" +
        "是硬功夫，不是花架子撑出来的。\n" +
        "台下有人吹了声口哨。\n" +
        "是实打实的底气，不是装出来的。\n" +
        "他清了清嗓子接着唱。\n",
      expectedRules: ["reverse-not-is"],
    },
    rni_combined_block: {
      text:
        "不是没有想过退路，而是根本没有退路。\n" +
        "不是不敢开口，而是懒得废话。\n" +
        "是真嗓子，不是修音修出来的。\n" +
        "他把门关上了。\n",
      expectedRules: ["not-is-comparison", "reverse-not-is"],
    },
    rni_exclusions_ok: {
      text:
        "是啊，不是他的错。\n" +
        "是不是他干的，不是我干的。\n" +
        "是挺好的一件事，不是吗。\n" +
        "还是太年轻，不是对手。\n" +
        "他点了点头。\n",
      expectedRules: [],
    },

    // 5. trailer-ending (tail 600-char window, threshold 2)
    te_block: {
      text: "他放下麦克风朝台下鞠了一躬。\n没人知道，这才刚刚开头。\n",
      expectedRules: ["trailer-ending"],
    },
    te_below: {
      text: "他放下麦克风朝台下鞠了一躬。\n没人知道他去了哪里。\n",
      expectedRules: [],
    },
    te_curtain_ok: {
      text: "钟声再度响起，比赛正式拉开序幕。\n第二场比赛也正式拉开帷幕。\n他站上了台。\n",
      expectedRules: [],
    },
    te_outside_window_ok: {
      text:
        "没人知道他练了多少年。也没人知道他去了哪里。\n" +
        "江晨把这段视频剪了又剪从凌晨剪到天亮每一帧都抠得死死的。".repeat(22) +
        "\n他把琴盖合上，起了身。\n",
      expectedRules: [],
    },

    // 6. trailer-summary (tail 600-char window, threshold 1)
    ts_block: {
      text: "他放下麦克风朝台下鞠了一躬。\n这一切都结束了。\n",
      expectedRules: ["trailer-summary"],
    },
    ts_fate_block: {
      text: "她把账单折好塞回包里。\n这一夜注定无人入眠。\n",
      expectedRules: ["trailer-summary"],
    },
    ts_gear_block: {
      text: "他握紧了那枚铜钱。\n命运的齿轮开始转动。\n",
      expectedRules: ["trailer-summary"],
    },
    ts_exclusions_ok: {
      text:
        "等这一切结束了，我们就能过上平静幸福的生活了。\n" +
        "世间的这一刻，所有人都接受了命中注定的结局！\n" +
        "他转身走了。\n",
      expectedRules: [],
    },
  }

  const tmp = mkTmp("hook-core-6rule-parity-")
  try {
    const files = []
    const fileToKey = new Map()
    for (const [key, spec] of Object.entries(cases)) {
      const f = path.join(tmp, `${key}.md`)
      fs.writeFileSync(f, spec.text, "utf8")
      files.push(f)
      fileToKey.set(f, key)
    }

    const det = spawnSync(process.execPath, [DETECTOR_PATH, "--json", ...files], {
      encoding: "utf8",
      maxBuffer: 10 * 1024 * 1024,
    })
    assert.ok(det.status === 0 || det.status === 1, `check-ai-patterns.js failed (${det.status}): ${det.stderr}`)
    const parsed = JSON.parse(det.stdout)
    const detByKey = Object.fromEntries(Object.keys(cases).map((k) => [k, new Set()]))
    for (const finding of parsed.findings) {
      if (finding.severity !== "blocking" && finding.severity !== "review_required") continue
      if (!TOXIC_RULES.includes(finding.type)) continue
      const key = fileToKey.get(finding.file)
      if (key) detByKey[key].add(finding.type)
    }

    for (const [key, spec] of Object.entries(cases)) {
      const hookFindings = core.proseNetFindings(spec.text)
      const hookRules = new Set()
      for (const line of hookFindings) {
        const m = line.match(/毒句式\[([a-z-]+)\]/)
        if (m) hookRules.add(m[1])
      }
      const detRules = detByKey[key]
      assert.deepEqual(
        [...hookRules].sort(),
        [...detRules].sort(),
        `${key}: story_hook_core vs check-ai-patterns.js blocking rule mismatch`
      )
      assert.deepEqual(
        [...hookRules].sort(),
        [...spec.expectedRules].sort(),
        `${key}: unexpected blocking rule set`
      )
    }
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true })
  }
})

test("CURRENT_AGENTS_VERSION, readSentinel, and agentsVersionNotice match current-contract.json and handle all states", () => {
  const contract = JSON.parse(fs.readFileSync(CONTRACT_PATH, "utf8"))
  assert.equal(core.CURRENT_AGENTS_VERSION, contract.agents_version)

  const root = mkTmp("hook-core-sentinel-")
  try {
    // Missing .story-deployed -> null sentinel, silent notice
    assert.equal(core.readSentinel(root), null)
    assert.equal(core.agentsVersionNotice(root), "")

    // Current version (even quoted and with lagging setup_skill_version) -> silent
    write(
      path.join(root, ".story-deployed"),
      `agents_version: "${contract.agents_version}"\nsetup_skill_version: 1.2.6\ntarget_cli: codex\n`
    )
    const parsed = core.readSentinel(root)
    assert.equal(parsed.agents_version, String(contract.agents_version))
    assert.equal(parsed.target_cli, "codex")
    assert.equal(core.agentsVersionNotice(root), "")

    // Stale version -> warns with custom setupCommand
    write(path.join(root, ".story-deployed"), `agents_version: ${contract.agents_version - 1}\ntarget_cli: codex\n`)
    const staleNotice = core.agentsVersionNotice(root, { setupCommand: "$story-setup" })
    assert.match(staleNotice, new RegExp(`agents_version=${contract.agents_version - 1} 低于 v${contract.agents_version}`))
    assert.match(staleNotice, /重新运行 \$story-setup/)

    // Future version -> downgrade warning
    write(path.join(root, ".story-deployed"), `agents_version: ${contract.agents_version + 1}\ntarget_cli: codex\n`)
    const futureNotice = core.agentsVersionNotice(root, { setupCommand: "$story-setup" })
    assert.match(futureNotice, new RegExp(`高于本 hook 支持的 v${contract.agents_version}`))
    assert.match(futureNotice, /不要降级覆盖/)

    // Missing or non-numeric agents_version -> warns
    write(path.join(root, ".story-deployed"), "agents_version: abc\ntarget_cli: zcode\n")
    const badNotice = core.agentsVersionNotice(root, { setupCommand: "$story-setup" })
    assert.match(badNotice, /缺少数字 agents_version/)
    assert.match(badNotice, /\$story-setup/)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test("proseNetFindings does not measure chapter wordcount (delegated solely to storyctl)", () => {
  const shortChapter = `# 第1章\n${"字".repeat(800)}。\n`
  assert.deepEqual(core.proseNetFindings(shortChapter), [])
})

test("extractProseTargets, extractPatchTargets, isGitCommitCommand, and ReDoS budget", () => {
  const proseCases = [
    ["echo x > book/正文/第1章.md", ["book/正文/第1章.md"]],
    ["echo x >| book/正文/第1章.md", ["book/正文/第1章.md"]],
    ["echo x >& book/正文/第1章.md", ["book/正文/第1章.md"]],
    ["echo book/正文/第1章.md >&2", []],
    ["cat a >> 正文.md", ["正文.md"]],
    ["echo x | tee book/正文/第2章.md", ["book/正文/第2章.md"]],
    ["printf y | tee -a 正文.md", ["正文.md"]],
    ["printf y | tee -- book/正文/第2章.md", ["book/正文/第2章.md"]],
    ["printf y | tee notes.md book/正文/第2章.md", ["book/正文/第2章.md"]],
    ["touch book/正文/第3章.md", ["book/正文/第3章.md"]],
    ["touch notes.md book/正文/第3章.md", ["book/正文/第3章.md"]],
    ["touch -r book/正文/第1章.md notes.md", []],
    ["cp src.md book/正文/第4章.md", ["book/正文/第4章.md"]],
    ["command cp src.md book/正文/第4章.md", ["book/正文/第4章.md"]],
    ["command -p cp src.md book/正文/第4章.md", ["book/正文/第4章.md"]],
    ["command -- cp src.md book/正文/第4章.md", ["book/正文/第4章.md"]],
    ["env -u FOO cp src.md book/正文/第4章.md", ["book/正文/第4章.md"]],
    ["env --unset FOO cp src.md book/正文/第4章.md", ["book/正文/第4章.md"]],
    ["/bin/cp src.md book/正文/第4章.md", ["book/正文/第4章.md"]],
    ["cp draft/第4章.md book/正文/", ["book/正文/第4章.md"]],
    ["cp --target-directory=book/正文 draft/第4章.md", ["book/正文/第4章.md"]],
    ["install draft.md book/正文/第4章.md", ["book/正文/第4章.md"]],
    ["mv 正文.md", []],
    ["cp -f a.md 正文.md", ["正文.md"]],
    ["grep -n book/正文/第1章.md notes.md", []],
    ['cat draft.md > "my book/正文/第1章_x.md"', ["my book/正文/第1章_x.md"]],
    ["cat draft.md > book/正文/第003章　开局.md", ["book/正文/第003章　开局.md"]],
    ["printf x | tee 'my book/正文/第1章_x.md'", ["my book/正文/第1章_x.md"]],
    ['cp draft.md "my book/正文/第1章_x.md"', ["my book/正文/第1章_x.md"]],
    ['cp draft.md "book|archive/正文/第11章.md"', ["book|archive/正文/第11章.md"]],
    ["echo '> book/正文/第7章.md'", []],
    ["cat <<EOF\n> book/正文/第7章.md\nEOF", []],
    ["cat <<A <<B\nfirst\nA\n> book/正文/第7章.md\nB", []],
    ["cat <<\\EOF\n> book/正文/第7章.md\nEOF", []],
    ["cat <<\\EOF\nliteral\nEOF\necho x > book/正文/第7章.md", ["book/正文/第7章.md"]],
    ['printf \'%s\\n\' "literal \\" | tee book/正文/第7章.md"', []],
    ["sh -c 'echo x > book/正文/第7章.md'", ["book/正文/第7章.md"]],
    ["bash -lc 'echo x > book/正文/第7章.md'", ["book/正文/第7章.md"]],
    ['echo "$(echo x > book/正文/第7章.md)"', ["book/正文/第7章.md"]],
    ['echo "`echo x > book/正文/第7章.md`"', ["book/正文/第7章.md"]],
    ['cd "/p/书" && cat > 正文/第022章_x.md <<EOF\nhi\nEOF', ["/p/书/正文/第022章_x.md"]],
    ["cd /a && cd b && tee 正文/第3章.md", ["/a/b/正文/第3章.md"]],
    ["cd 书 && cp draft.md 正文/第2章.md", ["书/正文/第2章.md"]],
    ["cd 书 && cat draft >| 正文/第3章.md", ["书/正文/第3章.md"]],
    ["cd 书 && echo x >& 正文/第3章.md", ["书/正文/第3章.md"]],
    ["cd 书 && echo x &> 正文/第3章.md", ["书/正文/第3章.md"]],
    ["cd 书/正文 && cat > 第3章.md", ["书/正文/第3章.md"]],
    ["cd 正文 && tee 第3章.md", ["正文/第3章.md"]],
    ["cd 书 && cat x > 正文/第3章.md 2>&1 | tee log", ["书/正文/第3章.md"]],
  ]
  for (const [cmd, expected] of proseCases) {
    assert.deepEqual(core.extractProseTargets(cmd), expected, cmd)
  }

  assert.deepEqual(core.extractPatchTargets("*** Begin Patch\n*** Add File: book/正文/第5章.md\n+正文\n*** End Patch"), ["book/正文/第5章.md"])
  assert.deepEqual(core.extractPatchTargets("*** Begin Patch\n*** Update File: draft.md\n*** Move to: book/正文/第6章.md\n+正文\n*** End Patch"), ["book/正文/第6章.md"])
  assert.deepEqual(core.extractPatchTargets("*** Begin Patch\n*** Delete File: draft.md\n*** Move to: book/正文/第7章.md\n*** End Patch"), ["book/正文/第7章.md"])
  assert.deepEqual(core.extractPatchTargets("*** Begin Patch\n*** Update File: book/正文/第8章.md\n*** Move to: draft.md\n+x\n*** End Patch"), ["draft.md"])
  assert.deepEqual(core.extractPatchTargets("*** Begin Patch\n*** Delete File: book/正文/第9章.md\n*** End Patch"), [])
  assert.deepEqual(core.extractPatchTargets("*** Begin Patch\n*** Add File: notes.md\n+x\n*** Update File: draft.md\n*** Move to: book/正文/第10章.md\n+正文\n*** End Patch"), ["notes.md", "book/正文/第10章.md"])
  assert.deepEqual(core.extractPatchTargets("*** Begin Patch\n*** Update File: book/正文/第12章.md\n@@\n *** Move to: notes.md\n+正文\n*** End Patch"), ["book/正文/第12章.md"])

  for (const cmd of [
    "git commit -m x",
    "git add . && git commit -m x",
    "if true; then git commit -m x; fi",
    "for f in *; do git commit -am x; done",
    "(cd sub && git commit)",
    "FOO=1 git commit",
    "git -c user.name=x commit",
    "git -C sub commit -m y",
  ]) {
    assert.equal(core.isGitCommitCommand(cmd), true, cmd)
  }
  for (const cmd of ["echo git commit docs", "git status && echo done"]) {
    assert.equal(core.isGitCommitCommand(cmd), false, cmd)
  }

  // Linear shellWords ReDoS regression (< 2000ms)
  const tricky = 'git commit -m "fix: 正则转义覆盖 ' + Array.from({ length: 18 }, () => "\\\\x").join(" ") + ' covered | see README"'
  const t0 = Date.now()
  assert.equal(core.isGitCommitCommand(tricky), true)
  assert.ok(Date.now() - t0 < 2000, "shellWords exceeded 2000ms budget")
})

test("stagedMarkdownWarnings narrows character sheets and passes windowsHide: true", () => {
  const repo = mkTmp("hook-core-staged-")
  const origSpawn = childProcess.spawnSync
  const calls = []
  try {
    execFileSync("git", ["-C", repo, "init", "-q"])
    write(path.join(repo, "book/正文/第1章.md"), "身高: 180\n他推门而入。\n年龄　：18\n")
    write(path.join(repo, "设定/主角.md"), "NAME：林远\n")
    write(path.join(repo, "设定/配角.md"), "　名字 ：苏离\n")
    write(path.join(repo, "设定/反派.md"), "简介：没有名字字段\n")
    write(path.join(repo, "设定/角色/新人.md"), "简介：没有名字字段的角色卡\n")
    write(path.join(repo, "设定/关系.md"), "# 角色关系图\n")
    write(path.join(repo, "设定/文风.md"), "# 文风\n")
    write(path.join(repo, "设定/世界观/地理.md"), "# 地理\n")
    execFileSync("git", ["-C", repo, "add", "-A"])

    childProcess.spawnSync = (cmd, args, opts) => {
      calls.push({ cmd, args, opts })
      return origSpawn(cmd, args, opts)
    }
    syncBuiltinESMExports()
    // Re-require fresh module so its destructured spawnSync uses the spy
    delete require.cache[require.resolve(CORE_PATH)]
    const freshCore = require(CORE_PATH)
    const out = freshCore.stagedMarkdownWarnings(repo)

    assert.match(out, /正文硬编码角色属性，应引用设定文件/)
    assert.match(out, /反派\.md: 设定文件缺少 name\/名字 必填字段。/)
    assert.match(out, /设定\/角色\/新人\.md: 设定文件缺少 name\/名字 必填字段。/)
    assert.ok(!out.includes("主角.md"))
    assert.ok(!out.includes("配角.md"))
    assert.ok(!out.includes("关系.md"))
    assert.ok(!out.includes("文风.md"))
    assert.ok(!out.includes("地理.md"))
    assert.equal(calls.length, 1)
    assert.equal(calls[0].opts?.windowsHide, true)
  } finally {
    childProcess.spawnSync = origSpawn
    syncBuiltinESMExports()
    delete require.cache[require.resolve(CORE_PATH)]
    fs.rmSync(repo, { recursive: true, force: true })
  }
})

test("proseBlockReason, outlineIsEmpty, debt gate, trackingCheckpointIssue, and toxicRescanHint", () => {
  const root = mkTmp("hook-core-block-")
  try {
    const filled = "# 第2章 细纲\n江晨在雨夜推开旧书店的门，发现柜台后坐着失踪三年的师父，两人对视良久谁都没先开口。\n"
    const toxic = "声音不大，却带着一股狠劲。他声音不高，却压住了整间屋子。\n"

    write(path.join(root, "long/大纲/细纲_第2章.md"), filled)
    writeCleanState(path.join(root, "long"), 1)
    assert.match(core.proseBlockReason(root, path.join(root, "long/正文/第1章_起.md")), /细纲_第001章\.md/)
    assert.equal(core.proseBlockReason(root, path.join(root, "long/正文/第2章_承.md")), null)

    write(path.join(root, "short/设定.md"), "")
    write(path.join(root, "short2/其他.md"), "")
    assert.match(core.proseBlockReason(root, path.join(root, "short/正文.md")), /小节大纲\.md/)
    assert.equal(core.proseBlockReason(root, path.join(root, "short2/正文.md")), null)

    // Bare project without scaffolding fails closed
    fs.mkdirSync(path.join(root, "bare/正文"), { recursive: true })
    assert.match(core.proseBlockReason(root, path.join(root, "bare/正文/第1章_起.md")), /缺少细纲/)

    // Unexpanded shell variables fail closed with explicit message
    const varReason = core.proseBlockReason(root, path.join(root, "$PROJ/正文/第001章_x.md"))
    assert.match(varReason, /未展开的 shell 变量/)
    assert.ok(!varReason.includes("缺少细纲"))
    assert.match(core.proseBlockReason(root, path.join(root, "$(pwd)/book/正文/第001章_y.md")), /未展开的 shell 变量/)

    // Prior-chapter toxic prose: softened from hard block to non-blocking pre-write advisory warning
    const debtCases = [
      ["debt", `# 第1章 旧\n\n${toxic}`, true],
      ["marker", `# 第1章 旧\n<!-- 去味:跳过 -->\n${toxic}`, false],
      ["fullwidth", `# 第1章 旧\n<!-- 去味：跳过 -->\n${toxic}`, false],
      ["spaced", `# 第1章 旧\n<!--  去味 : 跳过\t-->\n${toxic}`, false],
      ["bare", `# 第1章 旧\n去味:跳过\n${toxic}`, true],
      ["marker7", `# 第1章 旧\n1\n2\n3\n4\n5\n<!-- 去味:跳过 -->\n${toxic}`, true],
    ]
    for (const [name, prevBody, shouldWarn] of debtCases) {
      const b = path.join(root, name)
      write(path.join(b, "大纲/细纲_第2章.md"), filled)
      write(path.join(b, "正文/第1章_旧.md"), prevBody)
      writeCleanState(b, 1)
      const target = path.join(b, "正文/第2章_新.md")
      assert.equal(core.proseBlockReason(root, target), null, `${name}: prior-chapter toxic prose must not hard-block`)
      const warnings = core.prosePreWriteWarnings(root, target)
      assert.equal(warnings.length > 0, shouldWarn, name)
      if (shouldWarn) {
        assert.match(warnings.join("\n"), /写前复核提醒.*疑似 AI 毒句式/)
        assert.match(core.formatPreWriteAdvisory(warnings), /写正文前软门禁提醒/)
      }
    }

    // Prior-chapter > 6 hits does not hard-block, and advisory points to chapter check for chapter 1
    const many = path.join(root, "many")
    write(path.join(many, "大纲/细纲_第2章.md"), filled)
    write(path.join(many, "正文/第1章_旧.md"), "# 第1章 旧\n" + Array.from({ length: 8 }, (_, i) => `声音不大，却带着第${i + 1}股狠劲。`).join("\n") + "\n他把门关上了。\n")
    writeCleanState(many, 1)
    assert.equal(core.proseBlockReason(root, path.join(many, "正文/第2章_新.md")), null)
    assert.match(
      core.prosePreWriteWarnings(root, path.join(many, "正文/第2章_新.md")).join("\n"),
      /另有 2 处，完整检查：node <story-long-write>\/scripts\/storyctl\.js chapter check --project <书目录> --chapter 1/
    )

    // Empty outline boundary: 29 vs 30 chars, BOM+CRLF, dup, heading content, non-UTF8 GBK
    const body29 = "他推门进屋看见师父坐在柜台后面他推门进屋看见师父"
    const body30 = "他推门进屋看见师父坐在柜台后面他推门进屋看见师父坐"
    const outlineCases = [
      ["oe_zero", Buffer.from(""), true],
      ["oe_heading", Buffer.from("# 第1章 细纲\n## 目标情绪\n  ## 主角选择\n\n"), true],
      ["oe_bomcrlf", Buffer.from("\uFEFF# 第1章 细纲\r\n\r\n　　\t \r\n"), true],
      ["oe_29", Buffer.from(`# 第1章 细纲\n${body29}\n`), true],
      ["oe_30", Buffer.from(`# 第1章 细纲\n${body30}\n`), false],
      ["oe_headcontent", Buffer.from("# 第1章\n## 核心事件：江晨雨夜推门发现失踪三年的师父坐在柜台后\n## 主角选择：留下\n"), false],
      ["oe_gbk", Buffer.from([0xb5, 0xda, 0xb6, 0xfe, 0xcc, 0xec, 0x0a]), false],
    ]
    for (const [name, buf, shouldBlock] of outlineCases) {
      const b = path.join(root, name)
      fs.mkdirSync(path.join(b, "大纲"), { recursive: true })
      fs.writeFileSync(path.join(b, "大纲/细纲_第001章.md"), buf)
      writeCleanState(b, 0)
      const reason = core.proseBlockReason(root, path.join(b, "正文/第001章_a.md"))
      assert.equal(Boolean(reason), shouldBlock, name)
      if (shouldBlock) assert.match(reason, /细纲_第001章\.md）是空的/)
    }

    // Tracking checkpoint matrix: 100% deterministic integrity issues stay HARD; manual 上下文.md mismatch & chapter jump are SOFT
    const cp = path.join(root, "cp")
    fs.mkdirSync(path.join(cp, "missing/追踪"), { recursive: true })
    assert.match(core.trackingCheckpointIssue(path.join(cp, "missing"), true, null), /_tracking-state\.json 缺失/)
    write(path.join(cp, "malformed/追踪/_tracking-state.json"), "{not-json\n")
    write(path.join(cp, "malformed/追踪/上下文.md"), "> 状态修订：0\n")
    assert.match(core.trackingCheckpointIssue(path.join(cp, "malformed"), true, null), /无法解析/)
    write(path.join(cp, "old/追踪/_tracking-state.json"), JSON.stringify({ schema_version: 3, state_revision: 0, last_committed_chapter: 7 }))
    write(path.join(cp, "old/追踪/上下文.md"), "> 状态修订：0\n")
    assert.match(core.trackingCheckpointIssue(path.join(cp, "old"), true, null), /schema_version=4/)
    write(path.join(cp, "badrev/追踪/_tracking-state.json"), JSON.stringify({ schema_version: 4, last_committed_chapter: 7 }))
    assert.match(core.trackingCheckpointIssue(path.join(cp, "badrev"), true, null), /缺少整数 state_revision/)
    write(path.join(cp, "badlast/追踪/_tracking-state.json"), JSON.stringify({ schema_version: 4, state_revision: 0 }))
    assert.match(core.trackingCheckpointIssue(path.join(cp, "badlast"), true, 7), /缺少整数 last_committed_chapter/)

    writeCleanState(path.join(cp, "mismatch"), 7, 1, 0)
    write(path.join(cp, "mismatch/大纲/细纲_第8章.md"), filled)
    assert.equal(core.trackingCheckpointIssue(path.join(cp, "mismatch"), true, null), null)
    assert.equal(core.proseBlockReason(root, path.join(cp, "mismatch/正文/第8章_新.md")), null)
    assert.match(core.inspectTrackingCheckpoint(path.join(cp, "mismatch"), true, null).warnings.join("\n"), /状态修订.*mode=revision 事务/)
    assert.match(core.prosePreWriteWarnings(root, path.join(cp, "mismatch/正文/第8章_新.md")).join("\n"), /状态修订/)

    writeCleanState(path.join(cp, "behind"), 6, 0, 0)
    write(path.join(cp, "behind/大纲/细纲_第8章.md"), filled)
    assert.equal(core.trackingCheckpointIssue(path.join(cp, "behind"), true, 7), null)
    assert.equal(core.proseBlockReason(root, path.join(cp, "behind/正文/第8章_跳章.md")), null)
    assert.match(core.inspectTrackingCheckpoint(path.join(cp, "behind"), true, 7).warnings.join("\n"), /有意跳章起草/)
    assert.match(core.prosePreWriteWarnings(root, path.join(cp, "behind/正文/第8章_跳章.md")).join("\n"), /有意跳章起草/)

    writeCleanState(path.join(cp, "valid"), 7, 0, 0)
    assert.equal(core.trackingCheckpointIssue(path.join(cp, "valid"), true, 7), null)
    assert.deepEqual(core.inspectTrackingCheckpoint(path.join(cp, "valid"), true, 7).warnings, [])
    writeCleanState(path.join(cp, "revised"), 9, 0, 0)
    assert.equal(core.trackingCheckpointIssue(path.join(cp, "revised"), true, 7), null)
    assert.deepEqual(core.inspectTrackingCheckpoint(path.join(cp, "revised"), true, 7).warnings, [])

    // hasHardProseFindings distinguishes hard degeneration/truncation from stylistic-only toxic findings
    const hardBook = path.join(root, "hard-vs-style")
    const pad = "雨落在旧瓦上，檐角的水沿着石阶往下淌，院门外传来车轮碾过碎石的轻响。".repeat(5)
    write(path.join(hardBook, "设定.md"), "# 设定\n")
    const styleOnlyFile = path.join(hardBook, "正文/第001章_纯风格.md")
    write(styleOnlyFile, `# 第1章\n\n${pad}\n${toxic}\n他关上了门。\n`)
    assert.equal(core.hasHardProseFindings(root, styleOnlyFile), false)
    assert.match(core.proseAfterWrite(root, styleOnlyFile), /voice-contrast/)
    const truncatedFile = path.join(hardBook, "正文/第002章_截断.md")
    write(truncatedFile, `# 第2章\n\n${pad}\n他冲过去一拳砸在`)
    assert.equal(core.hasHardProseFindings(root, truncatedFile), true)
    const tinyFile = path.join(hardBook, "正文/第003章_极短.md")
    write(tinyFile, "他推开门。\n")
    assert.equal(core.hasHardProseFindings(root, tinyFile), true)

    // Hot context > 12288 bytes warning
    const hot = path.join(root, "hot")
    write(path.join(hot, "book/正文/第001章_开端.md"), "# 第1章 开端\n正文。\n")
    writeCleanState(path.join(hot, "book"), 1, 0, 0)
    write(path.join(hot, "book/追踪/上下文.md"), "> 状态修订：0\n" + "状态".repeat(7000))
    assert.ok(core.continuityFindings(hot).some((m) => m.includes("超出续写状态卡预算 12288 字节")))

    // toxicRescanHint
    assert.equal(
      core.toxicRescanHint("/p/书/正文/第012章_夜路.md"),
      "完整检查：node <story-long-write>/scripts/storyctl.js chapter check --project <书目录> --chapter 12"
    )
    for (const sample of ["/p/书/正文.md", "/p/书/草稿/第3章.md", ""]) {
      assert.equal(core.toxicRescanHint(sample), "完整扫描：node <skill>/scripts/check-ai-patterns.js --check <正文文件>")
    }
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test("bounded directory discovery (depth 4, pruned hidden/node_modules/拆文库/对标, no symlink escape)", () => {
  const root = mkTmp("hook-core-disc-")
  const outside = mkTmp("hook-core-outside-")
  try {
    fs.mkdirSync(path.join(root, "shallow/追踪"), { recursive: true })
    fs.mkdirSync(path.join(root, "node_modules/fake/追踪"), { recursive: true })
    fs.mkdirSync(path.join(root, ".hidden/fake/追踪"), { recursive: true })
    fs.mkdirSync(path.join(root, "拆文库/参考长篇/正文"), { recursive: true })
    write(path.join(root, "拆文库/参考长篇/正文/第1章.md"), "拆文原文\n")
    write(path.join(root, "拆文库/参考短篇/正文.md"), "拆文短篇\n")
    fs.mkdirSync(path.join(root, "对标/竞品长篇/追踪"), { recursive: true })
    fs.mkdirSync(path.join(root, "对标/竞品长篇/正文"), { recursive: true })
    write(path.join(root, "对标/竞品长篇/正文/第1章.md"), "对标原文\n")
    write(path.join(root, "shallow/对标/竞品短篇/正文.md"), "书内对标\n")
    fs.mkdirSync(path.join(root, "a/b/book/追踪"), { recursive: true })
    fs.mkdirSync(path.join(root, "a/b/c/book/追踪"), { recursive: true })
    fs.mkdirSync(path.join(outside, "追踪"), { recursive: true })

    const all = core.discoverAllBooks(root).map((p) => core.safeRelative(root, p)).sort()
    assert.deepEqual(all, ["a/b/book", "shallow"])

    // A workspace containing only 拆文库/ and 对标/ must yield no active book or gap warnings
    const refOnly = mkTmp("hook-core-ref-only-")
    try {
      fs.mkdirSync(path.join(refOnly, "拆文库/参考书/正文"), { recursive: true })
      write(path.join(refOnly, "拆文库/参考书/正文/第1章.md"), "拆文原文\n")
      write(path.join(refOnly, "拆文库/参考短篇/正文.md"), "拆文短篇\n")
      fs.mkdirSync(path.join(refOnly, "对标/竞品/正文"), { recursive: true })
      write(path.join(refOnly, "对标/竞品/正文/第1章.md"), "竞品原文\n")
      assert.equal(core.discoverActiveBook(refOnly), null)
      assert.deepEqual(core.discoverAllBooks(refOnly), [])
      assert.equal(core.detectStoryGaps(refOnly), "")
    } finally {
      fs.rmSync(refOnly, { recursive: true, force: true })
    }

    let linked = false
    try {
      fs.symlinkSync(outside, path.join(root, "escape"), "dir")
      linked = fs.lstatSync(path.join(root, "escape")).isSymbolicLink()
    } catch {}
    if (linked) {
      write(path.join(root, ".active-book"), "escape\n")
      const active = core.discoverActiveBook(root)
      assert.ok(active && !active.includes("outside"), `symlink escape accepted: ${active}`)
    }
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
    fs.rmSync(outside, { recursive: true, force: true })
  }
})

test("detectStoryGaps foreshadowing, gaps, incomplete analyses, and protocol/storyctl constant sync", () => {
  // 1) Protocol FORESHADOW_STATUSES sync with tracking_commit.js
  const trackingMod = require(TRACKING_PATH)
  const protocolStatuses = trackingMod.FORESHADOW_STATUSES
  assert.ok(Array.isArray(protocolStatuses) && protocolStatuses.length >= 4, "FORESHADOW_STATUSES not found in tracking_commit.js")
  for (const status of protocolStatuses) {
    assert.ok(
      core.FORESHADOW_NORMAL_STATUSES.has(status) || core.FORESHADOW_WARN_STATUSES.has(status),
      `protocol status not classified by story_hook_core.js: ${status}`
    )
  }

  // 2) DESLOP_SKIP_MARKER sync with storyctl.js
  const storyctlMod = require(STORYCTL_PATH)
  assert.equal(
    storyctlMod.DESLOP_SKIP.source,
    core.DESLOP_SKIP_MARKER.source,
    `storyctl.js DESLOP_SKIP drifted from story_hook_core.js DESLOP_SKIP_MARKER (${core.DESLOP_SKIP_MARKER.source})`
  )

  // 3) Behavioral detectStoryGaps matrix
  const root = mkTmp("hook-core-gaps-")
  try {
    const setupBook = (name, foreshadowRow) => {
      const b = path.join(root, name)
      fs.mkdirSync(path.join(b, "正文"), { recursive: true })
      fs.mkdirSync(path.join(b, "设定"), { recursive: true })
      fs.mkdirSync(path.join(b, "大纲"), { recursive: true })
      writeCleanState(b, 0)
      write(
        path.join(b, "追踪/伏笔.md"),
        `# 伏笔追踪\n\n| ID | 伏笔内容 | 埋设章节 | 预计回收章节 | 状态{${protocolStatuses.join("/")}} | 重要度 |\n|:---|---|:---:|---|---:|---|\n${foreshadowRow}\n`
      )
      return b
    }

    const normal = path.join(root, "normal")
    fs.mkdirSync(normal, { recursive: true })
    setupBook("normal/book", "| F001 | 玉佩 | 第1章 | 第20章 |　已埋　| 高 |\n| F002 | 回收 | 第1章 | 第3章 | 已回收 | 低 |\n| F003 | 放弃 | 第1章 | 第3章 | 放弃 | 低 |")
    assert.equal(core.detectStoryGaps(normal), "")

    for (const [label, row] of [
      ["overdue", "| F004 | 过期 | 第1章 | 第2章 | 已过期 | 高 |"],
      ["retired", "| F001 | 未埋 | 第5章 | 第10章 | 未埋 | 中 |"],
      ["unknown", "| F005 | 损坏 | 第1章 | 第2章 | 状态损坏 | 高 |"],
    ]) {
      const sub = path.join(root, label)
      fs.mkdirSync(sub, { recursive: true })
      setupBook(`${label}/book`, row)
      assert.match(core.detectStoryGaps(sub), /检测到过期或异常的伏笔条目/, label)
    }

    // Chapters > 10 & settings < 3 + incomplete vs completed _progress.md
    const gaps = path.join(root, "gaps")
    const b = setupBook("gaps/book", "")
    for (let i = 1; i <= 11; i += 1) write(path.join(b, `正文/第${i}章.md`), "正文\n")
    write(path.join(gaps, "拆文库/pending/_progress.md"), "# 进度\n- 最终状态：paused_after_stage1\n")
    write(path.join(gaps, "拆文库/done/_progress.md"), "# 进度\n- 最终状态：completed\n")
    const out = core.detectStoryGaps(gaps)
    assert.match(out, /正文 11 章，但设定文件只有 0 个/)
    assert.match(out, /拆文未完成：拆文库\/pending\/_progress\.md/)
    assert.ok(!out.includes("拆文库/done/_progress.md"))

    // safeRelative canonicalizes alias roots (symlink on POSIX / 8.3 short path on Windows)
    if (process.platform !== "win32") {
      const realRoot = path.join(root, "real-alias-root")
      const linkRoot = path.join(root, "link-alias-root")
      write(path.join(realRoot, "book/大纲/细纲_第1章.md"), "# 细纲\n")
      fs.symlinkSync(realRoot, linkRoot)
      assert.equal(
        core.safeRelative(realRoot, path.join(linkRoot, "book/大纲/细纲_第1章.md")),
        "book/大纲/细纲_第1章.md"
      )
      assert.equal(
        core.safeRelative(realRoot, path.join(linkRoot, "book/大纲/细纲_第999章.md")),
        "book/大纲/细纲_第999章.md"
      )
      assert.equal(
        core.safeRelative(realRoot, path.join(realRoot, "..draft/第1章.md")),
        "..draft/第1章.md"
      )
    }
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})
