"use strict";

/**
 * 生成自包含的交互式知识图谱可视化 HTML 文件
 */

const NODE_COLORS = {
  PERSON:     { bg: "#4A90D9", border: "#2E6AB0", shape: "dot", size: 25 },
  LOCATION:   { bg: "#50B86C", border: "#338A4A", shape: "diamond", size: 20 },
  EVENT:      { bg: "#F5A623", border: "#C07D10", shape: "dot", size: 15 },
  ITEM:       { bg: "#9B59B6", border: "#7D3C98", shape: "triangle", size: 18 },
  ORG:        { bg: "#E74C3C", border: "#B8312A", shape: "square", size: 22 },
  TIME_POINT: { bg: "#1ABC9C", border: "#148F77", shape: "hexagon", size: 14 },
  CHAPTER:    { bg: "#95A5A6", border: "#6C7A7B", shape: "square", size: 16 },
  HOOK:       { bg: "#E67E22", border: "#B5611A", shape: "star", size: 20 }
};

const EDGE_COLORS = {
  CAUSES: "#E74C3C", NARRATES: "#95A5A6", PARTICIPATES_IN: "#3498DB",
  LOCATED_AT: "#50B86C", OWNS: "#9B59B6", BELONGS_TO: "#E74C3C",
  ALLIED_WITH: "#2ECC71", HOSTILE_TO: "#E74C3C", KIN_TO: "#F39C12",
  ROMANTIC_WITH: "#E91E63", MENTOR_OF: "#8BC34A", KNOWS_ABOUT: "#1ABC9C",
  WITNESS: "#F5A623", INFORMED_BY: "#3498DB", OCCURS_AT: "#1ABC9C",
  TRIGGERED_IN: "#E67E22", RESOLVED_IN: "#27AE60",
  PREREQUISITE_FOR: "#F39C12", FLASHBACK_TO: "#9B59B6"
};
const DEFAULT_EDGE = "#BDC3C7";

/**
 * @param {object} graphData - { nodes: [{id, label, type, status, props}], edges: [{from, to, type, fromLabel, toLabel}] }
 * @param {string} dbPath
 * @returns {string} 完整的 HTML 文件内容
 */
