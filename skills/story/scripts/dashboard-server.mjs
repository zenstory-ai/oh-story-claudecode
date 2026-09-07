#!/usr/bin/env node

import { spawn } from "node:child_process";
import { realpathSync } from "node:fs";
import { createServer } from "node:http";
import {
  chmod,
  copyFile,
  lstat,
  readFile,
  readdir,
  realpath,
  rename,
  stat,
  unlink,
  writeFile,
} from "node:fs/promises";
import { extname, basename, dirname, isAbsolute, relative, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createHash, randomUUID } from "node:crypto";

const MODULE_PATH = fileURLToPath(import.meta.url);
const ASSET_DIR = fileURLToPath(new URL("../assets/", import.meta.url));
const EDITABLE_EXTENSIONS = new Set([".md", ".txt", ".json", ".yaml", ".yml", ".toml"]);
const LONG_PROJECT_DIRECTORY_MARKERS = new Set(["正文", "大纲", "设定", "追踪"]);
const SHORT_PROJECT_BODY_FILE = "正文.md";
const SHORT_PROJECT_COMPANION_FILES = new Set(["小节大纲.md", "设定.md"]);
const IGNORED_DIRECTORIES = new Set([
  ".git",
  ".omc",
  ".omx",
  ".claude",
  ".codex",
  ".opencode",
  ".zcode",
  ".agents",
  "node_modules",
  "test-results",
  "playwright-report",
  "__pycache__",
]);
const MAX_FILE_BYTES = 2 * 1024 * 1024;
const MAX_REQUEST_BYTES = MAX_FILE_BYTES + 64 * 1024;
const DIRECTORY_PAGE_SIZE = 200;
const MAX_SEARCH_RESULTS = 100;
const MAX_SEARCH_NODES = 5000;
const MAX_SEARCH_DEPTH = 20;
const LOOPBACK_HOSTS = new Set(["127.0.0.1", "::1", "localhost"]);
const FILE_MUTATION_TAILS = new Map();

const CONTENT_TYPES = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml; charset=utf-8",
};

export class DashboardError extends Error {
  constructor(status, code, message) {
    super(message);
    this.name = "DashboardError";
    this.status = status;
    this.code = code;
  }
}

function isPathInside(candidate, root) {
  const relation = relative(root, candidate);
  return relation === "" || (!relation.startsWith(`..${sep}`) && relation !== ".." && !isAbsolute(relation));
}

function toPosixPath(value) {
  return value.split(sep).join("/");
}

function isEditableFile(name) {
  return EDITABLE_EXTENSIONS.has(extname(name).toLowerCase());
}

function fileVersion(content) {
  return createHash("sha256").update(content, "utf8").digest("hex");
}

async function withSerializedFileMutation(absolutePath, operation) {
  const previous = FILE_MUTATION_TAILS.get(absolutePath) || Promise.resolve();
  let release;
  const gate = new Promise((accept) => {
    release = accept;
  });
  const tail = previous.catch(() => {}).then(() => gate);
  FILE_MUTATION_TAILS.set(absolutePath, tail);
  await previous.catch(() => {});
  try {
    return await operation();
  } finally {
    release();
    if (FILE_MUTATION_TAILS.get(absolutePath) === tail) {
      FILE_MUTATION_TAILS.delete(absolutePath);
    }
  }
}

function recordScanError(scanErrors, root, absolutePath, error) {
  const errorPath = toPosixPath(relative(root, absolutePath)) || ".";
  if (scanErrors.some((entry) => entry.path === errorPath)) {
    return;
  }
  scanErrors.push({
    path: errorPath,
    code: typeof error?.code === "string" ? error.code : "READ_ERROR",
    message: `目录无法读取，请检查访问权限或挂载状态：${errorPath}`,
  });
}

function shouldIgnoreDirectory(name) {
  return IGNORED_DIRECTORIES.has(name) || (name.startsWith(".") && name !== ".story");
}

function compareTreeEntries(left, right) {
  if (left.type !== right.type) {
    return left.type === "directory" ? -1 : 1;
  }
  return left.name.localeCompare(right.name, "zh-CN", { numeric: true, sensitivity: "base" });
}

