#!/usr/bin/env node
"use strict"

// Generate Antigravity 2.0 Markdown agents from the Claude Markdown source of
// truth. Antigravity and Claude both use Markdown bodies, but their frontmatter,
// tool names, model tiers, and deployed reference roots differ.

import fs from "node:fs"
import path from "node:path"
import process from "node:process"
import { fileURLToPath } from "node:url"

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url))
const DEFAULT_SOURCE = path.resolve(SCRIPT_DIR, "../references/templates/agents")
const DEFAULT_DEST = path.resolve(SCRIPT_DIR, "../references/antigravity/agents")

const TOOL_MAP = new Map([
  ["Read", ["view_file"]],
  ["Glob", ["find_by_name"]],
  ["Grep", ["grep_search"]],
  ["Write", ["write_to_file"]],
  ["Edit", ["replace_file_content", "multi_replace_file_content"]],
  ["Bash", ["run_command"]],
])
const CAPABILITY_FIELDS = new Set(["tools", "disallowedTools"])
const CAPABILITY_NAME_RE = /^[A-Za-z][A-Za-z0-9_-]*$/

function fail(message) {
  process.stderr.write(`generate-antigravity-agents: ${message}\n`)
  process.exit(2)
}

function parseArgs(argv) {
  const result = { source: DEFAULT_SOURCE, dest: DEFAULT_DEST }
  for (let index = 0; index < argv.length; index++) {
    const token = argv[index]
    if (token === "--source" || token === "--dest") {
      const value = argv[++index]
      if (!value) fail(`${token} requires a path`)
      result[token.slice(2)] = path.resolve(value)
    } else {
      fail(`unknown argument: ${token}`)
    }
  }
  return result
}