function generateVizHTML(graphData, dbPath) {
  // Build vis-network nodes
  const visNodes = graphData.nodes.map(n => {
    const c = NODE_COLORS[n.type] || { bg: "#BDC3C7", border: "#888", shape: "dot", size: 16 };
    const propsStr = JSON.stringify(n.props || {})
      .replace(/[{}"]/g, "").replace(/,/g, "<br>").substring(0, 300);
    return {
      id: n.id, label: n.label, group: n.type,
      color: { background: c.bg, border: c.border },
      shape: c.shape, size: c.size,
      title: "<b>" + n.type + "</b>: " + n.label + "<br>" + propsStr,
      font: { size: 11, face: "sans-serif" }
    };
  });

  // Build vis-network edges
  const visEdges = graphData.edges.map(e => ({
    from: e.from, to: e.to, label: e.type,
    color: { color: EDGE_COLORS[e.type] || DEFAULT_EDGE, opacity: 0.7 },
    arrows: "to", font: { size: 8, align: "middle" },
    title: e.fromLabel + " --[" + e.type + "]--> " + e.toLabel
  }));

  // Build legend HTML
  var legendHTML = Object.entries(NODE_COLORS).map(function(entry) {
    var type = entry[0], c = entry[1];
    return '<div class="item"><span class="swatch" style="background:' + c.bg + '"></span>' + type + '</div>';
  }).join("");

  // Build filter checkboxes
  var filtersHTML = Object.entries(NODE_COLORS).map(function(entry) {
    var type = entry[0], c = entry[1];
    return '<label style="border-color:' + c.bg + '"><input type="checkbox" data-type="' + type + '" checked onchange="toggleType(\'' + type + '\',this.checked)"> ' + type + '</label>';
  }).join("");

  var nodesJSON = JSON.stringify(visNodes);
  var edgesJSON = JSON.stringify(visEdges);

  return '<!DOCTYPE html>\n<html lang="zh">\n<head>\n<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width, initial-scale=1.0">\n<title>叙事知识图谱</title>\n' +
    '<style>\n' +
    '* { margin: 0; padding: 0; box-sizing: border-box; }\n' +
    'body { font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #1a1a2e; color: #eee; overflow: hidden; height: 100vh; }\n' +
    '#toolbar { position: absolute; top: 0; left: 0; right: 0; z-index: 10; background: rgba(26,26,46,0.95); padding: 8px 16px; display: flex; align-items: center; gap: 10px; border-bottom: 1px solid #2d2d4a; flex-wrap: wrap; }\n' +
    '#toolbar h2 { font-size: 16px; color: #fff; margin-right: 8px; white-space: nowrap; }\n' +
    '#toolbar label { font-size: 11px; cursor: pointer; display: flex; align-items: center; gap: 4px; padding: 3px 8px; border-radius: 4px; border: 1px solid #3d3d5a; user-select: none; white-space: nowrap; }\n' +
    '#toolbar label:hover { background: #2d2d4a; }\n' +
    '#network { position: absolute; top: 48px; left: 0; right: 0; bottom: 0; }\n' +
    '#legend { position: absolute; bottom: 12px; left: 12px; background: rgba(26,26,46,0.9); padding: 10px 14px; border-radius: 6px; font-size: 11px; z-index: 11; border: 1px solid #3d3d5a; }\n' +
    '#legend .item { display: flex; align-items: center; gap: 6px; margin: 3px 0; }\n' +
    '#legend .swatch { width: 14px; height: 14px; border-radius: 50%; flex-shrink: 0; }\n' +
    '.info-panel { position: absolute; top: 60px; right: 12px; background: rgba(26,26,46,0.92); padding: 12px 16px; border-radius: 6px; font-size: 12px; z-index: 11; border: 1px solid #3d3d5a; max-width: 300px; display: none; }\n' +
    '.info-panel.visible { display: block; }\n' +
    '.info-panel h3 { font-size: 14px; margin-bottom: 6px; }\n' +
    '.info-panel .prop { margin: 2px 0; color: #aaa; word-break: break-all; }\n' +
    '</style>\n</head>\n<body>\n' +
    '<div id="toolbar"><h2>叙事知识图谱</h2>' + filtersHTML +
    ' <span style="color:#888;font-size:11px;margin-left:8px">拖拽 | 滚轮缩放 | 点击查看详情</span></div>\n' +
    '<div id="network"></div>\n' +
    '<div id="legend">' + legendHTML + '</div>\n' +
    '<div id="info" class="info-panel"></div>\n' +
    '<script src="https://unpkg.com/vis-network@9.1.9/dist/vis-network.min.js"></script>\n' +
    '<script>\n' +
    'var nodes = new vis.DataSet(' + nodesJSON + ');\n' +
    'var edges = new vis.DataSet(' + edgesJSON + ');\n' +
    'var container = document.getElementById("network");\n' +
    'var data = { nodes: nodes, edges: edges };\n' +
    'var options = {\n' +
    '  physics: { solver: "forceAtlas2Based", forceAtlas2Based: { gravitationalConstant: -45, centralGravity: 0.01, springLength: 150, springConstant: 0.08 }, stabilization: { iterations: 200 } },\n' +
    '  edges: { smooth: { type: "continuous" }, width: 1.5 },\n' +
    '  interaction: { hover: true, tooltipDelay: 100 }\n' +
    '};\n' +
    'var network = new vis.Network(container, data, options);\n' +
    'network.on("click", function(p) {\n' +
    '  var info = document.getElementById("info");\n' +
    '  if (p.nodes.length) {\n' +
    '    var n = nodes.get(p.nodes[0]);\n' +
    '    var parts = n.title.split("<br>").filter(Boolean);\n' +
    '    info.innerHTML = "<h3>" + n.group + ": " + n.label + "</h3><div class=prop>" + parts.slice(1).join("</div><div class=prop>") + "</div>";\n' +
    '    info.classList.add("visible");\n' +
    '  } else { info.classList.remove("visible"); }\n' +
    '});\n' +
    'function toggleType(type, visible) {\n' +
    '  var list = nodes.get({ filter: function(n) { return n.group === type; } });\n' +
    '  nodes.update(list.map(function(n) { return { id: n.id, hidden: !visible }; }));\n' +
    '}\n' +
    '</script>\n</body>\n</html>\n';
}

module.exports = { generateVizHTML, NODE_COLORS, EDGE_COLORS };