async function existingRealRoot(root) {
  const absolute = resolve(root);
  const info = await stat(absolute).catch(() => null);
  if (!info?.isDirectory()) {
    throw new DashboardError(400, "invalid_workspace", `工作区不存在或不是目录：${absolute}`);
  }
  return realpath(absolute);
}

export async function resolveWorkspacePath(root, requestedPath, options = {}) {
  const { editableOnly = false } = options;
  if (typeof requestedPath !== "string" || requestedPath.length === 0) {
    throw new DashboardError(400, "invalid_path", "文件路径不能为空");
  }
  if (
    requestedPath.includes("\0") ||
    isAbsolute(requestedPath) ||
    /^[A-Za-z]:[\\/]/.test(requestedPath)
  ) {
    throw new DashboardError(403, "path_outside_workspace", "只允许访问工作区内的相对路径");
  }

  const realRoot = await existingRealRoot(root);
  const candidate = resolve(realRoot, requestedPath);
  if (!isPathInside(candidate, realRoot)) {
    throw new DashboardError(403, "path_outside_workspace", "路径超出工作区");
  }

  const info = await lstat(candidate).catch((error) => {
    if (error?.code === "ENOENT") {
      throw new DashboardError(404, "file_not_found", "文件不存在");
    }
    throw error;
  });
  if (info.isSymbolicLink()) {
    throw new DashboardError(403, "symlink_not_editable", "Dashboard 不读写符号链接文件");
  }
  if (!info.isFile()) {
    throw new DashboardError(400, "not_a_file", "目标不是普通文件");
  }

  const resolvedFile = await realpath(candidate);
  if (!isPathInside(resolvedFile, realRoot)) {
    throw new DashboardError(403, "path_outside_workspace", "符号链接指向工作区外部");
  }
  if (editableOnly && !isEditableFile(candidate)) {
    throw new DashboardError(415, "unsupported_file_type", "该文件类型不支持在线编辑");
  }

  return { absolutePath: candidate, realRoot, info };
}

function directoryNode(absolutePath, relativePath) {
  return {
    name: basename(absolutePath),
    path: relativePath ? toPosixPath(relativePath) : ".",
    type: "directory",
    children: [],
    loaded: false,
  };
}

function assertRelativeWorkspacePath(requestedPath, label = "路径") {
  if (typeof requestedPath !== "string" || requestedPath.length === 0) {
    throw new DashboardError(400, "invalid_path", `${label}不能为空`);
  }
  if (
    requestedPath.includes("\0") ||
    isAbsolute(requestedPath) ||
    /^[A-Za-z]:[\\/]/.test(requestedPath)
  ) {
    throw new DashboardError(403, "path_outside_workspace", "只允许访问工作区内的相对路径");
  }
}

export async function resolveWorkspaceDirectory(root, requestedPath) {
  assertRelativeWorkspacePath(requestedPath, "目录路径");
  const realRoot = await existingRealRoot(root);
  const candidate = resolve(realRoot, requestedPath);
  if (!isPathInside(candidate, realRoot)) {
    throw new DashboardError(403, "path_outside_workspace", "路径超出工作区");
  }
  if (
    requestedPath !== "." &&
    requestedPath.split(/[\\/]+/).some((segment) => shouldIgnoreDirectory(segment))
  ) {
    throw new DashboardError(403, "directory_hidden", "该目录不会显示在 Dashboard 中");
  }

  const info = await lstat(candidate).catch((error) => {
    if (error?.code === "ENOENT") {
      throw new DashboardError(404, "directory_not_found", "目录不存在");
    }
    throw error;
  });
  if (info.isSymbolicLink()) {
    throw new DashboardError(403, "symlink_not_readable", "Dashboard 不读取符号链接目录");
  }
  if (!info.isDirectory()) {
    throw new DashboardError(400, "not_a_directory", "目标不是目录");
  }

  const resolvedDirectory = await realpath(candidate);
  if (!isPathInside(resolvedDirectory, realRoot)) {
    throw new DashboardError(403, "path_outside_workspace", "符号链接指向工作区外部");
  }
  return { absolutePath: candidate, realRoot };
}

