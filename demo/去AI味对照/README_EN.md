# De-AI comparison — the deterministic checks in `/story-deslop`

[中文](README.md)

The local check in `story-deslop` is a **writing lint**: it matches known AI sentence templates one by one and returns
the line, the matched span and a rewrite direction. Blocking findings stop the write; advisory findings go to human judgement.

| File | What it is |
|---|---|
| [`改前.md`](改前.md) | A **hand-constructed** AI-flavored sample, written to show what the checker catches. Not skill output. |
| [`改后.md`](改后.md) | The same scene (first time at the piano in the rehearsal room), verbatim from [`第021章_离别怎么会开花`](../长篇/让你管账号，你高燃混剪炸全网/正文/第021章_离别怎么会开花.md) — written by `/story-long-write` in one real session, with paragraphs merged by hand afterwards. |
| This file | The full output of both real scans. |

Reproduce with:

```bash
node skills/story-deslop/scripts/check-ai-patterns.js --check --fail-on=blocking demo/去AI味对照/改前.md
```

## Scanning `改前.md`: 8 findings (7 blocking / 1 advisory), exit 1

```
改前.md:3:1: [advisory] cliche-density-tic: 套词密度过高：高危 AI 套词 8 处（24.9/千字）；不要同义词轮换，改成角色当下可见的动作、物件、对话和具体后果。 (仿佛 一丝 深吸一口气 缓缓 微微)
改前.md:7:20: [blocking] em-dash: 破折号按功能改写：打断→动作 beat/短句，拖长音→省略或动作，插入说明→逗号/冒号；勿一律改句号。 (么叫做命运的安排——不是巧合，而是一)
改前.md:7:22: [blocking] not-is-comparison: 高频 AI 对比句式；删掉否定铺垫，直接写后项，或改成动作/细节呈现。 (不是巧合，而是一种冥冥之中的注定)
改前.md:11:1: [blocking] negation-parade: 否定排比：「没有X，没有Y…」/「没X，没有Y，只是Z」是 AI 高频排比模板；删掉否定清单，直接写现场实际有什么，最多留一个最有信息量的否定。 (没有犹豫，没有生涩，)
改前.md:19:3: [blocking] voice-contrast: 音量反差腔：「声音不大/不高…却/但…」是 AI 高频反差模板；删掉音量铺垫，直接写声音落进场子的具体效果（谁停了手、哪排安静了）。 (声音不大，却)
改前.md:21:2: [blocking] not-is-comparison: 高频 AI 对比句式；删掉否定铺垫，直接写后项，或改成动作/细节呈现。 (不是一次简单的弹奏，而是一场蓄谋已久的惊艳亮相)
改前.md:23:6: [blocking] trailer-ending: 预告式总结收尾：「没人知道/才刚刚开始/正朝着…压了过去」是 AI 章尾预告腔；结尾停在具体动作、画面或一句台词上，悬念让事件自己挂住，别替读者预告下一章。 (才刚刚开始)
改前.md:25:1: [blocking] trailer-ending: 预告式总结收尾：「没人知道/才刚刚开始/正朝着…压了过去」是 AI 章尾预告腔；结尾停在具体动作、画面或一句台词上，悬念让事件自己挂住，别替读者预告下一章。 (没人知道)
```

Rule distribution: `not-is-comparison` ×2 · `trailer-ending` ×2 · `cliche-density-tic` · `em-dash` · `negation-parade` · `voice-contrast`

## Scanning `改后.md`: zero findings, exit 0

```
(no output)
```

## The two passages

| 改前 (blocked) | 改后 (shipped prose) |
|---|---|
| 这一刻，他终于明白了什么叫做命运的安排——不是巧合，而是一种冥冥之中的注定。 | 指尖刚一碰下去，手指就自己走了起来，跑在了脑子前头。一串音落下去，他才后知后觉。<br>这是《离别开出花》的调子。 |
| 键盘手的喉结滚动了一下，手中的搪瓷杯微微颤抖。<br>身后的战友们目光渐渐变了，那些原本准备好的调侃，仿佛被一只无形的手扼住了咽喉。 | 走廊上脚步声忽然停了。是乐队键盘手，手里端着一只搪瓷杯，人愣在原地，杯子里的水洒出来一点也没察觉。他身后跟着两个战友，一个张着嘴，半天没找回自己的声音，另一个手快，已经掏出手机对着门里录了起来。 |
| 而这一切，才刚刚开始。<br>没人知道，这段旋律将在十四天后，掀起怎样的惊涛骇浪。 | 键盘手回过神，声音都拔高了半分：“江导什么时候学的钢琴？这手上的功夫，没十年童子功压根摸不着边！”<br>江晨没接话，心里却乐了。<br>十年童子功，他今天上午刚拿到手。 |

Both passages tell the same beat. The first tells the reader what to feel; the second hands it to visible action and objects.

> The checker only handles deterministic sentence and punctuation patterns; how a passage reads is still a human call.
