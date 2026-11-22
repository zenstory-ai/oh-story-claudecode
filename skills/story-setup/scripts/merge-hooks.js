#!/usr/bin/env node
"use strict";

// Unified hook configuration merger for story-setup across hosts:
//   --host claude      merge .claude/settings.local.json
//   --host codex       merge .codex/hooks.json
//   --host antigravity merge .agents/hooks.json (named-group schema)
//
// Only story-setup managed registrations (including legacy names for smooth
// upgrades) are replaced; unrelated user hooks and top-level settings survive.

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const HOSTS = Object.freeze(["claude", "codex", "antigravity"]);

const CLAUDE_MANAGED_HOOK_SCRIPTS = Object.freeze([
  "run-story-hook.sh",
  "check-prose-after-write.sh",
  "detect-story-gaps.sh",
  "guard-outline-before-prose.sh",
  "post-compact.sh",
  "pre-compact.sh",
  "session-end.sh",
  "session-start.sh",
  "validate-story-commit.sh",
]);

const CODEX_MANAGED_COMMAND_MARKERS = Object.freeze([
  ".codex/hooks/story_codex_hook.py",
  ".codex/hooks/story_codex_hook.js",
  ".codex/hooks/run-story-hook.sh",
  ".codex/hooks/run-story-hook.cmd",
]);

