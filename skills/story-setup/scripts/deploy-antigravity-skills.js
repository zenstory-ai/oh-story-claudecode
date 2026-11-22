#!/usr/bin/env node
"use strict";

// Materialize oh-story skills into a project-local Antigravity skill root.
//
// Only the 14 known oh-story directories are replaced. Unknown user skills are
// preserved. An existing `.agents/skills` symlink is never followed for writes;
// it can be materialized only after the caller explicitly opts in.

const fs = require("node:fs");
const path = require("node:path");

const KNOWN_SKILLS = Object.freeze([
  "browser-cdp",
  "story",
  "story-cover",
  "story-deslop",
  "story-import",
  "story-long-analyze",
  "story-long-scan",
  "story-long-write",
  "story-publish",
  "story-review",
  "story-setup",
  "story-short-analyze",
  "story-short-scan",
  "story-short-write",
]);

class DeployError extends Error {
  constructor(message) {
    super(message);
    this.name = "DeployError";
  }
}

function lstatSafe(targetPath) {
  try {
    return fs.lstatSync(targetPath);
  } catch (err) {
    if (err && (err.code === "ENOENT" || err.code === "ENOTDIR")) return null;
    throw err;
  }
}

function statSafe(targetPath) {
  try {
    return fs.statSync(targetPath, { bigint: true });
  } catch (err) {
    if (err && (err.code === "ENOENT" || err.code === "ENOTDIR")) return null;
    throw err;
  }
}

function sameFile(a, b) {
  const s1 = statSafe(a);
  const s2 = statSafe(b);
  if (!s1 || !s2) return false;
  if (s1.ino !== 0n && s2.ino !== 0n) {
    return s1.dev === s2.dev && s1.ino === s2.ino;
  }
  return fs.realpathSync(a) === fs.realpathSync(b);
}

function symlinkTypeForTarget(sourcePath) {
  if (process.platform !== "win32") return undefined;
  const st = statSafe(sourcePath);
  return st && st.isDirectory() ? "dir" : "file";
}

function copyEntry(source, destination, { dereference }) {
  const lstat = fs.lstatSync(source);
  if (lstat.isSymbolicLink() && !dereference) {
    const linkTarget = fs.readlinkSync(source);
    fs.symlinkSync(linkTarget, destination, symlinkTypeForTarget(source));
    return;
  }

  const stat = dereference ? fs.statSync(source) : lstat;
  if (stat.isDirectory()) {
    fs.mkdirSync(destination, { recursive: true });
    for (const entry of fs.readdirSync(source)) {
      copyEntry(path.join(source, entry), path.join(destination, entry), { dereference });
    }
    try {
      fs.chmodSync(destination, stat.mode & 0o777);
    } catch (_) {
      // Ignore chmod quirks on Windows filesystems.
    }
    return;
  }

  fs.copyFileSync(source, destination);
  try {
    fs.chmodSync(destination, stat.mode & 0o777);
  } catch (_) {
    // Ignore chmod quirks on Windows filesystems.
  }
  try {
    fs.utimesSync(destination, stat.atime, stat.mtime);
  } catch (_) {
    // Ignore timestamp preservation failures on restricted filesystems.
  }
}

