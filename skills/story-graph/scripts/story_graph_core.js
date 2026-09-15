"use strict";

/**
 * story_graph_core.js — 叙事知识图谱核心操作库
 *
 * 提供 SQLite 数据库的 DDL 建表、CRUD、时间切片查询、钩子雷达等能力。
 * 被 graph-builder agent（写入）、story-explorer agent（查询）和 hook 脚本共用。
 *
 * 依赖: better-sqlite3（同步 SQLite 驱动）
 * 安装: npm install better-sqlite3
 */

const path = require("path");
const fs = require("fs");

// ─── better-sqlite3 驱动解析 ─────────────────────────────────
// 写作项目根通常没有 package.json / node_modules，不能依赖 Node 默认向上解析。
// 按部署拓扑依次尝试：
//   1. .claude/hooks/ 的兄弟目录 .claude/skills/story-graph/node_modules（deploy-graph 把
//      依赖装进 skill 目录，项目根保持干净）
//   2. 本文件所在目录逐级向上的 node_modules（仓库内开发/测试，repo/node_modules）
//   3. Node 默认解析（项目根有 node_modules 或全局安装时）
function requireBetterSqlite3() {
  const candidates = [
    // 链接形态（skills CLI 安装）：core 在 .claude/hooks/ → .agents/skills/story-graph/node_modules
    path.join(path.dirname(path.dirname(__dirname)), ".agents", "skills", "story-graph", "node_modules"),
    // 真实目录形态：core 在 .claude/hooks/ → .claude/skills/story-graph/node_modules
    path.join(path.dirname(__dirname), "skills", "story-graph", "node_modules"),
    // 仓库内开发/测试：scripts → story-graph → skills → repo/node_modules
    path.join(__dirname, "..", "..", "..", "node_modules"),
  ];
  try {
    return require(require.resolve("better-sqlite3", { paths: candidates }));
  } catch (e) {
    return require("better-sqlite3");
  }
}

const Database = requireBetterSqlite3();

// ─── 活跃书发现（与 story_hook_core.js::discoverActiveBook 同口径） ──
// 回退链：.active-book 首行（有效目录）→ 深度≤4 找「追踪/」目录（长篇）
//       → 找「正文/」目录 → 找「正文.md」文件（短篇）。
// 空/失效的 .active-book 绝不把项目根当书目录（否则 story.db 会建错位置）。
function findFirst(base, maxDepth, predicate) {
  if (maxDepth < 0) return null;
  let entries = [];
  try { entries = fs.readdirSync(base, { withFileTypes: true }); } catch { return null; }
  for (const entry of entries) {
    if (entry.name.startsWith(".") || entry.name === "node_modules") continue;
    const full = path.join(base, entry.name);
    if (predicate(full, entry)) return full;
  }
  if (maxDepth === 0) return null;
  for (const entry of entries) {
    if (!entry.isDirectory() || entry.name.startsWith(".") || entry.name === "node_modules") continue;
    const found = findFirst(path.join(base, entry.name), maxDepth - 1, predicate);
    if (found) return found;
  }
  return null;
}

function discoverBookDir(projectRoot) {
  const activeBookPath = path.join(projectRoot, ".active-book");
  if (fs.existsSync(activeBookPath)) {
    const declared = fs.readFileSync(activeBookPath, "utf8").split(/\r?\n/, 1)[0].trim();
    if (declared) {
      const candidate = path.resolve(projectRoot, declared);
      if (fs.existsSync(candidate) && fs.statSync(candidate).isDirectory()) return candidate;
    }
    // 空/失效声明：继续回退，不用项目根顶替
  }
  const tracking = findFirst(projectRoot, 4, (_full, entry) => entry.isDirectory() && entry.name === "追踪");
  if (tracking) return path.dirname(tracking);
  const body = findFirst(projectRoot, 4, (_full, entry) => entry.isDirectory() && entry.name === "正文");
  if (body) return path.dirname(body);
  const bodyFile = findFirst(projectRoot, 4, (_full, entry) => entry.isFile() && entry.name === "正文.md");
  return bodyFile ? path.dirname(bodyFile) : null;
}

// ─── 数据库连接管理 ──────────────────────────────────────────
// 按 dbPath 索引的连接池：同一进程可同时打开多本书的 story.db
// （session-status / prose-check 按书发现库，不能共享单例，否则串库）。
const _dbs = new Map();

/**
 * 打开（或创建）story.db
 * @param {string} dbPath - 数据库文件路径
 * @returns {import("better-sqlite3").Database}
 */
function open(dbPath) {
  if (_dbs.has(dbPath)) return _dbs.get(dbPath);
  const dir = path.dirname(dbPath);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  const db = new Database(dbPath);
  db.pragma("journal_mode = WAL");
  db.pragma("foreign_keys = ON");
  _dbs.set(dbPath, db);
  return db;
}

function close() {
  for (const db of _dbs.values()) db.close();
  _dbs.clear();
}

function getDb() {
  if (_dbs.size === 0) throw new Error("数据库未打开，请先调用 open(dbPath)");
  return _dbs.values().next().value;
}

// ─── DDL 建表 ────────────────────────────────────────────────

const SCHEMA_SQL = `
CREATE TABLE IF NOT EXISTS nodes (
    id          TEXT PRIMARY KEY,
    node_type   TEXT NOT NULL,
    label       TEXT NOT NULL,
    properties  TEXT NOT NULL DEFAULT '{}',
    status      TEXT DEFAULT 'active',
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(node_type);
CREATE INDEX IF NOT EXISTS idx_nodes_status ON nodes(status);

CREATE TABLE IF NOT EXISTS edges (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    from_node     TEXT NOT NULL,
    edge_type     TEXT NOT NULL,
    to_node       TEXT NOT NULL,
    properties    TEXT NOT NULL DEFAULT '{}',
    valid_since   TEXT,
    valid_until   TEXT,
    created_by    TEXT DEFAULT 'graph-builder',
    created_at    TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (from_node) REFERENCES nodes(id),
    FOREIGN KEY (to_node) REFERENCES nodes(id)
);

CREATE INDEX IF NOT EXISTS idx_edges_from ON edges(from_node, edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_to ON edges(to_node, edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_valid ON edges(valid_since, valid_until);

CREATE TABLE IF NOT EXISTS knowledge_sources (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id    TEXT NOT NULL,
    target_id    TEXT NOT NULL,
    source_type  TEXT NOT NULL,
    source_event TEXT,
    source_person TEXT,
    acquired_at  TEXT,
    confidence   REAL DEFAULT 1.0,
    FOREIGN KEY (person_id) REFERENCES nodes(id),
    FOREIGN KEY (target_id) REFERENCES nodes(id)
);

CREATE INDEX IF NOT EXISTS idx_ks_person ON knowledge_sources(person_id);
CREATE INDEX IF NOT EXISTS idx_ks_target ON knowledge_sources(target_id);

CREATE TABLE IF NOT EXISTS hook_conditions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    hook_id      TEXT NOT NULL,
    condition_type TEXT NOT NULL,
    target_id    TEXT,
    logic_op     TEXT DEFAULT 'ANY',
    combo_group  INTEGER DEFAULT 0,
    FOREIGN KEY (hook_id) REFERENCES nodes(id)
);

CREATE INDEX IF NOT EXISTS idx_hc_hook ON hook_conditions(hook_id);

CREATE TABLE IF NOT EXISTS staging_nodes (
    id          TEXT PRIMARY KEY,
    node_type   TEXT NOT NULL,
    label       TEXT NOT NULL,
    properties  TEXT NOT NULL DEFAULT '{}',
    status      TEXT DEFAULT 'draft',
    source_chapter TEXT,
    action      TEXT DEFAULT 'create'
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
    action        TEXT DEFAULT 'create'
);

CREATE TABLE IF NOT EXISTS narrative_physical_map (
    chapter_id      TEXT NOT NULL,
    physical_time   TEXT,
    story_day       INTEGER,
    absolute_order  INTEGER,
    PRIMARY KEY (chapter_id),
    FOREIGN KEY (chapter_id) REFERENCES nodes(id),
    FOREIGN KEY (physical_time) REFERENCES nodes(id)
);

CREATE INDEX IF NOT EXISTS idx_npm_story_day ON narrative_physical_map(story_day);
CREATE INDEX IF NOT EXISTS idx_npm_abs_order ON narrative_physical_map(absolute_order);

-- 边连接展开视图：SQLite 视图无法参数化，时间窗口过滤请用
-- stateAtTime() / stateWindow() 函数；本视图不做有效性过滤。
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

CREATE TABLE IF NOT EXISTS narrative_debts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    question        TEXT NOT NULL,
    answer_event    TEXT,
    answer_time     TEXT,
    triggered_by    TEXT,
    character_id    TEXT,
    priority        INTEGER DEFAULT 5,
    suggested_window TEXT,
    status          TEXT DEFAULT 'pending',
    repaid_chapter  INTEGER,
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (answer_event) REFERENCES nodes(id),
    FOREIGN KEY (triggered_by) REFERENCES nodes(id),
    FOREIGN KEY (character_id) REFERENCES nodes(id)
);

CREATE INDEX IF NOT EXISTS idx_nd_status ON narrative_debts(status);
CREATE INDEX IF NOT EXISTS idx_nd_char ON narrative_debts(character_id);
`;

function initSchema(dbPath) {
  const db = open(dbPath);
  db.exec(SCHEMA_SQL);
  return db;
}

// ─── 节点 CRUD ───────────────────────────────────────────────

