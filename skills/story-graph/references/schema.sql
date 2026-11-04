-- 叙事知识图谱 Schema v1.0
-- 故事实体与关系的完整 DDL

-----------------------------------------------------------
-- 1. 节点表
-----------------------------------------------------------
CREATE TABLE IF NOT EXISTS nodes (
    id          TEXT PRIMARY KEY,       -- P_沈栀 / L_青云城 / E_获得戒指 / I_盘龙戒指 / G_天机阁 / T_星辰历1024年春 / C_015 / H_玉佩秘密
    node_type   TEXT NOT NULL,          -- PERSON / LOCATION / EVENT / ITEM / ORG / TIME_POINT / CHAPTER / HOOK
    label       TEXT NOT NULL,          -- 人类可读名称
    properties  TEXT NOT NULL DEFAULT '{}',  -- JSON blob，动态属性
    status      TEXT DEFAULT 'active',  -- active / draft / archived / dead / lost
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(node_type);
CREATE INDEX IF NOT EXISTS idx_nodes_status ON nodes(status);

-----------------------------------------------------------
-- 各类型 properties 规范（注释）
--
-- PERSON:
--   {"aliases": ["阿栀"], "gender": "女", "age": 22, "role": "protagonist",
--    "abilities": ["医术lv3"], "motivation": "为父报仇", "backstory_knowledge": ["祖传玉佩的秘密"]}
--
-- LOCATION:
--   {"type": "city|building|wilderness|realm", "parent": "L_玉兰大陆", "owner": "G_巴鲁克家族"}
--
-- EVENT:
--   {"event_type": "conflict|revelation|transition|action|dialogue|state_change",
--    "summary": "沈栀在断魂崖发现黑衣人留下的密信",
--    "chapter": 15, "narrative_order": 15,
--    "participants": ["P_沈栀", "P_黑衣人"], "emotional_tone": "suspense"}
--
-- ITEM:
--   {"item_type": "weapon|artifact|consumable|clue|currency",
--    "owner": "P_沈栀", "location": "L_青云城", "significance": "critical|supporting|background"}
--
-- ORG:
--   {"org_type": "sect|family|empire|guild|clan", "leader": "P_掌门", "headquarters": "L_天机阁"}
--
-- TIME_POINT:
--   {"time_unit": "absolute|relative", "reference": null,
--    "description": "大战后第三日黄昏"}
--
-- CHAPTER:
--   {"chapter_number": 15, "title": "断魂崖之谜", "word_count": 3200}
--
-- HOOK:
--   {"hook_type": "mystery|foreshadow|red_herring|promise",
--    "priority": 7, "complexity": 5,
--    "expected_trigger_window": "20-30",
--    "planted_chapter": 3, "planted_time": null,
--    "triggered_chapter": null, "resolved_chapter": null}
-----------------------------------------------------------

-----------------------------------------------------------
-- 2. 边表
-----------------------------------------------------------
CREATE TABLE IF NOT EXISTS edges (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    from_node     TEXT NOT NULL,
    edge_type     TEXT NOT NULL,        -- 字符串类型，支持动态扩展
    to_node       TEXT NOT NULL,
    properties    TEXT NOT NULL DEFAULT '{}',  -- JSON: {confidence, reason, ...}
    valid_since   TEXT,                 -- 物理时间锚点 ID 或时间字符串
    valid_until   TEXT,                 -- NULL = 至今有效
    created_by    TEXT DEFAULT 'graph-builder',  -- graph-builder / manual / hook-engine
    created_at    TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (from_node) REFERENCES nodes(id),
    FOREIGN KEY (to_node) REFERENCES nodes(id)
);

CREATE INDEX IF NOT EXISTS idx_edges_from ON edges(from_node, edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_to ON edges(to_node, edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_valid ON edges(valid_since, valid_until);

-----------------------------------------------------------
-- 边类型目录（注释）
--
-- 叙事层:
--   NEXT_CHAPTER  CHAPTER → CHAPTER        阅读顺序
--   NARRATES      CHAPTER → EVENT          本章讲述了某事件
--   FLASHBACK_TO  CHAPTER → TIME_POINT     本章倒叙到某时间点
--
-- 物理时间:
--   BEFORE        TIME_POINT → TIME_POINT  物理时间先后
--   OCCURS_AT     EVENT → TIME_POINT       事件发生的物理时间
--
-- 空间:
--   LOCATED_AT    PERSON/ITEM/EVENT → LOCATION  在某地
--
-- 所有权:
--   OWNS          PERSON/ORG → ITEM        持有物品
--   BELONGS_TO    PERSON → ORG             从属组织
--
-- 事件参与:
--   PARTICIPATES_IN  PERSON/ITEM/ORG → EVENT  参与事件
--
-- 因果:
--   CAUSES        EVENT → EVENT            事件A导致事件B
--
-- 人物关系:
--   KIN_TO        PERSON → PERSON          亲属
--   ALLIED_WITH   PERSON → PERSON          同盟
--   HOSTILE_TO    PERSON → PERSON          敌对
--   ROMANTIC_WITH PERSON → PERSON          爱慕
--   MENTOR_OF     PERSON → PERSON          师徒
--
-- 知识:
--   WITNESS       PERSON → EVENT           亲眼所见
--   INFORMED_BY   PERSON → EVENT           被人告知
--   KNOWS_ABOUT   PERSON → NODE            聚合知识边（查询用）
--
-- 钩子:
--   PLANTS_IN         HOOK → CHAPTER       埋设在某章
--   CONCERNS          HOOK → NODE          关联某实体
--   TRIGGERS_ON_ENTITY   HOOK → NODE       触发条件：实体出现
--   TRIGGERS_ON_LOCATION HOOK → LOCATION   触发条件：到达某地
--   TRIGGERS_ON_TIME     HOOK → TIME_POINT 触发条件：到达某时间
--   TRIGGERS_ON_STATE    HOOK → NODE       触发条件：状态变更
--   PREREQUISITE_FOR     HOOK → HOOK       钩子A是钩子B的前提
--   TRIGGERED_IN         HOOK → CHAPTER    在某一章被触发
--   RESOLVED_IN          HOOK → CHAPTER    在某一章被解决
--
-- 技能/能力:
--   COUNTERS      ABILITY → ABILITY        克制关系
--   POSSESSES     PERSON → ABILITY         拥有能力
-----------------------------------------------------------

-----------------------------------------------------------
-- 3. 知识来源追踪表
-----------------------------------------------------------
CREATE TABLE IF NOT EXISTS knowledge_sources (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id    TEXT NOT NULL,          -- 谁知道
    target_id    TEXT NOT NULL,          -- 知道了什么 (NODE ID)
    source_type  TEXT NOT NULL,          -- WITNESS / INFORMED_BY / DEDUCTION / BACKSTORY
    source_event TEXT,                   -- 如果是 WITNESS/INFORMED_BY，指向具体的 EVENT
    source_person TEXT,                  -- 如果是 INFORMED_BY，谁告诉的
    acquired_at  TEXT,                   -- 物理时间点
    confidence   REAL DEFAULT 1.0,       -- 0.0-1.0
    FOREIGN KEY (person_id) REFERENCES nodes(id),
    FOREIGN KEY (target_id) REFERENCES nodes(id)
);

CREATE INDEX IF NOT EXISTS idx_ks_person ON knowledge_sources(person_id);
CREATE INDEX IF NOT EXISTS idx_ks_target ON knowledge_sources(target_id);

-----------------------------------------------------------
-- 4. 钩子触发条件表
-----------------------------------------------------------
CREATE TABLE IF NOT EXISTS hook_conditions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    hook_id      TEXT NOT NULL,
    condition_type TEXT NOT NULL,        -- entity/location/time/state/combo
    target_id    TEXT,                   -- 条件目标 NODE ID
    logic_op     TEXT DEFAULT 'ANY',     -- ANY / AND / OR / NOT
    combo_group  INTEGER DEFAULT 0,      -- 组合条件分组号
    FOREIGN KEY (hook_id) REFERENCES nodes(id)
);

CREATE INDEX IF NOT EXISTS idx_hc_hook ON hook_conditions(hook_id);

-----------------------------------------------------------
-- 5. Staging 表（graph-builder 增量写入用）
-----------------------------------------------------------
CREATE TABLE IF NOT EXISTS staging_nodes (
    id          TEXT PRIMARY KEY,
    node_type   TEXT NOT NULL,
    label       TEXT NOT NULL,
    properties  TEXT NOT NULL DEFAULT '{}',
    status      TEXT DEFAULT 'draft',
    source_chapter TEXT,
    action      TEXT DEFAULT 'create'   -- create / update / delete
);

CREATE TABLE IF NOT EXISTS staging_edges (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    from_node     TEXT NOT NULL,
    edge_type     TEXT NOT NULL,
    to_node       TEXT NOT NULL,
    properties    TEXT NOT NULL DEFAULT '{}',
    valid_since   TEXT,
    valid_until   TEXT,
    source_chapter TEXT,
    action        TEXT DEFAULT 'create'   -- create / update / delete
);

-----------------------------------------------------------
-- 6. 通用视图：边连接展开
-- 注：SQLite 视图无法参数化，时间窗口过滤请用 stateAtTime() / stateWindow()
--     函数（epoch 数值比较，见 story_graph_core.js）；本视图不做有效性过滤。
-----------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_state_at_time AS
SELECT
    n.id AS entity_id,
    n.label AS entity_label,
    n.node_type,
    e.edge_type,
    e.to_node AS related_node,
    n2.label AS related_label,
    n2.node_type AS related_type,
    e.valid_since,
    e.valid_until
FROM nodes n
JOIN edges e ON n.id = e.from_node
JOIN nodes n2 ON e.to_node = n2.id;