function parseDirectoryCursor(value) {
  if (value === null || value === "") return 0;
  if (!/^\d+$/.test(value)) {
    throw new DashboardError(400, "invalid_cursor", "目录游标无效");
  }
  const cursor = Number(value);
  if (!Number.isSafeInteger(cursor)) {
    throw new DashboardError(400, "invalid_cursor", "目录游标无效");
  }
  return cursor;
}

function visibleDirectoryEntries(entries) {
  return entries
    .filter(
      (entry) =>
        !entry.isSymbolicLink() &&
        (!entry.isDirectory() || !shouldIgnoreDirectory(entry.name)),
    )
    .sort((left, right) =>
      compareTreeEntries(
        { name: left.name, type: left.isDirectory() ? "directory" : "file" },
        { name: right.name, type: right.isDirectory() ? "directory" : "file" },
      ),
    );
}

export async function listWorkspaceDirectory(root, requestedPath, cursorValue = null) {
  const { absolutePath, realRoot } = await resolveWorkspaceDirectory(root, requestedPath);
  const cursor = parseDirectoryCursor(cursorValue);
  const entries = await readdir(absolutePath, { withFileTypes: true }).catch(() => {
    throw new DashboardError(
      403,
      "directory_unreadable",
      `目录无法读取，请检查访问权限或挂载状态：${toPosixPath(requestedPath)}`,
    );
  });
  const visibleEntries = visibleDirectoryEntries(entries);
  const page = visibleEntries.slice(cursor, cursor + DIRECTORY_PAGE_SIZE);
  const nodes = (
    await Promise.all(
      page.map(async (entry) => {
        const childAbsolute = resolve(absolutePath, entry.name);
        const childRelative = relative(realRoot, childAbsolute);
        if (entry.isDirectory()) {
          return directoryNode(childAbsolute, childRelative);
        }
        const info = await lstat(childAbsolute).catch(() => null);
        if (!info?.isFile() || info.isSymbolicLink()) return null;
        return {
          name: entry.name,
          path: toPosixPath(childRelative),
          type: "file",
          editable: isEditableFile(childAbsolute) && info.size <= MAX_FILE_BYTES,
          size: info.size,
        };
      }),
    )
  ).filter(Boolean);
  const nextOffset = cursor + page.length;
  return {
    path: toPosixPath(relative(realRoot, absolutePath)) || ".",
    entries: nodes,
    nextCursor: nextOffset < visibleEntries.length ? String(nextOffset) : null,
  };
}

async function listLibraryRoots(root, scanErrors) {
  const roots = [];
  const standardRoot = resolve(root, "拆文库");
  const standardInfo = await lstat(standardRoot).catch(() => null);
  if (standardInfo?.isDirectory() && !standardInfo.isSymbolicLink()) {
    // 单个拆文库读不动时保留其他项目，但把残缺扫描显式带回前端；空数组只能表达“确实为空”，
    // 不能再同时承担权限错误/外挂盘掉线，否则作者会把不可见文稿误当成不存在。
    const entries = await readdir(standardRoot, { withFileTypes: true }).catch((error) => {
      recordScanError(scanErrors, root, standardRoot, error);
      return [];
    });
    for (const entry of entries) {
      if (entry.isDirectory() && !entry.isSymbolicLink()) {
        roots.push({ absolutePath: resolve(standardRoot, entry.name), relativePath: `拆文库${sep}${entry.name}` });
      }
    }
  }

  // 工作区根目录读不动就没有任何可展示的树，直接给出可执行的报错，而不是静默返回空树。
  const rootEntries = await readdir(root, { withFileTypes: true }).catch(() => {
    throw new DashboardError(
      403,
      "workspace_unreadable",
      `工作区目录无法读取，请检查访问权限：${root}`,
    );
  });
  for (const entry of rootEntries) {
    if (
      entry.name.startsWith("拆文库-") &&
      entry.isDirectory() &&
      !entry.isSymbolicLink()
    ) {
      roots.push({ absolutePath: resolve(root, entry.name), relativePath: entry.name });
    }
  }

  return roots.sort((left, right) =>
    left.relativePath.localeCompare(right.relativePath, "zh-CN", { numeric: true }),
  );
}

function isUnderAnyPath(candidate, blockedPaths) {
  return blockedPaths.some((blocked) => isPathInside(candidate, blocked));
}