function upsertNode(node, db) {
  const d = db || getDb();
  const stmt = d.prepare(`
    INSERT INTO nodes (id, node_type, label, properties, status, updated_at)
    VALUES (@id, @node_type, @label, @properties, @status, datetime('now'))
    ON CONFLICT(id) DO UPDATE SET
      node_type=excluded.node_type,
      label=excluded.label,
      properties=excluded.properties,
      status=excluded.status,
      updated_at=datetime('now')
  `);
  return stmt.run({
    id: node.id,
    node_type: node.node_type,
    label: node.label,
    properties: typeof node.properties === "string" ? node.properties : JSON.stringify(node.properties || {}),
    status: node.status || "active"
  });
}

function upsertNodes(nodes, db) {
  const d = db || getDb();
  const insert = d.transaction((items) => {
    for (const node of items) upsertNode(node, d);
  });
  insert(nodes);
}

function getNode(id, db) {
  const d = db || getDb();
  const row = d.prepare("SELECT * FROM nodes WHERE id = ?").get(id);
  if (row) row.properties = JSON.parse(row.properties || "{}");
  return row;
}

function getNodesByType(nodeType, db) {
  const d = db || getDb();
  const rows = d.prepare("SELECT * FROM nodes WHERE node_type = ? AND status = 'active'").all(nodeType);
  for (const r of rows) r.properties = JSON.parse(r.properties || "{}");
  return rows;
}

function getAllNodes(db) {
  const d = db || getDb();
  const rows = d.prepare("SELECT * FROM nodes WHERE status = 'active'").all();
  for (const r of rows) r.properties = JSON.parse(r.properties || "{}");
  return rows;
}

function deleteNode(id, db) {
  const d = db || getDb();
  d.prepare("DELETE FROM nodes WHERE id = ?").run(id);
  d.prepare("DELETE FROM edges WHERE from_node = ? OR to_node = ?").run(id, id);
}

// ─── 边 CRUD ─────────────────────────────────────────────────

function upsertEdge(edge, db) {
  const d = db || getDb();
  const stmt = d.prepare(`
    INSERT INTO edges (from_node, edge_type, to_node, properties, valid_since, valid_until, created_by, created_at)
    VALUES (@from_node, @edge_type, @to_node, @properties, @valid_since, @valid_until, @created_by, datetime('now'))
  `);
  return stmt.run({
    from_node: edge.from_node,
    edge_type: edge.edge_type,
    to_node: edge.to_node,
    properties: typeof edge.properties === "string" ? edge.properties : JSON.stringify(edge.properties || {}),
    valid_since: edge.valid_since || null,
    valid_until: edge.valid_until || null,
    created_by: edge.created_by || "graph-builder"
  });
}

function upsertEdges(edges, db) {
  const d = db || getDb();
  const insert = d.transaction((items) => {
    for (const edge of items) upsertEdge(edge, d);
  });
  insert(edges);
}

/**
 * 删除并重建某实体的所有出边（用于增量更新时替换边集合）
 */
function replaceEdgesFrom(fromNode, edgeType, newEdges, db) {
  const d = db || getDb();
  const del = d.transaction(() => {
    d.prepare("DELETE FROM edges WHERE from_node = ? AND edge_type = ?").run(fromNode, edgeType);
    for (const edge of newEdges) {
      edge.from_node = fromNode;
      edge.edge_type = edgeType;
      upsertEdge(edge, d);
    }
  });
  del();
}

function getEdgesFrom(fromNode, edgeType, db) {
  const d = db || getDb();
  let sql = "SELECT * FROM edges WHERE from_node = ?";
  const params = [fromNode];
  if (edgeType) { sql += " AND edge_type = ?"; params.push(edgeType); }
  const rows = d.prepare(sql).all(...params);
  for (const r of rows) r.properties = JSON.parse(r.properties || "{}");
  return rows;
}

function getEdgesTo(toNode, edgeType, db) {
  const d = db || getDb();
  let sql = "SELECT * FROM edges WHERE to_node = ?";
  const params = [toNode];
  if (edgeType) { sql += " AND edge_type = ?"; params.push(edgeType); }
  const rows = d.prepare(sql).all(...params);
  for (const r of rows) r.properties = JSON.parse(r.properties || "{}");
  return rows;
}

// ─── 聚合查询：时间切片 ─────────────────────────────────────

/**
 * 解析 TIME_POINT 节点的 epoch（无该字段返回 null）
 */
function resolveTimePointEpoch(d, tpId) {
  if (!tpId) return null;
  const row = d.prepare(
    "SELECT json_extract(properties, '$.epoch') AS epoch FROM nodes WHERE id = ? AND node_type = 'TIME_POINT'"
  ).get(tpId);
  return row && row.epoch != null ? Number(row.epoch) : null;
}

/**
 * 判定边在给定时间点是否有效。
 *
 * 语义：valid_since <= time_point < valid_until（端点开区间）。
 * 时间锚点能解析成 epoch 时按数值比较；查询点无 epoch，或端点锚点无 epoch
 * 时退化为 ID 字符串比较（尽力而为，兼容旧数据），无法验证的端点按有效放行。
 *
 * @param {object} d
 * @param {object} edge - 含 valid_since / valid_until（TIME_POINT ID）
 * @param {string} timePointId - 查询时间点 ID
 * @param {number|null} timePointEpoch - 查询时间点 epoch（可缓存复用）
 */
function edgeValidInWindow(d, edge, timePointId, timePointEpoch) {
  const sinceEpoch = edge.valid_since != null ? resolveTimePointEpoch(d, edge.valid_since) : null;
  const untilEpoch = edge.valid_until != null ? resolveTimePointEpoch(d, edge.valid_until) : null;
  if (timePointEpoch != null) {
    const sinceOk = sinceEpoch == null || sinceEpoch <= timePointEpoch;
    const untilOk = untilEpoch == null || untilEpoch > timePointEpoch;
    return sinceOk && untilOk;
  }
  const sinceOk = edge.valid_since == null || edge.valid_since <= timePointId;
  const untilOk = edge.valid_until == null || edge.valid_until > timePointId;
  return sinceOk && untilOk;
}

/**
 * 判定边的有效区间是否与 [timeStart, timeEnd] 窗口相交。
 * 端点能解析成 epoch 时数值比较；否则退化 ID 字符串比较。
 */
function edgeOverlapsWindow(d, edge, timeStartId, timeStartEpoch, timeEndId, timeEndEpoch) {
  const sinceEpoch = edge.valid_since != null ? resolveTimePointEpoch(d, edge.valid_since) : null;
  const untilEpoch = edge.valid_until != null ? resolveTimePointEpoch(d, edge.valid_until) : null;
  if (timeStartEpoch != null && timeEndEpoch != null) {
    const sinceOk = sinceEpoch == null || sinceEpoch < timeEndEpoch;
    const untilOk = untilEpoch == null || untilEpoch > timeStartEpoch;
    return sinceOk && untilOk;
  }
  const sinceOk = edge.valid_since == null || edge.valid_since < timeEndId;
  const untilOk = edge.valid_until == null || edge.valid_until > timeStartId;
  return sinceOk && untilOk;
}

/**
 * 判定边的有效区间是否完整覆盖 [timeStart, timeEnd] 窗口（窗口内全程有效）。
 */
function edgeCoversWindow(d, edge, timeStartId, timeStartEpoch, timeEndId, timeEndEpoch) {
  const sinceEpoch = edge.valid_since != null ? resolveTimePointEpoch(d, edge.valid_since) : null;
  const untilEpoch = edge.valid_until != null ? resolveTimePointEpoch(d, edge.valid_until) : null;
  if (timeStartEpoch != null && timeEndEpoch != null) {
    const sinceOk = sinceEpoch == null || sinceEpoch <= timeStartEpoch;
    const untilOk = untilEpoch == null || untilEpoch > timeEndEpoch;
    return sinceOk && untilOk;
  }
  const sinceOk = edge.valid_since == null || edge.valid_since <= timeStartId;
  const untilOk = edge.valid_until == null || edge.valid_until > timeEndId;
  return sinceOk && untilOk;
}

/**
 * 查询某时间点的角色/实体状态快照
 *
 * 语义：沿物理时间线，取 valid_since <= time_point < valid_until 的所有边。
 *
 * @param {string} entityId - 实体 ID，如 "P_沈栀"
 * @param {string} timePointId - 时间点节点 ID，如 "T_星辰历1025年春"
 * @param {object} db
 * @returns {object} 状态快照
 */
function stateAtTime(entityId, timePointId, db) {
  const d = db || getDb();
  const timePointEpoch = resolveTimePointEpoch(d, timePointId);

  const allEdges = d.prepare(`
    SELECT e.edge_type, e.to_node, n2.label AS related_label, n2.node_type AS related_type,
           e.properties, e.valid_since, e.valid_until
    FROM edges e
    JOIN nodes n2 ON e.to_node = n2.id
    WHERE e.from_node = ?
    ORDER BY e.edge_type
  `).all(entityId).filter((edge) => edgeValidInWindow(d, edge, timePointId, timePointEpoch));

  const result = {
    entity_id: entityId,
    time_point: timePointId,
    location: null,
    holding: [],
    knows: [],
    relationships: [],
    abilities: [],
    org: null
  };

  for (const e of allEdges) {
    const props = JSON.parse(e.properties || "{}");
    switch (e.edge_type) {
      case "LOCATED_AT":
        result.location = { id: e.to_node, label: e.related_label, since: e.valid_since };
        break;
      case "OWNS":
        result.holding.push({ id: e.to_node, label: e.related_label, since: e.valid_since });
        break;
      case "KNOWS_ABOUT":
        result.knows.push({ id: e.to_node, label: e.related_label, via: props.via || "unknown" });
        break;
      case "BELONGS_TO":
        result.org = { id: e.to_node, label: e.related_label };
        break;
      case "POSSESSES":
        result.abilities.push({ id: e.to_node, label: e.related_label });
        break;
      case "KIN_TO":
      case "ALLIED_WITH":
      case "HOSTILE_TO":
      case "ROMANTIC_WITH":
      case "MENTOR_OF":
        result.relationships.push({
          target: { id: e.to_node, label: e.related_label },
          type: e.edge_type,
          since: e.valid_since
        });
        break;
    }
  }

  return result;
}

