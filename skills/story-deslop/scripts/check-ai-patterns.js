#!/usr/bin/env node
'use strict';

const fs = require('fs');
const { loadStyleWhitelist, maskStyleText } = require('./style-whitelist.js');
const path = require('path');

const USAGE = `Usage: node check-ai-patterns.js [--check] [--json] [--mode=auto|long|short] [--fail-on=blocking|review_required|all] [--respect-skip] <file...>
       node check-ai-patterns.js --list-review-classes

Detect high-risk AI-flavor prose patterns that need human rewrite:
  - negative setup followed by positive flip in the same sentence
  - comma/semicolon/colon + positive flip
  - sentence break + positive flip
  - repeated negative setup followed by positive flip
  - em-dash (按功能改写), 碎句号 (连续短叙述句), 长段落 (按镜头断段)
  - 微动作复读 (「了下/了一下」式轻量补语高密度，电报体指纹)
  - 套式反应细节 (指尖/指节/目光等无功能微动作与「平静得像在念」式语气比喻成片)
  - 抽象总结复读 (命运/棋局/这一刻终于明白/才刚刚开始，AI 结尾腔)
  - 套词密度过高 (仿佛/一丝/深吸一口气/平静无波等禁用词聚集)
  - 比喻密度过高 (像/好像/仿佛/如同等比喻标记成片复现)
  - 解释链密度过高 (知道/明白/这意味着/必须/需要等判断链聚集)
  - 系统公告公文腔过密 (方括号系统/规则行里硬规则词聚集)
  - 过度精炼短段 (长文本里短叙述段过密且自然连接偏少)
  - 低连接密度 (引号外叙述功能词/白话连接偏少且中长句不足，像提纲/电报体)
  - 监控摄像头式动作清单 (同段连续摆放动作动词，缺少视角温度/情绪缓冲)
  - 音量反差腔 (声音不高/不大…却…, 实战漏网句式)
  - 否定排比 (没有X，没有Y…连排 / 没X…只是Y 先否定后肯定, 实战漏网句式)
  - 工整并列 (至于X不X，怎么X / 同动词「不V A，不V B」，含台词，advisory)
  - 反序对比 (是A，不是B — not-is 的反序变种, 实战漏网句式)
  - 预告式总结收尾 (文末窗口 没人知道/才刚刚开始/正朝着…压了过去, 实战漏网句式)
  - 章尾状态总结体 (文末窗口 这一夜注定/这一切都结束了/新的人生才刚刚开始/命运的齿轮)
  - 引号强调滥用 (叙述里 1-4 字短词加引号强调，密度型)
  - 叙述省略号过密 (引号与面板外 …… 高密度刷屏，advisory)
  - 感叹号过密 (叙述旁白或全文 ！ 高密度咆哮标点，advisory)
  - 戏剧套词刷屏 (死寂同章重复或死寂/轰然/骤然/猛地/瞬间高密度聚集，advisory)
  - 女频油腻/言情套词聚集 (指节泛白/宠溺/喉结轻滚/眸色一暗/声音低哑/小女人聚集，豁免轻笑/低笑，advisory)
  - 短篇塑料反应套词聚集 (--mode=short 眼底闪过一丝/瞳孔骤缩|猛地一缩|失焦/喉结滚/指节泛白/气得浑身发抖/死一般寂静合计 ≥2 处，advisory)
  - 闲笔道具摆设过密 (--mode=long 没用的材质/服饰/光影/环境音效摆设聚集且叙述口语连接词偏低，advisory)

Book-local .deslop-whitelist literal spans are excluded from style scanning (no regex or ancestor inheritance).
Each finding carries severity: review_required for high-risk stylistic patterns (not-is-comparison / em-dash / voice-contrast / negation-parade / reverse-not-is / trailer-ending / trailer-summary), where single/low-count hits of rhetorical patterns (or moderate narration em-dash density, and all short-mode narration em-dash density) downgrade to semantic advisory and high-density clusters (or long-mode dense narration em-dash / trailer-summary) require explicit review-and-ack. This is a local style/readability soft-gate, not an AIGC detector score; functional human text can be kept with explicit acknowledgement instead of hard-blocked.
或 advisory (period-stutter / long-paragraph / micro-action-tic / negation-pair-tic / stock-reaction-tic / action-list-tic / abstract-summary-tic / cliche-density-tic / metaphor-density-tic / reasoning-chain-tic / system-notice-formality-tic / overcompressed-prose-tic / low-connective-density-tic / idle-prop-decoration-tic / quote-emphasis-tic / formulaic-parallelism / ellipsis-density-tic / exclamation-density-tic / dramatic-cliche-tic / romance-cliche-tic / short-plastic-reaction-tic / staccato-paragraph-tic，是提示，justified 的长推理/氛围段可保留)。
--fail-on=blocking 只在出现 hard blocking finding 时退出 1（当前风格规则均为 review_required/advisory，故返回 0）；--fail-on=review_required 在出现 blocking 或 review_required finding 时退出 1（阻断门禁请加 --fail-on=review_required）；默认 --fail-on=all 有任何 finding 即退出 1。
Each finding also carries review: mechanical（表面形态确定、就地改写或确认保留即可）或 semantic（可能承担叙事功能，需读上下文判断是否保留）；review_required / blocking 一律 mechanical。--list-review-classes 输出完整分类表（JSON）。
HTML comments (<!-- ... -->, e.g. the 去味:跳过 exemption marker) are metadata, not prose, and are never scanned.

The script reports findings only. It never rewrites text, because the safe fix is
contextual: usually delete the negative setup, write the positive term directly,
or show it via action/detail.`;

const STOP_CHARS = new Set(['。', '！', '？', '!', '?', '\n']);
const SOFT_SEPARATORS = new Set(['，', ',', '、', '；', ';', '：', ':']);
const HARD_SEPARATORS = new Set(['。', '.', '！', '!', '？', '?']);
const MAX_NEGATIVE_SPAN = 80;
const MAX_POSITIVE_SPAN = 80;

// 碎句号：连续 STUTTER_MIN_RUN 个「叙述」短句（每句可见字数 ≤ STUTTER_MAX_SENTENCE）无呼吸。
// 只数叙述句，跳过对话/弹幕/系统播报（成片短句是这些体裁的正常形态，不算碎句号）。
const STUTTER_MIN_RUN = 6;
const SHORT_STUTTER_MIN_RUN = 9;
const STUTTER_MAX_SENTENCE = 5;
// 长段落：单段原始字符数超过阈值即提示按镜头断段（长篇保守阈值 200；短篇竖屏叙述收紧到 100，纯引号台词/书信/公告放宽到 150）。
const LONG_PARAGRAPH_CHARS = 200;
const SHORT_LONG_PARAGRAPH_CHARS = 100;
const SHORT_LONG_QUOTED_PARAGRAPH_CHARS = 150;
// 旁白破折号密度门槛（真人网文长篇/短篇均常用 —— 做系统提示、拖音与转折揭底拍）：
// 长篇 ≥4 处且 ≥1.5/千字给 advisory（短篇 ≥6 处且 ≥1.5/千字）；长篇 ≥10 处且 ≥2.5/千字升为 review_required（短篇始终 advisory）。
const LONG_EM_DASH_ADVISORY_MIN_HITS = 4;
const EM_DASH_ADVISORY_MIN_HITS = 6;
const EM_DASH_ADVISORY_PER_KILO = 1.5;
const LONG_EM_DASH_REVIEW_MIN_HITS = 10;
const LONG_EM_DASH_REVIEW_PER_KILO = 2.5;
const ONOMATOPOEIA_BEFORE_DASH_RE = /(?:^|[\s，,。！？!?：:；;、—]|[声响一阵])[轰砰咚咔嗡吱嘟哗铮啪叮滴嘶呼唰呜嗷吼哒嚓啦咯嘎哐咣隆]{1,4}$/;
const ONOMATOPOEIA_PAIR_BEFORE_DASH_RE = /(?:轰隆隆?|铮铮|咔嚓|咔哒|哗啦|叮咚|嘎吱|哐当|哐啷|咣当|咕噜|嗡嗡|嘶嘶|呼呼|嘟嘟|滴滴|滋啦|刺啦|砰砰|咚咚|啪啪|嗷呜)$/;
const OPEN_TO_CLOSE_QUOTE = { '“': '”', '「': '」', '『': '』' };
// 短篇套式反应细节门槛：短篇情绪与生理速记频率高于长篇，抬高到 8 处且 3.0/千字。
const SHORT_STOCK_REACTION_MIN_HITS = 8;
const SHORT_STOCK_REACTION_PER_KILO = 3.0;

// 微动作复读：「V了下 / V了一下 / 拍了两下 / 松了半圈」式轻量补语在叙述里高密度复现，
// 容易形成删减过头的电报体指纹。只扫引号外叙述；密度与次数双门槛同时达标才报，
// 单次出现是正常中文。「了口气」（叹/喘/松了口气）计入，「了口」（喝了口茶/咬了口包子）属实义饮食动作不误伤。
const MICRO_TIC_PATTERN = /了(?:[一两三几半])?(?:口气|[下阵圈道声眼气会])/g;
const MICRO_TIC_MIN_HITS = 5;
// 「没A，也没B」「不A，也不B」否定对偶：七猫人类长篇约 0.07 处/千字，模型稿 0.4-1.5 处/千字；
// 写人物没做什么是英文式节奏，一章 3 处以上报一条提示。
const NEGATION_PAIR_PATTERN = /(?:没有|没|不)[^，。！？；,!?\n]{1,10}[，,；]\s*[^，。！？；,!?\n]{0,6}?也(?:没有|没|不)/g;
const NEGATION_PAIR_MIN_HITS = 3;
const MICRO_TIC_PER_KILO = 6;

// 套式反应细节：不是禁写身体，而是提示成片出现的“部位 + 轻微动作/状态”、
// “胸口像被撞了一下”、喉结/眼圈/声音放轻等通用情绪尾巴，以及“平静语气 +
// 像在念/宣判”模板。此类句子词面变化大，不能逐词 blocking；按章聚集到 4 处才
// advisory，要求逐处做删除测试。正常受伤、打斗、生理反应若承担物理后果可保留。
const STOCK_REACTION_PATTERNS = [
  /(?:指尖|指腹|手指|指节|手背|掌心|拳头|袖口|衣角|裙角|下唇|嘴唇|唇角|嘴角|眉头|眼底|眸光|目光|视线|肩膀|呼吸)[^。！？!?\n]{0,16}(?:轻轻|微微|缓缓|慢慢|悄然|不自觉|无意识|下意识|攥紧|握紧|收紧|绞紧|拢住|按住|压住|扣住|捻(?!起)|泛白|发白|叩|敲|摩挲|抿紧|抿成|移开|垂下|躲开|落[在到][^，。！？!?\n]{1,10}(?:停|顿)|一颤|颤了?一下|停了?一下|顿了?一下)/g,
  /(?:手|指尖|手指)往(?:袖口?|怀|兜|口袋|身后|背后)里?一?(?:缩|揣|收|藏)/g,
  /(?:语气|声音)[^。！？!?\n]{0,12}(?:平静|冷静|平淡|冷淡|淡漠|平直)[^。！？!?\n]{0,12}(?:像|仿佛|如同|好像)[^。！？!?\n]{0,16}(?:念|读|报|说|陈述|宣判|背诵)/g,
  /(?:胸口|心口)[^。！？!?\n]{0,16}(?:像|仿佛|如同|好像)[^。！？!?\n]{0,16}(?:撞|锤|压|攥|堵)[^。！？!?\n]{0,8}(?:一下|一记|一拳)?|(?:心跳|心头)漏跳?了?一拍/g,
  /(?:声音|嗓音|语气)[^。！？!?\n]{0,12}(?:放轻|压低|发紧|发颤|很轻|轻了些)/g,
  /(?:喉结|喉头|喉咙)[^。！？!?\n]{0,10}(?:滚|动|紧|堵|发涩|发干)/g,
  /(?:眼眶|眼圈|鼻子)[^。！？!?\n]{0,8}(?:发红|红了|发热|发酸|一酸)/g,
  /(?:抿了?下唇|抿了?抿唇|抿了?下嘴|抿着笑)/g,
];
const STOCK_REACTION_MIN_HITS = 4;
// 校准（真人语料，<br> 已还原为换行）：qimao 长篇 5584 章 + heiyan 短篇整篇 3983 篇。
// 长篇章尺度（中位约 2100 字）per-kilo 1.0→1.5 误报 0.43%→0.39%，几乎不动；
// 短篇整篇 8000-20000 字下 MIN_HITS 形同虚设、只剩密度门，1.0 时误报 5.57%，
// 1.5 降到 1.46%。故取 1.5，把两个总体拉到同一量级（四份副本共用一组阈值）。
const STOCK_REACTION_PER_KILO = 1.5;

// 监控摄像头式动作清单：同一段连续堆叠通用动作动词（伸手/拿起/取过/挑开/放下/转身等），
// 且用逗号/顿号串联成步骤表时，读感像无视角温度的监控记录。只做 advisory；
// 打斗/追逐等功能性动作编排可保留或人工复核。
const ACTION_LIST_VERB_PATTERN = /伸手|抬手|探手|拿起|拿过|取出|取过|掏出|摸出|抓起|攥住|握住|捏住|按住|推开|拉开|打开|关上|放下|递给|挑开|掀开|扯开|拧开|倒出|端起|转身|回头|抬头|低头|弯腰|俯身|走到|走向|坐下|站起|看向|看着|盯着|扫过/g;
const ACTION_LIST_MIN_HITS = 5;
const ACTION_LIST_MIN_SEPARATORS = 4;

// 抽象总结复读：模板化段落常把角色当下经历拔成「命运/棋局/
// 这一刻终于明白/才刚刚开始」的作者总结。单个词可能服务题材；高密度聚集才报。
const ABSTRACT_SUMMARY_PATTERNS = [
  /这一刻[，,]?[^\n。！？!?]{0,24}(?:终于|才)(?:明白|意识到)/g,
  /从这一刻开始/g,
  /(?:命运|宿命)[^\n。！？!?]{0,28}(?:齿轮|棋局|獠牙|改写|推向|安排)/g,
  /早已[^\n。！？!?]{0,8}(?:布好|安排好)[^\n。！？!?]{0,8}(?:棋局|局)/g,
  /前所未有的(?:决意|清醒|勇气|力量|恐惧|平静|信念)/g,
  /(?:反击|复仇|战争|较量|故事|命运)[^\n。！？!?]{0,12}才刚刚开始/g,
  /(?:新的开始|全新的开始)/g,
];
const ABSTRACT_SUMMARY_MIN_HITS = 3;
const ABSTRACT_SUMMARY_PER_KILO = 4;

// 套词密度：单个「仿佛/一丝」可能是正常中文，高密度聚集才会形成模板腔。
// 词表只收本 repo banned-words 中已明确标为高危的形态，避免把普通功能词一网打尽。
const CLICHE_PATTERNS = [
  /仿佛|犹如|宛若|如同/g,
  /一丝|一抹|些许|几分|隐约/g,
  /深吸一口气|缓缓|微微|轻轻|淡淡/g,
  /眼中闪过|嘴角勾起|眸光微微一闪|指节泛白|目光锐利|眼神锐利/g,
  /心中涌起一股|心头一震|心中一动|心下了然|心中暗道|心中一凛/g,
  /不容置疑|不容置喙|不易察觉|微不可察|显而易见|毫无疑问|不可否认/g,
  /声音不大[，,]?却带着|语气平静无波|平静无波|声音平直|听不出情绪/g,
  /不知何时|唾手可得|无声翻涌|沉默(?:在[^。！？!?\n]{0,16})?蔓延|难以言说/g,
  /散发着一股|冰冷的光|格外刺眼|深邃而冰冷/g,
];
const CLICHE_DENSITY_MIN_HITS = 8;
const CLICHE_DENSITY_PER_KILO = 12;

// 比喻密度：单个生活化比喻可服务画面；“像/好像/仿佛/如同”成片复现时，
// 容易变成 AI 式修辞堆叠。只做 advisory，修法是删到必要数量并回到具体画面，
// 不是把“像”换成另一组比喻词。
const METAPHOR_MARKER_PATTERN = /好像|像是|仿佛|宛如|如同|犹如|(?<![不头图画影录摄肖])像(?![头像素样话])/g;
const METAPHOR_COMPOUND_NOUN_PATTERN = /遗像|炭精像|画像|雕像|铜像|佛像|塑像|神像|头像|人像|肖像|蜡像|录像|影像|偶像|假像|表像|现象|印象|迹象|气象|星象|万象/g;
const METAPHOR_LIKE_PHRASE_PATTERN = /(?:死|水|冰|火|潮水|石头|木头|机器|纸|铁|鬼|死人|刀|针|网|墙)一样/g;
const METAPHOR_DENSITY_MIN_HITS = 7;
const METAPHOR_DENSITY_PER_KILO = 3;

// 解释链密度：常见“他知道/他明白/这意味着/必须需要”
// 连续替读者推理，读感像报告。单个判断词或领域名词可服务叙事；只有论文推导词/义务情态链成片出现才报。
// 顺序固定为 connector → modal → mental → abstract，供同一行去重重叠区间（如“必须在规则惩罚前做出判断”只计 1 次 modal）。
const REASONING_CHAIN_PATTERNS = [
  { key: 'connector', core: true, pattern: /这意味着|也就是说|换句话说|真正的问题(?:在于)?|问题在于|关键在于|在这种情况下|按照这个逻辑/g },
  { key: 'modal', core: true, pattern: /(?:(?<!不)(?:必须|需要|应该|只要|就会|可能|无法)|不能)[^。！？!?\n]{0,16}(?:判断|确认|承担|维持|稳住|控制|扩大|失控|带来|造成|默认|核对|筛选|减少|建立|风险|结果|秩序|责任)/g },
  { key: 'mental', core: true, pattern: /(?<![不没未无])(?:他|她|我)?(?:知道|明白|意识到|清楚|判断|确认|分析)/g },
  { key: 'abstract', core: false, pattern: /(?:任务|条件|风险|来源|逻辑|局面|结果|责任|秩序|规则|信息不足|决策能力)/g },
];
const REASONING_CHAIN_MIN_HITS = 8;
const REASONING_CHAIN_CORE_MIN_HITS = 4;
const REASONING_CHAIN_MIN_LINKS = 3;
const REASONING_CHAIN_MIN_BUCKETS = 2;
const REASONING_CHAIN_PER_KILO = 18;