async function findProjectRoots(
  root,
  libraryPaths,
  scanErrors,
  currentPath = root,
  depth = 0,
  projects = [],
) {
  if (depth > 3 || isUnderAnyPath(currentPath, libraryPaths)) {
    return projects;
  }

  const entries = await readdir(currentPath, { withFileTypes: true }).catch((error) => {
    recordScanError(scanErrors, root, currentPath, error);
    return [];
  });
  const childDirectoryNames = new Set(
    entries.filter((entry) => entry.isDirectory() && !entry.isSymbolicLink()).map((entry) => entry.name),
  );
  const childFileNames = new Set(
    entries.filter((entry) => entry.isFile() && !entry.isSymbolicLink()).map((entry) => entry.name),
  );
  const isLongProject = [...LONG_PROJECT_DIRECTORY_MARKERS].some((marker) =>
    childDirectoryNames.has(marker),
  );
  const isShortProject =
    childFileNames.has(SHORT_PROJECT_BODY_FILE) &&
    [...SHORT_PROJECT_COMPANION_FILES].some((marker) => childFileNames.has(marker));
  if (isLongProject || isShortProject) {
    projects.push({
      absolutePath: currentPath,
      relativePath: relative(root, currentPath),
    });
    return projects;
  }

  for (const entry of entries) {
    if (!entry.isDirectory() || entry.isSymbolicLink() || shouldIgnoreDirectory(entry.name)) {
      continue;
    }
    await findProjectRoots(
      root,
      libraryPaths,
      scanErrors,
      resolve(currentPath, entry.name),
      depth + 1,
      projects,
    );
  }
  return projects;
}

async function discoverWorkspaceRoots(realRoot) {
  const scanErrors = [];
  const libraryRoots = await listLibraryRoots(realRoot, scanErrors);
  const libraryPaths = libraryRoots.map((entry) => entry.absolutePath);
  const projectRoots = await findProjectRoots(realRoot, libraryPaths, scanErrors);
  return { libraryRoots, projectRoots, scanErrors };
}

export async function scanWorkspace(root) {
  const realRoot = await existingRealRoot(root);
  const { libraryRoots, projectRoots, scanErrors } = await discoverWorkspaceRoots(realRoot);
  const libraries = libraryRoots.map((entry) =>
    directoryNode(entry.absolutePath, entry.relativePath),
  );
  const projects = projectRoots.map((entry) =>
    directoryNode(entry.absolutePath, entry.relativePath),
  );
  libraries.sort(compareTreeEntries);
  projects.sort(compareTreeEntries);

  return {
    workspace: {
      name: basename(realRoot),
      path: realRoot,
    },
    libraries,
    projects,
    scanErrors,
    stats: {
      libraries: libraries.length,
      projects: projects.length,
      files: null,
      editableFiles: null,
      onDemand: true,
    },
    limits: {
      maxFileBytes: MAX_FILE_BYTES,
      editableExtensions: [...EDITABLE_EXTENSIONS],
      directoryPageSize: DIRECTORY_PAGE_SIZE,
      maxSearchResults: MAX_SEARCH_RESULTS,
      truncated: scanErrors.length > 0,
      truncatedByReadError: scanErrors.length > 0,
    },
  };
}