/**
 * 时空窗口批量查询 — 一次查询某时空范围内的所有实体状态
 *
 * @param {{timeStart: string, timeEnd: string, location: string|null}} window
 * @param {string[]} entityTypes - ['PERSON', 'ITEM', ...] 默认所有
 * @param {object} db
 * @returns {object} 窗口内每类实体的完整状态
 */
function stateWindow(window, entityTypes, db) {
  const d = db || getDb();
  const types = entityTypes || ["PERSON", "ITEM", "EVENT"];

  // 时间窗口解析一次，避免逐实体重复查 TIME_POINT
  const timeStartEpoch = resolveTimePointEpoch(d, window.timeStart);
  const timeEndEpoch = resolveTimePointEpoch(d, window.timeEnd);

  const result = {};

  for (const nodeType of types) {
    const entities = d.prepare(`
      SELECT id, label, properties FROM nodes
      WHERE node_type = ? AND status = 'active'
    `).all(nodeType);

    for (const entity of entities) {
      // 检查此实体是否在时空窗口内存在：有指向窗口地点的边，
      // 或有效区间与窗口相交（端点 epoch 数值比较；无 epoch 退化 ID 字符串）
      const relevantEdges = d.prepare(`
        SELECT * FROM edges e
        WHERE e.from_node = ?
          AND e.edge_type IN ('LOCATED_AT','OCCURS_AT','PARTICIPATES_IN')
      `).all(entity.id);
      const relevant = relevantEdges.some((edge) => {
        if (window.location && edge.to_node === window.location) return true;
        return edgeOverlapsWindow(d, edge, window.timeStart, timeStartEpoch, window.timeEnd, timeEndEpoch);
      });

      if (!relevant) continue;

      // 获取该实体的窗口内状态：有效区间覆盖整个窗口的边
      const state = d.prepare(`
        SELECT e.edge_type, e.to_node, n2.label AS related_label, n2.node_type AS related_type,
               e.properties, e.valid_since, e.valid_until
        FROM edges e
        JOIN nodes n2 ON e.to_node = n2.id
        WHERE e.from_node = ?
        ORDER BY e.edge_type
      `).all(entity.id).filter((edge) =>
        edgeCoversWindow(d, edge, window.timeStart, timeStartEpoch, window.timeEnd, timeEndEpoch),
      );

      const entityState = {
        id: entity.id,
        label: entity.label,
        type: nodeType,
        location: null,
        holding: [],
        knows: [],
        relationships: [],
        involved_events: []
      };

      for (const e of state) {
        switch (e.edge_type) {
          case "LOCATED_AT":
            entityState.location = { id: e.to_node, label: e.related_label };
            break;
          case "OWNS":
            entityState.holding.push({ id: e.to_node, label: e.related_label });
            break;
          case "KNOWS_ABOUT":
            entityState.knows.push({ id: e.to_node, label: e.related_label });
            break;
          case "PARTICIPATES_IN":
            entityState.involved_events.push({ id: e.to_node, label: e.related_label });
            break;
          case "KIN_TO": case "ALLIED_WITH": case "HOSTILE_TO":
          case "ROMANTIC_WITH": case "MENTOR_OF":
            entityState.relationships.push({
              target: { id: e.to_node, label: e.related_label },
              type: e.edge_type
            });
            break;
        }
      }

      if (!result[nodeType]) result[nodeType] = [];
      result[nodeType].push(entityState);
    }
  }

  // 添加时间窗口内的事件列表（按 OCCURS_AT → TIME_POINT.epoch 过滤，
  // 不再比较时间点 ID 字符串；无 epoch 的时间点无法验证，保留）
  const events = d.prepare(`
    SELECT n.id, n.label, json_extract(n.properties, '$.chapter') AS ch,
           json_extract(n.properties, '$.event_type') AS ev_type,
           json_extract(tp.properties, '$.epoch') AS epoch,
           COALESCE(json_extract(n.properties, '$.story_offset'), json_extract(n.properties, '$.narrative_order'), 0) AS offset
    FROM nodes n
    JOIN edges e ON n.id = e.from_node AND e.edge_type = 'OCCURS_AT'
    JOIN nodes tp ON e.to_node = tp.id
    WHERE n.node_type = 'EVENT' AND n.status = 'active'
    ORDER BY CAST(json_extract(tp.properties, '$.epoch') AS REAL), offset
  `).all().filter((ev) => {
    const ep = ev.epoch == null ? null : Number(ev.epoch);
    if (ep == null) return true;
    if (timeStartEpoch != null && ep < timeStartEpoch) return false;
    if (timeEndEpoch != null && ep > timeEndEpoch) return false;
    return true;
  });

  result.EVENTS = events;

  return {
    window: { timeStart: window.timeStart, timeEnd: window.timeEnd, location: window.location },
    entities: result
  };
}

// ─── 聚合查询：因果链 ───────────────────────────────────────

/**
 * 从某事件沿 CAUSES 边向下游（或上游）遍历
 * @param {string} eventId
 * @param {'forward'|'backward'} direction
 * @param {number} maxDepth
 * @param {object} db
 * @returns {Array<{from: string, to: string, depth: number, event_label: string}>}
 */
function causalChain(eventId, direction, maxDepth, db) {
  const d = db || getDb();
  if (maxDepth == null) maxDepth = 5;
  if (!direction) direction = "forward";

  const fromCol = direction === "forward" ? "from_node" : "to_node";
  const toCol = direction === "forward" ? "to_node" : "from_node";

  const rows = d.prepare(`
    WITH RECURSIVE chain AS (
        SELECT e.from_node, e.edge_type, e.to_node, 1 AS depth
        FROM edges e
        WHERE e.${fromCol} = ? AND e.edge_type = 'CAUSES'

        UNION ALL

        SELECT e.from_node, e.edge_type, e.to_node, c.depth + 1
        FROM edges e
        JOIN chain c ON e.${fromCol} = c.${toCol}
        WHERE e.edge_type = 'CAUSES' AND c.depth < ?
    )
    SELECT c.from_node, c.to_node, c.depth, n.label AS event_label
    FROM chain c
    JOIN nodes n ON c.to_node = n.id
    ORDER BY c.depth
  `).all(eventId, maxDepth);

  return rows;
}

// ─── 聚合查询：最短关系路径 ─────────────────────────────────

/**
 * 两个角色之间的最短关系路径
 */
function shortestRelationshipPath(fromPerson, toPerson, maxDepth, db) {
  const d = db || getDb();
  if (maxDepth == null) maxDepth = 4;

  const rows = d.prepare(`
    WITH RECURSIVE path AS (
        SELECT from_node, to_node, edge_type, 1 AS depth,
               from_node || '--[' || edge_type || ']-->' || to_node AS path_str
        FROM edges
        WHERE from_node = ?

        UNION ALL

        SELECT e.from_node, e.to_node, e.edge_type, p.depth + 1,
               p.path_str || '--[' || e.edge_type || ']-->' || e.to_node
        FROM edges e
        JOIN path p ON e.from_node = p.to_node
        WHERE p.depth < ? AND e.from_node != ?
    )
    SELECT * FROM path WHERE to_node = ?
    ORDER BY depth LIMIT 1
  `).all(fromPerson, maxDepth, toPerson, toPerson);

  return rows.length > 0 ? rows[0] : null;
}

// ─── 聚合查询：钩子雷达 ─────────────────────────────────────

/**
 * 给定场景实体，计算所有活跃钩子的匹配分数
 *
 * @param {{ entities: string[], states: string[], location: string|null, timePoint: string|null }} scene
 *   states — 场景中已发生的状态变更 NODE ID 列表（state 条件按它匹配）
 * @param {number} currentChapter - 当前章节号，用于遗忘惩罚计算
 * @param {object} db
 * @returns {Array<{hook_id: string, hook_label: string, score: number, reason: string}>}
 */
function hookRadar(scene, currentChapter, db) {
  const d = db || getDb();

  const hooks = d.prepare(`
    SELECT * FROM nodes WHERE node_type = 'HOOK' AND status IN ('active', 'dormant')
  `).all();

  const results = [];

  for (const hook of hooks) {
    const props = JSON.parse(hook.properties || "{}");
    let score = 0;
    const reasons = [];

    // 基础优先级分
    score += (props.priority || 5) * 5;

    // 遗忘惩罚：超过 30 章未触发
    if (props.planted_chapter && currentChapter - props.planted_chapter > 30) {
      score += 15;
      reasons.push(`埋设于第${props.planted_chapter}章，已过${currentChapter - props.planted_chapter}章未触发`);
    }

    // 检查触发条件
    const conditions = d.prepare("SELECT * FROM hook_conditions WHERE hook_id = ?").all(hook.id);

    for (const cond of conditions) {
      if (cond.condition_type === "entity" && scene.entities && scene.entities.includes(cond.target_id)) {
        score += 30;
        reasons.push(`实体匹配: ${cond.target_id}`);
      }
      if (cond.condition_type === "location" && scene.location === cond.target_id) {
        score += 25;
        reasons.push(`地点匹配: ${cond.target_id}`);
      }
      if (cond.condition_type === "time" && scene.timePoint === cond.target_id) {
        score += 20;
        reasons.push(`时间匹配: ${cond.target_id}`);
      }
      // state 条件必须与场景传入的状态变更列表匹配才加分，不得无条件命中
      if (cond.condition_type === "state" && scene.states && scene.states.includes(cond.target_id)) {
        score += 35;
        reasons.push(`状态变更触发: ${cond.target_id}`);
      }
    }

    results.push({
      hook_id: hook.id,
      hook_label: hook.label,
      hook_type: props.hook_type || "unknown",
      score,
      planted_chapter: props.planted_chapter,
      expected_trigger_window: props.expected_trigger_window,
      match_reason: reasons.join("; ") || "基础匹配"
    });
  }

  results.sort((a, b) => b.score - a.score);
  return results;
}