function parseFrontmatter(text, source) {
  if (!text.startsWith("---\n")) fail(`${source}: missing frontmatter`)
  const end = text.indexOf("\n---\n", 4)
  if (end < 0) fail(`${source}: unterminated frontmatter`)
  const raw = text.slice(4, end)
  const body = text.slice(end + 5).replace(/^\s+/, "")
  const data = {}
  const lines = raw.split(/\r?\n/)
  for (let index = 0; index < lines.length; index++) {
    const match = lines[index].match(/^([A-Za-z_][A-Za-z0-9_-]*):(?:\s*(.*))?$/)
    if (!match) continue
    const [, key, rawValue = ""] = match
    if (rawValue.trim() === "|") {
      const block = []
      while (index + 1 < lines.length && /^(?:\s|$)/.test(lines[index + 1])) {
        const line = lines[++index]
        block.push(line.startsWith("  ") ? line.slice(2) : line.trimStart())
      }
      data[key] = block.join("\n").trim()
    } else {
      const value = rawValue.trim()
      data[key] = CAPABILITY_FIELDS.has(key)
        ? value
        : value.replace(/^['"]|['"]$/g, "")
    }
  }
  return { data, body }
}

function parseCapabilityList(value, field, source) {
  if (value === undefined) return []
  if (!value) fail(`${source}: ${field}: empty or block-style capability declarations are unsupported`)
  const match = String(value).match(/^\[\s*(.*?)\s*\]$/)
  if (!match) fail(`${source}: ${field}: expected an inline list like [Read, Glob]`)
  if (!match[1].trim()) return []
  return match[1].split(",").map((rawItem) => {
    let item = rawItem.trim()
    if (!item) fail(`${source}: ${field}: empty capability-list item`)
    if (item[0] === '"' || item[0] === "'") {
      const quote = item[0]
      if (item.length < 2 || item.at(-1) !== quote || item.slice(1, -1).includes(quote)) {
        fail(`${source}: ${field}: malformed quoted capability ${JSON.stringify(item)}`)
      }
      item = item.slice(1, -1)
    } else if (item.includes('"') || item.includes("'")) {
      fail(`${source}: ${field}: malformed quoted capability ${JSON.stringify(item)}`)
    }
    if (!CAPABILITY_NAME_RE.test(item)) {
      fail(`${source}: ${field}: invalid capability name ${JSON.stringify(item)}`)
    }
    if (!TOOL_MAP.has(item)) {
      fail(`${source}: ${field}: unsupported Antigravity capability ${JSON.stringify(item)}`)
    }
    return item
  })
}

function parseInlineList(value) {
  const match = String(value || "").match(/^\[(.*)\]$/)
  if (!match) return []
  return match[1].split(",").map((item) => item.trim().replace(/^['"]|['"]$/g, "")).filter(Boolean)
}

function adaptBody(body, name, tools) {
  let adapted = body
    .replaceAll(".claude/skills/story-setup/references/agent-references/", ".agents/skills/story-setup/references/agent-references/")
    .replaceAll("当前 Claude 部署", "当前 Antigravity 部署")
    .replaceAll("Claude Code subagent", "Antigravity custom subagent")
    .replaceAll("subagent_type", "TypeName")

  for (const [source, targets] of TOOL_MAP) {
    adapted = adapted.replace(new RegExp(`\\b${source}\\b`, "g"), targets.join("/"))
  }

  if (!tools.includes("run_command")) {
    adapted = adapted.replace(
      "**确定项目根目录：** 执行 `git rev-parse --show-toplevel`，失败则用当前工作目录。以下所有路径均为项目根下的绝对路径。",
      "**确定项目根目录：** 直接使用宿主交给你的当前工作区/项目根；不要执行 shell。以下所有路径均从该根目录解析。",
    )
  }

  if (name === "story-researcher") {
    adapted = adapted
      .replace("WebSearch/webReader 作为兜底。", "CDP 不可用时返回结构化缺口，由父会话完成联网检索。")
      .replace("**核心原则：CDP 优先，WebSearch 兜底。**", "**核心原则：只在 CDP 可用时研究；否则交回父会话。**")
      .replace("CDP 能打开真实页面拿到完整正文；WebSearch 只返回摘要节选，信息量远不如全文。", "Antigravity custom subagent 只通过 `run_command` 使用 CDP；不假定存在额外联网工具。")
      .replace("3. WebSearch / webReader → 兜底（CDP 不可用或页面打不开时）", "3. CDP 不可用或页面打不开 → 返回结构化 research gap，由父会话继续")
      .replaceAll("直接降级到 WebSearch/webReader", "返回结构化 research gap，由父会话继续")
      .replaceAll("降级到 WebSearch/webReader 兜底", "返回结构化 research gap，由父会话继续")
      .replaceAll("降级到 WebSearch", "返回结构化 research gap，由父会话继续")
      .replace(
        /### 第四步：WebSearch\/webReader（兜底）[\s\S]*?(?=\n### 第五步：整理输出)/,
        "### 第四步：CDP 不可用时交回父会话\n\n返回 `status: \"failed\"`，在 `gaps` 中说明 CDP 不可用或页面提取失败，并给出建议检索词与候选来源类型。不要自行声称已调用联网兜底，也不要编造内容。\n",
      )
      .replace("{google | bing | websearch}", "{google | bing}")
  }

  const researchNote = name === "story-researcher"
    ? "- This custom subagent has no WebSearch/webReader tool. Prefer CDP through `run_command`; if CDP is unavailable, return a structured research gap to the parent agent and never claim that web fallback ran.\n"
    : ""

  return `${adapted.trimEnd()}\n\n---\n\nAntigravity adaptation notes:\n` +
    `- Call this agent through \`invoke_subagent\` with \`TypeName: "${name}"\`.\n` +
    "- If the Antigravity runtime does not expose custom subagents, fall back to solo/direct execution and report the fallback.\n" +
    "- Stay within this agent's role boundary; return adjacent work to the parent agent.\n" +
    "- Use only `.agents/skills/story-setup/references/agent-references/`; if it is missing, report an incomplete deployment instead of probing other CLI roots.\n" +
    "- Antigravity tool names and frontmatter are authoritative; do not assume Claude-only fields exist.\n" +
    researchNote
}

function renderAgent(sourceFile) {
  const text = fs.readFileSync(sourceFile, "utf8")
  const { data, body } = parseFrontmatter(text, sourceFile)
  const name = data.name || path.basename(sourceFile, ".md")
  if (name !== path.basename(sourceFile, ".md") || !/^[A-Za-z0-9][A-Za-z0-9_-]*$/.test(name)) {
    fail(`${sourceFile}: unsafe or mismatched agent name ${JSON.stringify(name)}`)
  }
  if (!data.description) fail(`${sourceFile}: missing description`)
  if (data.tools === undefined) fail(`${sourceFile}: tools: Antigravity requires an explicit tool list`)
  const sourceTools = parseCapabilityList(data.tools, "tools", sourceFile)
  const deniedTools = new Set(parseCapabilityList(data.disallowedTools, "disallowedTools", sourceFile))
  const effectiveSourceTools = sourceTools.filter((tool) => !deniedTools.has(tool))
  const tools = [...new Set(effectiveSourceTools.flatMap((tool) => TOOL_MAP.get(tool)))]
  if (!tools.length) fail(`${sourceFile}: no supported Antigravity tools mapped`)
  const sourceModel = String(data.model || "").toLowerCase()
  const model = sourceModel === "haiku" ? "flash" : "pro"
  const sourceSkills = parseInlineList(data.skills)
  const description = name === "story-researcher"
    ? String(data.description).replace("WebSearch/webReader 作为兜底", "CDP 不可用时返回缺口，由父会话联网检索")
    : String(data.description)

  const frontmatter = [
    "---",
    `name: ${name}`,
    "description: |",
    ...description.split("\n").map((line) => `  ${line}`),
    "tools:",
    ...tools.map((tool) => `  - ${tool}`),
    "mainAgent: false",
    "subagent: true",
    `model: ${model}`,
    "commandExecutionPolicy: sandbox",
  ]
  if (sourceSkills.length) {
    frontmatter.push("skills:", ...sourceSkills.map((skill) => `  - skills/${skill}`))
  }
  frontmatter.push("---", "")
  return `${frontmatter.join("\n")}\n${adaptBody(body, name, tools)}`
}

function prepareManagedDirectory(target) {
  try {
    const info = fs.lstatSync(target)
    if (info.isSymbolicLink() || !info.isDirectory()) {
      fs.rmSync(target, { recursive: true, force: true })
    }
  } catch (error) {
    if (error?.code !== "ENOENT") throw error
  }
  fs.mkdirSync(target, { recursive: true })
}

function publish(rendered, destination) {
  if (fs.existsSync(destination) && fs.lstatSync(destination).isSymbolicLink()) {
    fail(`destination directory must not be a symlink: ${destination}`)
  }
  if (fs.existsSync(destination) && !fs.statSync(destination).isDirectory()) {
    fail(`destination must be a directory: ${destination}`)
  }
  fs.mkdirSync(path.dirname(destination), { recursive: true })
  const staging = fs.mkdtempSync(path.join(path.dirname(destination), `.${path.basename(destination)}.staging-`))
  const existed = fs.existsSync(destination)
  const replacement = `${destination}.replacement-${process.pid}`
  const backup = `${destination}.backup-${process.pid}`
  try {
    if (existed) {
      for (const entry of fs.readdirSync(destination)) {
        fs.cpSync(path.join(destination, entry), path.join(staging, entry), { recursive: true, force: true })
      }
    }
    for (const [relative, content] of rendered) {
      const name = relative.split(path.sep)[0]
      fs.rmSync(path.join(staging, `${name}.md`), { recursive: true, force: true })
      const agentDir = path.join(staging, name)
      prepareManagedDirectory(agentDir)
      const target = path.join(staging, relative)
      fs.rmSync(target, { recursive: true, force: true })
      fs.writeFileSync(target, content, "utf8")
    }
    fs.rmSync(replacement, { recursive: true, force: true })
    fs.rmSync(backup, { recursive: true, force: true })
    fs.renameSync(staging, replacement)
    if (existed) fs.renameSync(destination, backup)
    fs.renameSync(replacement, destination)
    fs.rmSync(backup, { recursive: true, force: true })
  } catch (error) {
    if (!fs.existsSync(destination) && fs.existsSync(backup)) fs.renameSync(backup, destination)
    throw error
  } finally {
    fs.rmSync(staging, { recursive: true, force: true })
    fs.rmSync(replacement, { recursive: true, force: true })
    fs.rmSync(backup, { recursive: true, force: true })
  }
}

function main() {
  const { source, dest } = parseArgs(process.argv.slice(2))
  if (!fs.existsSync(source) || !fs.statSync(source).isDirectory()) fail(`source directory missing: ${source}`)
  const sources = fs.readdirSync(source).filter((name) => name.endsWith(".md")).sort()
  if (!sources.length) fail(`source directory contains no Markdown agents: ${source}`)
  const rendered = new Map(sources.map((filename) => [
    path.join(path.basename(filename, ".md"), "agent.md"),
    renderAgent(path.join(source, filename)),
  ]))
  publish(rendered, dest)
  process.stdout.write(`Generated ${rendered.size} Antigravity agents in ${dest}\n`)
}

main()