export async function searchWorkspace(root, queryValue, scopeValue) {
  const query = typeof queryValue === "string" ? queryValue.trim() : "";
  if (!query || query.length > 100) {
    throw new DashboardError(400, "invalid_query", "搜索词长度必须在 1–100 个字符之间");
  }
  if (!["libraries", "projects"].includes(scopeValue)) {
    throw new DashboardError(400, "invalid_scope", "搜索范围必须是拆文库或写作项目");
  }

  const realRoot = await existingRealRoot(root);
  const { libraryRoots, projectRoots, scanErrors } = await discoverWorkspaceRoots(realRoot);
  const roots = scopeValue === "libraries" ? libraryRoots : projectRoots;
  const normalizedQuery = query.toLocaleLowerCase("zh-CN");
  const state = {
    nodes: 0,
    truncatedByResults: false,
    truncatedByNodes: false,
    truncatedByDepth: false,
    results: [],
    scanErrors,
  };

  async function visit(absolutePath, relativePath, depth) {
    if (state.results.length >= MAX_SEARCH_RESULTS) {
      state.truncatedByResults = true;
      return;
    }
    if (state.nodes >= MAX_SEARCH_NODES) {
      state.truncatedByNodes = true;
      return;
    }
    if (depth > MAX_SEARCH_DEPTH) {
      state.truncatedByDepth = true;
      return;
    }
    state.nodes += 1;

    const info = await lstat(absolutePath).catch((error) => {
      recordScanError(state.scanErrors, realRoot, absolutePath, error);
      return null;
    });
    if (!info || info.isSymbolicLink()) return;
    if (info.isFile()) {
      const path = toPosixPath(relativePath);
      if (basename(absolutePath).toLocaleLowerCase("zh-CN").includes(normalizedQuery)) {
        state.results.push({
          name: basename(absolutePath),
          path,
          type: "file",
          editable: isEditableFile(absolutePath) && info.size <= MAX_FILE_BYTES,
          size: info.size,
        });
      }
      return;
    }
    if (!info.isDirectory()) return;

    const entries = await readdir(absolutePath, { withFileTypes: true }).catch((error) => {
      recordScanError(state.scanErrors, realRoot, absolutePath, error);
      return [];
    });
    for (const entry of visibleDirectoryEntries(entries)) {
      if (state.results.length >= MAX_SEARCH_RESULTS) {
        state.truncatedByResults = true;
        break;
      }
      if (state.nodes >= MAX_SEARCH_NODES) {
        state.truncatedByNodes = true;
        break;
      }
      await visit(
        resolve(absolutePath, entry.name),
        relativePath ? `${relativePath}${sep}${entry.name}` : entry.name,
        depth + 1,
      );
    }
  }

  for (const entry of roots) {
    await visit(entry.absolutePath, entry.relativePath, 0);
    if (state.truncatedByResults || state.truncatedByNodes) break;
  }
  state.results.sort(compareTreeEntries);
  const truncated =
    state.truncatedByResults ||
    state.truncatedByNodes ||
    state.truncatedByDepth ||
    state.scanErrors.length > 0;
  return {
    query,
    scope: scopeValue,
    results: state.results,
    truncated,
    truncation: {
      byResults: state.truncatedByResults,
      byNodes: state.truncatedByNodes,
      byDepth: state.truncatedByDepth,
      byReadError: state.scanErrors.length > 0,
    },
    scanErrors,
    limits: {
      maxResults: MAX_SEARCH_RESULTS,
      maxNodes: MAX_SEARCH_NODES,
      maxDepth: MAX_SEARCH_DEPTH,
    },
  };
}

async function readJsonBody(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > MAX_REQUEST_BYTES) {
      throw new DashboardError(413, "request_too_large", "保存内容超过 2 MiB 限制");
    }
    chunks.push(chunk);
  }

  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new DashboardError(400, "invalid_json", "请求正文不是有效 JSON");
  }
}

function responseHeaders(contentType) {
  return {
    "Cache-Control": "no-store",
    "Content-Security-Policy":
      "default-src 'self'; base-uri 'none'; connect-src 'self'; img-src 'self' data:; object-src 'none'; script-src 'self'; style-src 'self'",
    "Content-Type": contentType,
    "Cross-Origin-Resource-Policy": "same-origin",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
  };
}

function sendJson(response, status, payload) {
  response.writeHead(status, responseHeaders("application/json; charset=utf-8"));
  // Keep JSON safe even if a response is ever embedded in an HTML context.
  // The endpoint already sends application/json with nosniff and a strict CSP;
  // escaping HTML-significant characters adds defense in depth for user input.
  const body = JSON.stringify(payload).replace(/[<>&\u2028\u2029]/g, (character) => {
    switch (character) {
      case "<":
        return "\\u003c";
      case ">":
        return "\\u003e";
      case "&":
        return "\\u0026";
      case "\u2028":
        return "\\u2028";
      default:
        return "\\u2029";
    }
  });
  response.end(body);
}