// ─── 聚合查询：知识缺口检测 ─────────────────────────────────

/**
 * 检查某角色是否知道某事实，以及知识来源
 */
function knowledgeGap(personId, factId, db) {
  const d = db || getDb();

  const ks = d.prepare(`
    SELECT * FROM knowledge_sources
    WHERE person_id = ? AND target_id = ?
    ORDER BY confidence DESC LIMIT 1
  `).get(personId, factId);

  if (ks) {
    return {
      person_id: personId,
      fact_id: factId,
      knows: true,
      source_type: ks.source_type,
      source_event: ks.source_event,
      source_person: ks.source_person,
      acquired_at: ks.acquired_at,
      confidence: ks.confidence
    };
  }

  // 检查是否有 KNOWS_ABOUT 边
  const edge = d.prepare(`
    SELECT * FROM edges WHERE from_node = ? AND to_node = ? AND edge_type = 'KNOWS_ABOUT'
  `).get(personId, factId);

  if (edge) {
    return {
      person_id: personId,
      fact_id: factId,
      knows: true,
      source_type: "edge",
      properties: JSON.parse(edge.properties || "{}")
    };
  }

  return {
    person_id: personId,
    fact_id: factId,
    knows: false,
    gap: "角色表现出知道此信息，但无法追溯到 WITNESS/INFORMED_BY/DEDUCTION/BACKSTORY"
  };
}

// ─── 钩子生命周期管理 ────────────────────────────────────────

/**
 * 钩子状态机: dormant → triggered → resolved
 *              dormant/triggered → abandoned
 */

/**
 * 触发钩子: dormant → triggered
 */
function triggerHook(hookId, chapterNum, db) {
  const d = db || getDb();
  const node = d.prepare("SELECT * FROM nodes WHERE id = ? AND node_type = 'HOOK'").get(hookId);
  if (!node) throw new Error(`钩子不存在: ${hookId}`);
  if (node.status !== "active" && node.status !== "dormant") {
    throw new Error(`钩子 ${hookId} 当前状态为 ${node.status}，无法触发（需为 active/dormant）`);
  }

  d.prepare("UPDATE nodes SET status = 'triggered', updated_at = datetime('now') WHERE id = ?").run(hookId);

  const props = JSON.parse(node.properties || "{}");
  props.triggered_chapter = chapterNum;
  d.prepare("UPDATE nodes SET properties = ? WHERE id = ?").run(JSON.stringify(props), hookId);

  // 创建 TRIGGERED_IN 边
  d.prepare("DELETE FROM edges WHERE from_node = ? AND edge_type = 'TRIGGERED_IN'").run(hookId);
  d.prepare(`INSERT INTO edges (from_node, edge_type, to_node, properties, created_by)
    VALUES (?, 'TRIGGERED_IN', ?, '{}', 'hook-engine')`).run(hookId, `C_${String(chapterNum).padStart(3, '0')}`);

  return { hook_id: hookId, new_status: "triggered", triggered_chapter: chapterNum };
}

/**
 * 解决钩子: triggered → resolved
 */
function resolveHook(hookId, chapterNum, db) {
  const d = db || getDb();
  const node = d.prepare("SELECT * FROM nodes WHERE id = ? AND node_type = 'HOOK'").get(hookId);
  if (!node) throw new Error(`钩子不存在: ${hookId}`);
  if (node.status !== "triggered") {
    throw new Error(`钩子 ${hookId} 当前状态为 ${node.status}，无法解决（需为 triggered）`);
  }

  d.prepare("UPDATE nodes SET status = 'resolved', updated_at = datetime('now') WHERE id = ?").run(hookId);

  const props = JSON.parse(node.properties || "{}");
  props.resolved_chapter = chapterNum;
  d.prepare("UPDATE nodes SET properties = ? WHERE id = ?").run(JSON.stringify(props), hookId);

  // 创建 RESOLVED_IN 边
  d.prepare("DELETE FROM edges WHERE from_node = ? AND edge_type = 'RESOLVED_IN'").run(hookId);
  d.prepare(`INSERT INTO edges (from_node, edge_type, to_node, properties, created_by)
    VALUES (?, 'RESOLVED_IN', ?, '{}', 'hook-engine')`).run(hookId, `C_${String(chapterNum).padStart(3, '0')}`);

  return { hook_id: hookId, new_status: "resolved", resolved_chapter: chapterNum };
}

/**
 * 放弃钩子: any → abandoned
 */
function abandonHook(hookId, reason, db) {
  const d = db || getDb();
  const node = d.prepare("SELECT * FROM nodes WHERE id = ? AND node_type = 'HOOK'").get(hookId);
  if (!node) throw new Error(`钩子不存在: ${hookId}`);
  if (node.status === "resolved") {
    throw new Error(`钩子 ${hookId} 已解决，无法放弃`);
  }

  const props = JSON.parse(node.properties || "{}");
  props.abandoned_reason = reason || "作者废弃";
  d.prepare("UPDATE nodes SET status = 'abandoned', properties = ?, updated_at = datetime('now') WHERE id = ?")
    .run(JSON.stringify(props), hookId);

  return { hook_id: hookId, new_status: "abandoned", reason: props.abandoned_reason };
}

/**
 * 钩子生命周期汇总
 */
function hookLifecycleSummary(db) {
  const d = db || getDb();
  const rows = d.prepare(`
    SELECT id, label, status, properties FROM nodes WHERE node_type = 'HOOK' ORDER BY status, id
  `).all();

  const summary = { dormant: [], active: [], triggered: [], resolved: [], abandoned: [] };
  for (const r of rows) {
    const props = JSON.parse(r.properties || "{}");
    summary[r.status] = summary[r.status] || [];
    summary[r.status].push({
      id: r.id, label: r.label,
      hook_type: props.hook_type,
      priority: props.priority,
      planted_chapter: props.planted_chapter,
      triggered_chapter: props.triggered_chapter,
      resolved_chapter: props.resolved_chapter,
      expected_trigger_window: props.expected_trigger_window
    });
  }
  return summary;
}

/**
 * 检测钩子依赖环（PREREQUISITE_FOR 边）
 */
function checkHookDependencyCycle(newPrerequisiteId, newHookId, db) {
  const d = db || getDb();
  const row = d.prepare(`
    WITH RECURSIVE dep AS (
        SELECT from_node, to_node, 1 AS depth
        FROM edges
        WHERE edge_type = 'PREREQUISITE_FOR' AND from_node = ?

        UNION ALL

        SELECT e.from_node, e.to_node, d.depth + 1
        FROM edges e
        JOIN dep d ON e.from_node = d.to_node
        WHERE e.edge_type = 'PREREQUISITE_FOR' AND d.depth < 50
    )
    SELECT 1 FROM dep WHERE to_node = ? LIMIT 1
  `).get(newPrerequisiteId, newHookId);

  return row ? { cycle_detected: true, message: `添加 ${newPrerequisiteId} → ${newHookId} 会产生依赖环` }
             : { cycle_detected: false };
}

// ─── 伏笔文件同步（钩子数据源） ──────────────────────────────

/**
 * 解析 追踪/伏笔.md 状态表。
 *
 * 表格格式（与 detect-story-gaps.sh / story-explorer 的解析口径一致）：
 *   | ID | 伏笔内容 | 埋设章节 | 预计回收章节 | 状态 | 重要度 |
 * 状态取值：已埋 / 已回收 / 未埋 / 废弃。
 *
 * @param {string} filePath - 伏笔.md 绝对路径
 * @returns {Array<{id: string, summary: string, planted_chapter: number|null,
 *                   expected_recovery: string|null, status: string, importance: string}>}
 */
function parseForeshadowFile(filePath) {
  const fs = require("fs");
  let text;
  try {
    text = fs.readFileSync(filePath, "utf8");
  } catch {
    return [];
  }
  const rows = [];
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line.startsWith("|")) continue;
    const cells = line.split("|").map((cell) => cell.trim());
    // | ID | 内容 | 埋设章节 | 预计回收章节 | 状态 | 重要度 | → 7 个段（首尾空段）
    if (cells.length < 7) continue;
    const id = cells[1];
    const summary = cells[2];
    const plantedRaw = cells[3];
    const recoveryRaw = cells[4];
    const status = cells[5];
    const importance = cells[6];
    if (!id || /^-+$/.test(id) || /^ID$/i.test(id) || !summary) continue;
    const chapterMatch = String(plantedRaw).match(/第\s*(\d+)\s*章/);
    rows.push({
      id,
      summary,
      planted_chapter: chapterMatch ? Number(chapterMatch[1]) : null,
      expected_recovery: String(recoveryRaw).match(/第\s*(\d+)\s*章/) ? String(recoveryRaw) : null,
      status,
      importance,
    });
  }
  return rows;
}