function validateSource(source) {
  const rootStat = statSafe(source);
  if (!rootStat || !rootStat.isDirectory()) {
    throw new DeployError(`source skill root is missing: ${source}`);
  }
  for (const name of KNOWN_SKILLS) {
    const skillDir = path.join(source, name);
    const dirStat = statSafe(skillDir);
    const skillMdStat = statSafe(path.join(skillDir, "SKILL.md"));
    if (!dirStat || !dirStat.isDirectory() || !skillMdStat || !skillMdStat.isFile()) {
      throw new DeployError(`source skill is incomplete: ${skillDir}`);
    }
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

function removeEntry(targetPath) {
  const lst = lstatSafe(targetPath);
  if (!lst) return;
  if (lst.isDirectory() && !lst.isSymbolicLink()) {
    fs.rmSync(targetPath, { recursive: true, force: true });
  } else if (lst.isSymbolicLink()) {
    unlinkSymlink(targetPath);
  } else {
    fs.unlinkSync(targetPath);
  }
}

function deploy(sourceRaw, destinationRaw, { migrateSymlink = false } = {}) {
  const sourceResolvedPath = path.resolve(String(sourceRaw));
  let source;
  try {
    source = fs.realpathSync(sourceResolvedPath);
  } catch (err) {
    if (err && (err.code === "ENOENT" || err.code === "ENOTDIR")) {
      throw new DeployError(`source skill root is missing: ${sourceResolvedPath}`);
    }
    throw err;
  }
  validateSource(source);

  const destination = path.resolve(String(destinationRaw));
  const destLstat = lstatSafe(destination);
  const destIsSymlink = Boolean(destLstat && destLstat.isSymbolicLink());
  const destStat = statSafe(destination);

  if (destStat && !destIsSymlink && sameFile(destination, source)) {
    return "same-object no-op";
  }
  if (destIsSymlink && !migrateSymlink) {
    throw new DeployError(
      `destination is a symlink: ${destination}; rerun only after explicit symlink migration approval`
    );
  }
  if (destStat && !destStat.isDirectory()) {
    throw new DeployError(`destination must be a directory: ${destination}`);
  }

  const destParent = path.dirname(destination);
  const destName = path.basename(destination);
  fs.mkdirSync(destParent, { recursive: true });
  const staging = fs.mkdtempSync(path.join(destParent, `.${destName}.staging-`));
  const backup = path.join(destParent, `${destName}.backup-${process.pid}`);
  const originalLink = destIsSymlink ? fs.readlinkSync(destination) : null;

  let existingRoot = destination;
  if (destIsSymlink) {
    try {
      existingRoot = fs.realpathSync(destination);
    } catch (err) {
      if (err && (err.code === "ENOENT" || err.code === "ENOTDIR")) {
        existingRoot = null;
      } else {
        throw err;
      }
    }
  }

  let movedExisting = false;
  try {
    if (existingRoot !== null) {
      const existingStat = statSafe(existingRoot);
      if (existingStat) {
        if (!existingStat.isDirectory()) {
          throw new DeployError(`symlink target must be a directory: ${existingRoot}`);
        }
        for (const entry of fs.readdirSync(existingRoot)) {
          copyEntry(path.join(existingRoot, entry), path.join(staging, entry), {
            dereference: false,
          });
        }
      }
    }

    for (const name of KNOWN_SKILLS) {
      const target = path.join(staging, name);
      removeEntry(target);
      copyEntry(path.join(source, name), target, { dereference: true });
    }

    if (lstatSafe(backup) !== null) {
      throw new DeployError(`stale deployment backup exists: ${backup}`);
    }
    if (destIsSymlink) {
      unlinkSymlink(destination);
    } else if (destStat !== null) {
      fs.renameSync(destination, backup);
      movedExisting = true;
    }
    fs.renameSync(staging, destination);
    if (movedExisting) {
      fs.rmSync(backup, { recursive: true, force: true });
    }
    return "materialized";
  } catch (err) {
    if (lstatSafe(destination) === null) {
      if (movedExisting && lstatSafe(backup) !== null) {
        fs.renameSync(backup, destination);
      } else if (originalLink !== null) {
        fs.symlinkSync(
          originalLink,
          destination,
          process.platform === "win32" ? "dir" : undefined
        );
      }
    }
    throw err;
  } finally {
    if (lstatSafe(staging) !== null) {
      fs.rmSync(staging, { recursive: true, force: true });
    }
    if (movedExisting && lstatSafe(destination) !== null && lstatSafe(backup) !== null) {
      fs.rmSync(backup, { recursive: true, force: true });
    }
  }
}

class CliUsageError extends Error {
  constructor(message) {
    super(message);
    this.name = "CliUsageError";
  }
}

const USAGE = "usage: deploy-antigravity-skills.js --source <dir> --dest <dir> [--migrate-symlink]\n";

function parseArgs(argv) {
  let source = null;
  let dest = null;
  let migrateSymlink = false;
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--source" || arg.startsWith("--source=")) {
      const value = arg.startsWith("--source=") ? arg.slice("--source=".length) : argv[++i];
      if (value === undefined) {
        throw new CliUsageError("deploy-antigravity-skills: --source requires a value\n");
      }
      source = value;
    } else if (arg === "--dest" || arg.startsWith("--dest=")) {
      const value = arg.startsWith("--dest=") ? arg.slice("--dest=".length) : argv[++i];
      if (value === undefined) {
        throw new CliUsageError("deploy-antigravity-skills: --dest requires a value\n");
      }
      dest = value;
    } else if (arg === "--migrate-symlink") {
      migrateSymlink = true;
    } else if (arg === "-h" || arg === "--help") {
      return { help: true };
    } else {
      throw new CliUsageError(`deploy-antigravity-skills: unknown argument: ${arg}\n`);
    }
  }
  if (!source || !dest) {
    throw new CliUsageError(USAGE);
  }
  return { help: false, source, dest, migrateSymlink };
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
  try {
    const status = deploy(args.source, args.dest, { migrateSymlink: args.migrateSymlink });
    process.stdout.write(status + "\n");
    return 0;
  } catch (err) {
    process.stderr.write(`ERROR: ${err.message || err}\n`);
    return 1;
  }
}

if (require.main === module) {
  process.exit(main());
}

module.exports = {
  DeployError,
  KNOWN_SKILLS,
  deploy,
  main,
  validateSource,
};
