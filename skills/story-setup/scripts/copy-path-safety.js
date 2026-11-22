#!/usr/bin/env node
"use strict";

// Classify a recursive deployment copy before any filesystem mutation,
// and optionally prune retired files in managed target directories.

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

function expandUser(rawPath) {
  const value = String(rawPath);
  if (value === "~") return os.homedir();
  if (value.startsWith("~/") || (process.platform === "win32" && value.startsWith("~\\"))) {
    return path.join(os.homedir(), value.slice(2));
  }
  return value;
}

function lstatSafe(targetPath) {
  try {
    return fs.lstatSync(targetPath);
  } catch (err) {
    if (err && (err.code === "ENOENT" || err.code === "ENOTDIR")) return null;
    throw err;
  }
}

function canonicalPath(rawPath) {
  let absPath = path.resolve(expandUser(rawPath));
  const parts = [];
  let cur = absPath;
  const seenLinks = new Set();

  while (true) {
    try {
      const real = fs.realpathSync(cur);
      return parts.length ? path.join(real, ...parts.reverse()) : real;
    } catch (err) {
      if (err && (err.code === "ENOENT" || err.code === "ENOTDIR")) {
        let lst = null;
        try {
          lst = fs.lstatSync(cur);
        } catch (_) {
          lst = null;
        }
        if (lst && lst.isSymbolicLink() && !seenLinks.has(cur)) {
          seenLinks.add(cur);
          try {
            const linkTarget = fs.readlinkSync(cur);
            cur = path.resolve(path.dirname(cur), linkTarget);
            continue;
          } catch (_) {
            // Fall through to walking up the parent.
          }
        }
        const parent = path.dirname(cur);
        if (parent === cur) {
          return parts.length ? path.join(cur, ...parts.reverse()) : cur;
        }
        parts.push(path.basename(cur));
        cur = parent;
        continue;
      }
      return absPath;
    }
  }
}

function statPath(targetPath) {
  try {
    const st = fs.statSync(targetPath, { bigint: true });
    return { exists: true, stat: st, error: null };
  } catch (err) {
    if (err && (err.code === "ENOENT" || err.code === "ENOTDIR")) {
      return { exists: false, stat: null, error: null };
    }
    return { exists: null, stat: null, error: err };
  }
}