const FORESHADOW_STATUS_TO_NODE = {
  "已埋": "dormant",
  "未埋": "draft",
  "已回收": "resolved",
  "废弃": "abandoned",
};
const FORESHADOW_IMPORTANCE_PRIORITY = { "高": 9, "中": 5, "低": 2 };

/**
 * 将 追踪/伏笔.md 同步为 HOOK 节点 + PLANTS_IN 边（幂等，可重复执行）。
 *
 * - 每个伏笔行 → HOOK 节点（id = H_{ID}），status 按状态映射；
 *   已埋→dormant、未埋→draft、已回收→resolved、废弃→abandoned。
 * - 手动管理保护：文件中为「已埋」但图中已是 triggered/resolved/abandoned 的
 *   钩子不降级（保留手动状态）；「已回收」则统一置 resolved。
 * - 埋设章节可解析时，幂等重建 PLANTS_IN → C_{三位章号} 边（章节点不存在则跳过）。
 * - 文件是钩子状态的权威源；手动 trigger/resolve/abandon 与文件状态冲突时
 *   以文件为准（「已埋」除外，见上）。
 *
 * @param {object} db
 * @param {string} foreshadowFilePath - 追踪/伏笔.md 路径
 * @returns {{created: number, updated: number, resolved: number, kept_manual: number, total: number, hooks: Array<{id: string, status: string}>}}
 */
function syncHooksFromForeshadowFile(db, foreshadowFilePath) {
  const d = db || getDb();
  const rows = parseForeshadowFile(foreshadowFilePath);
  const summary = { created: 0, updated: 0, resolved: 0, kept_manual: 0, total: rows.length, hooks: [] };

  const plantStmt = d.prepare("DELETE FROM edges WHERE from_node = ? AND edge_type = 'PLANTS_IN'");
  const insertPlantStmt = d.prepare(`
    INSERT INTO edges (from_node, edge_type, to_node, properties, created_by)
    VALUES (?, 'PLANTS_IN', ?, '{}', 'graph-builder')
  `);

  const tx = d.transaction(() => {
    for (const row of rows) {
      const hookId = `H_${row.id}`;
      const targetStatus = FORESHADOW_STATUS_TO_NODE[row.status] || "dormant";
      const priority = FORESHADOW_IMPORTANCE_PRIORITY[row.importance] || 5;
      const existing = d.prepare("SELECT * FROM nodes WHERE id = ? AND node_type = 'HOOK'").get(hookId);

      let effectiveStatus = targetStatus;
      let mode = "created";
      if (existing) {
        // 手动管理保护：已埋 不降级已触发/已解决/已废弃的钩子
        if (targetStatus === "dormant" && ["triggered", "resolved", "abandoned"].includes(existing.status)) {
          effectiveStatus = existing.status;
          mode = "kept_manual";
        } else if (targetStatus === "resolved" && existing.status !== "resolved") {
          effectiveStatus = "resolved";
          mode = "resolved";
        } else if (targetStatus !== existing.status) {
          effectiveStatus = targetStatus;
          mode = "updated";
        } else {
          mode = "unchanged";
        }
      }

      const props = {
        hook_type: "foreshadow",
        summary: row.summary,
        priority,
        source: "伏笔.md",
      };
      if (row.planted_chapter != null) props.planted_chapter = row.planted_chapter;
      if (row.expected_recovery != null) props.expected_trigger_window = row.expected_recovery;

      upsertNode({
        id: hookId,
        node_type: "HOOK",
        label: row.summary.length > 40 ? `${row.summary.slice(0, 40)}…` : row.summary,
        properties: props,
        status: effectiveStatus,
      }, d);

      if (summary[mode] == null) summary[mode] = 0;
      summary[mode] += 1;
      summary.hooks.push({ id: hookId, status: effectiveStatus });

      // 幂等重建 PLANTS_IN 边
      if (row.planted_chapter != null) {
        const chapterId = `C_${String(row.planted_chapter).padStart(3, "0")}`;
        const chapterExists = d.prepare("SELECT 1 FROM nodes WHERE id = ?").get(chapterId);
        if (chapterExists) {
          plantStmt.run(hookId);
          insertPlantStmt.run(hookId, chapterId);
        }
      }
    }
  });
  tx();

  return summary;
}

// ─── 快照导出 ────────────────────────────────────────────────

/**
 * 导出节点为文本表格（按类型分组）
 */
function exportNodesText(db) {
  const d = db || getDb();
  const types = ["PERSON", "LOCATION", "EVENT", "ITEM", "ORG", "TIME_POINT", "CHAPTER", "HOOK"];
  const result = {};

  for (const t of types) {
    const rows = d.prepare("SELECT id, label, status, properties FROM nodes WHERE node_type = ? ORDER BY id").all(t);
    if (rows.length === 0) continue;
    const lines = [];
    lines.push(`# ${t}`);
    for (const r of rows) {
      const props = JSON.parse(r.properties || "{}");
      const brief = Object.entries(props)
        .filter(([k]) => !["aliases", "backstory_knowledge"].includes(k))
        .map(([k, v]) => typeof v === "string" ? `${k}=${v}` : `${k}=${JSON.stringify(v)}`)
        .join(" | ");
      lines.push(`${r.id} | ${r.label} | ${r.status} | ${brief}`);
    }
    result[`nodes_${t.toLowerCase()}.txt`] = lines.join("\n") + "\n";
  }

  return result;
}

/**
 * 导出边为文本表格（按类型分组）
 */
function exportEdgesText(db) {
  const d = db || getDb();
  const edgeTypes = d.prepare("SELECT DISTINCT edge_type FROM edges ORDER BY edge_type").all();
  const result = {};

  for (const { edge_type } of edgeTypes) {
    const rows = d.prepare(`
      SELECT e.from_node, e.to_node, e.valid_since, e.valid_until,
             n1.label AS from_label, n2.label AS to_label
      FROM edges e
      JOIN nodes n1 ON e.from_node = n1.id
      JOIN nodes n2 ON e.to_node = n2.id
      WHERE e.edge_type = ?
      ORDER BY e.from_node
    `).all(edge_type);

    const lines = [];
    lines.push(`# ${edge_type}`);
    for (const r of rows) {
      const period = r.valid_since ? ` [${r.valid_since} → ${r.valid_until || "至今"}]` : "";
      lines.push(`${r.from_label} --[${edge_type}]--> ${r.to_label}${period}`);
    }
    const key = edge_type.toLowerCase().replace(/_/g, "-");
    result[`edges_${key}.txt`] = lines.join("\n") + "\n";
  }

  return result;
}

/**
 * 导出双线时间线（物理时间 + 叙事顺序合并视图）
 */
function exportTimelineText(db) {
  const d = db || getDb();

  // 物理时间线
  const timePoints = d.prepare(`
    SELECT id, label FROM nodes WHERE node_type = 'TIME_POINT' ORDER BY id
  `).all();

  const lines = [];
  lines.push("# 时间线合并视图");
  lines.push("");

  for (const tp of timePoints) {
    lines.push(`## ${tp.label} (${tp.id})`);
    const events = d.prepare(`
      SELECT n.id, n.label,
             json_extract(n.properties, '$.chapter') AS chapter,
             json_extract(n.properties, '$.event_type') AS event_type
      FROM nodes n
      JOIN edges e ON n.id = e.from_node AND e.edge_type = 'OCCURS_AT'
      WHERE e.to_node = ?
      ORDER BY CAST(json_extract(n.properties, '$.chapter') AS INTEGER)
    `).all(tp.id);

    for (const ev of events) {
      lines.push(`  Ch${ev.chapter || "?"}: ${ev.label} [${ev.event_type || "event"}]`);
    }
    lines.push("");
  }

  // 叙事顺序线（按章节）
  lines.push("## 叙事顺序线（按章节）");
  lines.push("");
  const chapters = d.prepare(`
    SELECT id, label,
           json_extract(properties, '$.chapter_number') AS num,
           json_extract(properties, '$.word_count') AS wc
    FROM nodes WHERE node_type = 'CHAPTER' ORDER BY id
  `).all();

  for (const ch of chapters) {
    lines.push(`### ${ch.label}`);
    const events = d.prepare(`
      SELECT n.label, json_extract(n.properties, '$.event_type') AS event_type
      FROM nodes n
      JOIN edges e ON n.id = e.to_node AND e.edge_type = 'NARRATES'
      WHERE e.from_node = ?
      ORDER BY n.id
    `).all(ch.id);

    for (const ev of events) {
      lines.push(`  - ${ev.label} [${ev.event_type || "event"}]`);
    }
    lines.push("");
  }

  return { "timeline_merged.txt": lines.join("\n") };
}

/**
 * 导出 SUMMARY.md（人类可读摘要）
 */
function exportSummary(db) {
  const d = db || getDb();
  const stats = graphStats(d);

  const lines = [];
  lines.push("# 知识图谱快照摘要");
  lines.push(`> 导出时间: ${new Date().toISOString()}`);
  lines.push("");
  lines.push("## 统计");
  lines.push(`- 总节点: ${stats.total_nodes}`);
  for (const [type, count] of Object.entries(stats.nodes_by_type)) {
    lines.push(`  - ${type}: ${count}`);
  }
  lines.push(`- 总边: ${stats.total_edges}`);
  lines.push(`- 活跃钩子: ${stats.active_hooks}`);
  lines.push(`- 已解决钩子: ${stats.resolved_hooks}`);
  lines.push("");

  // 人物表
  const persons = d.prepare("SELECT id, label, properties FROM nodes WHERE node_type = 'PERSON' AND status = 'active' ORDER BY id").all();
  if (persons.length > 0) {
    lines.push("## 人物");
    for (const p of persons) {
      const props = JSON.parse(p.properties || "{}");
      lines.push(`- **${p.label}** (${p.id}): ${props.role || ""} ${props.motivation ? `— ${props.motivation}` : ""}`);
    }
    lines.push("");
  }

  // 事件数（最近10个）
  const recentEvents = d.prepare(`
    SELECT label, json_extract(properties, '$.chapter') AS chapter
    FROM nodes WHERE node_type = 'EVENT' AND status = 'active'
    ORDER BY id DESC LIMIT 10
  `).all();
  if (recentEvents.length > 0) {
    lines.push("## 最近事件");
    for (const ev of recentEvents) {
      lines.push(`- Ch${ev.chapter || "?"}: ${ev.label}`);
    }
    lines.push("");
  }

  return { "SUMMARY.md": lines.join("\n") };
}

