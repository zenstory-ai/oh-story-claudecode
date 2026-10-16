#!/usr/bin/env node
"use strict";

const core = require("./story_graph_core");
const viz = require("./viz_html");
const path = require("path");

function resolveDb(p) {
  return path.resolve(p || "story.db");
}

const cmd = process.argv[2];
const dbPath = resolveDb(process.argv[3]);

function out(obj) {
  process.stdout.write(JSON.stringify(obj, null, 2) + "\n");
}

function fail(msg) {
  process.stderr.write(msg + "\n");
  process.exit(1);
}

try {
  switch (cmd) {
    case "init": {
      core.initSchema(dbPath);
      out({ status: "ok", message: "Schema initialized", db: dbPath });
      break;
    }

    case "stats": {
      const db = core.open(dbPath);
      const stats = core.graphStats(db);
      out(stats);
      break;
    }

    case "state-at-time": {
      const entityId = process.argv[4], timePointId = process.argv[5];
      if (!entityId || !timePointId) fail("Usage: state-at-time <db> <entityId> <timePointId>");
      out(core.stateAtTime(entityId, timePointId, core.open(dbPath)));
      break;
    }

    case "hook-radar": {
      // entities 支持两种形态：数组 ["P_x"]，或对象 {"entities":[...],"states":[...]}
      const raw = process.argv[4] || "[]";
      let entities = [];
      let states = [];
      try {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) entities = parsed;
        else if (parsed && typeof parsed === "object") {
          entities = parsed.entities || [];
          states = parsed.states || [];
        }
      } catch (e) {}
      const location = process.argv[5] || null;
      const timePoint = process.argv[6] || null;
      const chapter = parseInt(process.argv[7]) || 0;
      out(core.hookRadar({ entities, states, location, timePoint }, chapter, core.open(dbPath)));
      break;
    }

    case "causal-chain": {
      const eventId = process.argv[4], direction = process.argv[5] || "forward";
      const maxDepth = parseInt(process.argv[6]) || 5;
      if (!eventId) fail("Usage: causal-chain <db> <eventId> [forward|backward] [depth]");
      out(core.causalChain(eventId, direction, maxDepth, core.open(dbPath)));
      break;
    }

    case "knowledge-gap": {
      const personId = process.argv[4], factId = process.argv[5];
      if (!personId || !factId) fail("Usage: knowledge-gap <db> <personId> <factId>");
      out(core.knowledgeGap(personId, factId, core.open(dbPath)));
      break;
    }

    case "shortest-path": {
      const fromPerson = process.argv[4], toPerson = process.argv[5];
      if (!fromPerson || !toPerson) fail("Usage: shortest-path <db> <fromPerson> <toPerson>");
      const db = core.open(dbPath);
      const result = core.shortestRelationshipPath(fromPerson, toPerson, null, db);
      out(result || { found: false, message: "未找到路径" });
      break;
    }

    case "trigger-hook": {
      const hookId = process.argv[4], ch = parseInt(process.argv[5]) || 0;
      if (!hookId || !ch) fail("Usage: trigger-hook <db> <hookId> <chapterNum>");
      out(core.triggerHook(hookId, ch, core.open(dbPath)));
      break;
    }

    case "resolve-hook": {
      const hookId = process.argv[4], ch = parseInt(process.argv[5]) || 0;
      if (!hookId || !ch) fail("Usage: resolve-hook <db> <hookId> <chapterNum>");
      out(core.resolveHook(hookId, ch, core.open(dbPath)));
      break;
    }

    case "abandon-hook": {
      const hookId = process.argv[4], reason = process.argv[5] || "作者废弃";
      if (!hookId) fail("Usage: abandon-hook <db> <hookId> [reason]");
      out(core.abandonHook(hookId, reason, core.open(dbPath)));
      break;
    }

    case "hook-summary": {
      out(core.hookLifecycleSummary(core.open(dbPath)));
      break;
    }

    case "state-window": {
      const ts = process.argv[4], te = process.argv[5], loc = process.argv[6] || null;
      if (!ts || !te) fail("Usage: state-window <db> <timeStart> <timeEnd> [location]");
      out(core.stateWindow({ timeStart: ts, timeEnd: te, location: loc }, null, core.open(dbPath)));
      break;
    }

    case "detect-debts": {
      const ch = parseInt(process.argv[4]) || 0;
      if (!ch) fail("Usage: detect-debts <db> <chapterNum>");
      out(core.detectNarrativeDebts(ch, core.open(dbPath)));
      break;
    }

    case "flashback-opps": {
      const ch = parseInt(process.argv[4]) || 0;
      const entities = JSON.parse(process.argv[5] || "[]");
      if (!ch) fail("Usage: flashback-opps <db> <chapterNum> <entitiesJSON>");
      out(core.flashbackOpportunities(ch, { entities }, core.open(dbPath)));
      break;
    }

    case "repay-debt": {
      const debtId = parseInt(process.argv[4]) || 0, ch = parseInt(process.argv[5]) || 0;
      if (!debtId || !ch) fail("Usage: repay-debt <db> <debtId> <chapterNum>");
      out(core.repayDebt(debtId, ch, core.open(dbPath)));
      break;
    }

    case "set-chapter-time": {
      const chId = process.argv[4], timeId = process.argv[5];
      const day = parseInt(process.argv[6]) || 0, order = parseInt(process.argv[7]) || 0;
      if (!chId || !timeId || !day) fail("Usage: set-chapter-time <db> <chId> <timeId> <storyDay> <absOrder>");
      core.setChapterTime(chId, timeId, day, order);
      out({ status: "ok" });
      break;
    }

    case "repair-timeline": {
      const db = core.open(dbPath);
      const result = core.repairTimeline(db);
      out(result);
      break;
    }

    case "set-timepoint-time": {
      const tpId = process.argv[4], ep = parseFloat(process.argv[5]), dl = process.argv[6] || null, u = process.argv[7] || null;
      if (!tpId || isNaN(ep)) fail("Usage: set-timepoint-time <db> <timePointId> <epoch> [dateLabel] [unit:day|hour|second]");
      out(core.setTimePointTime(tpId, ep, dl, u, core.open(dbPath)));
      break;
    }

    case "set-event-offset": {
      const evId = process.argv[4], off = parseInt(process.argv[5]) || 0;
      if (!evId) fail("Usage: set-event-offset <db> <eventId> <offset>");
      out(core.setEventOffset(evId, off, core.open(dbPath)));
      break;
    }

    case "timeline": {
      out(core.getTimeline(core.open(dbPath)));
      break;
    }

    case "time-gaps": {
      out(core.getTimeGaps(core.open(dbPath)));
      break;
    }

    case "story-timeline": {
      out(core.getStoryTimeline(core.open(dbPath)));
      break;
    }

    case "session-status": {
      const projectRoot = process.argv[4] || process.cwd();
      const result = core.sessionStatus(projectRoot);
      if (result.message) process.stdout.write(result.message + "\n");
      else out(result);
      break;
    }

    case "prose-check": {
      // 注意: CLI 全局 dbPath 占用了 argv[3]，所以 targetFile 从 argv[4] 取
      const targetFile = process.argv[4];
      const projectRoot = process.argv[5] || process.cwd();
      if (!targetFile) fail("Usage: prose-check _ <targetFile> [projectRoot]");
      const result = core.checkGraphUpdate(targetFile, projectRoot);
      if (result.message) process.stdout.write(result.message + "\n");
      else out(result);
      break;
    }

    case "viz": {
      const outFile = process.argv[4];
      if (!outFile) fail("Usage: viz <db> <outFile>");
      const db = core.open(dbPath);
      const fs = require("fs");

      const nodes = db.prepare("SELECT id, node_type, label, properties, status FROM nodes WHERE status != 'deleted'").all();
      const edges = db.prepare(`
        SELECT e.from_node, e.edge_type, e.to_node, n1.label AS from_label, n2.label AS to_label
        FROM edges e JOIN nodes n1 ON e.from_node = n1.id JOIN nodes n2 ON e.to_node = n2.id
      `).all();

      const graphData = { nodes: [], edges: [] };
      for (const n of nodes) {
        graphData.nodes.push({ id: n.id, label: n.label, type: n.node_type, status: n.status, props: JSON.parse(n.properties || "{}") });
      }
      for (const e of edges) {
        graphData.edges.push({ from: e.from_node, to: e.to_node, type: e.edge_type, fromLabel: e.from_label, toLabel: e.to_label });
      }

      const html = viz.generateVizHTML(graphData, dbPath);
      fs.writeFileSync(outFile, html, "utf8");
      out({ status: "ok", file: outFile, nodes: graphData.nodes.length, edges: graphData.edges.length });
      break;
    }

    case "export-snapshot": {
      const outDir = process.argv[4];
      if (!outDir) fail("Usage: export-snapshot <db> <outDir>");
      const db = core.open(dbPath);
      const snapshot = core.exportFullSnapshot(db);
      const fs = require("fs"), p = require("path");
      if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });
      for (const [filename, content] of Object.entries(snapshot)) {
        fs.writeFileSync(p.join(outDir, filename), content, "utf8");
      }
      out({ status: "ok", snapshot_dir: outDir, files: Object.keys(snapshot) });
      break;
    }

    case "sync-hooks": {
      const filePath = process.argv[4];
      if (!filePath) fail("Usage: sync-hooks <db> <foreshadowFile>");
      out(core.syncHooksFromForeshadowFile(core.open(dbPath), filePath));
      break;
    }

    case "exec": {
      const sql = process.argv[4];
      if (!sql) fail("Usage: exec <db> <sql>");
      const db = core.open(dbPath);
      const trimmed = sql.trim().toUpperCase();
      if (trimmed.startsWith("SELECT") || trimmed.startsWith("WITH") || trimmed.startsWith("PRAGMA")) {
        out({ rows: db.prepare(sql).all(), count: db.prepare("SELECT changes()").get() });
      } else {
        const result = db.prepare(sql).run();
        out({ changes: result.changes, lastInsertRowid: result.lastInsertRowid });
      }
      break;
    }

    default:
      fail("Commands: init stats state-at-time state-window hook-radar causal-chain knowledge-gap shortest-path trigger-hook resolve-hook abandon-hook hook-summary detect-debts flashback-opps repay-debt set-chapter-time set-timepoint-time set-event-offset repair-timeline timeline time-gaps story-timeline session-status prose-check sync-hooks viz export-snapshot exec");
  }
} catch (err) {
  fail("Error: " + err.message);
} finally {
  core.close();
}