function normCase(filePath) {
  if (process.platform === "win32") {
    return filePath.replace(/\//g, "\\").toLowerCase();
  }
  return filePath;
}

function isDescendant(targetPath, parentPath) {
  const pathKey = normCase(String(targetPath));
  const parentKey = normCase(String(parentPath));
  if (pathKey === parentKey) return false;
  const rel = path.relative(parentKey, pathKey);
  if (!rel) return false;
  if (rel === ".." || rel.startsWith(".." + path.sep) || path.isAbsolute(rel)) {
    return false;
  }
  return true;
}

const ops = {
  sameFile(source, target) {
    const s1 = fs.statSync(source, { bigint: true });
    const s2 = fs.statSync(target, { bigint: true });
    if (s1.ino !== 0n && s2.ino !== 0n) {
      return s1.dev === s2.dev && s1.ino === s2.ino;
    }
    return normCase(canonicalPath(source)) === normCase(canonicalPath(target));
  },
};

function classifyCopy(sourceRaw, targetRaw) {
  const source = canonicalPath(sourceRaw);
  const target = canonicalPath(targetRaw);
  const result = {
    copy_allowed: false,
    source_realpath: source,
    target_realpath: target,
  };

  const sourceStat = statPath(source);
  if (sourceStat.error !== null) {
    result.status = "filesystem_identity_error";
    result.error = String(sourceStat.error.message || sourceStat.error);
    return result;
  }
  if (!sourceStat.exists) {
    result.status = "source_missing";
    return result;
  }

  if (normCase(source) === normCase(target)) {
    result.status = "same";
    return result;
  }

  const targetStat = statPath(target);
  if (targetStat.error !== null) {
    result.status = "filesystem_identity_error";
    result.error = String(targetStat.error.message || targetStat.error);
    return result;
  }
  if (targetStat.exists) {
    let sameObject = false;
    try {
      sameObject = ops.sameFile(source, target);
    } catch (err) {
      result.status = "filesystem_identity_error";
      result.error = String(err.message || err);
      return result;
    }
    if (sameObject) {
      result.status = "same";
      return result;
    }
  }

  if (isDescendant(target, source)) {
    result.status = "unsafe_target_within_source";
    return result;
  }

  result.status = "safe";
  result.copy_allowed = true;
  return result;
}

function existsFollow(filePath) {
  try {
    fs.statSync(filePath);
    return true;
  } catch (_) {
    return false;
  }
}

function isRealDirFollow(filePath) {
  try {
    return fs.statSync(filePath).isDirectory();
  } catch (_) {
    return false;
  }
}

function isSymlink(filePath) {
  try {
    return fs.lstatSync(filePath).isSymbolicLink();
  } catch (_) {
    return false;
  }
}

function unlinkSymlink(targetPath) {
  try {
    fs.unlinkSync(targetPath);
  } catch (err) {
    if (err && (err.code === "EPERM" || err.code === "EISDIR")) {
      fs.rmdirSync(targetPath);
      return;
    }
    throw err;
  }
}

function walkAndPrune(curDir, sourceRoot, targetRoot, pruned) {
  const entries = fs.readdirSync(curDir, { withFileTypes: true });
  for (const entry of entries) {
    const tEntry = path.join(curDir, entry.name);
    const relOs = path.relative(targetRoot, tEntry);
    const relPosix = relOs.split(path.sep).join("/");
    const sEntry = path.join(sourceRoot, relOs);

    if (entry.isSymbolicLink()) {
      const targetPointsToDir = isRealDirFollow(tEntry);
      if (targetPointsToDir) {
        if (!existsFollow(sEntry)) {
          unlinkSymlink(tEntry);
          pruned.push(relPosix);
        }
      } else if (!existsFollow(sEntry) || (isRealDirFollow(sEntry) && !isSymlink(sEntry))) {
        unlinkSymlink(tEntry);
        pruned.push(relPosix);
      }
    } else if (entry.isDirectory()) {
      walkAndPrune(tEntry, sourceRoot, targetRoot, pruned);
      if (!isRealDirFollow(sEntry) || isSymlink(sEntry)) {
        try {
          fs.rmdirSync(tEntry);
          pruned.push(relPosix + "/");
        } catch (_) {
          // Non-empty directory or permission issue; leave intact.
        }
      }
    } else {
      if (!existsFollow(sEntry) || (isRealDirFollow(sEntry) && !isSymlink(sEntry))) {
        fs.unlinkSync(tEntry);
        pruned.push(relPosix);
      }
    }
  }
}

function pruneOrphans(sourceRaw, targetRaw) {
  const rawTarget = path.resolve(expandUser(targetRaw));
  const result = classifyCopy(sourceRaw, targetRaw);
  result.pruned = [];
  if (result.status !== "safe" || !result.copy_allowed) {
    return result;
  }
  if (isSymlink(rawTarget)) {
    result.status = "unsafe_target_symlink";
    result.copy_allowed = false;
    return result;
  }

  const source = String(result.source_realpath);
  const target = String(result.target_realpath);
  if (!isRealDirFollow(source) || !existsFollow(target) || !isRealDirFollow(target) || isSymlink(target)) {
    return result;
  }

  const pruned = [];
  walkAndPrune(target, source, target, pruned);
  pruned.sort();
  result.pruned = pruned;
  return result;
}

function statusExitCode(status) {
  return status === "safe" || status === "same" ? 0 : 2;
}

function sortObjectKeys(obj) {
  const sorted = {};
  for (const key of Object.keys(obj).sort()) {
    sorted[key] = obj[key];
  }
  return sorted;
}

class CliUsageError extends Error {
  constructor(message) {
    super(message);
    this.name = "CliUsageError";
  }
}

const USAGE = "usage: copy-path-safety.js [--prune-orphans] <source> <target>\n";

function parseArgs(argv) {
  let doPrune = false;
  const positional = [];
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--prune-orphans") {
      doPrune = true;
    } else if (arg === "-h" || arg === "--help") {
      return { help: true };
    } else if (arg === "--") {
      positional.push(...argv.slice(i + 1));
      break;
    } else if (arg.startsWith("-")) {
      throw new CliUsageError(`copy-path-safety: unknown option: ${arg}\n`);
    } else {
      positional.push(arg);
    }
  }
  if (positional.length !== 2) {
    throw new CliUsageError(USAGE);
  }
  return { help: false, pruneOrphans: doPrune, source: positional[0], target: positional[1] };
}

function main(argv = process.argv.slice(2)) {
  let args;
  try {
    args = parseArgs(argv);
  } catch (err) {
    if (err instanceof CliUsageError) {
      process.stderr.write(err.message);
      return 2;
    }
    throw err;
  }
  if (args.help) {
    process.stdout.write(USAGE);
    return 0;
  }
  const result = args.pruneOrphans
    ? pruneOrphans(args.source, args.target)
    : classifyCopy(args.source, args.target);
  process.stdout.write(JSON.stringify(sortObjectKeys(result)) + "\n");
  return statusExitCode(String(result.status));
}

if (require.main === module) {
  process.exit(main());
}

module.exports = {
  canonicalPath,
  classifyCopy,
  isDescendant,
  main,
  ops,
  pruneOrphans,
  statPath,
  statusExitCode,
};
