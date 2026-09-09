# 长篇写前召回

本文承接 workflow-chapter.md 步骤 3；路径优先级及缺失修复见 [project-files.md](project-files.md)。

- **模块召回、题材卡与文风召回**：
  - **成熟项目短路径（召回降档）**：`custom_style=true`（见 (d)）、`设定/题材正文提示卡.md` 有实质内容、且本章细纲「目标情绪」有实际内容——且单元卡的情绪引擎、节拍分配有有效内容时**跳过 (a)(b)(e)(f)**：情绪目标取细纲「目标情绪」与单元卡「单元情绪引擎」，节奏取单元「节拍/章功能分配」，`selected_emotion_module` / `rhythm_reference` 记「降档：细纲/单元卡」，(c)(d) 照常执行，(g) 按缩减集输出。任一条件不满足走下方全量召回。判定由组装脚本做出并写进核对报告，主会话不重判。**降档下不检查对标 `剧情/情绪模块.md` 与 `剧情/节奏.md` 的存在性**，(a)(b) 的 `missing_primary_contract` fail-fast 只在全量召回路径生效。降档舍掉匹配章的扩写技法层与原文锚点，节奏补偿只到单元级——**细纲「目标情绪」写得敷衍的章不降档**。
  - ① 本章目标情绪词？② 借鉴哪个参考文件的哪个技法？③ 用在哪些段落？答不出 → 先回读参考再动笔
  - (a) **情绪模块召回**：按「对标书路径查找」规则读 `{对标书路径}/剧情/情绪模块.md`，选出 1 个与本章目标情绪最贴近的 `selected_emotion_module`（读者需求、触发器、戏剧单元、可替换要素、反抄袭提醒）。缺失时设置 `missing_primary_contract: true`，返回明确 `repair_action` 后停止准备
  - (b) **节奏召回**：读 `{对标书路径}/剧情/节奏.md`，选出 1 条 `rhythm_reference`（关键信息 → 扩写技法 → 情绪触动点 → 爆发/冷却）。缺失时设置 `missing_primary_contract: true`，返回明确 `repair_action` 后停止准备
  - (c) **题材正文提示卡召回**：优先读 `设定/题材正文提示卡.md`；缺失则先读 `设定/题材定位.md` + `references/genre-prose-cards.md` 索引，按主题材精确匹配后只读取 `references/genre-prose-cards/` 中对应单题材卡（如 都市脑洞 / 豪门总裁 / 年代 / 双男主；低置信卡必须在意图确认标注低置信，并要求同题材对标校准），无命中再读 `references/style-genre-modules.md` 通用流派模块。跨题材时主题材抽 3-5 条、辅题材抽 1-2 条，生成短 `genre_prose_card`（题材边界、核心逻辑、读者期待、核心爽点/情绪、正文落点、前中后期打法、节奏密度、场景颗粒、禁止漂移、本章取舍、卡片置信度）。题材卡只约束正文层题材味，不改细纲剧情、不覆盖 `selected_emotion_module` / `rhythm_reference` / `设定/文风.md`；只在内部校准取舍，正文里不得出现卡名/标签/置信度/条目/合规自评
  - (d) **文风召回**：先直接读 `设定/文风.md`（不经 explorer）：有可执行表达要求即置 `custom_style=true`，不设最低字数；空白、纯标题或待补充不算。全文按 `style-resolution.md` 作权威风格基，`设定/_文风摘要.md` 仅作索引，写作与去味都传全文路径及同一 `style_resolution`。有自定义文风时对标只补未声明的维度；否则按「对标书路径查找」规则读 `{对标书路径}/文风.md`（路径优先 `{项目}/对标/{书名}/`，回退 `拆文库/{书名}/`）；多本对标书时从 `设定/题材定位.md` 读 `主对标书` 字段。**未进入自定义文风模式且**文风文件不存在 → **fail-fast 报错**：「对标书 X 缺少 文风.md。请用 `/story-long-analyze` 跑 Stage 6 生成文风，再 `/story-import` 同步。」不 inline 生成（自定义文风模式则不 fail-fast；情绪 / 节奏轴 `missing_primary_contract` 仍独立阻塞）
  - (e) **匹配章节挑选**：从 `{对标书路径}/章节/*_摘要.md` grep `基调：(紧张|轻松|悲伤|热血|爽|甜|温馨|恐怖|压抑|其他)`（全角冒号），按本章目标情绪挑章 K——多章同基调时选择规则：先看爽点类型是否接近，再看情节点数量/原文章节估算字数是否接近本章目标字数，最后取章节号最小者；必读 `{对标书路径}/章节/第K章_摘要.md`，若同章存在 `第K章_深度拆解.md` 则加读，否则回退黄金三章深度拆解/文风文件里的可借鉴技巧，不因非黄金三章缺少深度拆解而失败
  - (f) **结构化模块召回**：从对标的结构化子目录（角色/剧情/设定）中按本章情节检索相关模块；若与 `剧情/情绪模块.md` / `剧情/节奏.md` 冲突，权威文件优先，记录 `conflict`
  - (g) 输出"主对标召回摘要 + 副对标召回摘要 + selected_emotion_module + rhythm_reference + genre_prose_card + 文风召回指令 + 原文锚点片段引用"，作为 narrative-writer 的输入。**多对标书时**参 `references/cross-book-recall.md`：主对标提供文风、原文锚点与 selected_emotion_module / rhythm_reference；副对标/参考对标按阶段预算提供结构化摘要，不限制登记书目，不读取副书 `文风.md` / 原文，超过预算时裁条目不裁书目记录。
  - **快捷路径**：项目已部署 story-explorer agent 时，可一次性召回文风/模块材料。
    - 按本文件顶部规则确认 story-explorer 已部署。
    - 查询类型：`benchmark_style_load`；传入项目目录、章节号、目标基调/字数和爽点类型。
    - 需要返回：`style_profile_path`、`style_profile_summary`、`selected_emotion_module`、`rhythm_reference`、来源路径、匹配章节、锚点片段、`gaps`。
    - `gaps.missing_primary_contract` 为 true 时先按 `repair_action` 修复，不进入正文生成。
    - 主会话另行直接读 `设定/文风.md`：含实质内容时作为本书风格基准；但不豁免情绪/节奏缺失。