// 系统公告公文腔：只看成片方括号规则/面板行里的硬规则词。
// 这不是特定题材词表；单条严肃规则、日常叙述或普通对话不触发。
const NOTICE_FORMAL_PATTERNS = [
  /不得|必须|不可|禁止|严禁|应当|须|需|务必/g,
  /当前|本公告|本规则|本系统|提示|任务失败|临时权限|权限|状态|等级/g,
  /维持|公共区域|秩序|优先|惩罚|处罚|违规|指令|执行/g,
  /被视为|同样计入|计入|承担|责任|单位|撤回|转发|截图/g,
];
const NOTICE_FORMAL_CORE_PATTERN = /不得|必须|不可|禁止|严禁|应当|须|需|务必|被视为|同样计入|计入/g;
const NOTICE_FORMAL_MIN_LINES = 4;
const NOTICE_FORMAL_MIN_HITS = 12;
const NOTICE_FORMAL_CORE_MIN_HITS = 5;
const NOTICE_FORMAL_PER_KILO = 60;

// 过度精炼短段：仅抓极端“提纲/电报体”（大量 ≤10 字极碎叙述段且几乎无自然虚词），
// 不误伤手机竖屏网文正常的 15-30 字短段节奏。此项只做 advisory，禁止机械注水。
const OVERCOMPRESSED_PROSE_PARTICLE_PATTERN = /[的了就着过呢吧啊呀嘛]/g;
const OVERCOMPRESSED_PROSE_MIN_CHARS = 1200;
const OVERCOMPRESSED_PROSE_MIN_PARAS = 45;
const OVERCOMPRESSED_PROSE_SHORT_MAX_CHARS = 10;
const OVERCOMPRESSED_PROSE_SHORT_RATIO = 0.55;
const OVERCOMPRESSED_PROSE_PARTICLE_PER_KILO = 50;