/**
 * 完整快照导出：返回 {filename: content} 映射
 */
function exportFullSnapshot(db) {
  const d = db || getDb();
  return {
    ...exportNodesText(d),
    ...exportEdgesText(d),
    ...exportTimelineText(d),
    ...exportSummary(d)
  };
}

// ─── 叙事债务管理 ────────────────────────────────────────────

/**
 * 创建叙事债务: 物理因果链有答案但叙事尚未交代
 */
function upsertNarrativeDebt(debt, db) {
  const d = db || getDb();
  const stmt = d.prepare(`
    INSERT INTO narrative_debts (question, answer_event, answer_time, triggered_by, character_id, priority, suggested_window, status)
    VALUES (@question, @answer_event, @answer_time, @triggered_by, @character_id, @priority, @suggested_window, @status)
    ON CONFLICT DO NOTHING
  `);
  return stmt.run(debt);
}

/**
 * 检测未偿还的叙事债务 — 在因果链中寻找有前因但叙事未交代的事件
 *
 * 算法: 对新增章节中每个有 CAUSES 关系的事件，追溯其物理因果链。
 * 如果前因事件在物理时间线中存在但还没有在任何章节被NARRATES — 创建叙事债务。
 */
function detectNarrativeDebts(chapterNum, db) {
  const d = db || getDb();
  const debts = [];

  // 找到本章所有有因果前驱的事件
  const events = d.prepare(`
    SELECT n.id, n.label, json_extract(n.properties, '$.chapter') AS chapter,
           json_extract(n.properties, '$.participants') AS participants
    FROM nodes n
    JOIN edges e ON n.id = e.to_node AND e.edge_type = 'CAUSES'
    WHERE n.node_type = 'EVENT' AND n.status = 'active'
      AND CAST(json_extract(n.properties, '$.chapter') AS INTEGER) <= ?
    GROUP BY n.id
  `).all(chapterNum);

  for (const evt of events) {
    // 追溯物理因果链中的所有前因事件
    const causes = d.prepare(`
      WITH RECURSIVE cause_chain AS (
          SELECT from_node, to_node, 1 AS depth
          FROM edges WHERE to_node = ? AND edge_type = 'CAUSES'
          UNION ALL
          SELECT e.from_node, e.to_node, c.depth + 1
          FROM edges e
          JOIN cause_chain c ON e.to_node = c.from_node
          WHERE e.edge_type = 'CAUSES' AND c.depth < 10
      )
      SELECT DISTINCT cc.from_node AS cause_event_id,
             n.label AS cause_label,
             json_extract(n.properties, '$.chapter') AS cause_chapter,
             json_extract(n.properties, '$.emotional_tone') AS tone
      FROM cause_chain cc
      JOIN nodes n ON cc.from_node = n.id
      WHERE n.node_type = 'EVENT'
    `).all(evt.id);

    for (const cause of causes) {
      // 检查这个原因事件是否已经在叙事中被交代
      const alreadyNarrated = d.prepare(`
        SELECT 1 FROM edges
        WHERE from_node LIKE 'C_%' AND edge_type = 'NARRATES' AND to_node = ?
        LIMIT 1
      `).get(cause.cause_event_id);

      if (!alreadyNarrated) {
        // 发现叙事债务: 这个原因事件存在但没有在任何章节叙述过
        // 检查是否已创建过这笔债务
        const existing = d.prepare(`
          SELECT id FROM narrative_debts
          WHERE answer_event = ? AND triggered_by = ?
          LIMIT 1
        `).get(cause.cause_event_id, evt.id);

        if (!existing) {
          const participants = JSON.parse(evt.participants || "[]");
          const charId = participants.length > 0 ? participants[0] : null;
          const priority = cause.tone === "shock" || cause.tone === "ominous" ? 9 :
                          cause.tone === "revelation" ? 7 : 5;
          const startWindow = Math.max(chapterNum, 10);
          const endWindow = Math.min(chapterNum + 80, 200);

          debts.push({
            question: `为什么${evt.label}？原因追溯到: ${cause.cause_label}`,
            answer_event: cause.cause_event_id,
            answer_time: null,
            triggered_by: evt.id,
            character_id: charId,
            priority: priority,
            suggested_window: `${startWindow}-${endWindow}`,
            status: "pending"
          });
        }
      }
    }
  }

  // 批量写入
  for (const debt of debts) {
    upsertNarrativeDebt(debt, d);
  }

  return { chapter: chapterNum, new_debts: debts.length, debts: debts };
}

/**
 * 闪回建议 — 当前章可以偿还哪些叙事债务
 *
 * 返回: 评分排序的债务列表，AI 根据节奏、情绪、场景自由决定是否偿还
 */
function flashbackOpportunities(chapterNum, scene, db) {
  const d = db || getDb();

  const debts = d.prepare(`
    SELECT nd.*,
           n.label AS answer_label,
           json_extract(n.properties, '$.summary') AS answer_summary
    FROM narrative_debts nd
    LEFT JOIN nodes n ON nd.answer_event = n.id
    WHERE nd.status = 'pending'
    ORDER BY nd.priority DESC, nd.created_at ASC
  `).all();

  const results = [];

  for (const debt of debts) {
    let score = 0;
    const reasons = [];

    // 优先级基础分
    score += (debt.priority || 5) * 7;

    // 窗口匹配: 当前章在建议窗口内
    if (debt.suggested_window) {
      const [lo, hi] = debt.suggested_window.split("-").map(Number);
      if (chapterNum >= lo && chapterNum <= hi) {
        score += 25;
        reasons.push(`在建议窗口内(${debt.suggested_window})`);
      }
    }

    // 角色匹配: 债务涉及的角色在当前场景中
    if (debt.character_id && scene && scene.entities &&
        scene.entities.includes(debt.character_id)) {
      score += 20;
      reasons.push(`场景中有相关角色: ${debt.character_id}`);
    }

    // 未偿还时间惩罚
    const debtAge = chapterNum - (debt.repaid_chapter || 0);
    if (debtAge > 30) {
      score += 15;
      reasons.push(`已等待${debtAge}章未偿还`);
    }

    results.push({
      debt_id: debt.id,
      question: debt.question,
      answer_event: debt.answer_event,
      answer_label: debt.answer_label,
      answer_summary: debt.answer_summary,
      score: score,
      priority: debt.priority,
      suggested_window: debt.suggested_window,
      reasons: reasons.join("; ") || "基础匹配",
      suggested_action: score >= 70 ? "建议偿还: 可在本章插入闪回" :
                        score >= 50 ? "关注: 可铺垫暗示" :
                        score >= 30 ? "观察: 等待更合适时机" : "暂缓"
    });
  }

  results.sort((a, b) => b.score - a.score);
  return results;
}

/**
 * 偿还叙事债务: pending → repaid
 */
function repayDebt(debtId, chapterNum, db) {
  const d = db || getDb();
  d.prepare(`
    UPDATE narrative_debts SET status = 'repaid', repaid_chapter = ?
    WHERE id = ?
  `).run(chapterNum, debtId);
  return { debt_id: debtId, status: "repaid", chapter: chapterNum };
}

// ─── 叙事-物理时间对齐 ──────────────────────────────────────

/**
 * 设置章节的物理时间映射
 */
function setChapterTime(chapterId, physicalTime, storyDay, absoluteOrder, db) {
  const d = db || getDb();
  d.prepare(`
    INSERT OR REPLACE INTO narrative_physical_map (chapter_id, physical_time, story_day, absolute_order)
    VALUES (?, ?, ?, ?)
  `).run(chapterId, physicalTime, storyDay, absoluteOrder);
}

/**
 * 查询叙事-物理时间对齐表: 回答"穿越后过了几天？"
 */
function getStoryTimeline(db) {
  const d = db || getDb();
  return d.prepare(`
    SELECT chapter_id, physical_time, story_day, absolute_order
    FROM narrative_physical_map
    ORDER BY absolute_order
  `).all();
}

// ─── Staging 管理 ────────────────────────────────────────────

function commitStaging(db) {
  const d = db || getDb();
  const commit = d.transaction(() => {
    // 提交 create/update 节点
    const insertNodes = d.prepare(`
      INSERT OR REPLACE INTO nodes (id, node_type, label, properties, status, created_at, updated_at)
      SELECT id, node_type, label, properties, status, datetime('now'), datetime('now')
      FROM staging_nodes WHERE action != 'delete'
    `);
    insertNodes.run();

    // 删除标记为 delete 的节点
    d.prepare(`
      DELETE FROM nodes WHERE id IN (SELECT id FROM staging_nodes WHERE action = 'delete')
    `).run();

    // 提交 create 边
    d.prepare(`
      INSERT INTO edges (from_node, edge_type, to_node, properties, valid_since, valid_until, created_by, created_at)
      SELECT from_node, edge_type, to_node, properties, valid_since, valid_until, 'graph-builder', datetime('now')
      FROM staging_edges WHERE action = 'create'
    `).run();

    // 提交 update 边（删旧插新）
    d.prepare(`
      DELETE FROM edges WHERE id IN (SELECT id FROM staging_edges WHERE action = 'update')
    `).run();
    d.prepare(`
      INSERT INTO edges (from_node, edge_type, to_node, properties, valid_since, valid_until, created_by, created_at)
      SELECT from_node, edge_type, to_node, properties, valid_since, valid_until, 'graph-builder', datetime('now')
      FROM staging_edges WHERE action = 'update'
    `).run();

    // 清空 staging
    d.prepare("DELETE FROM staging_nodes").run();
    d.prepare("DELETE FROM staging_edges").run();
  });
  commit();
}