async function readWorkspaceFile(root, requestedPath) {
  const { absolutePath, info } = await resolveWorkspacePath(root, requestedPath, {
    editableOnly: true,
  });
  if (info.size > MAX_FILE_BYTES) {
    throw new DashboardError(413, "file_too_large", "文件超过 2 MiB，无法在 Dashboard 中打开");
  }
  const content = await readFile(absolutePath, "utf8");
  return {
    path: toPosixPath(relative(await existingRealRoot(root), absolutePath)),
    name: basename(absolutePath),
    content,
    size: Buffer.byteLength(content),
    mtimeMs: info.mtimeMs,
    version: fileVersion(content),
  };
}

async function replaceFileAtomically(target, content, mode) {
  const temporary = resolve(dirname(target), `.${basename(target)}.story-dashboard-${randomUUID()}.tmp`);
  await writeFile(temporary, content, { encoding: "utf8", mode });
  // open(2) 的 mode 会被进程 umask 削掉，光靠 writeFile 保不住原文件权限，
  // 所以改名前显式补一次；个别文件系统不支持权限位，失败就按原样落盘。
  await chmod(temporary, mode & 0o7777).catch(() => {});
  try {
    await rename(temporary, target);
  } catch (error) {
    if (process.platform !== "win32" || !["EACCES", "EPERM", "EEXIST"].includes(error?.code)) {
      await unlink(temporary).catch(() => {});
      throw error;
    }
    await copyFile(temporary, target);
    await unlink(temporary).catch(() => {});
  }
}

async function saveWorkspaceFile(root, payload) {
  if (!payload || typeof payload !== "object") {
    throw new DashboardError(400, "invalid_payload", "缺少保存参数");
  }
  if (typeof payload.content !== "string") {
    throw new DashboardError(400, "invalid_content", "文件内容必须是文本");
  }
  if (Buffer.byteLength(payload.content) > MAX_FILE_BYTES) {
    throw new DashboardError(413, "file_too_large", "文件超过 2 MiB，无法保存");
  }
  if (!/^[a-f0-9]{64}$/.test(payload.expectedVersion || "")) {
    throw new DashboardError(400, "missing_file_version", "保存请求缺少文件版本，请重新载入后再试");
  }

  const initial = await resolveWorkspacePath(root, payload.path, {
    editableOnly: true,
  });
  return withSerializedFileMutation(initial.absolutePath, async () => {
    let current;
    try {
      current = await resolveWorkspacePath(root, payload.path, { editableOnly: true });
    } catch (error) {
      if (error instanceof DashboardError && error.code === "file_not_found") {
        throw new DashboardError(409, "file_changed", "文件已被其他程序删除。请刷新目录后再保存。");
      }
      throw error;
    }
    const currentContent = await readFile(current.absolutePath, "utf8");
    if (fileVersion(currentContent) !== payload.expectedVersion) {
      throw new DashboardError(
        409,
        "file_changed",
        "文件已被其他程序修改。请重新载入后再保存，避免覆盖新内容。",
      );
    }

    await replaceFileAtomically(current.absolutePath, payload.content, current.info.mode);
    const updated = await stat(current.absolutePath);
    return {
      ok: true,
      path: toPosixPath(relative(current.realRoot, current.absolutePath)),
      size: updated.size,
      mtimeMs: updated.mtimeMs,
      version: fileVersion(payload.content),
    };
  });
}

async function deleteWorkspaceFile(root, payload) {
  if (!payload || typeof payload !== "object") {
    throw new DashboardError(400, "invalid_payload", "缺少删除参数");
  }
  if (!/^[a-f0-9]{64}$/.test(payload.expectedVersion || "")) {
    throw new DashboardError(400, "missing_file_version", "删除请求缺少文件版本，请重新载入后再试");
  }

  const initial = await resolveWorkspacePath(root, payload.path, {
    editableOnly: true,
  });
  return withSerializedFileMutation(initial.absolutePath, async () => {
    let current;
    try {
      current = await resolveWorkspacePath(root, payload.path, { editableOnly: true });
    } catch (error) {
      if (error instanceof DashboardError && error.code === "file_not_found") {
        throw new DashboardError(409, "file_changed", "文件已被其他程序删除。请刷新目录后再操作。");
      }
      throw error;
    }
    const currentContent = await readFile(current.absolutePath, "utf8");
    if (fileVersion(currentContent) !== payload.expectedVersion) {
      throw new DashboardError(
        409,
        "file_changed",
        "文件已被其他程序修改。请重新载入后再删除，避免误删新版本。",
      );
    }

    await unlink(current.absolutePath);
    return {
      ok: true,
      path: toPosixPath(relative(current.realRoot, current.absolutePath)),
    };
  });
}