// 低连接密度：仅抓极端机械大纲电报体（≥50% 叙述句为 ≤10 字碎片、自然连接极低且几乎无 ≥25 字承接句），
// 不误伤番茄/七猫等手机竖屏网文（70%+ 段落 ≤30 字）。只做 advisory。
const LOW_CONNECTIVE_FUNCTION_TERMS = ['的', '了', '就', '在', '是', '也', '都', '还', '又', '把', '被', '给', '这个', '那个', '里面', '以后', '时候', '现在', '因为', '所以', '但是', '不过', '然后', '已经', '还是', '起来', '出来', '下去'];
const LOW_CONNECTIVE_PLAIN_TERMS = ['的', '了', '就', '也', '还', '又', '这个', '那个', '东西', '事情', '时候', '里面', '以后', '一下', '一点', '有点', '还是'];
const LOW_CONNECTIVE_MIN_CHARS = 800;
const LOW_CONNECTIVE_FUNCTION_PER_KILO = 55;
const LOW_CONNECTIVE_PLAIN_PER_KILO = 30;
const LOW_CONNECTIVE_TINY_SENTENCE_CHARS = 10;
const LOW_CONNECTIVE_TINY_SENTENCE_RATIO = 0.50;
const LOW_CONNECTIVE_LONG_SENTENCE_CHARS = 25;
const LOW_CONNECTIVE_LONG_SENTENCE_RATIO = 0.05;
// 长篇干硬镜头叙述分支（2,450 篇真 9.0+ 长篇标定，误报 0.33%）：纯叙述段偏长（中位 ≥28 字）却同时缺口语连接词（≤5.5/千字）
// 与自然「的」（≤25.0/千字），即抽干人物内心盘算的剧本报幕体；绝不误伤正常手机竖屏短段（中位 ~23 字）。
const COLLOQUIAL_CONNECTIVE_PATTERN = /但是|可是|不过|虽然|因为|所以|偏偏|干脆|其实|毕竟|竟然|居然|好在|幸好|倒也|哪知道|省得|免得|结果|反正|关键是|要不然|怪不得|难怪|只是|倒是|反倒|反而|索性|压根|谁知|谁料|原本|本来|终究|总归|哪怕|就算|只好|只得|愣是|硬是|却|才|便|正要|已经/g;
const DRY_NARRATION_MIN_CHARS = 400;
const DRY_NARRATION_MIN_UNIQUE_PARAS = 8;
const DRY_NARRATION_MAX_CONN_PER_KILO = 5.5;
const DRY_NARRATION_MAX_DE_PER_KILO = 25.0;
const DRY_NARRATION_MIN_PURE_MEDIAN = 28;
const PURE_NARRATION_QUOTE_RE = /[“”「」『』"]/;

// 闲笔材质/道具/光影贴纸过密（advisory only；2,450 篇真 9.0+ 长篇标定，误报 0.00%）：
// 仅在 --mode=long 扫描引号外叙述（≥400 字），同时要求命中 ≥3 种不同装饰贴纸、唯一密度 ≥1.8/千字，
// 且口语连接词 ≤7.0/千字（写专业器物但带活人口语因果的真人类自动放行）。
const IDLE_PROP_DECORATION_PATTERN = /磨砂|骨瓷|紫檀|红木|黄铜|青漆|红漆(?!封条|官印|火漆)|黑漆(?!漆)|漆面|太师椅|酸枝|花梨|珐琅|青砖|青石板|玻璃幕墙|落地窗|百叶窗|大理石|胡桃木|亚光|鎏金|描金|雕花|算盘珠|水渍|茶渍|烟炱|(?:深灰|藏青|炭黑|烟灰|定制|高定)(?:西装|西服|大衣|羊绒|风衣|旗袍|礼服)|熨得|一丝不苟|袖扣|领带夹|鳄鱼皮|公文包|腕表|表盘|白炽灯|日光灯|吸顶灯|冷白光|暖黄光|咖啡机|嗡鸣|低鸣|空调外机|淅淅沥沥|滴答作响|钟摆|窗霜|瓷盏|茶盏|折扇|油灯/g;
const IDLE_PROP_MIN_CHARS = 400;
const IDLE_PROP_MIN_UNIQUE = 3;
const IDLE_PROP_MIN_UNIQUE_PER_KILO = 1.8;
const IDLE_PROP_MAX_CONN_PER_KILO = 7.0;

// either-or「不是A就是B / 不是A也是B」及紧凑子句中的合成词/人称主语前字，不作为无逗号紧凑翻转的肯定项系动词。
const COMPACT_EITHER_OR_PREV = new Set([
  '不', '就', '也', '还', '只', '可', '但', '于', '倒', '像', '若', '要', '正', '便', '总', '老',
  '更', '最', '算', '怕', '凡', '或', '即', '自', '竟', '原', '本', '仍', '许', '净', '光', '单',
  '尽', '又', '才', '都', '真', '你', '我', '他', '她', '它', '这', '那',
]);
const COMPACT_NOT_IS_CLAUSE_PREFIX_RE = /^不是(?:因为|说|听说|以为|觉得|认为)/;
const COMPACT_NOT_IS_TAIL_EXCLUDE_RE = /^是(?:什么|假的|真的|错的|对的|谁|哪|怎么)/;
// 句尾语气/反问助词；「…，是吗 / 是吧 / 是嘛」是反问尾巴，不是否定后的肯定翻转。
const TAG_PARTICLES = new Set(['吗', '吧', '嘛']);
// 段首确认语；「不是第一次来。是的，他还记得……」里的「是的/是啊」
// 是承接确认，不是「不是 A，是 B」的肯定翻转。
const AFFIRMATION_TAG_PARTICLES = new Set(['的', '啊', '呀', '呢']);
const AFFIRMATION_TAG_BOUNDARY = new Set(['', '，', ',', '。', '.', '！', '!', '？', '?', '、', '；', ';', '：', ':', '\n', '\r', '\t', ' ']);

// 成对引号（台词/系统播报/弹幕）的字符对，stripQuoted 与 quotedRanges 共用一份来源。
// 引号片段一律不跨行（字符类里排掉 \n）：正文漏一个收引号很常见（多段台词只在末段收尾、
// 全半角引号混用都会漏），若允许跨行配对，一个未闭合的开引号会把后面成百上千字全算成
// 「引号内」，让 quotedRanges 的消费方（not-is 跨行扫描）把整段叙述静默豁免掉。
const QUOTE_PAIRS = [['「', '」'], ['『', '』'], ['【', '】'], ['“', '”'], ['‘', '’'], ['"', '"'], ["'", "'"]];
const QUOTE_SOURCES = QUOTE_PAIRS.map(([open, close]) => `${escapeRegExp(open)}[^${escapeRegExpCharClass(close)}\\n]*${escapeRegExp(close)}`);

// ---- 实战测试漏网句式（来源：实战写作抓到的真实漏网例句；2026-07 校准）----
// 校准基线：《万疆》真人正文 20 章（第1/10/20/…/190章）+ demo 前 20 章。
// blocking 规则要求真人语料命中 ≈0（每 20 章 ≤1 处且人工判定确属该句式）；数据见各规则注释。

// 音量反差腔（实战漏网 A）：「声音不高，第一句却稳稳压住了整个大厅。」
// 旧网只有套词密度桶里的「声音不大，却带着」，音量词/转折词一换就漏。
// 引号外叙述逐处 blocking；修法是删掉音量铺垫，直接写声音落进场子的具体效果。
// 校准：《万疆》20 章 0 命中，demo 前 20 章 0 命中。
const VOICE_CONTRAST_PATTERN = /(?:声音|嗓音|语调|语气)(?:(?:并)?不[大高响亮]|很淡)[^。！？!?\n]{0,16}[却但偏]/g;

// 否定排比（实战漏网 B）：「没有伴奏，没有和声，没有提词器。」同句 ≥2 个「没有X，」连排；
// 变体「他没炫技，没有那种…架势。他只是唱」先否定铺垫、再用「只是/只会/只有」收肯定。
// 只收「没/没有」段，不收「不X」段——真人叙述里「不哭不闹」类太常见，收进来误报换不来收益。
// 光杆「没」还得挡两类非否定用法，否则正常叙述会被判成排比：
//   1) 黏着语素（沉没/淹没/埋没/出没/隐没…）——前字排除，「船沉没在雾里，没人回头，…只有…」不算；
//   2) 时间惯用语（没多久/没过多久/没等X）——后字排除，「没多久，没等她撑伞，…只有…」不算。
// 「没有X」段不带这两种歧义（黏着语素后接不出「有」，时间惯用语已被后字排除覆盖），
// 第一条连排式照旧不加护栏。
// 校准：《万疆》20 章 0 命中，demo 前 20 章 0 命中。
const NEGATION_PARADE_PATTERNS = [
  /(?:没有[^。！？!?\n，,]{1,12}[，,]){2}/g,
  /(?<![沉淹埋出隐湮吞覆漫泯])没(?!有?过?多久)(?:有)?[^。！？!?\n，,]{1,12}[，,]\s*没(?!有?过?多久)(?:有)?[^。！？!?\n，,]{1,16}[，,。.][^。！？!?\n，,]{0,6}只(?:是|会|有)/g,
];
const CROSS_NEGATION_START = /^不是[^。！？!?\n]{1,24}[。！？!?]?$/;
const CROSS_NEGATION_MIDDLE = /^(?:也|还)不是[^。！？!?\n]{1,24}[。！？!?]?$/;
const CROSS_NEGATION_END = /^只是[^。！？!?\n]{1,32}[。！？!?]?$/;
// 跨句/跨行「没有A，没有B。只有C。」与三段「没有A / 也没有B / 只有C」（Wave 3D FN-7，仅 advisory）
const PERIOD_NEGATION_ONLY_PATTERN = /没有[^。！？!?\n，,]{1,14}[。！？!?]\s*(?:也)?没有[^。！？!?\n，,]{1,14}[。！？!?]\s*[^。！？!?\n，,]{0,6}只有/g;
const CROSS_MEIYOU_PAIR_END = /没有[^。！？!?\n，,]{1,14}[，,]\s*(?:也)?没有[^。！？!?\n，,]{1,14}[。！？!?]$/;
const CROSS_MEIYOU_SINGLE_START = /^没有[^。！？!?\n]{1,20}[。！？!?]?$/;
const CROSS_MEIYOU_SINGLE_MIDDLE = /^(?:也)?没有[^。！？!?\n]{1,20}[。！？!?]?$/;
const CROSS_ZHIYOU_START = /^只有[^。！？!?\n]{1,32}[。！？!?]?$/;
// 极碎电报体（Wave 3D FN-4，advisory）：整章/场景 ≥350 可见字，且纯叙述自然段 ≥15 段、段长中位数 ≤12 字（排除纯对白/面板/聊天体）。
const STACCATO_PARA_MIN_COUNT = 15;
const STACCATO_PARA_MAX_MEDIAN = 12;
const SHORT_STACCATO_PARA_MAX_MEDIAN = 9;
const STACCATO_PARA_MIN_DOC_CHARS = 350;

// 两类常见但不能直接判错的工整框架，只做 advisory。与 blocking 规则不同，这里故意扫描
// 台词：自然点单「不放辣，不放葱」靠对象最短长度排除；更长的同动词清单交语义审查判断功能。
const DECISION_FRAME_PATTERN = /至于([\u3400-\u9fff]{1,3})不\1[，,]\s*怎么\1/g;
const REPEATED_NEGATIVE_VERB_PATTERN = /不([\u3400-\u9fff]{1,2})([\u3400-\u9fff]{2,8})[，,]\s*不\1([\u3400-\u9fff]{2,8})/g;
// 排除常见虚词/关联词/情态词（不管…不管…、不是…不是…、不要…不要…、不想…不想…），避免误杀自然中文情绪递进。
const PARALLELISM_EXCLUDED_STEMS = new Set([
  '管', '论', '是', '用', '要', '想', '会', '能', '敢', '准', '许', '必', '可', '得',
  '知', '知道', '愿', '愿意', '肯', '再', '仅', '但', '只', '止', '够', '配', '值', '值得',
  '顾', '顾及', '停', '断', '该', '让', '怕',
]);

// 反序对比腔（实战漏网 C）：「是真嗓子，不是修音修出来的」——not-is-comparison 的反序变种。
// 复用 not-is 的排除基建：引号内剥离（maskQuoted）、「是的/是啊」确认语（isAffirmationTagAt）；
// 前字排除从 either-or 的 不/就/也 扩展到全部「X是」连词/副词合成词（还是/只是/可是/但是/
// 于是/倒是/像是/若是/要是/正是/便是/总是/老是/更是/最是/算是/怕是/凡是/或是/即是/自是/
// 竟是/原是/本是/仍是/许是/净是/光是/单是/尽是）；「是不是」问句起头与「不是吗/不是么/
// 不是吧」反问尾巴单独排除。
// 校准：《万疆》20 章 0 命中，demo 前 20 章 0 命中，按 blocking 实现。
const REVERSE_NOT_IS_PATTERN = /是([^。！？!?\n，,]{1,12})[，,]\s*(?:而)?不是([^。！？!?\n]{1,20})/g;
const REVERSE_NOT_IS_PREV_EXCLUDE = new Set([...COMPACT_EITHER_OR_PREV, '还', '只', '可', '但', '于', '倒', '像', '若', '要', '正', '便', '总', '老', '更', '最', '算', '怕', '凡', '或', '即', '自', '竟', '原', '本', '仍', '许', '净', '光', '单', '尽']);

// 预告式总结收尾（实战漏网 D）：「没人知道，这才刚刚开头。」「一场…震惊接力，正朝着…缓缓压了过去。」
// 章尾替读者预告下一章走向是 AI 收尾腔。只扫文末窗口（剥引号后可见字数，按行取整），
// 正文中段的「没人知道」多为普通叙述，不误伤；引号内台词（「没人知道…」）不计。
// 「正式拉开序幕/帷幕」是场内事件的报幕式陈述（真人语料「钟声再度响起，比赛正式拉开序幕」），
// 不是叙述者预告，前置 lookbehind 排除。
// 「他/她/它(们)不知道的是」是全知旁白跳出视角预告后事（banned-words 抽象收束、预告行）；
// 必须带「的是」，「她不知道该说什么」这类普通叙述不计。
// 校准：《万疆》20 章排除「正式拉开序幕」2 处报幕句后 0 命中，demo 前 20 章 0 命中。
const TRAILER_SPOILER_PATTERN = /没人知道(?!怎么|哪|谁|啥|什么|的)|谁也不知道(?!怎么|哪|谁|啥|什么|的)|谁也没想到|[他她它]们?不知道的是|殊不知/g;
const TRAILER_CLICHE_PATTERN = /(?:这)?才刚刚开(?:始|头)|正(?:朝着|向着)[^。！？!?\n]{0,24}(?:压|涌|袭|逼)(?:了?过去|了?过来|来)|(?<!正式)拉开(?:序幕|帷幕)|即将(?:开始|来临|降临)/g;
const TRAILER_ENDING_PATTERN = new RegExp(`${TRAILER_SPOILER_PATTERN.source}|${TRAILER_CLICHE_PATTERN.source}`, 'g');
const TRAILER_ENDING_WINDOW_CHARS = 250;
const TRAILER_ENDING_WINDOW_MAX_LINES = 4;
const TRAILER_ENDING_LINE_CAP_MIN_DOC_CHARS = 500;
const shortSpoilerFindings = new WeakSet();

// 章尾状态总结体：把细纲「结尾设定」原样写成总结句收章（「这一夜注定无人入眠」
// 「这一切都结束了」「新的人生才刚刚开始」「命运的齿轮」）。与 trailer-ending 共用文末窗口，
// 区别是它盖章过去、trailer-ending 预告将来；收的都是 banned-words 已按名禁掉的形态。
// 不收「(这|那)一刻…终于明白」：真人语料里那是正常的认知节拍，短篇第一人称审判句还是卖点
// （short-deslop.md「审判金句 / 直白收尾」），密度型由 advisory 的 abstract-summary-tic 兜。
// 各分支都要求落在句末断言位，否则会吃进条件从句（等这一切结束了，我们就…）、动补
// （这一切都说明得非常清楚）、成语跨匹配（这一刻…命中注定）、系表（这一战的结果是注定的）、
// 及物用法（就这样…才结束了这个话题）、场内报幕（就这样…宣布…圆满落幕）和否定认知
// （他不知道这一切意味着什么）——最后一类靠 (?!什么) 排掉间接疑问，那是盖章的反面。
// 校准（文末 600 字窗口，命中逐条人工复核）：qimao 章中段 20000 章命中 1 处（0.005%）、
// heiyan 整篇 3999 篇命中 22 处（0.550%，全部是上列禁用形态）；同批既有 trailer-ending
// 分别命中 1.345% / 6.602%——本规则误报面显著小于已上线的同窗口规则。短篇整篇即收口，
// 基线天然高于长篇章中段，故两个总体分别报数。
const TRAILER_SUMMARY_PATTERN = /这一(?:夜|天|刻|战|年|局|役)[，,]?[^。！？!?，,\n]{0,6}(?<!命中)(?<!是)注定[^。！？!?\n]{0,8}[。！]|就这样[，,][^。！？!?，,\n]{0,8}(?:一切|全部)[^。！？!?，,\n]{0,4}(?:结束了|落幕|收场)[。！]|这一切[，,]?[^。！？!?，,\n]{0,6}(?:都)?(?:说明|意味着|结束了)(?!的)(?:(?!什么)[^。！？!?\n]){0,6}[。！]|(?:新的篇章|新的旅程|崭新的篇章|新的人生)[^。！？!?\n]{0,6}(?:开始|拉开|展开)|命运[^。！？!?\n]{0,6}齿轮|(?:这就是|这才是)[^。！？!?\n]{1,10}(?:最大的)?意义|活下来的[，,]?是一个更|花了[一二三四五六七八九十百千万0-9]+年[，,]?才明白这个道理|获得了[^。！？!?\n]{0,12}(?:真正的自由|解脱)/g;

// 引号强调滥用（实战漏网 E，advisory 密度型，风格照 metaphor-density-tic）：
// 叙述里短词加引号强调（他是被请来"把关"的）。只数叙述层 1-4 字成对引号片段；
// 排除项：【】系统面板载体、引语动词（说|道|问|喊|答|念|叫|回|吼|嘀咕，加细 骂|写|读|唱）
// 前 6 字/后 3 字邻接的极短台词、引号内含句读的台词、引号外无叙述的行（独立台词/
// 弹幕流/拟声词连发）、引号套引号（台词内强调）。单处强调是正常修辞，高密度聚集才报。
// 校准：网文单章常有设定词/称号/系统名词引号（如“系统”“废材”），按篇幅比例取
// Math.max(8, Math.round(4 * scale))，只抓高频泛滥强调。
const QUOTE_EMPHASIS_MIN_HITS = 8;
const QUOTE_EMPHASIS_MAX_VISIBLE = 4;
const QUOTE_EMPHASIS_SPEECH_VERB_PATTERN = /[说道问喊答念叫回吼骂写读唱笑叹应哼嗤啐呸嘀咕]|开口|摇头|点头|出声|冷笑|苦笑|轻声|低声|沉声/;
// 历史/世情专名与印信匾额豁免（如“江宁崔氏”“仁和堂”或 刻着/写着/印着/挂着/贴着“……”）
const QUOTE_EMPHASIS_PROPER_SUFFIX_PATTERN = /[氏府堂号铺庄坊印匾]$/;
const QUOTE_EMPHASIS_INSCRIPTION_BEFORE_PATTERN = /刻着|写着|印着|挂着|贴着/;
const QUOTE_EMPHASIS_ONOMATOPOEIA_PATTERN = /^(?:啪|噼啪|咔哒|咔嚓|咣当|砰|咚|哗啦|哗|哇|嗡|嘶|滴答|叮|叮咚|哐当|哐啷|轰隆|呼啦|嘎吱)$/;

// 叙述旁白省略号密度：真人网文（尤其番茄男频/女频）常用旁白 `……` 表达停顿/心理吐槽，
// 少量留白正常保留；全章引号与面板外 ≥10 处且 ≥6.0/千字才报 advisory。
const ELLIPSIS_DENSITY_PATTERN = /…+|\.{3,}|。{3,}/g;
const ELLIPSIS_DENSITY_MIN_HITS = 10;
const ELLIPSIS_DENSITY_PER_KILO = 6.0;

// 感叹号过密（advisory only）：反文学腔后模型常出现叙述咆哮标点过矫正。
// 引号与面板外叙述 ！ ≥12 处且 ≥10.0/千字，或全文（含对白）！ ≥25 处且 ≥22.0/千字（短篇 ≥28 处且 ≥21.0/千字）给 advisory。
const EXCLAMATION_PATTERN = /[！!]/g;
const EXCLAMATION_NARRATION_MIN_HITS = 12;
const EXCLAMATION_NARRATION_PER_KILO = 10.0;
const EXCLAMATION_TOTAL_MIN_HITS = 25;
const EXCLAMATION_TOTAL_PER_KILO = 22.0;
const SHORT_EXCLAMATION_TOTAL_MIN_HITS = 28;
const SHORT_EXCLAMATION_TOTAL_PER_KILO = 21.0;

// 戏剧套词刷屏（advisory only）：死寂同章重复（长篇 ≥2 处，短篇按篇幅缩放 ≥3 处）、
// 核心戏剧震惊套词（死寂/轰然/骤然/骇然/色变/倒吸）聚集，或正常动作副词（猛地/瞬间）极端高频刷屏。
const DRAMATIC_SIJI_PATTERN = /死寂/g;
const DRAMATIC_CORE_PATTERN = /死寂|轰然|骤然|骇然|色变|倒吸/g;
const DRAMATIC_ACTION_PATTERN = /猛地|瞬间/g;
const LONG_DRAMATIC_SIJI_MIN_HITS = 2;
const SHORT_DRAMATIC_SIJI_MIN_HITS = 3;
const LONG_DRAMATIC_CORE_MIN_HITS = 4;
const LONG_DRAMATIC_CORE_PER_KILO = 2.5;
const SHORT_DRAMATIC_CORE_MIN_HITS = 6;
const SHORT_DRAMATIC_CORE_PER_KILO = 2.5;
const LONG_DRAMATIC_ACTION_MIN_HITS = 10;
const LONG_DRAMATIC_ACTION_PER_KILO = 5.5;
const SHORT_DRAMATIC_ACTION_MIN_HITS = 16;
const SHORT_DRAMATIC_ACTION_PER_KILO = 6.0;

// 女频油腻/言情套词聚集（advisory only；262.4 万字女频实证：指节泛白 6.10×、宠溺 2.98×、喉结 2.69×、声音低哑 2.44×、耳尖泛红 2.26×）。
// 严禁收录「轻笑/低笑」（实测 0.90× 为人类高口碑女频正常语感）。单章命中 ≥3 处且密度 ≥1.5/千字时提示人工去油。
const ROMANCE_CLICHE_NARRATION_PATTERN = /指节泛白|眸色一暗|眸光一暗|喉结(?:轻)?滚|声音低(?:沉)?沙哑|声音低哑|耳尖(?:泛红|发烫|微红)|(?:眼神|满眼|语气|带着[^，。\n]{0,4})宠溺|骨节分明的大手|骨节分明|(?:心跳|心头)漏跳?了?一拍|微不可察|拆吞入腹|暧昧流转|木质雪松|眼底(?:掠过|闪过)一丝(?:难以察觉|不易察觉|微不可察)/g;
const ROMANCE_CLICHE_PATERNAL_PATTERN = /小女人|香香软软|小白兔|女人[，,]你/g;
// 极高危女频言情 AI 套词：单次即出低级 advisory（2000 篇实库几乎零误报），防单次漏网。
// 注：「微不可察」已移出单次触发，改由 ≥2 处聚集规则兜底，避免误伤高分男频/女频单次正常用法。
const ROMANCE_CLICHE_SINGLE_HIGH_RISK_PATTERN = /骨节分明的大手|眼底(?:掠过|闪过)一丝(?:难以察觉|不易察觉|微不可察)|(?:心跳|心头)漏跳?了?一拍|拆吞入腹|小女人|香香软软|女人[，,]你/g;
const ROMANCE_CLICHE_WEIBUKECHA_PATTERN = /微不可察/g;
const ROMANCE_CLICHE_WEIBUKECHA_MIN_HITS = 2;
const ROMANCE_CLICHE_MIN_HITS = 3;
const ROMANCE_CLICHE_PER_KILO = 1.5;
// 非言情语境（末世异兽/怪兽/丧尸/虫族等字面吞噬）里的「拆吞入腹」不计入言情油腻套词（Wave 6 P04 实测误伤修复）。
const MONSTER_DEVOUR_CTX_RE = /异兽|丧尸|魔兽|妖兽|巨兽|虫族|怪物|荒兽|猛兽|凶兽|血口|獠牙|利齿|吞噬|啃食|咬碎|尸潮|兽潮/;

// 短篇高频塑料反应套词聚集（advisory only；R077/R080 真人盲测补漏）：
// 短篇整篇体量下通用密度门常漏掉离散 AI 塑料反应词；仅在 --mode=short 下扫描引号外叙述，
// 合计命中 ≥2 处即发 1 条 semantic advisory，不阻断也不误伤单次偶发。
const SHORT_PLASTIC_REACTION_PATTERN = /眼底闪过一丝|瞳孔(?:骤缩|猛地?一缩|失焦)|喉结[^，。！？!?\n]{0,3}滚|指节[^，。！？!?\n]{0,3}泛白|气得浑身发抖|死一般(?:的)?寂静/g;
const SHORT_PLASTIC_REACTION_MIN_HITS = 2;

// 单章密度分级门槛（800 章真人长篇 + 500 篇真人短篇误报校准）：偶发 1 处（not-is 族 1-2 处）常承担正常纠错、转折或章末钩子，
// 降为 advisory + semantic 交上下文判断；同章高频连刷升为 blocking + mechanical 强制清零。
// 短篇整篇（约 8,000-12,000 字）写在单个 正文.md 时，按章节当量 DENSITY_SCALE_UNIT_CHARS 等比抬升全篇句式阻断线（单章 ≤6,749 字时倍数为 1）。
const DENSITY_SCALE_UNIT_CHARS = 4500;
const NOT_IS_BLOCKING_MIN_HITS = 3;
const VOICE_CONTRAST_BLOCKING_MIN_HITS = 2;
const NEGATION_PARADE_BLOCKING_MIN_HITS = 2;
const TRAILER_ENDING_BLOCKING_MIN_HITS = 2;

// review 分类：下游按它分流。mechanical = 命中的表面形态本身就是问题，写作端就地改写即可；
// semantic = 同一形态可能承担叙事功能，要读上下文判断保留还是改（交语义审查）。blocking 只能是
// mechanical（blocking 的含义就是不需判断、必须清零）。新增 finding type 必须在此登记，否则运行期
// 直接报错退出（scripts/test-ai-patterns.mjs 另从源码抽 type 与本表双向核对）。
//   type                         review      理由
//   not-is-comparison            mechanical  固定句式模板「不是A，而是B」，blocking
//   voice-contrast               mechanical  固定反差模板「声音不大…却」，blocking
//   negation-parade              mechanical  固定否定排比模板，blocking
//   reverse-not-is               mechanical  固定反序对比模板「是A，不是B」，blocking
//   trailer-ending               mechanical  文末窗口固定预告短语，blocking
//   trailer-summary              mechanical  文末窗口固定总结短语，blocking
//   em-dash                      mechanical  标点密度过密（低中密度与短篇按 semantic advisory）
//   long-paragraph               mechanical  段长阈值，断段即可
//   period-stutter               mechanical  连续短句计数，合句即可
//   micro-action-tic             mechanical  固定补语「了下/了一下」密度
//   negation-pair-tic            semantic    「没A，也没B」否定对偶，留真正要强调的
//   cliche-density-tic           mechanical  固定禁用词表密度
//   stock-reaction-tic           semantic    身体反应可能承担物理后果或情绪，要逐处做删除测试
//   action-list-tic              semantic    打斗/追逐等功能性动作编排可保留
//   abstract-summary-tic         semantic    作者总结/上帝视角，是否越位要看语境
//   metaphor-density-tic         semantic    比喻是否服务画面、删哪几个要读上下文
//   reasoning-chain-tic          semantic    替读者推理的解释链，长推理段可能是正当的
//   system-notice-formality-tic  semantic    系统/规则文本本就可以公文腔，看体裁功能
//   overcompressed-prose-tic     semantic    短段过密可能是节奏选择，禁止机械注水
//   low-connective-density-tic   semantic    同上，连接词补不补要看读感
//   idle-prop-decoration-tic     semantic    材质/服饰/光影/声效贴纸是否承担实证功能要读上下文
//   quote-emphasis-tic           semantic    标语/转述载体的引号是正常写法
//   formulaic-parallelism        semantic    工整并列可能承担辩解或悬念排除
const REVIEW_CLASSES = Object.freeze({
  'not-is-comparison': 'mechanical',
  'voice-contrast': 'mechanical',
  'negation-parade': 'mechanical',
  'reverse-not-is': 'mechanical',
  'trailer-ending': 'mechanical',
  'trailer-summary': 'mechanical',
  'em-dash': 'mechanical',
  'long-paragraph': 'mechanical',
  'period-stutter': 'mechanical',
  'micro-action-tic': 'mechanical',
  'negation-pair-tic': 'semantic',
  'cliche-density-tic': 'mechanical',
  'stock-reaction-tic': 'semantic',
  'action-list-tic': 'semantic',
  'abstract-summary-tic': 'semantic',
  'metaphor-density-tic': 'semantic',
  'reasoning-chain-tic': 'semantic',
  'system-notice-formality-tic': 'semantic',
  'overcompressed-prose-tic': 'semantic',
  'low-connective-density-tic': 'semantic',
  'idle-prop-decoration-tic': 'semantic',
  'quote-emphasis-tic': 'semantic',
  'formulaic-parallelism': 'semantic',
  'ellipsis-density-tic': 'semantic',
  'exclamation-density-tic': 'semantic',
  'dramatic-cliche-tic': 'semantic',
  'romance-cliche-tic': 'semantic',
  'short-plastic-reaction-tic': 'semantic',
  'staccato-paragraph-tic': 'semantic',
});

// 与 hooks / storyctl 同一语法：文件前 6 行含 `<!-- 去味:跳过 -->` 时，仅在传入 `--respect-skip` 时将
// blocking/review_required 降为 advisory（带 exempted: '去味:跳过'）；默认不降级，供显式 /story-deslop 扫描并清理标记。
const DESLOP_SKIP_PATTERN = /<!--[ \t]*去味[ \t]*(：|:)[ \t]*跳过[ \t]*-->/;

function hasDeslopSkip(input) {
  const head = String(input || '').replace(/^\ufeff/, '').split(/\r?\n/).slice(0, 6).join('\n');
  return DESLOP_SKIP_PATTERN.test(head);
}

const options = {
  json: false,
  files: [],
  failOn: 'all',
  mode: 'auto',
  respectSkip: false,
};

for (let i = 2; i < process.argv.length; i += 1) {
  const arg = process.argv[i];
  if (arg === '--check') {
    // Accepted for symmetry with normalize-punctuation.js; detection is always check-only.
  } else if (arg === '--respect-skip') {
    options.respectSkip = true;
  } else if (arg === '--list-review-classes') {
    process.stdout.write(`${JSON.stringify(REVIEW_CLASSES, null, 2)}\n`);
    process.exit(0);
  } else if (arg === '--json') {
    options.json = true;
  } else if (arg === '--mode') {
    const v = process.argv[i + 1];
    if (v !== 'auto' && v !== 'long' && v !== 'short') {
      die("--mode must be 'auto', 'long', or 'short'");
    }
    options.mode = v;
    i += 1;
  } else if (arg.startsWith('--mode=')) {
    const v = arg.slice('--mode='.length);
    if (v !== 'auto' && v !== 'long' && v !== 'short') {
      die("--mode must be 'auto', 'long', or 'short'");
    }
    options.mode = v;
  } else if (arg === '--fail-on') {
    const v = process.argv[i + 1];
    if (v !== 'blocking' && v !== 'review_required' && v !== 'all') {
      die("--fail-on must be 'blocking', 'review_required', or 'all'");
    }
    options.failOn = v;
    i += 1;
  } else if (arg.startsWith('--fail-on=')) {
    const v = arg.slice('--fail-on='.length);
    if (v !== 'blocking' && v !== 'review_required' && v !== 'all') {
      die("--fail-on must be 'blocking', 'review_required', or 'all'");
    }
    options.failOn = v;
  } else if (arg === '-h' || arg === '--help') {
    process.stdout.write(`${USAGE}\n`);
    process.exit(0);
  } else if (arg.startsWith('-')) {
    die(`Unknown option: ${arg}`);
  } else {
    options.files.push(arg);
  }
}

function resolveMode(fullPath, requestedMode) {
  if (requestedMode === 'short' || requestedMode === 'long') return requestedMode;
  if (path.basename(fullPath) === '正文.md') {
    const dir = path.dirname(fullPath);
    if (fs.existsSync(path.join(dir, '设定.md')) || fs.existsSync(path.join(dir, '小节大纲.md'))) {
      return 'short';
    }
  }
  return 'long';
}

if (options.files.length === 0) {
  die('No files provided');
}

let failed = false;
const allFindings = [];

for (const file of options.files) {
  const fullPath = path.resolve(file);
  let input;
  try {
    input = fs.readFileSync(fullPath, 'utf8');
  } catch (error) {
    failed = true;
    if (!options.json) console.error(`${file}: unable to read (${error.message})`);
    continue;
  }

  let whitelist;
  try { whitelist = loadStyleWhitelist(fullPath); }
  catch (error) { die(`${file}: unable to read .deslop-whitelist (${error.message})`); }
  const effectiveMode = resolveMode(fullPath, options.mode);
  const exempt = options.respectSkip && hasDeslopSkip(input);
  const findings = scanDocument(maskStyleText(input, whitelist), new Set(), effectiveMode).map((finding) => {
    const baseReview = reviewClass(finding.type);
    const row = { file, ...finding, review: finding.review || baseReview };
    if (exempt && (row.severity === 'blocking' || row.severity === 'review_required')) {
      return { ...row, severity: 'advisory', exempted: '去味:跳过' };
    }
    return row;
  });
  allFindings.push(...findings);
}

const blockingCount = allFindings.filter((f) => f.severity === 'blocking').length;
const reviewRequiredCount = allFindings.filter((f) => f.severity === 'review_required').length;
const advisoryCount = allFindings.filter((f) => f.severity === 'advisory').length;

if (options.json) {
  process.stdout.write(`${JSON.stringify({
    fail_on: options.failOn,
    findings: allFindings,
    blocking: blockingCount,
    review_required: reviewRequiredCount,
    advisory: advisoryCount,
  }, null, 2)}\n`);
} else {
  for (const finding of allFindings) {
    console.log(`${finding.file}:${finding.line}:${finding.column}: [${finding.severity}] ${finding.type}: ${finding.message} (${finding.excerpt})`);
  }
}

if (failed) process.exit(2);
// --fail-on=blocking 只在出现 hard blocking finding 时退出 1；--fail-on=review_required 在 blocking/review_required 时退出 1；
// 默认 all 沿用「有任何 finding 即 1」。用 process.exitCode 确保 >64KB JSON 管道输出完整刷出后再退出。
const shouldFail =
  options.failOn === 'blocking'
    ? blockingCount > 0
    : options.failOn === 'review_required'
      ? blockingCount > 0 || reviewRequiredCount > 0
      : allFindings.length > 0;
if (shouldFail) process.exitCode = 1;

function reviewClass(type) {
  const review = REVIEW_CLASSES[type];
  if (!review) {
    console.error(`internal error: finding type '${type}' has no review class (add it to REVIEW_CLASSES)`);
    process.exit(2);
  }
  return review;
}

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function escapeRegExpCharClass(text) {
  return text.replace(/[\\\]^-]/g, '\\$&');
}