function clearStaging(db) {
  const d = db || getDb();
  d.prepare("DELETE FROM staging_nodes").run();
  d.prepare("DELETE FROM staging_edges").run();
}

// ─── 统计信息 ────────────────────────────────────────────────

function graphStats(db) {
  const d = db || getDb();

  const nodeCounts = {};
  const nodeRows = d.prepare(`
    SELECT node_type, COUNT(*) as cnt FROM nodes WHERE status = 'active' GROUP BY node_type
  `).all();
  for (const r of nodeRows) nodeCounts[r.node_type] = r.cnt;

  const edgeCount = d.prepare("SELECT COUNT(*) as cnt FROM edges").get().cnt;
  const hookCount = d.prepare("SELECT COUNT(*) as cnt FROM nodes WHERE node_type = 'HOOK' AND status IN ('active','dormant')").get().cnt;
  const resolvedHookCount = d.prepare("SELECT COUNT(*) as cnt FROM nodes WHERE node_type = 'HOOK' AND status = 'resolved'").get().cnt;

  return {
    total_nodes: Object.values(nodeCounts).reduce((a, b) => a + b, 0),
    nodes_by_type: nodeCounts,
    total_edges: edgeCount,
    active_hooks: hookCount,
    resolved_hooks: resolvedHookCount
  };
}

// ─── 时间系统 ────────────────────────────────────────────────

/*
 * 时间模型（对标时空大数据系统: 统一时间戳 + 偏移 + 粒度自由）
 *
 *   TIME_POINT 携带:
 *     epoch       — 从纪元起算的绝对时间值 (整数/浮点, 单位由用户定义)
 *     date_label  — 人类可读标签, 如 "星辰历123年7月8日"
 *     time_unit   — 单位标识: "day"|"hour"|"second"
 *
 *   EVENT 携带:
 *     story_offset — 同一 epoch 内的偏移 (同一天内第几件事, 用于区分顺序)
 *
 *   排序规则:
 *     ORDER BY tp.epoch, COALESCE(ev.story_offset, ev.narrative_order, 0)
 *
 *   规则很简单:
 *     - 开书时, 选定时间原点。第一个 TIME_POINT 的 epoch=0
 *     - 后续每个 TIME_POINT 手动设定 epoch 值
 *     - 如果两个事件同一天: 设 story_offset=1,2,3 区分先后
 *     - 如果不设 story_offset: 默认按 narrative_order 排序 (先叙述的先发生)
 *     - repairTimeline() 自动补全缺失值
 *     - getTimeline()  返回按时间排序的完整事件列表
 *     - getTimeGaps()  检测时间空白 (可插入新内容的区间)
 */
function repairTimeline(db) {
  const d = db || getDb();

  // 1. TIME_POINT: 补全 epoch（从 narrative_physical_map.story_day 取初始值）
  const tps = d.prepare(`SELECT n.id, n.properties FROM nodes n WHERE n.node_type = 'TIME_POINT'`).all();
  const updateTP = d.transaction(() => {
    for (const tp of tps) {
      const props = JSON.parse(tp.properties || "{}");
      if (props.epoch != null) continue;
      const npm = d.prepare(`SELECT MIN(story_day) AS sd FROM narrative_physical_map WHERE physical_time = ? LIMIT 1`).get(tp.id);
      if (npm && npm.sd != null) { props.epoch = npm.sd; props.time_unit = "day"; }
      d.prepare("UPDATE nodes SET properties = ? WHERE id = ?").run(JSON.stringify(props), tp.id);
    }
  });
  updateTP();

  // 清理旧字段
  d.prepare(`UPDATE nodes SET properties = json_remove(properties, '$.story_time') WHERE json_extract(properties, '$.story_time') IS NOT NULL`).run();
  d.prepare(`UPDATE nodes SET properties = json_remove(properties, '$.physical_order') WHERE json_extract(properties, '$.physical_order') IS NOT NULL`).run();

  // 2. BEFORE 边
  const ordered = d.prepare(`SELECT id, CAST(json_extract(properties,'$.epoch') AS REAL) AS ep FROM nodes WHERE node_type='TIME_POINT' AND json_extract(properties,'$.epoch') IS NOT NULL ORDER BY ep`).all();
  d.prepare("DELETE FROM edges WHERE edge_type = 'BEFORE'").run();
  for (let i = 0; i < ordered.length - 1; i++) {
    if (ordered[i].ep === ordered[i+1].ep) continue;
    d.prepare(`INSERT INTO edges (from_node, edge_type, to_node, properties) VALUES (?, 'BEFORE', ?, '{}')`).run(ordered[i].id, ordered[i+1].id);
  }

  // 3. 给同 TIME_POINT 的事件自动填充 story_offset
  const tps2 = d.prepare(`SELECT id FROM nodes WHERE node_type='TIME_POINT'`).all();
  for (const tp of tps2) {
    const events = d.prepare(`
      SELECT e.from_node AS evid, CAST(json_extract(n.properties,'$.narrative_order') AS INTEGER) AS no
      FROM edges e JOIN nodes n ON e.from_node=n.id
      WHERE e.edge_type='OCCURS_AT' AND e.to_node=? AND n.node_type='EVENT'
      ORDER BY CAST(json_extract(n.properties,'$.chapter') AS INTEGER), no
    `).all(tp.id);

    const stmtUpdate = d.prepare(`UPDATE nodes SET properties = json_set(properties, '$.story_offset', ?) WHERE id = ?`);
    for (let i = 0; i < events.length; i++) {
      const offset = i;
      stmtUpdate.run(offset, events[i].evid);
    }
  }

  // 4. 回填缺失 OCCURS_AT
  const evtMissing = d.prepare(`SELECT n.id, n.properties FROM nodes n WHERE n.node_type='EVENT' AND n.status='active' AND NOT EXISTS (SELECT 1 FROM edges e WHERE e.from_node=n.id AND e.edge_type='OCCURS_AT')`).all();
  const fill = d.transaction(() => {
    for (const ev of evtMissing) {
      const ch = parseInt(JSON.parse(ev.properties||"{}").chapter)||0;
      if (ch > 0) {
        const npm = d.prepare(`SELECT physical_time FROM narrative_physical_map WHERE chapter_id=? LIMIT 1`).get(`C_${String(ch).padStart(3,'0')}`);
        if (npm) d.prepare(`INSERT INTO edges (from_node, edge_type, to_node, properties) VALUES (?, 'OCCURS_AT', ?, '{}')`).run(ev.id, npm.physical_time);
      }
    }
  });
  fill();

  return { timePoints: tps.length, beforeEdges: ordered.length-1, offsetsFilled: true, occursAtFilled: evtMissing.length };
}

/**
 * 设置 TIME_POINT 的绝对时间
 * @param {number} epoch - 从纪元算起的值 (单位由你定: 天/小时/秒)
 * @param {string} dateLabel - "星辰历123年7月8日"
 * @param {string} unit - "day"|"hour"|"second"
 */
function setTimePointTime(timePointId, epoch, dateLabel, unit, db) {
  const d = db || getDb();
  const node = d.prepare("SELECT properties FROM nodes WHERE id=? AND node_type='TIME_POINT'").get(timePointId);
  if (!node) throw new Error("TIME_POINT 不存在: " + timePointId);
  const props = JSON.parse(node.properties || "{}");
  props.epoch = epoch;
  if (dateLabel) props.date_label = dateLabel;
  if (unit) props.time_unit = unit;
  d.prepare("UPDATE nodes SET properties=? WHERE id=?").run(JSON.stringify(props), timePointId);
  return { id: timePointId, epoch, date_label: dateLabel, time_unit: unit };
}

/**
 * 设置 EVENT 在同时间点内的偏移 (区分同一天的事)
 */
function setEventOffset(eventId, offset, db) {
  const d = db || getDb();
  d.prepare(`UPDATE nodes SET properties = json_set(properties, '$.story_offset', ?) WHERE id=? AND node_type='EVENT'`).run(offset, eventId);
  return { id: eventId, story_offset: offset };
}

/**
 * 完整时间线: 所有事件按 epoch → offset → narrative_order 排序
 */
function getTimeline(db) {
  const d = db || getDb();
  return d.prepare(`
    SELECT n.label, n.id,
      json_extract(n.properties,'$.chapter') AS ch,
      json_extract(n.properties,'$.event_type') AS etype,
      json_extract(n.properties,'$.story_offset') AS off,
      COALESCE((SELECT n2.label FROM edges e JOIN nodes n2 ON e.to_node=n2.id WHERE e.from_node=n.id AND e.edge_type='OCCURS_AT'),'-') AS tp,
      COALESCE((SELECT json_extract(n2.properties,'$.epoch') FROM edges e JOIN nodes n2 ON e.to_node=n2.id WHERE e.from_node=n.id AND e.edge_type='OCCURS_AT'),'-') AS epoch,
      COALESCE((SELECT json_extract(n2.properties,'$.date_label') FROM edges e JOIN nodes n2 ON e.to_node=n2.id WHERE e.from_node=n.id AND e.edge_type='OCCURS_AT'),'-') AS date_label
    FROM nodes n WHERE n.node_type='EVENT' AND n.status='active'
    ORDER BY
      CAST(COALESCE((SELECT json_extract(n2.properties,'$.epoch') FROM edges e JOIN nodes n2 ON e.to_node=n2.id WHERE e.from_node=n.id AND e.edge_type='OCCURS_AT'),'99999999') AS REAL),
      CAST(COALESCE(json_extract(n.properties,'$.story_offset'), json_extract(n.properties,'$.narrative_order'), '0') AS REAL)
  `).all();
}