class MergeError extends Error {
  constructor(message) {
    super(message);
    this.name = "MergeError";
  }
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function deepClone(value) {
  return structuredClone(value);
}

function isClaudeStorySetupHook(hook) {
  if (!isPlainObject(hook) || typeof hook.command !== "string") {
    return false;
  }
  const normalized = hook.command.replace(/\\/g, "/");
  return CLAUDE_MANAGED_HOOK_SCRIPTS.some((name) => normalized.includes(`/.claude/hooks/${name}`));
}

function normalizedCommand(value) {
  return typeof value === "string" ? value.toLowerCase().replace(/\\/g, "/") : "";
}

function isCodexStorySetupHook(hook) {
  if (!isPlainObject(hook)) {
    return false;
  }
  const commands = [normalizedCommand(hook.command), normalizedCommand(hook.commandWindows)];
  return CODEX_MANAGED_COMMAND_MARKERS.some((marker) =>
    commands.some((command) => command.includes(marker))
  );
}

function requireHooks(document, label) {
  if (!isPlainObject(document)) {
    throw new MergeError(`${label} root must be a JSON object`);
  }
  const hooks = Object.prototype.hasOwnProperty.call(document, "hooks") ? document.hooks : {};
  if (!isPlainObject(hooks)) {
    throw new MergeError(`${label}.hooks must be a JSON object`);
  }
  return hooks;
}

function stripManagedRegistrations(hooks, isManagedHook) {
  const cleaned = {};
  for (const [event, rawBlocks] of Object.entries(hooks)) {
    if (!Array.isArray(rawBlocks)) {
      cleaned[event] = deepClone(rawBlocks);
      continue;
    }
    const blocks = [];
    for (const rawBlock of rawBlocks) {
      if (!isPlainObject(rawBlock) || !Array.isArray(rawBlock.hooks)) {
        blocks.push(deepClone(rawBlock));
        continue;
      }
      const keptHooks = rawBlock.hooks
        .filter((hook) => !isManagedHook(hook))
        .map((hook) => deepClone(hook));
      if (!keptHooks.length) {
        continue;
      }
      const block = deepClone(rawBlock);
      block.hooks = keptHooks;
      blocks.push(block);
    }
    if (blocks.length) {
      cleaned[event] = blocks;
    }
  }
  return cleaned;
}

function mergeHookMapDocuments(existing, template, isManagedHook) {
  const existingHooks = requireHooks(existing, "existing");
  const templateHooks = requireHooks(template, "template");
  for (const [event, blocks] of Object.entries(templateHooks)) {
    if (!Array.isArray(blocks)) {
      throw new MergeError(`template.hooks.${event} must be an array`);
    }
  }

  const result = deepClone(existing);
  const mergedHooks = stripManagedRegistrations(existingHooks, isManagedHook);
  for (const [event, blocks] of Object.entries(templateHooks)) {
    // 只在与模板事件撞名时要求用户侧是数组：未知事件的非数组值由
    // stripManagedRegistrations 原样保留（保留用户已有配置的契约），
    // 撞名却无法合并时给出 MergeError 诊断。
    if (Object.prototype.hasOwnProperty.call(mergedHooks, event) && !Array.isArray(mergedHooks[event])) {
      throw new MergeError(`existing.hooks.${event} must be an array`);
    }
    if (!Object.prototype.hasOwnProperty.call(mergedHooks, event)) {
      mergedHooks[event] = [];
    }
    mergedHooks[event].push(...deepClone(blocks));
  }
  result.hooks = mergedHooks;
  return result;
}

function mergeAntigravityDocuments(existing, template) {
  if (!isPlainObject(existing)) {
    throw new MergeError("expected a JSON object in existing");
  }
  if (!isPlainObject(template)) {
    throw new MergeError("expected a JSON object in template");
  }
  const managed = template["oh-story"];
  if (!isPlainObject(managed)) {
    throw new MergeError("template must contain an object-valued oh-story group");
  }
  const result = deepClone(existing);
  result["oh-story"] = deepClone(managed);
  return result;
}

function mergeDocuments(host, existing, template) {
  if (host === "claude") {
    return mergeHookMapDocuments(existing, template, isClaudeStorySetupHook);
  }
  if (host === "codex") {
    return mergeHookMapDocuments(existing, template, isCodexStorySetupHook);
  }
  if (host === "antigravity") {
    return mergeAntigravityDocuments(existing, template);
  }
  throw new MergeError(`unsupported host: ${host}`);
}

function readJson(filePath, { missingOk = false, requireObject = false } = {}) {
  if (missingOk && !fs.existsSync(filePath)) {
    return {};
  }
  let raw;
  try {
    raw = fs.readFileSync(filePath, "utf8").replace(/^\uFEFF/, "");
  } catch (err) {
    throw new MergeError(`unable to read ${filePath}: ${err.message || err}`);
  }
  let value;
  try {
    value = JSON.parse(raw);
  } catch (err) {
    throw new MergeError(`unable to read ${filePath}: ${err.message || err}`);
  }
  if (requireObject && !isPlainObject(value)) {
    throw new MergeError(`expected a JSON object in ${filePath}`);
  }
  return value;
}

function atomicWriteJson(filePath, document) {
  const dir = path.dirname(filePath);
  const base = path.basename(filePath);
  fs.mkdirSync(dir, { recursive: true });
  const mode = fs.existsSync(filePath) ? fs.statSync(filePath).mode & 0o777 : 0o644;
  const payload = JSON.stringify(document, null, 2) + "\n";
  const tmp = path.join(dir, `.${base}.${process.pid}.${crypto.randomBytes(6).toString("hex")}.tmp`);
  let fd = null;
  try {
    fd = fs.openSync(tmp, "wx", mode);
    fs.writeSync(fd, payload, 0, "utf8");
    fs.fsyncSync(fd);
    fs.closeSync(fd);
    fd = null;
    try {
      fs.chmodSync(tmp, mode);
    } catch (_) {
      // Ignore chmod quirks on Windows filesystems.
    }
    fs.renameSync(tmp, filePath);
  } finally {
    if (fd !== null) {
      try {
        fs.closeSync(fd);
      } catch (_) {}
    }
    try {
      fs.unlinkSync(tmp);
    } catch (_) {}
  }
}

function usage() {
  return (
    "usage:\n" +
    "  merge-hooks.js --host claude|codex --existing <path> --template <path> --output <path>\n" +
    "  merge-hooks.js --host antigravity --existing <path> --template <path> [--output <path>]\n" +
    "  merge-hooks.js --host antigravity <existing> <template>\n"
  );
}

function parseArgs(argv) {
  const opts = {};
  const positional = [];
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--host" || arg === "--existing" || arg === "--template" || arg === "--output") {
      const value = argv[++i];
      if (value === undefined) {
        process.stderr.write(`merge-hooks: ${arg} requires a value\n`);
        process.exit(2);
      }
      opts[arg.slice(2)] = value;
    } else if (arg === "-h" || arg === "--help") {
      process.stdout.write(usage());
      process.exit(0);
    } else if (arg.startsWith("-")) {
      process.stderr.write(`merge-hooks: unknown option: ${arg}\n`);
      process.exit(2);
    } else {
      positional.push(arg);
    }
  }

  if (!opts.host || !HOSTS.includes(opts.host)) {
    process.stderr.write(`merge-hooks: --host must be one of ${HOSTS.join(", ")}\n`);
    process.exit(2);
  }

  if (opts.host === "antigravity" && positional.length === 2 && !opts.existing && !opts.template) {
    opts.existing = positional[0];
    opts.template = positional[1];
    if (!opts.output) opts.output = opts.existing;
  } else if (positional.length > 0) {
    process.stderr.write(`merge-hooks: unexpected positional arguments: ${positional.join(" ")}\n`);
    process.exit(2);
  }

  if (opts.host === "antigravity" && !opts.output && opts.existing) {
    opts.output = opts.existing;
  }

  if (!opts.existing || !opts.template || !opts.output) {
    process.stderr.write(usage());
    process.exit(2);
  }

  return opts;
}

function main(argv = process.argv.slice(2)) {
  const args = parseArgs(argv);
  try {
    const requireObject = args.host === "antigravity";
    const existing = readJson(args.existing, { missingOk: true, requireObject });
    const template = readJson(args.template, { missingOk: false, requireObject });
    atomicWriteJson(args.output, mergeDocuments(args.host, existing, template));
    return 0;
  } catch (err) {
    if (err instanceof MergeError) {
      process.stderr.write(`ERROR: ${err.message}\n`);
      return 2;
    }
    process.stderr.write(`ERROR: ${err.message || err}\n`);
    return 2;
  }
}

if (require.main === module) {
  process.exit(main());
}

module.exports = {
  CLAUDE_MANAGED_HOOK_SCRIPTS,
  CODEX_MANAGED_COMMAND_MARKERS,
  HOSTS,
  MergeError,
  atomicWriteJson,
  isClaudeStorySetupHook,
  isCodexStorySetupHook,
  main,
  mergeAntigravityDocuments,
  mergeDocuments,
  mergeHookMapDocuments,
  readJson,
};