function die(message) {
  console.error(message);
  console.error(USAGE.trimEnd());
  process.exit(2);
}

// unclosedOpenings：到文末都没闭合的 `<!--` 位置（"行号:列号"）。未闭合的注释不是注释，
// 否则一个漏写的 `-->` 会把后面整章藏起来；这些位置按正文扫描，只把 `<!--` 本身抹掉。
function scanDocument(input, unclosedOpenings = new Set(), mode = 'long') {
  // 剥离零宽不可见字符，防从网页/飞书/微信粘贴夹带 \u200b 绕过机械检测
  const cleanedInput = String(input || '').replace(/[\u200B-\u200D\uFEFF]/g, '');
  const lines = cleanedInput.split(/\r?\n/);
  const findings = [];
  let fence = null;
  let inFrontMatter = hasYamlFrontMatter(lines);
  let commentOpen = false;
  let commentStart = null;
  let block = [];
  const proseLines = [];

  const flushBlock = () => {
    if (block.length === 0) return;
    findings.push(...scanBlock(block));
    block = [];
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const trimmed = line.trim();

    if (inFrontMatter) {
      if (index > 0 && trimmed === '---') inFrontMatter = false;
      continue;
    }

    const fenceMarker = parseFenceMarker(trimmed);
    if (fence) {
      if (fenceMarker && fenceMarker.char === fence.char && fenceMarker.length >= fence.length) {
        fence = null;
      }
      continue;
    }

    if (fenceMarker && !commentOpen) {
      flushBlock();
      fence = fenceMarker;
      continue;
    }

    // HTML 注释（如 `<!-- 去味:跳过 -->` 豁免标记）是元信息不是正文：注释段等长换成空格
    // 保列号，整行都是注释的直接跳过；注释可跨行。
    const masked = maskHtmlComments(line, commentOpen, index, unclosedOpenings);
    commentOpen = masked.open;
    if (masked.openedAt !== null) commentStart = masked.openedAt;
    if (masked.text !== line && !masked.text.trim()) continue;

    block.push({ text: masked.text, lineNo: index + 1 });
    proseLines.push({ text: masked.text, stripped: masked.stripped, lineNo: index + 1 });
  }

  if (commentOpen && commentStart !== null) {
    return scanDocument(input, new Set([...unclosedOpenings, commentStart]), mode);
  }

  flushBlock();
  let proseChars = 0;
  for (const { text } of proseLines) {
    const trimmed = text.trim();
    if (!trimmed || isDivider(trimmed) || isStructural(trimmed)) continue;
    proseChars += Array.from(trimmed.replace(/\s+/g, '')).length;
  }
  const scale = computeDensityScale(proseChars);
  findings.push(...scanProsePatterns(proseLines, mode, scale));
  applyDensitySeverityGates(findings, proseChars, mode);
  findings.sort((a, b) => a.line - b.line || a.column - b.column);
  return findings;
}

function computeDensityScale(proseChars = 0) {
  return Math.max(1, Math.floor((proseChars + Math.floor(DENSITY_SCALE_UNIT_CHARS / 2)) / DENSITY_SCALE_UNIT_CHARS));
}

function applyDensitySeverityGates(findings, proseChars = 0, mode = 'long') {
  const scale = computeDensityScale(proseChars);
  const counts = new Map();
  let trailerClicheCount = 0;
  for (const f of findings) {
    counts.set(f.type, (counts.get(f.type) || 0) + 1);
    if (f.type === 'trailer-ending' && !shortSpoilerFindings.has(f)) {
      trailerClicheCount += 1;
    }
  }
  const notIsCombined = (counts.get('not-is-comparison') || 0) + (counts.get('reverse-not-is') || 0);
  const notIsThreshold = mode === 'short'
    ? Math.max(6, Math.round(3 * scale))
    : NOT_IS_BLOCKING_MIN_HITS * scale;
  for (const f of findings) {
    let block = null;
    if (f.type === 'not-is-comparison' || f.type === 'reverse-not-is') {
      block = notIsCombined >= notIsThreshold;
    } else if (f.type === 'voice-contrast') {
      block = (counts.get('voice-contrast') || 0) >= VOICE_CONTRAST_BLOCKING_MIN_HITS * scale;
    } else if (f.type === 'negation-parade') {
      block = (counts.get('negation-parade') || 0) >= NEGATION_PARADE_BLOCKING_MIN_HITS * scale;
    } else if (f.type === 'trailer-ending') {
      if (mode === 'short') {
        block = !shortSpoilerFindings.has(f) && trailerClicheCount >= TRAILER_ENDING_BLOCKING_MIN_HITS;
      } else {
        block = (counts.get('trailer-ending') || 0) >= TRAILER_ENDING_BLOCKING_MIN_HITS;
      }
    }
    if (block === true) {
      f.severity = 'review_required';
      f.review = 'mechanical';
    } else if (block === false) {
      f.severity = 'advisory';
      f.review = 'semantic';
    }
  }
}