async function serveStaticFile(requestPath, response) {
  const assetName = requestPath === "/" ? "index.html" : requestPath.slice(1);
  if (!["index.html", "styles.css", "app.js"].includes(assetName)) {
    sendJson(response, 404, { error: { code: "not_found", message: "页面不存在" } });
    return;
  }
  const assetPath = resolve(ASSET_DIR, assetName);
  const body = await readFile(assetPath);
  response.writeHead(200, responseHeaders(CONTENT_TYPES[extname(assetName)] || "application/octet-stream"));
  response.end(body);
}

function normalizedHostname(hostHeader) {
  if (!hostHeader) return "";
  try {
    return new URL(`http://${hostHeader}`).hostname.replace(/^\[|\]$/g, "").toLowerCase();
  } catch {
    return "";
  }
}

function normalizedOriginHostname(origin) {
  try {
    return new URL(origin).hostname.replace(/^\[|\]$/g, "").toLowerCase();
  } catch {
    return "";
  }
}

function assertLocalRequest(request, allowNetwork) {
  if (allowNetwork) return;
  const hostname = normalizedHostname(request.headers.host);
  if (!LOOPBACK_HOSTS.has(hostname)) {
    throw new DashboardError(403, "invalid_host", "Dashboard 只接受本机回环地址请求");
  }
  if (["PUT", "DELETE"].includes(request.method) && request.headers.origin) {
    const originHostname = normalizedOriginHostname(request.headers.origin);
    if (!LOOPBACK_HOSTS.has(originHostname)) {
      throw new DashboardError(403, "invalid_origin", "拒绝来自非本机页面的写入请求");
    }
  }
}

export function createDashboardServer({ root, allowNetwork = false }) {
  const workspaceRoot = resolve(root);
  return createServer(async (request, response) => {
    try {
      assertLocalRequest(request, allowNetwork);
      const url = new URL(request.url || "/", "http://127.0.0.1");
      if (request.method === "GET" && url.pathname === "/health") {
        sendJson(response, 200, { ok: true });
        return;
      }
      if (request.method === "GET" && url.pathname === "/api/workspace") {
        sendJson(response, 200, await scanWorkspace(workspaceRoot));
        return;
      }
      if (request.method === "GET" && url.pathname === "/api/tree") {
        sendJson(
          response,
          200,
          await listWorkspaceDirectory(
            workspaceRoot,
            url.searchParams.get("path") || "",
            url.searchParams.get("cursor"),
          ),
        );
        return;
      }
      if (request.method === "GET" && url.pathname === "/api/search") {
        sendJson(
          response,
          200,
          await searchWorkspace(
            workspaceRoot,
            url.searchParams.get("q") || "",
            url.searchParams.get("scope") || "",
          ),
        );
        return;
      }
      if (request.method === "GET" && url.pathname === "/api/file") {
        sendJson(response, 200, await readWorkspaceFile(workspaceRoot, url.searchParams.get("path") || ""));
        return;
      }
      if (request.method === "PUT" && url.pathname === "/api/file") {
        sendJson(response, 200, await saveWorkspaceFile(workspaceRoot, await readJsonBody(request)));
        return;
      }
      if (request.method === "DELETE" && url.pathname === "/api/file") {
        sendJson(response, 200, await deleteWorkspaceFile(workspaceRoot, await readJsonBody(request)));
        return;
      }
      if (request.method === "GET") {
        await serveStaticFile(url.pathname, response);
        return;
      }
      sendJson(response, 405, {
        error: { code: "method_not_allowed", message: "请求方法不支持" },
      });
    } catch (error) {
      const known = error instanceof DashboardError;
      if (!known) {
        console.error("[story-dashboard]", error);
      }
      sendJson(response, known ? error.status : 500, {
        error: {
          code: known ? error.code : "internal_error",
          message: known ? error.message : "Dashboard 处理请求时发生错误",
        },
      });
    }
  });
}