/**
 * 检测时间空白: TIME_POINT 之间可以插入新内容的区间
 */
function getTimeGaps(db) {
  const d = db || getDb();
  const tps = d.prepare(`SELECT id,label,json_extract(properties,'$.epoch') AS ep,json_extract(properties,'$.date_label') AS dl FROM nodes WHERE node_type='TIME_POINT' AND json_extract(properties,'$.epoch') IS NOT NULL ORDER BY CAST(json_extract(properties,'$.epoch') AS REAL)`).all();
  const gaps = [];
  for (let i = 0; i < tps.length - 1; i++) {
    const gap = tps[i+1].ep - tps[i].ep;
    if (gap > 1) gaps.push({ from: tps[i].label, to: tps[i+1].label, fromDate: tps[i].dl, toDate: tps[i+1].dl, gapSize: gap });
  }
  return gaps;
}
// ─── Hook 状态查询 ──────────────────────────────────────────

/**
 * 会话启动时的图状态检查（替代 session-start-graph.sh 的业务逻辑）
 * @returns {{ message: string, status: string }}
 */
function sessionStatus(projectRoot) {
  const fs = require("fs");
  const path = require("path");

  // 发现活跃书（回退链：.active-book → 追踪/ → 正文/ → 正文.md）
  const bookDir = discoverBookDir(projectRoot);

  if (!bookDir) return { status: "no-book", message: "" };

  const dbPath = path.join(bookDir, "story.db");
  const markerPath = path.join(projectRoot, ".claude", ".graph-update-pending");

  // 检查是否有待处理更新
  // 标记格式: {时间戳}\t{章节号}\t{文件路径}（checkGraphUpdate 追加写）
  let pending = false, pendingChapters = "", pendingNumbers = [], pendingTotal = 0;
  if (fs.existsSync(markerPath)) {
    pending = true;
    try {
      const numbers = [];
      const labels = [];
      for (const line of fs.readFileSync(markerPath, "utf8").split("\n")) {
        const raw = (line.split("\t")[1] || "").trim();
        if (!raw) continue;
        labels.push(raw);
        const num = Number(raw);
        if (Number.isInteger(num) && num > 0) numbers.push(num);
      }
      pendingChapters = labels.join(",");
      pendingNumbers = numbers;
      pendingTotal = labels.length;
    } catch (e) {}
  }

  // story.db 不存在
  if (!fs.existsSync(dbPath)) {
    // 检查是否可以 seed
    let canSeed = false;
    try {
      const charDir = path.join(bookDir, "设定", "角色");
      const outlineDir = path.join(bookDir, "大纲");
      if ((fs.existsSync(charDir) && fs.readdirSync(charDir).some(f => f.endsWith(".md")))) canSeed = true;
      if (fs.existsSync(outlineDir)) canSeed = true;
    } catch (e) {}
    return { status: "no-db", canSeed, message: "未初始化知识图谱。运行 /story-graph seed" };
  }

  // 打开数据库查统计
  let db = null;
  let stats = null;
  try {
    db = open(dbPath);
    stats = graphStats(db);
  } catch (e) {
    return { status: "db-error", message: "story.db 读取失败: " + e.message };
  }

  if (pending) {
    // 自愈：标记中所有章节号都已入库（≤ 图内最新章节号，且全部可解析为数字）
    // → 标记是上次 /story-graph update 的残留，清理并返回就绪，避免反复提示
    const maxChapter = db.prepare(
      "SELECT MAX(CAST(json_extract(properties, '$.chapter_number') AS INTEGER)) AS m FROM nodes WHERE node_type = 'CHAPTER'",
    ).get().m;
    const allProcessed = pendingTotal > 0
      && pendingNumbers.length === pendingTotal
      && maxChapter != null
      && pendingNumbers.every((n) => n <= maxChapter);
    if (allProcessed) {
      try { fs.unlinkSync(markerPath); } catch (e) {}
      return {
        status: "ready",
        nodes: stats.total_nodes,
        edges: stats.total_edges,
        activeHooks: stats.active_hooks,
        resolvedHooks: stats.resolved_hooks,
        selfHealed: true,
        message: `知识图谱就绪（待更新标记已清理）: ${stats.total_nodes}节点 / ${stats.total_edges}边 / ${stats.active_hooks}活跃钩子`
      };
    }
    return {
      status: "pending-update",
      nodes: stats.total_nodes,
      edges: stats.total_edges,
      pendingChapters,
      message: `知识图谱需更新 — 第${pendingChapters}章。当前: ${stats.total_nodes}节点/${stats.total_edges}边。运行 /story-graph update`
    };
  }

  // 清理残留标记
  try { fs.unlinkSync(markerPath); } catch (e) {}

  return {
    status: "ready",
    nodes: stats.total_nodes,
    edges: stats.total_edges,
    activeHooks: stats.active_hooks,
    resolvedHooks: stats.resolved_hooks,
    message: `知识图谱就绪: ${stats.total_nodes}节点 / ${stats.total_edges}边 / ${stats.active_hooks}活跃钩子 → story-explorer 可用（图查询）`
  };
}

/**
 * 正文落盘后检测是否需要增量更新（替代 graph-update-check.sh 的业务逻辑）
 * @returns {{ needsUpdate: boolean, message: string }}
 */
function checkGraphUpdate(targetFile, projectRoot) {
  const fs = require("fs");
  const path = require("path");

  // 发现活跃书（回退链：.active-book → 追踪/ → 正文/ → 正文.md）
  const bookDir = discoverBookDir(projectRoot);
  if (!bookDir) return { needsUpdate: false, message: "" };

  const dbPath = path.join(bookDir, "story.db");
  if (!fs.existsSync(dbPath)) {
    return { needsUpdate: false, message: "未初始化知识图谱。运行 /story-graph seed" };
  }

  // 判断是否是正文文件
  const base = path.basename(targetFile);
  const parent = path.basename(path.dirname(targetFile));
  let isProse = false;
  if (base === "正文.md" && fs.existsSync(path.join(path.dirname(targetFile), "设定.md"))) isProse = true;
  if (base.startsWith("第") && base.includes("章") && base.endsWith(".md") && parent === "正文") isProse = true;
  if (!isProse) return { needsUpdate: false, message: "" };

  // 写标记文件
  const markerPath = path.join(projectRoot, ".claude", ".graph-update-pending");
  const chapterNum = (base.match(/\d+/) || ["?"])[0];
  const stamp = new Date().toISOString().slice(0, 19);
  try {
    const markersDir = path.dirname(markerPath);
    if (!fs.existsSync(markersDir)) fs.mkdirSync(markersDir, { recursive: true });
    fs.appendFileSync(markerPath, `${stamp}\t${chapterNum}\t${targetFile}\n`, "utf8");
  } catch (e) {}

  // 读统计
  let statsStr = "";
  try {
    const db = open(dbPath);
    const s = graphStats(db);
    statsStr = `${s.total_nodes}节点/${s.total_edges}边/${s.active_hooks}活跃钩子`;
  } catch (e) {}

  return {
    needsUpdate: true,
    chapterNum,
    stats: statsStr,
    message: `知识图谱需更新 — 第${chapterNum}章已写入。当前: ${statsStr}。请运行 /story-graph update`
  };
}

// ─── 导出 ────────────────────────────────────────────────────

module.exports = {
  open,
  close,
  getDb,
  initSchema,

  // 节点
  upsertNode,
  upsertNodes,
  getNode,
  getNodesByType,
  getAllNodes,
  deleteNode,

  // 边
  upsertEdge,
  upsertEdges,
  replaceEdgesFrom,
  getEdgesFrom,
  getEdgesTo,

  // 聚合查询
  stateAtTime,
  stateWindow,
  causalChain,
  shortestRelationshipPath,
  hookRadar,
  knowledgeGap,

  // 时间窗口判定（导出供测试）
  resolveTimePointEpoch,
  edgeValidInWindow,
  edgeOverlapsWindow,
  edgeCoversWindow,

  // 钩子生命周期
  triggerHook,
  resolveHook,
  abandonHook,
  hookLifecycleSummary,
  checkHookDependencyCycle,

  // 伏笔文件同步
  parseForeshadowFile,
  syncHooksFromForeshadowFile,

  // 叙事债务
  upsertNarrativeDebt,
  detectNarrativeDebts,
  flashbackOpportunities,
  repayDebt,

  // 叙事-物理时间对齐
  setChapterTime,
  getStoryTimeline,

  // 快照导出
  exportNodesText,
  exportEdgesText,
  exportTimelineText,
  exportSummary,
  exportFullSnapshot,

  // Staging
  commitStaging,
  clearStaging,

  // 统计
  graphStats,

  // Hook 状态
  sessionStatus,
  checkGraphUpdate,
  discoverBookDir,

  // 时间线
  repairTimeline,
  setTimePointTime,
  setEventOffset,
  getTimeline,
  getTimeGaps,
};