function isQuotedMonologueParagraph(para) {
  if (/^[“「『"【]/.test(para)) return true;
  const totalVis = visibleLength(para);
  if (totalVis === 0) return false;
  const narVis = visibleLength(stripQuotedWithUnclosed(para));
  return narVis <= 20 || (totalVis - narVis) / totalVis >= 0.7;
}

// 段落级检测：碎句号（连续短叙述句）、长段落、旁白破折号密度（对白引号与面板内豁免）。
function scanProsePatterns(proseLines, mode = 'long', scale = 1) {
  const findings = [];
  let dashHits = 0;
  let dashNarrativeChars = 0;
  let dashFirstLine = null;
  let dashFirstCol = 1;
  const dashSamples = [];

  for (const { text, stripped, lineNo } of proseLines) {
    const trimmed = text.trim();
    if (!trimmed || isDivider(trimmed) || isStructural(trimmed)) continue;

    const dashScanText = maskQuotedWithUnclosed(text);
    const dashPattern = /——+|—|--+/g;
    dashNarrativeChars += visibleLength(stripQuotedWithUnclosed(trimmed));
    let dash;
    while ((dash = dashPattern.exec(dashScanText)) !== null) {
      // 跳过连续 ≥3 个「—」的行内场景装饰线（如 ————）与紧跟拟声词的拖音（如 轰隆隆——！/嘟——嘟——）
      if (dash[0].length >= 3 && /^—+$/.test(dash[0])) continue;
      const beforeDash = dashScanText.slice(Math.max(0, dash.index - 6), dash.index);
      if (ONOMATOPOEIA_BEFORE_DASH_RE.test(beforeDash) || ONOMATOPOEIA_PAIR_BEFORE_DASH_RE.test(beforeDash)) continue;
      dashHits += 1;
      if (dashFirstLine === null) {
        dashFirstLine = lineNo;
        dashFirstCol = dash.index + 1;
      }
      const ex = compact(text.slice(Math.max(0, dash.index - 8), dash.index + dash[0].length + 8));
      if (dashSamples.length < 5 && ex && !dashSamples.includes(ex)) dashSamples.push(ex);
    }

    const effectivePara = (stripped !== undefined ? stripped : text).trim();
    const longParaLimit = mode === 'short'
      ? (isQuotedMonologueParagraph(effectivePara) ? SHORT_LONG_QUOTED_PARAGRAPH_CHARS : SHORT_LONG_PARAGRAPH_CHARS)
      : LONG_PARAGRAPH_CHARS;
    if (effectivePara.length > longParaLimit) {
      findings.push({
        line: lineNo,
        column: 1,
        type: 'long-paragraph',
        severity: 'advisory',
        message: `段落过长（${effectivePara.length} 字）：按镜头/新动作/新线索/视线切换断段，别一段到底。`,
        excerpt: compact(effectivePara.slice(0, 40)),
      });
    }
  }

  const emDashAdvisoryMinHits = mode === 'short' ? EM_DASH_ADVISORY_MIN_HITS : LONG_EM_DASH_ADVISORY_MIN_HITS;
  if (dashHits >= emDashAdvisoryMinHits) {
    const perKilo = dashNarrativeChars > 0 ? (dashHits / dashNarrativeChars) * 1000 : Infinity;
    const rateLabel = Number.isFinite(perKilo) ? `（${perKilo.toFixed(1)}/千字）` : '';
    if (mode !== 'short' && dashHits >= LONG_EM_DASH_REVIEW_MIN_HITS && perKilo >= LONG_EM_DASH_REVIEW_PER_KILO) {
      findings.push({
        line: dashFirstLine,
        column: dashFirstCol,
        type: 'em-dash',
        severity: 'review_required',
        review: 'mechanical',
        message: `叙述旁白破折号过密：${dashHits} 处${rateLabel}；保留关键系统提示、拖音或转折揭底拍，其余按功能改为逗号、冒号或动作，勿高频刷屏。`,
        excerpt: compact(dashSamples.join(' | ')),
      });
    } else if (perKilo >= EM_DASH_ADVISORY_PER_KILO) {
      findings.push({
        line: dashFirstLine,
        column: dashFirstCol,
        type: 'em-dash',
        severity: 'advisory',
        review: 'semantic',
        message: `${mode === 'short' ? '短篇' : ''}旁白破折号偏密：${dashHits} 处${rateLabel}；保留关键反转、系统提示或情绪揭底拍，其余按功能改逗号或冒号。`,
        excerpt: compact(dashSamples.join(' | ')),
      });
    }
  }

  findings.push(...findVoiceContrast(proseLines));
  findings.push(...findNegationParade(proseLines));
  findings.push(...findFormulaicParallelism(proseLines));
  findings.push(...findReverseNotIs(proseLines));
  findings.push(...findTrailerEnding(proseLines, mode));
  findings.push(...findQuoteEmphasisTic(proseLines, mode, scale));
  findings.push(...findPeriodStutter(proseLines, mode));
  findings.push(...findMicroActionTic(proseLines));
  findings.push(...findNegationPairTic(proseLines, mode, scale));
  findings.push(...findStockReactionTic(proseLines, mode));
  findings.push(...findActionListTic(proseLines));
  findings.push(...findAbstractSummaryTic(proseLines));
  findings.push(...findClicheDensityTic(proseLines));
  findings.push(...findMetaphorDensityTic(proseLines));
  findings.push(...findReasoningChainTic(proseLines));
  findings.push(...findNoticeFormalityTic(proseLines));
  if (mode !== 'short') {
    findings.push(...findOvercompressedProseTic(proseLines));
    findings.push(...findLowConnectiveDensityTic(proseLines));
    findings.push(...findIdlePropDecorationTic(proseLines, mode));
  }
  findings.push(...findEllipsisDensityTic(proseLines));
  findings.push(...findExclamationDensityTic(proseLines, mode));
  findings.push(...findDramaticClicheTic(proseLines, mode, scale));
  findings.push(...findRomanceClicheTic(proseLines));
  findings.push(...findShortPlasticReactionTic(proseLines, mode));
  findings.push(...findStaccatoParagraphTic(proseLines, mode));
  return findings;
}

// 音量反差腔（实战漏网 A）：引号外叙述命中，单处 advisory、同章 ≥2 处 blocking。
function findVoiceContrast(proseLines) {
  const findings = [];

  for (const { text, lineNo } of proseLines) {
    const trimmed = text.trim();
    if (!trimmed || isDivider(trimmed) || isStructural(trimmed)) continue;
    const masked = maskQuoted(text);
    VOICE_CONTRAST_PATTERN.lastIndex = 0;
    let match;
    while ((match = VOICE_CONTRAST_PATTERN.exec(masked)) !== null) {
      findings.push({
        line: lineNo,
        column: match.index + 1,
        type: 'voice-contrast',
        severity: 'review_required',
        message: '音量反差腔：「声音不大/不高…却/但…」是 AI 高频反差模板；删掉音量铺垫，直接写台词分量、利害后果或在场者的立场反应。',
        excerpt: compact(text.slice(match.index, match.index + match[0].length)),
      });
    }
  }

  return findings;
}

// 否定排比（实战漏网 B）：同句「没有X，」连排 / 先否定后「只是」收肯定。
// 可能在同一片文字上重叠命中，按区间去重只报一次。
function findNegationParade(proseLines) {
  const findings = [];

  for (const { text, lineNo } of proseLines) {
    const trimmed = text.trim();
    if (!trimmed || isDivider(trimmed) || isStructural(trimmed)) continue;
    const masked = maskQuoted(text);

    const spans = [];
    for (const pattern of NEGATION_PARADE_PATTERNS) {
      pattern.lastIndex = 0;
      let match;
      while ((match = pattern.exec(masked)) !== null) {
        spans.push([match.index, match.index + match[0].length]);
      }
    }
    spans.sort((a, b) => a[0] - b[0]);

    let lastEnd = -1;
    for (const [start, end] of spans) {
      if (start < lastEnd) {
        lastEnd = Math.max(lastEnd, end);
        continue;
      }
      lastEnd = end;
      findings.push({
        line: lineNo,
        column: start + 1,
        type: 'negation-parade',
        severity: 'review_required',
        message: '否定排比：「没有X，没有Y…」/「没X，没有Y，只是Z」是 AI 高频排比模板；删掉否定清单，直接写现场实际有什么，最多留一个最有信息量的否定。',
        excerpt: compact(text.slice(start, end)),
      });
    }
  }

  return findings;
}

function findFormulaicParallelism(proseLines) {
  const findings = [];

  for (const { text, lineNo } of proseLines) {
    const trimmed = text.trim();
    if (!trimmed || isDivider(trimmed) || isStructural(trimmed)) continue;
    for (const [pattern, message] of [
      [DECISION_FRAME_PATTERN, '「至于X不X，怎么X」把同一决定拆成工整栏目；若只是复述细纲，压成角色当下的一次判断或直接动作。'],
      [REPEATED_NEGATIVE_VERB_PATTERN, '同动词「不V A，不V B」容易写成否定清单；含台词也要按语境复核，保留真正有功能的一项即可。'],
    ]) {
      pattern.lastIndex = 0;
      let match;
      while ((match = pattern.exec(text)) !== null) {
        if (pattern === REPEATED_NEGATIVE_VERB_PATTERN) {
          const stem = match[1];
          if (PARALLELISM_EXCLUDED_STEMS.has(stem) || (stem.length === 2 && PARALLELISM_EXCLUDED_STEMS.has(stem[0]))) {
            continue;
          }
        }
        findings.push({
          line: lineNo,
          column: match.index + 1,
          type: 'formulaic-parallelism',
          severity: 'advisory',
          message,
          excerpt: compact(match[0]),
        });
      }
    }
    PERIOD_NEGATION_ONLY_PATTERN.lastIndex = 0;
    const maskedLine = maskQuoted(text);
    let pMatch;
    while ((pMatch = PERIOD_NEGATION_ONLY_PATTERN.exec(maskedLine)) !== null) {
      findings.push({
        line: lineNo,
        column: pMatch.index + 1,
        type: 'formulaic-parallelism',
        severity: 'advisory',
        message: '跨句「没有A。没有B。只有C。」属于否定铺排对比腔；删掉多余否定句，直接写现场实景。',
        excerpt: compact(text.slice(pMatch.index, pMatch.index + pMatch[0].length + 8)),
      });
    }
  }

  // 跨段「不是A / 也不是B / 只是C」及「没有A，没有B。/ 只有C」「没有A / 也没有B / 只有C」：
  // 纯句法无法稳定区分修辞铺排与悬念排除，因此只给 advisory，交给语义复核。
  const window = [];
  for (const { text, lineNo } of proseLines) {
    const trimmed = text.trim();
    if (!trimmed) continue;
    if (isDivider(trimmed) || isStructural(trimmed)) {
      window.length = 0;
      continue;
    }
    if (window.length && lineNo - window[window.length - 1].lineNo > 2) window.length = 0;
    const curEntry = { text: maskQuoted(trimmed), original: trimmed, lineNo };
    if (window.length >= 1) {
      const prevEntry = window[window.length - 1];
      if (CROSS_MEIYOU_PAIR_END.test(prevEntry.text) && CROSS_ZHIYOU_START.test(curEntry.text)) {
        findings.push({
          line: prevEntry.lineNo,
          column: 1,
          type: 'formulaic-parallelism',
          severity: 'advisory',
          message: '跨行「没有A，没有B。/ 只有C。」属于否定铺排对比腔；删掉空泛否定铺垫，直接写现场实景。',
          excerpt: compact(`${prevEntry.original} / ${curEntry.original}`),
        });
      }
    }
    window.push(curEntry);
    if (window.length > 3) window.shift();
    if (window.length !== 3) continue;
    if (CROSS_NEGATION_START.test(window[0].text)
      && CROSS_NEGATION_MIDDLE.test(window[1].text)
      && CROSS_NEGATION_END.test(window[2].text)) {
      findings.push({
        line: window[0].lineNo,
        column: 1,
        type: 'formulaic-parallelism',
        severity: 'advisory',
        message: '跨段「不是… / 也不是… / 只是…」可能是工整否定铺排，也可能承担辩解或悬念排除；通读语境，只在重复细纲或拖慢画面时改写。',
        excerpt: compact(window.map((entry) => entry.original).join(' / ')),
      });
    } else if (CROSS_MEIYOU_SINGLE_START.test(window[0].text)
      && CROSS_MEIYOU_SINGLE_MIDDLE.test(window[1].text)
      && CROSS_ZHIYOU_START.test(window[2].text)) {
      findings.push({
        line: window[0].lineNo,
        column: 1,
        type: 'formulaic-parallelism',
        severity: 'advisory',
        message: '跨段「没有… / 也没有… / 只有…」属于否定铺排对比腔；通读语境，删掉多余否定句直接写现场实景。',
        excerpt: compact(window.map((entry) => entry.original).join(' / ')),
      });
    }
  }

  return findings;
}

// 反序对比腔（实战漏网 C）：「是A，不是B」。排除基建复用 not-is-comparison：
// 引号内剥离、「是的/是啊」确认语；前字合成词与反问尾巴见 REVERSE_NOT_IS_PREV_EXCLUDE 注释。
function findReverseNotIs(proseLines) {
  const findings = [];

  for (const { text, lineNo } of proseLines) {
    const trimmed = text.trim();
    if (!trimmed || isDivider(trimmed) || isStructural(trimmed)) continue;
    const masked = maskQuoted(text);
    REVERSE_NOT_IS_PATTERN.lastIndex = 0;
    let match;
    while ((match = REVERSE_NOT_IS_PATTERN.exec(masked)) !== null) {
      const start = match.index;
      // 「就是/也是/还是/只是/可是…」里的「是」是合成词一部分，不是肯定项系动词。
      if (REVERSE_NOT_IS_PREV_EXCLUDE.has(masked[start - 1])) continue;
      // 「是不是…」问句起头。
      if (masked[start + 1] === '不') continue;
      // 「是的，…不是…」承接确认语（复用 not-is 的判定）。
      if (isAffirmationTagAt(masked, start)) continue;
      // 「…，不是吗/不是么/不是吧」反问尾巴。
      if (/^[吗么吧]/.test(match[2])) continue;
      findings.push({
        line: lineNo,
        column: start + 1,
        type: 'reverse-not-is',
        severity: 'review_required',
        message: '反序对比腔：「是A，不是B」与「不是A，是B」同族；删掉后置否定，直接写 A 的具体表现，或用细节让读者自己对比。',
        excerpt: compact(text.slice(start, start + match[0].length)),
      });
    }
  }

  return findings;
}

// 预告式总结收尾（实战漏网 D）：只扫文末窗口（正文 ≥500 字时收紧为 min(末 4 行, 末 250 字)，
// 根治 1k 字场景中段「没人知道」误报；短测试样本 <500 字仅按 250 字截断）。
function findTrailerEnding(proseLines, mode = 'long') {
  let totalDocChars = 0;
  for (const { text } of proseLines) {
    const trimmed = text.trim();
    if (!trimmed || isDivider(trimmed) || isStructural(trimmed)) continue;
    totalDocChars += visibleLength(stripQuoted(trimmed));
  }
  const maxLines = totalDocChars >= TRAILER_ENDING_LINE_CAP_MIN_DOC_CHARS
    ? TRAILER_ENDING_WINDOW_MAX_LINES
    : Infinity;
  const windowLines = [];
  let accumulated = 0;

  for (let i = proseLines.length - 1; i >= 0 && accumulated < TRAILER_ENDING_WINDOW_CHARS && windowLines.length < maxLines; i -= 1) {
    const { text } = proseLines[i];
    const trimmed = text.trim();
    if (!trimmed || isDivider(trimmed) || isStructural(trimmed)) continue;
    windowLines.unshift(proseLines[i]);
    accumulated += visibleLength(stripQuoted(trimmed));
  }

  const findings = [];
  for (const { text, lineNo } of windowLines) {
    const masked = maskQuoted(text);
    if (mode === 'short') {
      TRAILER_SPOILER_PATTERN.lastIndex = 0;
      let spoilerMatch;
      while ((spoilerMatch = TRAILER_SPOILER_PATTERN.exec(masked)) !== null) {
        const finding = {
          line: lineNo,
          column: spoilerMatch.index + 1,
          type: 'trailer-ending',
          severity: 'advisory',
          review: 'semantic',
          message: '短篇文末信息差/剧透钩子提示：确属后文兑现或火葬场预告可保留，无具体事件支撑则删改。',
          excerpt: compact(text.slice(spoilerMatch.index, spoilerMatch.index + spoilerMatch[0].length)),
        };
        shortSpoilerFindings.add(finding);
        findings.push(finding);
      }
      TRAILER_CLICHE_PATTERN.lastIndex = 0;
      let clicheMatch;
      while ((clicheMatch = TRAILER_CLICHE_PATTERN.exec(masked)) !== null) {
        findings.push({
          line: lineNo,
          column: clicheMatch.index + 1,
          type: 'trailer-ending',
          severity: 'review_required',
          message: '预告式总结收尾：「才刚刚开始/拉开序幕/正朝着…压了过去」是 AI 章尾预告腔；结尾停在具体决定、动作、画面或一句台词上，悬念让事件自己挂住，别替读者预告下一章。',
          excerpt: compact(text.slice(clicheMatch.index, clicheMatch.index + clicheMatch[0].length)),
        });
      }
    } else {
      TRAILER_ENDING_PATTERN.lastIndex = 0;
      let match;
      while ((match = TRAILER_ENDING_PATTERN.exec(masked)) !== null) {
        findings.push({
          line: lineNo,
          column: match.index + 1,
          type: 'trailer-ending',
          severity: 'review_required',
          message: '预告式总结收尾：「没人知道/才刚刚开始/正朝着…压了过去」是 AI 章尾预告腔；结尾停在具体决定、动作、画面或一句台词上，悬念让事件自己挂住，别替读者预告下一章。',
          excerpt: compact(text.slice(match.index, match.index + match[0].length)),
        });
      }
    }
    TRAILER_SUMMARY_PATTERN.lastIndex = 0;
    let summaryMatch;
    while ((summaryMatch = TRAILER_SUMMARY_PATTERN.exec(masked)) !== null) {
      findings.push({
        line: lineNo,
        column: summaryMatch.index + 1,
        type: 'trailer-summary',
        severity: 'review_required',
        message: '章尾状态总结体：「这一夜注定…/这一切都结束了/新的人生才刚刚开始/命运的齿轮」是把细纲的结尾设定原样写成了总结句；结尾设定要落成最后一个具体决定、动作、画面或台词，别替读者盖章。',
        excerpt: compact(text.slice(summaryMatch.index, summaryMatch.index + summaryMatch[0].length)),
      });
    }
  }

  return findings;
}

// 引号强调滥用（实战漏网 E）：统计叙述层 1-4 字成对引号强调片段，全文只报一条
// （密度型分布指纹）。台词类排除见 QUOTE_EMPHASIS_* 常量注释。
function findQuoteEmphasisTic(proseLines, mode = 'long', scale = 1) {
  let hits = 0;
  let firstLine = null;
  const samples = [];

  for (const { text, lineNo } of proseLines) {
    const trimmed = text.trim();
    if (!trimmed || isDivider(trimmed) || isStructural(trimmed)) continue;
    // 引号外没有叙述的行（独立台词/弹幕流/拟声词连发「“叮咚~”“叮咚~”」）整行跳过：
    // 强调滥用是叙述层指纹，没有叙述就无所谓强调。
    if (visibleLength(stripQuoted(trimmed)) === 0) continue;
    const ranges = quotedRanges(text);

    for (const [start, end] of ranges) {
      if (text[start] === '【') continue; // 系统面板/公告载体，不是强调引号
      // 引号套引号：台词内部的强调属于角色语言，不算叙述层强调滥用。
      if (ranges.some(([s2, e2]) => s2 <= start && end <= e2 && (s2 !== start || e2 !== end))) continue;
      const inner = text.slice(start + 1, end - 1);
      const visible = visibleLength(inner);
      if (visible < 1 || visible > QUOTE_EMPHASIS_MAX_VISIBLE) continue;
      if (/[。！？!?…，,；;：:—]|\.{2,}/.test(inner)) continue; // 含句读/省略/破折的是台词或播报，不是强调
      if (QUOTE_EMPHASIS_PROPER_SUFFIX_PATTERN.test(inner)) continue; // 宗族/商号/府邸/印信匾额专名（如“江宁崔氏”“仁和堂”）
      if (QUOTE_EMPHASIS_ONOMATOPOEIA_PATTERN.test(inner)) continue; // 常见拟声词引号（如“啪”“咣当”）
      const before = text.slice(Math.max(0, start - 8), start);
      const after = text.slice(end, end + 6);
      if (QUOTE_EMPHASIS_INSCRIPTION_BEFORE_PATTERN.test(before)) continue; // 刻着/写着/印着/挂着/贴着“……”类碑匾印文
      if (QUOTE_EMPHASIS_SPEECH_VERB_PATTERN.test(before) || QUOTE_EMPHASIS_SPEECH_VERB_PATTERN.test(after)) continue; // 引语动词邻接=极短台词
      if (/^(?:的|地)?一?[声下响]/.test(after)) continue; // 「“唰”的一声」类拟声词不是强调滥用
      hits += 1;
      if (firstLine === null) firstLine = lineNo;
      if (samples.length < 6 && !samples.includes(inner)) samples.push(inner);
    }
  }

  const minHits = Math.max(QUOTE_EMPHASIS_MIN_HITS, Math.round(4 * scale));
  if (hits < minHits) return [];

  return [{
    line: firstLine,
    column: 1,
    type: 'quote-emphasis-tic',
    severity: 'advisory',
    message: `引号强调滥用：叙述里 1-4 字短词加引号强调 ${hits} 处；只留真正反讽/转述必要的一两处，其余去掉引号直写原意，或把话里的反讽直接点明。`,
    excerpt: compact(samples.join(' ')),
  }];
}

// 否定对偶：统计引号外叙述里「没A，也没B」式句子，全文只报一条。
function findNegationPairTic(proseLines, mode = 'long', scale = 1) {
  let hits = 0;
  let firstLine = null;
  const samples = [];
  for (const { text, lineNo } of proseLines) {
    const trimmed = text.trim();
    if (!trimmed || isDivider(trimmed) || isStructural(trimmed)) continue;
    const narrative = stripQuoted(trimmed);
    NEGATION_PAIR_PATTERN.lastIndex = 0;
    let match;
    while ((match = NEGATION_PAIR_PATTERN.exec(narrative)) !== null) {
      hits += 1;
      if (firstLine === null) firstLine = lineNo;
      if (samples.length < 4) samples.push(match[0]);
    }
  }
  const minHits = mode === 'short' ? Math.max(6, Math.round(3 * scale)) : NEGATION_PAIR_MIN_HITS;
  if (hits < minHits) return [];
  return [{
    line: firstLine,
    column: 1,
    type: 'negation-pair-tic',
    severity: 'advisory',
    message: `否定对偶偏多：「没A，也没B」式叙述 ${hits} 处；写人物没做什么是英文式节奏，改成他做了什么（留一两处真正要强调的）。`,
    excerpt: compact(samples.join(' | ')),
  }];
}

function findEllipsisDensityTic(proseLines) {
  let hits = 0;
  let narrativeChars = 0;
  let firstLine = null;
  const samples = [];

  for (const { text, lineNo } of proseLines) {
    const trimmed = text.trim();
    if (!trimmed || isDivider(trimmed) || isStructural(trimmed)) continue;
    const narrative = stripQuotedWithUnclosed(trimmed);
    narrativeChars += visibleLength(narrative);
    ELLIPSIS_DENSITY_PATTERN.lastIndex = 0;
    let match;
    while ((match = ELLIPSIS_DENSITY_PATTERN.exec(narrative)) !== null) {
      hits += 1;
      if (firstLine === null) firstLine = lineNo;
      const sample = sentenceAround(narrative, match.index);
      if (samples.length < 5 && sample && !samples.includes(sample)) samples.push(sample);
    }
  }

  if (narrativeChars === 0 || hits < ELLIPSIS_DENSITY_MIN_HITS) return [];
  const perKilo = (hits / narrativeChars) * 1000;
  if (perKilo < ELLIPSIS_DENSITY_PER_KILO) return [];

  return [{
    line: firstLine,
    column: 1,
    type: 'ellipsis-density-tic',
    severity: 'advisory',
    message: `叙述省略号过密：引号与面板外省略号 ${hits} 处（${perKilo.toFixed(1)}/千字）；保留关键思绪留白，其余改成逗号承接、直白判断或具体动作，别几句一刷。`,
    excerpt: compact(samples.join(' | ')),
  }];
}

function findClosingQuoteAhead(proseLines, startIdx, closeChar, maxLookahead = 8) {
  let seen = 0;
  for (let j = startIdx + 1; j < proseLines.length && seen < maxLookahead; j += 1) {
    const t = proseLines[j].text.trim();
    if (!t) continue;
    if (isDivider(t) || isStructural(t)) return false;
    seen += 1;
    if (t.includes(closeChar)) return true;
  }
  return false;
}

function findExclamationDensityTic(proseLines, mode = 'long') {
  let narHits = 0;
  let narChars = 0;
  let totalHits = 0;
  let totalChars = 0;
  let firstNarLine = null;
  let firstTotalLine = null;
  const narSamples = [];
  const totalSamples = [];
  let activeCloseQuote = null;

  for (let i = 0; i < proseLines.length; i += 1) {
    const { text, lineNo } = proseLines[i];
    const trimmed = text.trim();
    if (!trimmed) continue;
    if (isDivider(trimmed) || isStructural(trimmed)) {
      activeCloseQuote = null;
      continue;
    }
    totalChars += visibleLength(trimmed);

    let working = trimmed;
    if (activeCloseQuote) {
      const closeIdx = working.indexOf(activeCloseQuote);
      if (closeIdx === -1) {
        working = '';
      } else {
        working = working.slice(closeIdx + 1);
        activeCloseQuote = null;
      }
    }
    const afterPaired = stripQuoted(working);
    const unclosed = /[“「『"]/.exec(afterPaired);
    let narrative = afterPaired;
    if (unclosed) {
      narrative = afterPaired.slice(0, unclosed.index);
      const closer = OPEN_TO_CLOSE_QUOTE[unclosed[0]];
      if (closer && findClosingQuoteAhead(proseLines, i, closer)) {
        activeCloseQuote = closer;
      }
    }
    narChars += visibleLength(narrative);

    EXCLAMATION_PATTERN.lastIndex = 0;
    let m;
    while ((m = EXCLAMATION_PATTERN.exec(narrative)) !== null) {
      narHits += 1;
      if (firstNarLine === null) firstNarLine = lineNo;
      const sample = sentenceAround(narrative, m.index);
      if (narSamples.length < 4 && sample && !narSamples.includes(sample)) narSamples.push(sample);
    }

    EXCLAMATION_PATTERN.lastIndex = 0;
    while ((m = EXCLAMATION_PATTERN.exec(trimmed)) !== null) {
      totalHits += 1;
      if (firstTotalLine === null) firstTotalLine = lineNo;
      const sample = sentenceAround(trimmed, m.index);
      if (totalSamples.length < 4 && sample && !totalSamples.includes(sample)) totalSamples.push(sample);
    }
  }

  const narPerKilo = narChars > 0 ? (narHits / narChars) * 1000 : 0;
  const totalPerKilo = totalChars > 0 ? (totalHits / totalChars) * 1000 : 0;
  const totalMinHits = mode === 'short' ? SHORT_EXCLAMATION_TOTAL_MIN_HITS : EXCLAMATION_TOTAL_MIN_HITS;
  const totalPerKiloLimit = mode === 'short' ? SHORT_EXCLAMATION_TOTAL_PER_KILO : EXCLAMATION_TOTAL_PER_KILO;

  const narTriggered = narChars > 0 && narHits >= EXCLAMATION_NARRATION_MIN_HITS && narPerKilo >= EXCLAMATION_NARRATION_PER_KILO;
  const totalTriggered = totalChars > 0 && totalHits >= totalMinHits && totalPerKilo >= totalPerKiloLimit;
  if (!narTriggered && !totalTriggered) return [];

  const reasons = [];
  if (narTriggered) reasons.push(`叙述旁白 ${narHits} 处（${narPerKilo.toFixed(1)}/千字）`);
  if (totalTriggered) reasons.push(`全文 ${totalHits} 处（${totalPerKilo.toFixed(1)}/千字）`);
  const samples = narTriggered ? narSamples : totalSamples;

  return [{
    line: narTriggered ? firstNarLine : firstTotalLine,
    column: 1,
    type: 'exclamation-density-tic',
    severity: 'advisory',
    message: `感叹号过密：${reasons.join('、')}；旁白默认用句号，只把感叹号留给真正的高点震撼与当面爆喝，其余改回句号让情绪落稳。`,
    excerpt: compact(samples.join(' | ')),
  }];
}

function findDramaticClicheTic(proseLines, mode = 'long', scale = 1) {
  let sijiHits = 0;
  let coreHits = 0;
  let actionHits = 0;
  let narrativeChars = 0;
  let firstSijiLine = null;
  let firstCoreLine = null;
  let firstActionLine = null;
  const coreSamples = [];
  const actionSamples = [];

  for (const { text, lineNo } of proseLines) {
    const trimmed = text.trim();
    if (!trimmed || isDivider(trimmed) || isStructural(trimmed)) continue;
    const narrative = stripQuoted(trimmed);
    narrativeChars += visibleLength(narrative);

    DRAMATIC_SIJI_PATTERN.lastIndex = 0;
    let m;
    while ((m = DRAMATIC_SIJI_PATTERN.exec(narrative)) !== null) {
      sijiHits += 1;
      if (firstSijiLine === null) firstSijiLine = lineNo;
    }

    DRAMATIC_CORE_PATTERN.lastIndex = 0;
    while ((m = DRAMATIC_CORE_PATTERN.exec(narrative)) !== null) {
      coreHits += 1;
      if (firstCoreLine === null) firstCoreLine = lineNo;
      if (coreSamples.length < 6) coreSamples.push(m[0]);
    }

    DRAMATIC_ACTION_PATTERN.lastIndex = 0;
    while ((m = DRAMATIC_ACTION_PATTERN.exec(narrative)) !== null) {
      actionHits += 1;
      if (firstActionLine === null) firstActionLine = lineNo;
      if (actionSamples.length < 6) actionSamples.push(m[0]);
    }
  }

  const sijiMinHits = mode === 'short' ? Math.max(SHORT_DRAMATIC_SIJI_MIN_HITS, Math.round(1.5 * scale)) : LONG_DRAMATIC_SIJI_MIN_HITS;
  const coreMinHits = mode === 'short' ? SHORT_DRAMATIC_CORE_MIN_HITS : LONG_DRAMATIC_CORE_MIN_HITS;
  const corePerKiloLimit = mode === 'short' ? SHORT_DRAMATIC_CORE_PER_KILO : LONG_DRAMATIC_CORE_PER_KILO;
  const actionMinHits = mode === 'short' ? SHORT_DRAMATIC_ACTION_MIN_HITS : LONG_DRAMATIC_ACTION_MIN_HITS;
  const actionPerKiloLimit = mode === 'short' ? SHORT_DRAMATIC_ACTION_PER_KILO : LONG_DRAMATIC_ACTION_PER_KILO;
  const corePerKilo = narrativeChars > 0 ? (coreHits / narrativeChars) * 1000 : 0;
  const actionPerKilo = narrativeChars > 0 ? (actionHits / narrativeChars) * 1000 : 0;

  const sijiTriggered = sijiHits >= sijiMinHits;
  const coreTriggered = narrativeChars > 0 && coreHits >= coreMinHits && corePerKilo >= corePerKiloLimit;
  const actionTriggered = narrativeChars > 0 && actionHits >= actionMinHits && actionPerKilo >= actionPerKiloLimit;
  if (!sijiTriggered && !coreTriggered && !actionTriggered) return [];

  const reasons = [];
  if (sijiTriggered) reasons.push(`「死寂」重复 ${sijiHits} 次`);
  if (coreTriggered) reasons.push(`死寂/轰然/骤然/骇然/色变/倒吸 聚集 ${coreHits} 处（${corePerKilo.toFixed(1)}/千字）`);
  if (actionTriggered) reasons.push(`猛地/瞬间 刷屏 ${actionHits} 处（${actionPerKilo.toFixed(1)}/千字）`);
  const samples = coreSamples.length ? coreSamples : actionSamples;
  const firstLine = sijiTriggered ? firstSijiLine : (coreTriggered ? firstCoreLine : firstActionLine);

  return [{
    line: firstLine,
    column: 1,
    type: 'dramatic-cliche-tic',
    severity: 'advisory',
    message: `戏剧套词刷屏：${reasons.join('、')}；保留最有冲击力的一处，其余改写为具体环境声响、人物失态动作或利害反应，避免强行拉满惊愕感。`,
    excerpt: compact([...new Set(samples)].join(' ')),
  }];
}

function findRomanceClicheTic(proseLines) {
  let hits = 0;
  let highRiskHits = 0;
  let weiBuKeChaHits = 0;
  let totalChars = 0;
  let firstLine = null;
  let firstHighRiskLine = null;
  let firstWeiLine = null;
  const samples = [];
  const highRiskSamples = [];

  for (const { text, lineNo } of proseLines) {
    const trimmed = text.trim();
    if (!trimmed || isDivider(trimmed) || isStructural(trimmed)) continue;
    totalChars += visibleLength(trimmed);
    const narrative = stripQuoted(trimmed);
    const isMonsterDevourLine = MONSTER_DEVOUR_CTX_RE.test(narrative);

    ROMANCE_CLICHE_NARRATION_PATTERN.lastIndex = 0;
    let m;
    while ((m = ROMANCE_CLICHE_NARRATION_PATTERN.exec(narrative)) !== null) {
      if (m[0] === '拆吞入腹' && isMonsterDevourLine) continue;
      hits += 1;
      if (firstLine === null) firstLine = lineNo;
      if (samples.length < 6) samples.push(m[0]);
    }

    ROMANCE_CLICHE_PATERNAL_PATTERN.lastIndex = 0;
    while ((m = ROMANCE_CLICHE_PATERNAL_PATTERN.exec(trimmed)) !== null) {
      hits += 1;
      if (firstLine === null) firstLine = lineNo;
      if (samples.length < 6) samples.push(m[0]);
    }

    ROMANCE_CLICHE_SINGLE_HIGH_RISK_PATTERN.lastIndex = 0;
    while ((m = ROMANCE_CLICHE_SINGLE_HIGH_RISK_PATTERN.exec(narrative)) !== null) {
      if (m[0] === '拆吞入腹' && isMonsterDevourLine) continue;
      highRiskHits += 1;
      if (firstHighRiskLine === null) firstHighRiskLine = lineNo;
      if (highRiskSamples.length < 6) highRiskSamples.push(m[0]);
    }
    ROMANCE_CLICHE_PATERNAL_PATTERN.lastIndex = 0;
    while ((m = ROMANCE_CLICHE_PATERNAL_PATTERN.exec(trimmed)) !== null) {
      highRiskHits += 1;
      if (firstHighRiskLine === null) firstHighRiskLine = lineNo;
      if (highRiskSamples.length < 6) highRiskSamples.push(m[0]);
    }

    ROMANCE_CLICHE_WEIBUKECHA_PATTERN.lastIndex = 0;
    while (ROMANCE_CLICHE_WEIBUKECHA_PATTERN.exec(narrative) !== null) {
      weiBuKeChaHits += 1;
      if (firstWeiLine === null) firstWeiLine = lineNo;
    }
  }

  if (totalChars === 0) return [];
  const perKilo = (hits / totalChars) * 1000;
  if (hits >= ROMANCE_CLICHE_MIN_HITS && perKilo >= ROMANCE_CLICHE_PER_KILO) {
    return [{
      line: firstLine,
      column: 1,
      type: 'romance-cliche-tic',
      severity: 'advisory',
      message: `女频油腻/言情套词聚集：${hits} 处（${perKilo.toFixed(1)}/千字）；砍掉壁咚生理标签与物化称呼，改用边界尊重、微物件偏爱或上位者体面认错立苏感（注：轻笑/低笑属正常语感，不计入本项）。`,
      excerpt: compact([...new Set(samples)].join(' ')),
    }];
  }
  if (highRiskHits >= 1) {
    return [{
      line: firstHighRiskLine,
      column: 1,
      type: 'romance-cliche-tic',
      severity: 'advisory',
      message: `高危言情 AI 套词提示（${highRiskHits} 处）：尽量改写为具体动作、视线停顿或手边物象，避免模板化描写（注：轻笑/低笑属正常语感，不计入本项）。`,
      excerpt: compact([...new Set(highRiskSamples)].join(' ')),
    }];
  }
  if (weiBuKeChaHits >= ROMANCE_CLICHE_WEIBUKECHA_MIN_HITS) {
    return [{
      line: firstWeiLine,
      column: 1,
      type: 'romance-cliche-tic',
      severity: 'advisory',
      message: `高危言情 AI 套词聚集：「微不可察」同章出现 ${weiBuKeChaHits} 处；保留必要一处，其余改写为具体动作、视线停顿或手边物象。`,
      excerpt: '微不可察',
    }];
  }
  return [];
}

function findShortPlasticReactionTic(proseLines, mode = 'long') {
  if (mode !== 'short') return [];
  let hits = 0;
  let firstLine = null;
  const samples = [];

  for (const { text, lineNo } of proseLines) {
    const trimmed = text.trim();
    if (!trimmed || isDivider(trimmed) || isStructural(trimmed)) continue;
    const narrative = stripQuoted(trimmed);
    SHORT_PLASTIC_REACTION_PATTERN.lastIndex = 0;
    let m;
    while ((m = SHORT_PLASTIC_REACTION_PATTERN.exec(narrative)) !== null) {
      hits += 1;
      if (firstLine === null) firstLine = lineNo;
      const sample = compact(m[0]);
      if (samples.length < 6 && !samples.includes(sample)) samples.push(sample);
    }
  }

  if (hits < SHORT_PLASTIC_REACTION_MIN_HITS) return [];
  return [{
    line: firstLine,
    column: 1,
    type: 'short-plastic-reaction-tic',
    severity: 'advisory',
    review: 'semantic',
    message: `短篇高频塑料反应套词聚集（${hits} 处）：眼底闪过一丝/瞳孔骤缩/喉结滚/指节泛白/气得浑身发抖/死一般寂静等易显 AI 腔；保留必要体感，其余改写为具体物件动作、台词反击或可核验细节。`,
    excerpt: compact(samples.join(' | ')),
  }];
}

// 极碎电报体（Wave 3D FN-4，advisory only）：纯叙述自然段 ≥15 段且段长中位数 ≤12 字，
// 抓碎段电报清单（排除纯对白、面板、聊天体与极短片段），不误伤正常手机竖屏 18-30 字短段。
function findStaccatoParagraphTic(proseLines, mode = 'long') {
  const maxMedian = mode === 'short' ? SHORT_STACCATO_PARA_MAX_MEDIAN : STACCATO_PARA_MAX_MEDIAN;
  const lens = [];
  let totalDocChars = 0;
  let firstLine = null;
  const samples = [];

  for (const { text, lineNo } of proseLines) {
    const trimmed = text.trim();
    if (!trimmed || isDivider(trimmed) || isStructural(trimmed) || /^【[^】]+】$/.test(trimmed)) continue;
    totalDocChars += visibleLength(trimmed);
    // 跳过微信/短信聊天体发言人行
    if (/^[\u4e00-\u9fffA-Za-z0-9_()（）]{1,10}[：:](?:\s*$|[^“「『"【]*$)/.test(trimmed) && !/[说道问喊笑叹]/.test(trimmed.slice(0, trimmed.search(/[：:]/)))) {
      continue;
    }
    // 只统计纯叙述段落（跳过含引号台词的行，避免把短台词接动作归成电报碎段）
    if (quotedRanges(trimmed).length > 0) continue;
    const len = visibleLength(trimmed);
    if (len === 0) continue;
    if (firstLine === null) firstLine = lineNo;
    lens.push(len);
    if (len <= maxMedian && samples.length < 5) samples.push(trimmed);
  }

  if (lens.length < STACCATO_PARA_MIN_COUNT || totalDocChars < STACCATO_PARA_MIN_DOC_CHARS) return [];
  lens.sort((a, b) => a - b);
  const mid = Math.floor(lens.length / 2);
  const median = lens.length % 2 === 1 ? lens[mid] : (lens[mid - 1] + lens[mid]) / 2;
  if (median > maxMedian) return [];

  return [{
    line: firstLine,
    column: 1,
    type: 'staccato-paragraph-tic',
    severity: 'advisory',
    message: `极碎电报体：纯叙述段 ${lens.length} 段，段长中位数仅 ${median} 字（≤${maxMedian} 字）；合并连排碎片句拉出长短呼吸，刻意快切动作镜头可保留。`,
    excerpt: compact(samples.join(' | ')),
  }];
}

// 微动作复读：统计引号外叙述里「了X量词」轻量补语的密度。次数与每千字密度双门槛，
// 全文只报一条（这是分布级指纹，不是逐处问题）。
function findMicroActionTic(proseLines) {
  let hits = 0;
  let narrativeChars = 0;
  let firstLine = null;
  const samples = [];

  for (const { text, lineNo } of proseLines) {
    const trimmed = text.trim();
    if (!trimmed || isDivider(trimmed) || isStructural(trimmed)) continue;
    const narrative = stripQuoted(trimmed);
    narrativeChars += visibleLength(narrative);
    MICRO_TIC_PATTERN.lastIndex = 0;
    let match;
    while ((match = MICRO_TIC_PATTERN.exec(narrative)) !== null) {
      hits += 1;
      if (firstLine === null) firstLine = lineNo;
      if (samples.length < 6 && !samples.includes(match[0])) samples.push(match[0]);
    }
  }

  if (narrativeChars === 0 || hits < MICRO_TIC_MIN_HITS) return [];
  const perKilo = (hits / narrativeChars) * 1000;
  if (perKilo < MICRO_TIC_PER_KILO) return [];

  return [{
    line: firstLine,
    column: 1,
    type: 'micro-action-tic',
    severity: 'advisory',
    message: `微动作复读：「了下/了一下」式轻量补语 ${hits} 处（${perKilo.toFixed(1)}/千字）；同一反应模板高密度复现是机械指纹，合并连串小动作、换具体细节，别每个动作都补一个轻反应尾巴。`,
    excerpt: compact(samples.join(' ')),
  }];
}

// 套式反应细节：统计引号外叙述中通用的部位/声线反应与固定语气比喻。
// 这是删除测试的候选集，不是身体描写黑名单；全篇只报一条，保留有动作后果、
// 伤势、人物习惯或情节功能的细节。
function findStockReactionTic(proseLines, mode = 'long') {
  let hits = 0;
  let narrativeChars = 0;
  let firstLine = null;
  const samples = [];

  for (const { text, lineNo } of proseLines) {
    const trimmed = text.trim();
    if (!trimmed || isDivider(trimmed) || isStructural(trimmed)) continue;
    const narrative = stripQuoted(trimmed);
    narrativeChars += visibleLength(narrative);

    for (const pattern of STOCK_REACTION_PATTERNS) {
      pattern.lastIndex = 0;
      let match;
      while ((match = pattern.exec(narrative)) !== null) {
        hits += 1;
        if (firstLine === null) firstLine = lineNo;
        const sample = sentenceAround(narrative, match.index);
        if (samples.length < 6 && sample && !samples.includes(sample)) samples.push(sample);
      }
    }
  }

  const minHits = mode === 'short' ? SHORT_STOCK_REACTION_MIN_HITS : STOCK_REACTION_MIN_HITS;
  const perKiloLimit = mode === 'short' ? SHORT_STOCK_REACTION_PER_KILO : STOCK_REACTION_PER_KILO;
  if (narrativeChars === 0 || hits < minHits) return [];
  const perKilo = (hits / narrativeChars) * 1000;
  if (perKilo < perKiloLimit) return [];

  return [{
    line: firstLine,
    column: 1,
    type: 'stock-reaction-tic',
    severity: 'advisory',
    message: `套式反应细节：指尖/指腹/喉结/眼圈/拢住按住/视线停顿等套式微动作或“平静得像在念”式语气比喻 ${hits} 处（${perKilo.toFixed(1)}/千字）；逐处做删除测试，只标注情绪、不改变选择、关系或物理结果的直接删掉，或改成直白情绪与利害判断，不要换部位或换道具继续演。`,
    excerpt: compact(samples.join(' | ')),
  }];
}

function findActionListTic(proseLines) {
  const findings = [];

  for (const { text, lineNo } of proseLines) {
    const trimmed = text.trim();
    if (!trimmed || isDivider(trimmed) || isStructural(trimmed)) continue;
    const narrative = stripQuoted(trimmed).trim();
    if (!narrative) continue;

    ACTION_LIST_VERB_PATTERN.lastIndex = 0;
    const verbs = [];
    let match;
    while ((match = ACTION_LIST_VERB_PATTERN.exec(narrative)) !== null) {
      verbs.push(match[0]);
    }

    if (verbs.length < ACTION_LIST_MIN_HITS) continue;
    const separators = (narrative.match(/[，、；;]/g) || []).length;
    if (separators < ACTION_LIST_MIN_SEPARATORS) continue;

    findings.push({
      line: lineNo,
      column: 1,
      type: 'action-list-tic',
      severity: 'advisory',
      message: `监控摄像头式动作清单：同段连续动作动词 ${verbs.length} 个、分隔符 ${separators} 个；合并琐碎步骤，只保留有情绪/情节功能的动作，必要时用角色犹豫、误判或环境反馈做缓冲。`,
      excerpt: compact(verbs.slice(0, 8).join(' ')),
    });
  }

  return findings;
}

// 套词密度：统计引号外叙述中的高危禁用词聚集。不是逐词替换器；只在密度高到
// 形成模板腔时提示，修法是删总结、换具体动作/物件/对话，不是同义词轮换。
function findClicheDensityTic(proseLines) {
  let hits = 0;
  let narrativeChars = 0;
  let firstLine = null;
  const samples = [];

  for (const { text, lineNo } of proseLines) {
    const trimmed = text.trim();
    if (!trimmed || isDivider(trimmed) || isStructural(trimmed)) continue;
    const narrative = stripQuoted(trimmed);
    narrativeChars += visibleLength(narrative);

    for (const pattern of CLICHE_PATTERNS) {
      pattern.lastIndex = 0;
      let match;
      while ((match = pattern.exec(narrative)) !== null) {
        hits += 1;
        if (firstLine === null) firstLine = lineNo;
        if (samples.length < 8 && !samples.includes(match[0])) samples.push(match[0]);
      }
    }
  }

  if (narrativeChars === 0 || hits < CLICHE_DENSITY_MIN_HITS) return [];
  const perKilo = (hits / narrativeChars) * 1000;
  if (perKilo < CLICHE_DENSITY_PER_KILO) return [];

  return [{
    line: firstLine,
    column: 1,
    type: 'cliche-density-tic',
    severity: 'advisory',
    message: `套词密度过高：高危 AI 套词 ${hits} 处（${perKilo.toFixed(1)}/千字）；不要同义词轮换，直接删或改成直白情绪、角色利害判断、对话或具体后果，别硬塞手眼小动作。`,
    excerpt: compact(samples.join(' ')),
  }];
}

// 比喻密度：统计引号外叙述中“像/好像/仿佛/如同”等比喻标记。
// 单个比喻不是问题；高密度成片时才提示，避免把文本改成另一种修辞模板。
function findMetaphorDensityTic(proseLines) {
  let hits = 0;
  let narrativeChars = 0;
  let firstLine = null;
  const samples = [];

  for (const { text, lineNo } of proseLines) {
    const trimmed = text.trim();
    if (!trimmed || isDivider(trimmed) || isStructural(trimmed)) continue;
    const narrative = stripQuoted(trimmed);
    narrativeChars += visibleLength(narrative);
    const metaphorScanText = narrative.replace(METAPHOR_COMPOUND_NOUN_PATTERN, (seg) => ' '.repeat(seg.length));

    METAPHOR_MARKER_PATTERN.lastIndex = 0;
    let match;
    while ((match = METAPHOR_MARKER_PATTERN.exec(metaphorScanText)) !== null) {
      hits += 1;
      if (firstLine === null) firstLine = lineNo;
      const sample = sentenceAround(narrative, match.index);
      if (samples.length < 6 && sample && !samples.includes(sample)) samples.push(sample);
    }

    METAPHOR_LIKE_PHRASE_PATTERN.lastIndex = 0;
    while ((match = METAPHOR_LIKE_PHRASE_PATTERN.exec(narrative)) !== null) {
      const prefix = narrative.slice(Math.max(0, match.index - 8), match.index);
      if (/好像|像是|像|仿佛|宛如|如同|犹如/.test(prefix)) continue;
      hits += 1;
      if (firstLine === null) firstLine = lineNo;
      const sample = sentenceAround(narrative, match.index);
      if (samples.length < 6 && sample && !samples.includes(sample)) samples.push(sample);
    }
  }

  if (narrativeChars === 0 || hits < METAPHOR_DENSITY_MIN_HITS) return [];
  const perKilo = (hits / narrativeChars) * 1000;
  if (perKilo < METAPHOR_DENSITY_PER_KILO) return [];

  return [{
    line: firstLine,
    column: 1,
    type: 'metaphor-density-tic',
    severity: 'advisory',
    message: `比喻密度过高：像/好像/仿佛/如同等比喻标记 ${hits} 处（${perKilo.toFixed(1)}/千字）；保留最有叙事功能的少数比喻，其余回到直白情绪、角色判断、对话或具体后果，不要换成新比喻或小动作。`,
    excerpt: compact(samples.join(' | ')),
  }];
}

// 解释链密度：统计引号外叙述中“知道/明白/这意味着/必须需要”等论文式推导链。
// 角色正常算利害、讲因果保留；同一行内去重重叠区间，且至少出现 3 处连接词/情态推导链才报。
function findReasoningChainTic(proseLines) {
  let hits = 0;
  let coreHits = 0;
  let linkHits = 0;
  let narrativeChars = 0;
  let firstLine = null;
  const samples = [];
  const buckets = new Set();

  for (const { text, lineNo } of proseLines) {
    const trimmed = text.trim();
    if (!trimmed || isDivider(trimmed) || isStructural(trimmed)) continue;
    const narrative = stripQuoted(trimmed);
    narrativeChars += visibleLength(narrative);
    const acceptedSpans = [];

    for (const { pattern, key, core } of REASONING_CHAIN_PATTERNS) {
      pattern.lastIndex = 0;
      let match;
      while ((match = pattern.exec(narrative)) !== null) {
        const start = match.index;
        const end = start + match[0].length;
        if (acceptedSpans.some(([a, b]) => start < b && end > a)) continue;
        acceptedSpans.push([start, end]);
        hits += 1;
        if (core) coreHits += 1;
        if (key === 'connector' || key === 'modal') linkHits += 1;
        buckets.add(key);
        if (firstLine === null) firstLine = lineNo;
        const sample = compact(match[0]);
        if (samples.length < 8 && !samples.includes(sample)) samples.push(sample);
      }
    }
  }

  if (narrativeChars === 0 || hits < REASONING_CHAIN_MIN_HITS) return [];
  if (coreHits < REASONING_CHAIN_CORE_MIN_HITS || buckets.size < REASONING_CHAIN_MIN_BUCKETS) return [];
  if (linkHits < REASONING_CHAIN_MIN_LINKS) return [];
  const perKilo = (hits / narrativeChars) * 1000;
  if (perKilo < REASONING_CHAIN_PER_KILO) return [];

  return [{
    line: firstLine,
    column: 1,
    type: 'reasoning-chain-tic',
    severity: 'advisory',
    message: `解释链密度过高：知道/明白/这意味着/必须/需要等论文式推导 ${hits} 处（${perKilo.toFixed(1)}/千字）；删掉“这意味着/按照这个逻辑”式公文腔，保留角色自己的利害算账与因果判断，或落到对话与选择后果，别全改成手眼小动作。`,
    excerpt: compact(samples.join(' | ')),
  }];
}

// 系统/规则行如果连续像 API 文档或政府公文，读者容易闻到机器味。
// 修法不是删除规则，而是保留功能后把一部分硬词改成白话或具体后果。
function findNoticeFormalityTic(proseLines) {
  let hits = 0;
  let noticeChars = 0;
  let noticeLines = 0;
  let coreHits = 0;
  let firstLine = null;
  const samples = [];

  for (const { text, lineNo } of proseLines) {
    const trimmed = text.trim();
    if (!/^【[^】]+】$/.test(trimmed)) continue;
    noticeLines += 1;
    noticeChars += visibleLength(trimmed);

    NOTICE_FORMAL_CORE_PATTERN.lastIndex = 0;
    while (NOTICE_FORMAL_CORE_PATTERN.exec(trimmed) !== null) coreHits += 1;

    for (const pattern of NOTICE_FORMAL_PATTERNS) {
      pattern.lastIndex = 0;
      let match;
      while ((match = pattern.exec(trimmed)) !== null) {
        hits += 1;
        if (firstLine === null) firstLine = lineNo;
        const sample = compact(match[0]);
        if (samples.length < 8 && !samples.includes(sample)) samples.push(sample);
      }
    }
  }

  if (noticeLines < NOTICE_FORMAL_MIN_LINES || noticeChars === 0 || hits < NOTICE_FORMAL_MIN_HITS || coreHits < NOTICE_FORMAL_CORE_MIN_HITS) return [];
  const perKilo = (hits / noticeChars) * 1000;
  if (perKilo < NOTICE_FORMAL_PER_KILO) return [];

  return [{
    line: firstLine,
    column: 1,
    type: 'system-notice-formality-tic',
    severity: 'advisory',
    message: `系统公告公文腔过密：方括号规则行中硬规则词 ${hits} 处（${perKilo.toFixed(1)}/千字）；保留为角色看见的屏幕/公告/规则载体，只在载体内部白话化部分硬词，或补角色当场看懂的具体后果，不改成叙述者解释。`,
    excerpt: compact(samples.join(' | ')),
  }];
}

// 长文本整体过于“精炼”：短段很多、自然连接偏少，读起来像处理过的梗概/分镜表。
// 修法是通读后补断裂处，不是为凑阈值全局加“的/了/就”。
function findOvercompressedProseTic(proseLines) {
  let narrativeChars = 0;
  let narrativeParas = 0;
  let shortParas = 0;
  let particles = 0;
  let firstLine = null;
  const samples = [];

  for (const { text, lineNo } of proseLines) {
    const trimmed = text.trim();
    if (!trimmed || isDivider(trimmed) || isStructural(trimmed) || /^【[^】]+】$/.test(trimmed)) continue;
    const narrative = stripQuoted(trimmed).trim();
    const len = visibleLength(narrative);
    if (len === 0) continue;

    if (firstLine === null) firstLine = lineNo;
    narrativeParas += 1;
    narrativeChars += len;
    if (len <= OVERCOMPRESSED_PROSE_SHORT_MAX_CHARS) {
      shortParas += 1;
      if (samples.length < 6) samples.push(narrative);
    }

    OVERCOMPRESSED_PROSE_PARTICLE_PATTERN.lastIndex = 0;
    while (OVERCOMPRESSED_PROSE_PARTICLE_PATTERN.exec(narrative) !== null) particles += 1;
  }

  if (narrativeChars < OVERCOMPRESSED_PROSE_MIN_CHARS || narrativeParas < OVERCOMPRESSED_PROSE_MIN_PARAS) return [];
  const shortRatio = shortParas / narrativeParas;
  if (shortRatio < OVERCOMPRESSED_PROSE_SHORT_RATIO) return [];
  const particlePerKilo = (particles / narrativeChars) * 1000;
  if (particlePerKilo >= OVERCOMPRESSED_PROSE_PARTICLE_PER_KILO) return [];

  return [{
    line: firstLine,
    column: 1,
    type: 'overcompressed-prose-tic',
    severity: 'advisory',
    message: `过度精炼短段：叙述段 ${narrativeParas} 个，其中 ${shortParas} 个≤${OVERCOMPRESSED_PROSE_SHORT_MAX_CHARS}字（${(shortRatio * 100).toFixed(0)}%），自然连接 ${particlePerKilo.toFixed(1)}/千字偏少；先通读判断，确有提纲感再补断裂处和必要结构虚词，有意短镜头可留，别机械注水。`,
    excerpt: compact(samples.join(' | ')),
  }];

}

// 低连接密度：长篇引号外叙述包含两条互补分支（均仅 advisory）：
//   1) 极碎大纲电报体：≥50% 叙述句 ≤10 字、功能词与白话连接双低且缺 ≥25 字承接句；
//   2) 干硬镜头报幕体（2,450 篇真 9.0+ 长篇标定，误报 0.33%）：纯叙述段中位 ≥28 字，但口语连接词 ≤5.5/千字且「的」≤25.0/千字。
// 修法是恢复角色内心盘算与自然口语连接，不是全局机械注水。
function findLowConnectiveDensityTic(proseLines) {
  let bodyChars = 0;
  let functionHits = 0;
  let plainHits = 0;
  let connHits = 0;
  let deHits = 0;
  let firstLine = null;
  const sentences = [];
  const samples = [];
  const pureNarrLens = [];
  const uniquePureNarr = new Set();
  const drySamples = [];

  for (const { text, lineNo } of proseLines) {
    const trimmed = text.trim();
    if (!trimmed || isDivider(trimmed) || isStructural(trimmed)) continue;

    if (!/^【[^】]+】$/.test(trimmed) && !PURE_NARRATION_QUOTE_RE.test(trimmed)) {
      const compactPara = trimmed.replace(/\s+/g, '');
      const paraLen = Array.from(compactPara).length;
      if (paraLen > 0) {
        pureNarrLens.push(paraLen);
        uniquePureNarr.add(compactPara);
        if (drySamples.length < 4 && paraLen >= DRY_NARRATION_MIN_PURE_MEDIAN) {
          drySamples.push(compact(trimmed.slice(0, 36)));
        }
      }
    }

    // 只看引号外叙述。台词/弹幕/系统播报可以天然短促，混入统计会把体裁特征误当电报体。
    const narrative = stripQuoted(trimmed).trim();
    const narrativeLen = visibleLength(narrative);
    if (narrativeLen === 0) continue;

    if (firstLine === null) firstLine = lineNo;
    bodyChars += narrativeLen;
    functionHits += countTerms(narrative, LOW_CONNECTIVE_FUNCTION_TERMS);
    plainHits += countTerms(narrative, LOW_CONNECTIVE_PLAIN_TERMS);
    COLLOQUIAL_CONNECTIVE_PATTERN.lastIndex = 0;
    while (COLLOQUIAL_CONNECTIVE_PATTERN.exec(narrative) !== null) connHits += 1;
    for (let i = 0; i < narrative.length; i += 1) {
      if (narrative[i] === '的') deHits += 1;
    }

    for (const sentence of splitSentences(narrative)) {
      const len = visibleLength(sentence);
      if (len === 0) continue;
      sentences.push(len);
      if (len <= 12 && samples.length < 6) samples.push(sentence);
    }
  }

  if (bodyChars === 0 || sentences.length === 0) return [];

  // 分支 1：既有极碎大纲电报体契约
  if (bodyChars >= LOW_CONNECTIVE_MIN_CHARS) {
    const functionPerKilo = (functionHits / bodyChars) * 1000;
    const plainPerKilo = (plainHits / bodyChars) * 1000;
    const tinySentenceRatio = sentences.filter((len) => len <= LOW_CONNECTIVE_TINY_SENTENCE_CHARS).length / sentences.length;
    const longSentenceRatio = sentences.filter((len) => len >= LOW_CONNECTIVE_LONG_SENTENCE_CHARS).length / sentences.length;
    if (
      functionPerKilo < LOW_CONNECTIVE_FUNCTION_PER_KILO &&
      plainPerKilo < LOW_CONNECTIVE_PLAIN_PER_KILO &&
      tinySentenceRatio >= LOW_CONNECTIVE_TINY_SENTENCE_RATIO &&
      longSentenceRatio < LOW_CONNECTIVE_LONG_SENTENCE_RATIO
    ) {
      return [{
        line: firstLine,
        column: 1,
        type: 'low-connective-density-tic',
        severity: 'advisory',
        message: `疑似大纲电报体：引号外叙述≤${LOW_CONNECTIVE_TINY_SENTENCE_CHARS}字碎句占比 ${(tinySentenceRatio * 100).toFixed(0)}%、功能词 ${functionPerKilo.toFixed(1)}/千字、白话连接 ${plainPerKilo.toFixed(1)}/千字；通读检查是否有动作跳跃或主语/因果残缺，有意快切镜头可保留，别机械注水。`,
        excerpt: compact(samples.join(' | ')),
      }];
    }
  }

  // 分支 2：长篇干硬镜头报幕体（纯叙述段偏长但口语连接与「的」双低）
  if (bodyChars >= DRY_NARRATION_MIN_CHARS && uniquePureNarr.size >= DRY_NARRATION_MIN_UNIQUE_PARAS && pureNarrLens.length > 0) {
    const sorted = [...pureNarrLens].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    const pureNarrMedian = sorted.length % 2 === 1 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
    const connPerKilo = (connHits / bodyChars) * 1000;
    const dePerKilo = (deHits / bodyChars) * 1000;
    if (
      pureNarrMedian >= DRY_NARRATION_MIN_PURE_MEDIAN &&
      connPerKilo <= DRY_NARRATION_MAX_CONN_PER_KILO &&
      dePerKilo <= DRY_NARRATION_MAX_DE_PER_KILO
    ) {
      return [{
        line: firstLine,
        column: 1,
        type: 'low-connective-density-tic',
        severity: 'advisory',
        message: `疑似抽干内心的剧本报幕体：纯叙述段中位 ${pureNarrMedian} 字，但口语连接词仅 ${connPerKilo.toFixed(1)}/千字、「的」${dePerKilo.toFixed(1)}/千字；通读补回人物当下利害盘算与自然口语转折，别机械注水。`,
        excerpt: compact((drySamples.length ? drySamples : samples).join(' | ')),
      }];
    }
  }

  return [];
}

// 闲笔材质/道具/光影贴纸过密（advisory only；仅长篇）：
// 引号外叙述堆砌无功能材质、服饰熨烫、光影音效贴纸且口语连接偏低时提醒按刀子物件原则收口。
function findIdlePropDecorationTic(proseLines, mode = 'long') {
  if (mode === 'short') return [];
  let narrativeChars = 0;
  let connHits = 0;
  let firstLine = null;
  const uniqueProps = new Set();

  for (const { text, lineNo } of proseLines) {
    const trimmed = text.trim();
    if (!trimmed || isDivider(trimmed) || isStructural(trimmed) || /^【[^】]+】$/.test(trimmed)) continue;
    const narrative = stripQuoted(trimmed).trim();
    const narrativeLen = visibleLength(narrative);
    if (narrativeLen === 0) continue;

    narrativeChars += narrativeLen;
    COLLOQUIAL_CONNECTIVE_PATTERN.lastIndex = 0;
    while (COLLOQUIAL_CONNECTIVE_PATTERN.exec(narrative) !== null) connHits += 1;

    IDLE_PROP_DECORATION_PATTERN.lastIndex = 0;
    let match;
    while ((match = IDLE_PROP_DECORATION_PATTERN.exec(narrative)) !== null) {
      if (firstLine === null) firstLine = lineNo;
      uniqueProps.add(match[0]);
    }
  }

  if (narrativeChars < IDLE_PROP_MIN_CHARS || uniqueProps.size < IDLE_PROP_MIN_UNIQUE) return [];
  const uniquePerKilo = (uniqueProps.size / narrativeChars) * 1000;
  const connPerKilo = (connHits / narrativeChars) * 1000;
  if (uniquePerKilo < IDLE_PROP_MIN_UNIQUE_PER_KILO || connPerKilo > IDLE_PROP_MAX_CONN_PER_KILO) return [];

  return [{
    line: firstLine,
    column: 1,
    type: 'idle-prop-decoration-tic',
    severity: 'advisory',
    message: `闲笔材质/道具摆设过密：引号外叙述出现 ${uniqueProps.size} 种材质/服饰/光影/声效摆设（${uniquePerKilo.toFixed(1)}/千字），且口语连接仅 ${connPerKilo.toFixed(1)}/千字；只留改变局势或露破绽的关键道具和证物，删掉没用的环境摆设并补足人物盘算。`,
    excerpt: compact([...uniqueProps].slice(0, 8).join(' | ')),
  }];
}

// 抽象总结复读：统计引号外叙述中的高抽象收束模板。全篇只报一条，提醒回到角色
// 当下可见的文件、动作、对话或物理后果；不要用命运大词替读者总结。
function findAbstractSummaryTic(proseLines) {
  let hits = 0;
  let narrativeChars = 0;
  let firstLine = null;
  const samples = [];

  for (const { text, lineNo } of proseLines) {
    const trimmed = text.trim();
    if (!trimmed || isDivider(trimmed) || isStructural(trimmed)) continue;
    const narrative = stripQuoted(trimmed);
    narrativeChars += visibleLength(narrative);

    for (const pattern of ABSTRACT_SUMMARY_PATTERNS) {
      pattern.lastIndex = 0;
      let match;
      while ((match = pattern.exec(narrative)) !== null) {
        hits += 1;
        if (firstLine === null) firstLine = lineNo;
        const sample = compact(match[0]);
        if (samples.length < 6 && !samples.includes(sample)) samples.push(sample);
      }
    }
  }

  if (narrativeChars === 0 || hits < ABSTRACT_SUMMARY_MIN_HITS) return [];
  const perKilo = (hits / narrativeChars) * 1000;
  if (perKilo < ABSTRACT_SUMMARY_PER_KILO) return [];

  return [{
    line: firstLine,
    column: 1,
    type: 'abstract-summary-tic',
    severity: 'advisory',
    message: `抽象总结复读：命运/棋局/这一刻终于明白/才刚刚开始等作者总结 ${hits} 处（${perKilo.toFixed(1)}/千字）；删掉作者盖章，回到角色当下的具体处境、利害盘算、对话或实际后果，别拿微动作顶替。`,
    excerpt: compact(samples.join(' | ')),
  }];
}

function findPeriodStutter(proseLines, mode = 'long') {
  const findings = [];
  const stutterMinRun = mode === 'short' ? SHORT_STUTTER_MIN_RUN : STUTTER_MIN_RUN;
  let runLen = 0;
  let runStartLine = null;
  let runSample = [];

  const flush = () => {
    if (runLen >= stutterMinRun) {
      findings.push({
        line: runStartLine,
        column: 1,
        type: 'period-stutter',
        severity: 'advisory',
        message: `碎句号：连续 ${runLen} 个短句无呼吸；若为缺主语或因果断裂的机械碎句则按行动主干接顺，有意短镜头或聊天体可保留。`,
        excerpt: compact(runSample.join(' ')),
      });
    }
    runLen = 0;
    runStartLine = null;
    runSample = [];
  };

  for (const { text, lineNo } of proseLines) {
    const trimmed = text.trim();
    if (!trimmed) continue; // 空行是一句一段排版，不打断叙述连贯
    if (isDivider(trimmed) || isStructural(trimmed)) {
      flush(); // 分隔线/markdown 结构行：重置碎句计数
      continue;
    }
    // 跳过微信/短信聊天体发言人行（如「我：」「老公李伟：」「老公：今晚不回。」）
    if (/^[\u4e00-\u9fffA-Za-z0-9_()（）]{1,10}[：:](?:\s*$|[^“「『"【]*$)/.test(trimmed) && !/[说道问喊笑叹]/.test(trimmed.slice(0, trimmed.search(/[：:]/)))) {
      flush();
      continue;
    }
    const narrative = stripQuoted(trimmed);
    if (visibleLength(narrative) === 0) {
      flush(); // 纯对话/弹幕/系统播报：成片短句是正常形态，重置碎句计数
      continue;
    }
    // 无句末标点的短名词列举/清单项（如无标点条目行）不是碎句号
    if (!/[。！？!?]/.test(narrative) && visibleLength(narrative) <= 8) {
      flush();
      continue;
    }
    // 只数引号外叙述句：混合行（叙述+引号内物件/短台词）的引号外片段仍参与碎句计数。
    for (const sentence of splitSentences(narrative)) {
      if (visibleLength(sentence) <= STUTTER_MAX_SENTENCE) {
        if (runLen === 0) runStartLine = lineNo;
        runLen += 1;
        if (runSample.length < 6) runSample.push(sentence);
      } else {
        flush();
      }
    }
  }
  flush();
  return findings;
}

function isDivider(trimmed) {
  const compactDiv = trimmed.replace(/\s+/g, '');
  if (compactDiv.length < 2) return false;
  return /^(?:-{3,}|—{2,}|─{3,}|={3,}|[*_]{3,}|[·•.~～]{3,})$/.test(compactDiv);
}

// markdown 结构行（标题/列表/引用/表格/短篇纯数字小节标 `1.`）不是叙述正文，长段落/碎句号/破折号检测都跳过。
function isStructural(trimmed) {
  return /^(#{1,6}(?:\s|\d)|>\s?|[-*+]\s|\d+[.)](?:\s|$)|\|)/.test(trimmed)
    || /^第\s*[零〇一二三四五六七八九十百千万两\d]+\s*[章节回](?:$|[\s_：:——\-]+[^\n；;]{0,36}$)/.test(trimmed);
}

// 去掉成对引号内的片段（台词/系统播报），只留引号外叙述。碎句号判定用：纯对话/弹幕成片短句
// 是体裁正常形态（豁免），但「叙述 + 引号内物件/短台词」混合行的引号外叙述仍要参与短句计数。
function stripQuoted(text) {
  let out = text;
  for (const src of QUOTE_SOURCES) out = out.replace(new RegExp(src, 'g'), '');
  return out;
}

function stripQuotedWithUnclosed(text) {
  const out = stripQuoted(text);
  const unclosed = /[“「『"]/.exec(out);
  return unclosed ? out.slice(0, unclosed.index) : out;
}

// 把成对引号片段（含引号）替换为等长问号占位：既豁免引号内台词/播报，又保住原文
// 偏移量，供逐处 blocking 规则定位与截取原文摘录（stripQuoted 会移位，不适合定位）。
// 占位字符用「？」而不是「。」：占位既要截断各规则的 [^。！？!?…] 否定类（？与句号在每条
// 规则的否定类里等效），又不能落在任何规则的接受位。句号占位会替 trailer-summary 的句末
// [。！] 伪造出终止符，让「这一战注定是「血屠」的开端，…」这类引号里放代号/绰号的叙述行
// 被误报，且报出的『这一战注定是。』在原文里 grep 不到。占位长度不变，故偏移与摘录窗口不漂移。
function maskQuoted(text) {
  let out = text;
  for (const src of QUOTE_SOURCES) {
    out = out.replace(new RegExp(src, 'g'), (m) => '？'.repeat(m.length));
  }
  return out;
}

// 与 normalize-punctuation.js 的 quoteSpans 对齐：闭合引号/面板先等长占位，行末未收口的开引号
// （如 `他猛地抬头：“你敢——` 或 `"等等——`）算到行尾，同时保留开引号前的旁白文本参与扫描。
function maskQuotedWithUnclosed(text) {
  const out = maskQuoted(text);
  const unclosed = /[“「『"]/.exec(out);
  if (!unclosed) return out;
  return out.slice(0, unclosed.index) + '？'.repeat(out.length - unclosed.index);
}

// 返回引号内片段（含引号本身）的 [start, end) 区间，供 not-is 对比句豁免台词用。
function quotedRanges(text) {
  const ranges = [];
  for (const src of QUOTE_SOURCES) {
    const re = new RegExp(src, 'g');
    let match;
    while ((match = re.exec(text)) !== null) ranges.push([match.index, match.index + match[0].length]);
  }
  return ranges;
}

function insideRanges(pos, ranges) {
  return ranges.some(([start, end]) => pos >= start && pos < end);
}

function splitSentences(trimmed) {
  return trimmed
    .split(/[。！？!?]/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function sentenceAround(text, index) {
  let start = index;
  while (start > 0 && !STOP_CHARS.has(text[start - 1])) start -= 1;
  let end = index;
  while (end < text.length && !STOP_CHARS.has(text[end])) end += 1;
  return compact(text.slice(start, end).trim());
}

function visibleLength(sentence) {
  const matched = sentence.match(/[一-鿿Ａ-ｚA-Za-z0-9]/g);
  return matched ? matched.length : 0;
}

function countTerms(text, terms) {
  let count = 0;
  for (const term of terms) {
    let index = text.indexOf(term);
    while (index !== -1) {
      count += 1;
      index = text.indexOf(term, index + term.length);
    }
  }
  return count;
}

// 把行内 HTML 注释（含 `<!--`、`-->` 本身）换成等长空格；openBefore 表示上一行留下未闭合注释。
// unclosedOpenings 里的 `<!--` 到文末都没闭合：只抹掉这四个字符，后面照常当正文。
// openedAt 是本行最后一个开始注释的 `<!--` 位置（"行号:列号"），没有则为 null。
function maskHtmlComments(line, openBefore, lineIndex = 0, unclosedOpenings = new Set()) {
  let out = '';
  let stripped = '';
  let open = openBefore;
  let cursor = 0;
  let openedAt = null;
  while (cursor < line.length) {
    if (open) {
      const close = line.indexOf('-->', cursor);
      const end = close === -1 ? line.length : close + 3;
      out += ' '.repeat(end - cursor);
      cursor = end;
      if (close !== -1) open = false;
      continue;
    }
    const start = line.indexOf('<!--', cursor);
    if (start === -1) {
      const rest = line.slice(cursor);
      out += rest;
      stripped += rest;
      break;
    }
    const before = line.slice(cursor, start);
    out += before + '    ';
    stripped += before;
    cursor = start + 4;
    const key = `${lineIndex}:${start}`;
    if (unclosedOpenings.has(key)) continue;
    open = true;
    openedAt = key;
  }
  return { text: out, stripped, open, openedAt };
}

function parseFenceMarker(trimmedLine) {
  const match = /^(?:`{3,}|~{3,})/.exec(trimmedLine);
  if (!match) return null;
  return { char: match[0][0], length: match[0].length };
}

function hasYamlFrontMatter(lines) {
  if (!lines[0] || lines[0].trim() !== '---') return false;
  let sawYamlField = false;
  for (let i = 1; i < Math.min(lines.length, 40); i += 1) {
    const trimmed = lines[i].trim();
    if (trimmed === '---') return sawYamlField;
    if (/^[A-Za-z0-9_-]+:\s*/.test(trimmed)) sawYamlField = true;
  }
  return false;
}

function scanBlock(block) {
  const text = block.map((entry) => entry.text).join('\n');
  const lineStarts = [];
  let cursor = 0;

  for (const entry of block) {
    lineStarts.push({ offset: cursor, lineNo: entry.lineNo });
    cursor += entry.text.length + 1;
  }

  return findNotIsComparisons(text, (offset) => positionForOffset(lineStarts, offset));
}

function positionForOffset(lineStarts, offset) {
  let low = 0;
  let high = lineStarts.length - 1;

  while (low <= high) {
    const mid = Math.floor((low + high) / 2);
    const current = lineStarts[mid];
    const next = lineStarts[mid + 1];

    if (offset < current.offset) {
      high = mid - 1;
    } else if (next && offset >= next.offset) {
      low = mid + 1;
    } else {
      return {
        line: current.lineNo,
        column: offset - current.offset + 1,
      };
    }
  }

  return { line: lineStarts[0].lineNo, column: 1 };
}

function findNotIsComparisons(text, getPosition) {
  const findings = [];
  const quoted = quotedRanges(text);
  let offset = 0;

  while (offset < text.length) {
    const start = text.indexOf('不是', offset);
    if (start === -1) break;

    // 引号内是台词/系统播报：口语里「不是A，是B」是自然辩解/反问，不算叙述层 AI 对比句式
    // （与碎句号一致豁免引号内容）。
    if (insideRanges(start, quoted)) {
      offset = start + 2;
      continue;
    }

    // Avoid the common yes/no question fragment “是不是” and counterfactual conditionals (“要不是/若不是/如果不是”).
    if (start > 0 && (text[start - 1] === '是' || text[start - 1] === '要' || text[start - 1] === '若')) {
      offset = start + 2;
      continue;
    }
    if (start >= 2 && (text.slice(start - 2, start) === '如果' || text.slice(start - 2, start) === '倘若' || text.slice(start - 2, start) === '假如')) {
      offset = start + 2;
      continue;
    }

    const candidate = text.slice(start);
    const markerEnd = findPositiveFlipEnd(candidate);

    if (markerEnd === -1) {
      offset = start + 2;
      continue;
    }

    const raw = trimTrailingNoise(extractFinding(candidate, markerEnd));
    if (raw.length >= 4) {
      const position = getPosition(start);
      findings.push({
        line: position.line,
        column: position.column,
        type: 'not-is-comparison',
        severity: 'review_required',
        message: '高频 AI 对比句式；删掉否定铺垫，直接写后项（直白情绪、判断、对话或具体细节皆可）。',
        excerpt: compact(raw),
      });
    }

    offset = start + Math.max(raw.length, 2);
  }

  return findings;
}

function findPositiveFlipEnd(candidate) {
  let index = 2; // after “不是”
  let scanned = 0;
  let crossedSeparator = false;

  while (index < candidate.length && scanned <= MAX_NEGATIVE_SPAN) {
    const char = candidate[index];

    if (startsWithAt(candidate, index, '而是')) return index + 2;

    if (SOFT_SEPARATORS.has(char)) {
      const next = skipGap(candidate, index + 1);
      if (startsWithAt(candidate, next, '而是')) return next + 2;
      if (candidate[next] === '是' && !TAG_PARTICLES.has(candidate[next + 1]) && !isAffirmationTagAt(candidate, next)) return next + 1;
      crossedSeparator = true;
    }

    if (HARD_SEPARATORS.has(char)) {
      const next = skipGap(candidate, index + 1);
      if (candidate[next] === '是' && !TAG_PARTICLES.has(candidate[next + 1]) && !isAffirmationTagAt(candidate, next)) return next + 1;
      if (char !== '.') break;
      crossedSeparator = true;
    }

    if (STOP_CHARS.has(char)) break;

    // Catch compact forms such as “不是A是B”, but only within the first clause —
    // before any separator. After a separator the trailing “是” of a conjunction
    // (只是/可是/但是/还是/于是/倒是/总是…) is part of that word, not a positive
    // copula (issue #166 false-positive class). Post-separator flips are still
    // caught when separator-adjacent (“，是”/“，而是”) by the separator branches
    // above; subject-present flips like “，他是”/“，那是” are intentionally NOT
    // caught here — there is no separator-local way to tell them from a
    // conjunction without a word list, and on a hard rescan-to-0 gate a false
    // positive (forcing a rewrite of good prose) costs more than missing this
    // rarer form. The “是” in the either-or idiom “不是A就是B / 也是B” is part of
    // the 就是/也是 conjunction, not a copula, so 就/也 are excluded too. Also never
    // treat the “是” inside a second negative fragment (“不是A，也不是B”) as the flip.
    if (
      char === '是' &&
      !COMPACT_EITHER_OR_PREV.has(candidate[index - 1]) &&
      !crossedSeparator &&
      !COMPACT_NOT_IS_CLAUSE_PREFIX_RE.test(candidate) &&
      !COMPACT_NOT_IS_TAIL_EXCLUDE_RE.test(candidate.slice(index)) &&
      !TAG_PARTICLES.has(candidate[index + 1]) &&
      !isAffirmationTagAt(candidate, index)
    ) {
      return index + 1;
    }

    index += 1;
    scanned += 1;
  }

  return -1;
}

function extractFinding(candidate, markerEnd) {
  let end = markerEnd;
  const limit = Math.min(candidate.length, markerEnd + MAX_POSITIVE_SPAN);

  while (end < limit) {
    if (STOP_CHARS.has(candidate[end])) break;
    end += 1;
  }

  return candidate.slice(0, end);
}

function startsWithAt(text, index, needle) {
  return text.slice(index, index + needle.length) === needle;
}

function isAffirmationTagAt(text, index) {
  if (text[index] !== '是') return false;
  const particle = text[index + 1];
  if (!AFFIRMATION_TAG_PARTICLES.has(particle)) return false;
  const boundary = text[index + 2] || '';
  return AFFIRMATION_TAG_BOUNDARY.has(boundary);
}

// 跳过行内空白与换行（含空行/段落间距），停在下一个实义字符。原实现只吞一个换行，
// 会漏掉跨空行的「不是A。（空行）是B」这类分段揭示句。
function skipGap(text, index) {
  while (index < text.length && (isInlineSpace(text[index]) || text[index] === '\n')) index += 1;
  return index;
}

function isInlineSpace(char) {
  return char === ' ' || char === '\t' || char === '\r';
}

function trimTrailingNoise(text) {
  return text.replace(/[\s|）)】\]]+$/u, '');
}

function compact(text) {
  const normalized = text.replace(/\s+/g, ' ').trim();
  return normalized.length > 80 ? `${normalized.slice(0, 77)}...` : normalized;
}