function parseCliArguments(argv) {
  const options = {
    root: process.cwd(),
    host: process.env.STORY_DASHBOARD_HOST || "127.0.0.1",
    port: Number(process.env.STORY_DASHBOARD_PORT || 43110),
    open: false,
    allowNetwork: false,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === "--root") {
      options.root = argv[++index];
    } else if (value === "--host") {
      options.host = argv[++index];
    } else if (value === "--port") {
      options.port = Number(argv[++index]);
    } else if (value === "--open") {
      options.open = true;
    } else if (value === "--allow-network") {
      options.allowNetwork = true;
    } else if (value === "--help" || value === "-h") {
      options.help = true;
    } else {
      throw new DashboardError(400, "unknown_argument", `未知参数：${value}`);
    }
  }

  if (!options.root) {
    throw new DashboardError(400, "missing_root", "--root 需要目录参数");
  }
  if (!Number.isInteger(options.port) || options.port < 0 || options.port > 65535) {
    throw new DashboardError(400, "invalid_port", "端口必须是 0–65535 的整数");
  }
  if (!LOOPBACK_HOSTS.has(options.host) && !options.allowNetwork) {
    throw new DashboardError(
      400,
      "network_binding_requires_opt_in",
      "非本机地址需要显式增加 --allow-network；通常不应把写作文件暴露到局域网",
    );
  }
  return options;
}

async function listen(server, host, preferredPort) {
  const attempts = preferredPort === 0 ? [0] : Array.from({ length: 11 }, (_, index) => preferredPort + index);
  for (const port of attempts) {
    try {
      await new Promise((accept, reject) => {
        const onError = (error) => {
          server.off("listening", onListening);
          reject(error);
        };
        const onListening = () => {
          server.off("error", onError);
          accept();
        };
        server.once("error", onError);
        server.once("listening", onListening);
        server.listen(port, host);
      });
      return server.address().port;
    } catch (error) {
      if (error?.code !== "EADDRINUSE" || port === attempts.at(-1)) {
        throw error;
      }
    }
  }
  throw new Error("No available port");
}

function openBrowser(url) {
  const { command, args } = browserLaunchCommand(url);
  const child = spawn(command, args, { detached: true, stdio: "ignore" });
  child.on("error", () => {});
  child.unref();
}

export function browserLaunchCommand(url, platform = process.platform) {
  if (platform === "darwin") {
    return { command: "open", args: [url] };
  }
  if (platform === "win32") {
    return { command: "cmd", args: ["/c", "start", "", url] };
  }
  return { command: "xdg-open", args: [url] };
}

export function pathsReferToSameFile(left, right) {
  if (!left || !right) return false;
  try {
    return realpathSync(left) === realpathSync(right);
  } catch {
    return false;
  }
}

function printHelp() {
  console.log(`Story Dashboard

Usage:
  node dashboard-server.mjs [--root <dir>] [--host 127.0.0.1] [--port 43110] [--open]

Options:
  --root <dir>       写作工作区，默认当前目录
  --host <host>      监听地址，默认 127.0.0.1
  --port <port>      首选端口，默认 43110；0 表示随机端口
  --open             启动后用系统默认浏览器打开
  --allow-network    显式允许绑定非回环地址（不推荐）
`);
}

async function main() {
  const options = parseCliArguments(process.argv.slice(2));
  if (options.help) {
    printHelp();
    return;
  }

  const workspace = await existingRealRoot(options.root);
  const server = createDashboardServer({ root: workspace, allowNetwork: options.allowNetwork });
  const port = await listen(server, options.host, options.port);
  const displayHost = options.host === "::1" ? "[::1]" : options.host;
  const url = `http://${displayHost}:${port}`;

  console.log("Story Dashboard 已启动");
  console.log(`工作区：${workspace}`);
  console.log(`本机地址：${url}`);
  if (options.open) {
    openBrowser(url);
  }

  const shutdown = () => {
    server.close(() => process.exit(0));
  };
  process.once("SIGINT", shutdown);
  process.once("SIGTERM", shutdown);
}

const isMain = pathsReferToSameFile(process.argv[1], MODULE_PATH);
if (isMain) {
  main().catch((error) => {
    const message = error instanceof DashboardError ? error.message : error?.stack || String(error);
    console.error(`Story Dashboard 启动失败：${message}`);
    process.exitCode = 1;
  });
}
