const state = {
  workspace: null,
  activeView: "libraries",
  activeFile: null,
  originalContent: "",
  dirty: false,
  mode: "edit",
  restored: false,
  showLineNumbers: true,
  filter: "",
  loadingFile: false,
  saving: false,
  deleting: false,
  searching: false,
  searchResults: [],
  searchTruncation: null,
  searchSequence: 0,
  searchTimer: null,
  // 记住作者手动展开/收起过的目录，重绘文件树时不要把人正在翻的章节文件夹关掉
  expandedDirs: new Set(),
  collapsedDirs: new Set(),
};

const elements = {
  workspaceName: document.querySelector("#workspaceName"),
  workspacePath: document.querySelector("#workspacePath"),
  connectionStatus: document.querySelector("#connectionStatus"),
  treeSearch: document.querySelector("#treeSearch"),
  libraryCount: document.querySelector("#libraryCount"),
  projectCount: document.querySelector("#projectCount"),
  fileCount: document.querySelector("#fileCount"),
  librariesBadge: document.querySelector("#librariesBadge"),
  projectsBadge: document.querySelector("#projectsBadge"),
  archiveTabs: [...document.querySelectorAll(".archive-tabs [role='tab']")],
  treePanel: document.querySelector("#treePanel"),
  treeLoading: document.querySelector("#treeLoading"),
  fileTree: document.querySelector("#fileTree"),
  refreshButton: document.querySelector("#refreshButton"),
  mobileBackButton: document.querySelector("#mobileBackButton"),
  editorEmpty: document.querySelector("#editorEmpty"),
  editorWorkspace: document.querySelector("#editorWorkspace"),
  editorBody: document.querySelector("#editorBody"),
  editorContainer: document.querySelector("#editorContainer"),
  lineNumbersGutter: document.querySelector("#lineNumbersGutter"),
  lineNumbersButton: document.querySelector("#lineNumbersButton"),
  editorTitle: document.querySelector("#editorTitle"),
  breadcrumbs: document.querySelector("#breadcrumbs"),
  dirtyStatus: document.querySelector("#dirtyStatus"),
  documentMeta: document.querySelector("#documentMeta"),
  editorInput: document.querySelector("#editorInput"),
  previewPane: document.querySelector("#previewPane"),
  modeButtons: [...document.querySelectorAll(".mode-switch button")],
  deleteButton: document.querySelector("#deleteButton"),
  saveButton: document.querySelector("#saveButton"),
  cursorPosition: document.querySelector("#cursorPosition"),
  encodingLabel: document.querySelector("#encodingLabel"),
  toastRegion: document.querySelector("#toastRegion"),
  conflictDialog: document.querySelector("#conflictDialog"),
  reloadConflictButton: document.querySelector("#reloadConflictButton"),
  truncationNotice: null,
};

class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

async function requestJson(url, options) {
  let response;
  try {
    response = await fetch(url, options);
  } catch {
    setConnection("offline", "连接中断");
    throw new ApiError(0, "network_error", "无法连接本地 Dashboard 服务");
  }

  let payload;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    throw new ApiError(
      response.status,
      payload?.error?.code || "request_failed",
      payload?.error?.message || `请求失败（${response.status}）`,
    );
  }
  setConnection("online", "仅本机");
  return payload;
}

function setConnection(status, label) {
  elements.connectionStatus.dataset.state = status;
  elements.connectionStatus.querySelector("span:last-child").textContent = label;
}

function showToast(message, kind = "success") {
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.dataset.kind = kind;
  const text = document.createElement("p");
  text.textContent = message;
  toast.append(text);
  elements.toastRegion.append(toast);
  window.setTimeout(() => toast.remove(), 4200);
}

function formatNumber(value) {
  return new Intl.NumberFormat("zh-CN").format(value || 0);
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

function countCharacters(content) {
  return [...content.replace(/\s/g, "")].length;
}

// textarea 的 value 永远是 LF：读盘时先归一化，写盘时再换回原文件的换行符，
// 否则 CRLF 稿件会被一次改动整篇重写，而且脏标记永远对不上、清不掉。
function detectEol(content) {
  let crlf = 0;
  let lf = 0;
  let cr = 0;
  for (let index = 0; index < content.length; index += 1) {
    if (content[index] === "\r") {
      if (content[index + 1] === "\n") {
        crlf += 1;
        index += 1;
      } else {
        cr += 1;
      }
    } else if (content[index] === "\n") {
      lf += 1;
    }
  }
  // 按 LF/CRLF 的主流风格回写；只有纯 CR 文件才保留 CR。一个粘贴进来的孤立 CR
  // 不能把每个 LF 都扩散成 CR，反过来也不能让 CRLF 稿件整篇变成 LF。
  if (crlf > lf) return "\r\n";
  if (lf > 0) return "\n";
  if (cr > 0) return "\r";
  return "\n";
}

function normalizeEol(content) {
  return content.replaceAll("\r\n", "\n").replaceAll("\r", "\n");
}

function applyEol(content, eol) {
  return !eol || eol === "\n" ? content : content.replaceAll("\n", eol);
}

function activeEol() {
  return state.activeFile?.eol || "\n";
}

function currentByteSize() {
  return new TextEncoder().encode(applyEol(elements.editorInput.value, activeEol())).length;
}

function fileExtension(name) {
  const index = name.lastIndexOf(".");
  return index >= 0 ? name.slice(index + 1) : "";
}

function iconSvg(kind) {
  if (kind === "folder") {
    return `<svg class="tree-icon folder-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M3.5 6.5h6l2 2h9v10h-17z"></path></svg>`;
  }
  return `<svg class="tree-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3.5h8l4 4v13H6z"></path><path d="M14 3.5v4h4M9 12h6M9 16h5"></path></svg>`;
}

function createTreeEntry(node, depth = 0) {
  const item = document.createElement("li");
  if (node.type === "directory") {
    const details = document.createElement("details");
    details.dataset.path = node.path;
    const shouldOpen =
      state.expandedDirs.has(node.path) ||
      (depth === 0 && !state.collapsedDirs.has(node.path));
    details.open = shouldOpen;
    // 只记录作者亲手的展开/收起；首层程序化展开不算偏好。
    let recorded = shouldOpen;
    details.addEventListener("toggle", () => {
      if (details.open === recorded) return;
      recorded = details.open;
      if (details.open) {
        state.expandedDirs.add(node.path);
        state.collapsedDirs.delete(node.path);
        if (!node.loaded && !node.loading) loadDirectory(node);
      } else {
        state.expandedDirs.delete(node.path);
        state.collapsedDirs.add(node.path);
      }
    });
    const summary = document.createElement("summary");
    summary.innerHTML = iconSvg("folder");
    const label = document.createElement("span");
    label.className = "tree-label";
    label.textContent = node.name;
    summary.append(label);
    details.append(summary);

    const list = document.createElement("ul");
    node.children.forEach((child) => {
      const childItem = createTreeEntry(child, depth + 1);
      if (childItem) list.append(childItem);
    });
    if (node.loading) {
      const loading = document.createElement("li");
      loading.className = "tree-inline-status";
      loading.textContent = "正在读取目录…";
      list.append(loading);
    } else if (node.loadError) {
      const retry = document.createElement("li");
      retry.className = "tree-inline-status";
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "目录加载失败，点击重试";
      button.addEventListener("click", () => loadDirectory(node));
      retry.append(button);
      list.append(retry);
    } else if (node.loaded && node.children.length === 0) {
      const empty = document.createElement("li");
      empty.className = "tree-inline-status";
      empty.textContent = "空目录";
      list.append(empty);
    }
    if (node.nextCursor && !node.loading) {
      const more = document.createElement("li");
      more.className = "tree-inline-status";
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "加载更多";
      button.addEventListener("click", () => loadDirectory(node, { append: true }));
      more.append(button);
      list.append(more);
    }
    details.append(list);
    item.append(details);
    if (shouldOpen && !node.loaded && !node.loading && !node.loadError && !node.loadQueued) {
      node.loadQueued = true;
      window.queueMicrotask(() => {
        node.loadQueued = false;
        if (!node.loaded && !node.loading && !node.loadError) loadDirectory(node);
      });
    }
    return item;
  }

  const button = document.createElement("button");
  button.type = "button";
  button.className = "file-row";
  button.dataset.path = node.path;
  button.dataset.active = String(state.activeFile?.path === node.path);
  button.disabled = !node.editable;
  button.title = node.editable ? node.path : `${node.path}（此文件类型只展示，不可编辑）`;
  button.innerHTML = iconSvg("file");

  const label = document.createElement("span");
  label.className = "tree-label";
  label.textContent = node.name;
  button.append(label);

  const extension = document.createElement("span");
  extension.className = "file-ext";
  extension.textContent = fileExtension(node.name);
  button.append(extension);
  if (node.editable) {
    button.addEventListener("click", () => openFile(node.path));
  }
  item.append(button);
  return item;
}

function mergeDirectoryEntries(node, entries, append) {
  if (!append) {
    node.children = entries;
    return;
  }
  const existingPaths = new Set(node.children.map((entry) => entry.path));
  node.children.push(...entries.filter((entry) => !existingPaths.has(entry.path)));
}

async function loadDirectory(node, { append = false } = {}) {
  if (node.loading) return;
  node.loading = true;
  node.loadError = "";
  renderTree();
  try {
    const cursor = append && node.nextCursor ? `&cursor=${encodeURIComponent(node.nextCursor)}` : "";
    const page = await requestJson(`/api/tree?path=${encodeURIComponent(node.path)}${cursor}`);
    mergeDirectoryEntries(node, page.entries, append);
    node.nextCursor = page.nextCursor;
    node.loaded = true;
  } catch (error) {
    node.loadError = error.message;
    showToast(error.message, "error");
  } finally {
    node.loading = false;
    renderLoadedFileCount();
    renderTree();
  }
}

function loadedFileCount() {
  const paths = new Set();
  function visit(node) {
    if (node.type === "file") {
      paths.add(node.path);
      return;
    }
    node.children.forEach(visit);
  }
  state.workspace?.libraries.forEach(visit);
  state.workspace?.projects.forEach(visit);
  return paths.size;
}

function renderLoadedFileCount() {
  if (!state.workspace) return;
  const count = loadedFileCount();
  elements.fileCount.textContent = count ? `${formatNumber(count)}+` : "按需";
  elements.fileCount.title = "文稿随目录展开按需加载，不预先遍历整个工作区";
}

// 只改当前高亮行，不重建整棵树——重建会把作者正在翻的目录全部收起
function syncActiveRow() {
  const activePath = state.activeFile?.path;
  elements.fileTree.querySelectorAll(".file-row").forEach((row) => {
    row.dataset.active = String(row.dataset.path === activePath);
  });
}

function searchTruncationMessage() {
  const status = state.searchTruncation;
  if (!status) return "";
  const messages = [];
  if (status.byResults) {
    messages.push(
      `匹配结果超过 ${formatNumber(status.limits.maxResults)} 条，仅显示最先找到的部分，请输入更精确的文件名`,
    );
  }
  if (status.byNodes) {
    messages.push(
      `搜索达到 ${formatNumber(status.limits.maxNodes)} 个节点的扫描上限，后续目录尚未检查，请直接展开目标目录查找`,
    );
  }
  if (status.byDepth) {
    messages.push(
      `部分目录超过 ${formatNumber(status.limits.maxDepth)} 层，更深处未搜索；其他项目已继续搜索`,
    );
  }
  if (status.byReadError) {
    const paths = status.scanErrors.map((entry) => entry.path).filter(Boolean);
    const shown = paths.slice(0, 3).join("、") || "部分目录";
    const more = paths.length > 3 ? `等 ${formatNumber(paths.length)} 处` : "";
    messages.push(
      `${shown}${more}无法读取，搜索结果可能不完整。请检查目录访问权限或外挂盘挂载状态`,
    );
  }
  return messages.join("；");
}

function renderTree() {
  elements.fileTree.replaceChildren();
  elements.treeLoading.hidden = true;
  const query = state.filter.trim();
  const collection = query
    ? state.searchResults
    : state.workspace?.[state.activeView] || [];

  if (query && state.searching) {
    const message = document.createElement("div");
    message.className = "tree-message";
    const text = document.createElement("p");
    text.textContent = `正在搜索“${query}”…`;
    message.append(text);
    elements.fileTree.append(message);
    return;
  }

  if (!collection.length) {
    const message = document.createElement("div");
    message.className = "tree-message";
    const text = document.createElement("p");
    text.textContent = query
      ? state.searchTruncation
        ? `搜索未完成，暂时无法确认是否存在“${query}”`
        : `没有找到“${query}”`
      : state.activeView === "libraries"
        ? "工作区里还没有拆文库。运行拆文 skill 后，档案会出现在这里。"
        : "还没有识别到写作项目。长篇需包含正文、大纲、设定或追踪目录；短篇需包含正文.md，并同时包含小节大纲.md或设定.md。";
    message.append(text);
    elements.fileTree.append(message);
    const truncation = searchTruncationMessage();
    if (query && truncation) {
      const status = document.createElement("div");
      status.className = "tree-message";
      status.setAttribute("role", "status");
      const statusText = document.createElement("p");
      statusText.textContent = truncation;
      status.append(statusText);
      elements.fileTree.append(status);
    }
    return;
  }

  const list = document.createElement("ul");
  collection.forEach((node) => {
    const item = createTreeEntry(node);
    if (item) list.append(item);
  });
  const truncation = searchTruncationMessage();
  if (query && truncation) {
    const status = document.createElement("li");
    status.className = "tree-inline-status";
    status.setAttribute("role", "status");
    status.textContent = truncation;
    list.append(status);
  }
  elements.fileTree.append(list);
}

function truncationMessage(scanErrors = []) {
  const paths = scanErrors.map((entry) => entry.path).filter(Boolean);
  const shown = paths.slice(0, 3).join("、") || "部分目录";
  const more = paths.length > 3 ? `等 ${formatNumber(paths.length)} 处` : "";
  return `${shown}${more}无法读取，其中的文稿没有列出。请检查这些目录的访问权限和外挂盘挂载状态，恢复后刷新目录。`;
}

function renderTruncationNotice(limits, scanErrors) {
  if (!limits?.truncated) {
    elements.truncationNotice?.remove();
    elements.truncationNotice = null;
    return;
  }
  if (!elements.truncationNotice) {
    const notice = document.createElement("div");
    notice.id = "treeTruncationNotice";
    notice.className = "tree-message";
    notice.setAttribute("role", "status");
    notice.append(document.createElement("p"));
    elements.treePanel.insertBefore(notice, elements.fileTree);
    elements.truncationNotice = notice;
  }
  elements.truncationNotice.querySelector("p").textContent = truncationMessage(scanErrors);
}

function renderWorkspace() {
  const { workspace, stats, libraries, projects, limits, scanErrors } = state.workspace;
  elements.workspaceName.textContent = workspace.name;
  elements.workspacePath.textContent = workspace.path;
  elements.workspacePath.title = workspace.path;
  elements.libraryCount.textContent = formatNumber(stats.libraries);
  elements.projectCount.textContent = formatNumber(stats.projects);
  renderLoadedFileCount();
  elements.librariesBadge.textContent = formatNumber(libraries.length);
  elements.projectsBadge.textContent = formatNumber(projects.length);
  renderTruncationNotice(limits, scanErrors);
  renderTree();
}

async function loadWorkspace({ announce = false } = {}) {
  window.clearTimeout(state.searchTimer);
  state.searchSequence += 1;
  elements.treeLoading.hidden = false;
  elements.fileTree.replaceChildren();
  setConnection("", "连接中");
  try {
    state.workspace = await requestJson("/api/workspace");
    state.searchResults = [];
    state.searchTruncation = null;
    state.searching = Boolean(state.filter.trim());
    renderWorkspace();
    if (!state.restored) await restoreViewState();
    if (state.filter.trim()) scheduleSearch();
    if (announce) showToast("工作区目录已刷新");
  } catch (error) {
    elements.treeLoading.hidden = true;
    const message = document.createElement("div");
    message.className = "tree-message";
    const text = document.createElement("p");
    text.textContent = error.message;
    message.append(text);
    elements.fileTree.replaceChildren(message);
    showToast(error.message, "error");
  }
}

function confirmDiscard() {
  return !state.dirty || window.confirm("当前文稿还有未保存的修改。确定放弃并打开另一份文件吗？");
}

function setDirty(dirty) {
  state.dirty = dirty;
  elements.dirtyStatus.dataset.state = dirty ? "dirty" : "saved";
  elements.dirtyStatus.querySelector("span:last-child").textContent = dirty ? "待保存" : "已保存";
  syncActionAvailability();
}

function syncActionAvailability() {
  const busy = state.loadingFile || state.saving || state.deleting;
  elements.saveButton.disabled = busy || !state.dirty;
  elements.deleteButton.disabled = busy || !state.activeFile;
}

function setSaving(saving) {
  state.saving = saving;
  elements.dirtyStatus.dataset.state = saving ? "saving" : state.dirty ? "dirty" : "saved";
  elements.dirtyStatus.querySelector("span:last-child").textContent = saving
    ? "保存中"
    : state.dirty
      ? "待保存"
      : "已保存";
  syncActionAvailability();
}

function renderBreadcrumbs(path) {
  elements.breadcrumbs.replaceChildren();
  path.split("/").forEach((part, index, parts) => {
    const label = document.createElement("span");
    label.textContent = part;
    elements.breadcrumbs.append(label);
    if (index < parts.length - 1) {
      const divider = document.createElement("i");
      divider.textContent = "／";
      elements.breadcrumbs.append(divider);
    }
  });
}

function updateDocumentMeta() {
  if (!state.activeFile) return;
  const content = elements.editorInput.value;
  elements.documentMeta.textContent = [
    formatBytes(currentByteSize()),
    `${formatNumber(countCharacters(content))} 字符`,
    fileExtension(state.activeFile.name).toUpperCase(),
  ].join("  ·  ");
}

function updateCursorPosition() {
  const content = elements.editorInput.value;
  const caret = elements.editorInput.selectionStart;
  const before = content.slice(0, caret);
  const lines = before.split("\n");
  updateActiveGutterLine(lines.length);
  elements.cursorPosition.textContent = `第 ${lines.length} 行，第 ${[...lines.at(-1)].length + 1} 列`;
}

function updateActiveGutterLine(currentLine) {
  const prevActive = elements.lineNumbersGutter.querySelector(".gutter-line.active");
  if (prevActive && prevActive.dataset.line === String(currentLine)) return;
  if (prevActive) prevActive.classList.remove("active");
  const target = elements.lineNumbersGutter.querySelector(`.gutter-line[data-line='${currentLine}']`);
  if (target) target.classList.add("active");
}

let lineMirror = null;
function getLineMirror() {
  if (!lineMirror) {
    lineMirror = document.createElement("div");
    lineMirror.className = "editor-line-mirror";
    document.body.appendChild(lineMirror);
  }
  return lineMirror;
}

function updateLineNumbers() {
  if (!state.showLineNumbers || elements.editorContainer.hidden) return;
  const input = elements.editorInput;
  const text = input.value;
  const lines = text.split("\n");
  const count = lines.length;

  const style = window.getComputedStyle(input);
  const mirror = getLineMirror();
  mirror.style.fontFamily = style.fontFamily;
  mirror.style.fontSize = style.fontSize;
  mirror.style.fontWeight = style.fontWeight;
  mirror.style.fontStyle = style.fontStyle;
  // 与 textarea 一样使用无单位行高，避免像素小数取整在长文中累积偏移。
  mirror.style.lineHeight = String(parseFloat(style.lineHeight) / parseFloat(style.fontSize));
  mirror.style.letterSpacing = style.letterSpacing;
  mirror.style.wordSpacing = style.wordSpacing;
  mirror.style.textTransform = style.textTransform;
  mirror.style.textIndent = style.textIndent;
  mirror.style.whiteSpace = "pre-wrap";
  mirror.style.wordBreak = style.wordBreak;
  mirror.style.overflowWrap = "break-word";
  mirror.style.tabSize = style.tabSize || "4";

  const padLeft = parseFloat(style.paddingLeft) || 0;
  const padRight = parseFloat(style.paddingRight) || 0;
  const innerWidth = input.clientWidth - padLeft - padRight;
  if (innerWidth <= 0) return;
  mirror.style.width = `${innerWidth}px`;

  mirror.innerHTML = lines.map((line) => `<div>${escapeHtml(line) || "&#8203;"}</div>`).join("");

  const caret = input.selectionStart || 0;
  const beforeCaret = text.slice(0, caret);
  const activeLineIndex = beforeCaret.split("\n").length - 1;

  elements.lineNumbersGutter.style.paddingTop = style.paddingTop;
  elements.lineNumbersGutter.style.paddingBottom = style.paddingBottom;
  elements.lineNumbersGutter.style.lineHeight = style.lineHeight;
  const children = mirror.children;
  const rows = document.createDocumentFragment();
  for (let i = 0; i < count; i++) {
    const isActive = i === activeLineIndex ? " active" : "";
    const row = document.createElement("div");
    row.className = `gutter-line${isActive}`;
    row.dataset.line = String(i + 1);
    row.textContent = String(i + 1);
    row.style.height = `${children[i].getBoundingClientRect().height}px`;
    rows.append(row);
  }
  elements.lineNumbersGutter.replaceChildren(rows);
  elements.lineNumbersGutter.scrollTop = input.scrollTop;
}

let lineNumbersFrame = null;
function scheduleLineNumbers() {
  if (lineNumbersFrame !== null) return;
  lineNumbersFrame = window.requestAnimationFrame(() => {
    lineNumbersFrame = null;
    updateLineNumbers();
  });
}

function setLineNumbersVisible(visible) {
  state.showLineNumbers = visible;
  elements.editorBody.classList.toggle("show-line-numbers", visible);
  elements.lineNumbersButton.setAttribute("aria-pressed", String(visible));
  scheduleLineNumbers();
  syncViewState();
}

function viewStateKey() {
  return `story_dashboard_view:${state.workspace.workspace.path}`;
}

function syncViewState() {
  if (!state.restored) return;
  const saved = {
    view: state.activeView,
    file: state.activeFile?.path || null,
    mode: state.mode,
    showLineNumbers: state.showLineNumbers,
  };
  try {
    localStorage.setItem(viewStateKey(), JSON.stringify(saved));
  } catch {}
  const url = new URL(window.location.href);
  url.searchParams.set("view", saved.view);
  if (saved.file) {
    url.searchParams.set("file", saved.file);
    url.searchParams.set("mode", saved.mode);
  } else {
    url.searchParams.delete("file");
    url.searchParams.delete("mode");
  }
  window.history.replaceState(null, "", url);
}

async function restoreViewState() {
  let saved = {};
  try {
    saved = JSON.parse(localStorage.getItem(viewStateKey())) || {};
  } catch {}
  const params = new URLSearchParams(window.location.search);
  // 显式链接优先于这个工作区上次打开的文稿。
  const linked = ["view", "file", "mode"].some((key) => params.has(key));
  const file = linked ? params.get("file") : saved.file;
  const mode = (linked ? params.get("mode") : saved.mode) === "preview" ? "preview" : "edit";
  const requestedView = linked ? params.get("view") : saved.view;
  const defaultView = state.workspace.libraries.length ? "libraries" : "projects";
  const view = ["libraries", "projects"].includes(requestedView)
    ? requestedView
    : typeof file === "string" ? deduceViewForPath(file) : defaultView;
  setLineNumbersVisible(saved.showLineNumbers !== false);
  setMode(mode);
  if (typeof file === "string" && file) await openFile(file, { force: true });
  setActiveView(view);
  state.restored = true;
  syncViewState();
}

function expandParentDirs(filePath) {
  if (!filePath) return;
  const parts = filePath.split("/");
  let current = "";
  for (let i = 0; i < parts.length - 1; i++) {
    current = current ? `${current}/${parts[i]}` : parts[i];
    state.expandedDirs.add(current);
    state.collapsedDirs.delete(current);
  }
}

function deduceViewForPath(filePath) {
  if (!state.workspace || !filePath) return state.activeView;
  const containsFile = ({ path }) => path === "." || filePath.startsWith(`${path}/`);
  if (state.workspace.libraries.some(containsFile)) {
    return "libraries";
  }
  if (state.workspace.projects.some(containsFile)) {
    return "projects";
  }
  return state.activeView;
}

async function openFile(path, { force = false } = {}) {
  if (state.loadingFile || (!force && !confirmDiscard())) return;
  state.loadingFile = true;
  syncActionAvailability();
  elements.fileTree.setAttribute("aria-busy", "true");
  try {
    const file = await requestJson(`/api/file?path=${encodeURIComponent(path)}`);
    const normalized = normalizeEol(file.content);
    file.eol = detectEol(file.content);
    file.content = normalized;
    state.activeFile = file;
    state.originalContent = normalized;
    elements.editorInput.value = normalized;
    elements.editorTitle.textContent = file.name;
    renderBreadcrumbs(file.path);
    setDirty(false);
    expandParentDirs(file.path);
    setActiveView(deduceViewForPath(file.path));
    setMode(state.mode);
    updateDocumentMeta();
    updateCursorPosition();
    elements.editorEmpty.hidden = true;
    elements.editorWorkspace.hidden = false;
    document.body.classList.add("document-open");
    syncActiveRow();
    syncViewState();
    scheduleLineNumbers();
    if (state.mode === "edit") window.requestAnimationFrame(() => elements.editorInput.focus());
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    state.loadingFile = false;
    syncActionAvailability();
    elements.fileTree.removeAttribute("aria-busy");
  }
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function inlineMarkdown(value) {
  return value
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_]+)__/g, "<strong>$1</strong>")
    .replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, "<em>$1</em>");
}

function markdownToSafeHtml(markdown) {
  const lines = escapeHtml(markdown).replaceAll("\r\n", "\n").split("\n");
  const output = [];
  let inCode = false;
  let codeLines = [];
  let codeStartLine = 1;
  let listType = null;

  const closeList = () => {
    if (listType) output.push(`</${listType}>`);
    listType = null;
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const lineNum = i + 1;
    if (line.trim().startsWith("```")) {
      closeList();
      if (inCode) {
        output.push(`<div class="preview-code-block" data-line="${codeStartLine}"><pre><code>${codeLines.join("\n")}</code></pre></div>`);
        codeLines = [];
      } else {
        codeStartLine = lineNum;
      }
      inCode = !inCode;
      continue;
    }
    if (inCode) {
      codeLines.push(line);
      continue;
    }

    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    const unordered = line.match(/^\s*[-*+]\s+(.+)$/);
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (heading) {
      closeList();
      const level = heading[1].length;
      output.push(`<h${level} data-line="${lineNum}">${inlineMarkdown(heading[2])}</h${level}>`);
    } else if (unordered || ordered) {
      const nextType = unordered ? "ul" : "ol";
      if (listType !== nextType) {
        closeList();
        listType = nextType;
        output.push(`<${listType}>`);
      }
      output.push(`<li data-line="${lineNum}">${inlineMarkdown((unordered || ordered)[1])}</li>`);
    } else if (/^\s*([-*_])(?:\s*\1){2,}\s*$/.test(line)) {
      closeList();
      output.push(`<hr data-line="${lineNum}">`);
    } else if (line.startsWith("&gt; ")) {
      closeList();
      output.push(`<blockquote data-line="${lineNum}">${inlineMarkdown(line.slice(5))}</blockquote>`);
    } else if (line.trim()) {
      closeList();
      output.push(`<p data-line="${lineNum}">${inlineMarkdown(line)}</p>`);
    } else {
      closeList();
    }
  }
  if (inCode) output.push(`<div class="preview-code-block" data-line="${codeStartLine}"><pre><code>${codeLines.join("\n")}</code></pre></div>`);
  closeList();
  return output.join("");
}

function setMode(mode) {
  state.mode = mode;
  elements.modeButtons.forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.mode === mode));
  });
  const previewing = mode === "preview";
  elements.editorContainer.hidden = previewing;
  elements.previewPane.hidden = !previewing;
  if (previewing) {
    elements.previewPane.innerHTML = markdownToSafeHtml(elements.editorInput.value);
  } else {
    window.requestAnimationFrame(() => elements.editorInput.focus());
  }
  scheduleLineNumbers();
  syncViewState();
}

async function saveFile() {
  if (!state.activeFile || !state.dirty || state.saving || state.deleting) return;
  // 请求发出前就把身份和正文快照下来：保存期间作者可能换文件、也可能接着敲字，
  // 收尾只允许写回这次真正送出去的那份，绝不能落到别的文稿头上。
  const file = state.activeFile;
  const sent = elements.editorInput.value;
  setSaving(true);
  try {
    const saved = await requestJson("/api/file", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        path: file.path,
        content: applyEol(sent, file.eol),
        expectedVersion: file.version,
      }),
    });
    file.mtimeMs = saved.mtimeMs;
    file.version = saved.version;
    file.size = saved.size;
    showToast(`已保存《${file.name}》`);
    if (state.activeFile !== file) return;
    state.originalContent = sent;
    // 保存途中敲进来的字仍是未保存修改，不能被这次结果抹平成「已保存」
    setDirty(elements.editorInput.value !== sent);
    updateDocumentMeta();
  } catch (error) {
    if (state.activeFile !== file) {
      showToast(`《${file.name}》保存失败：${error.message}`, "error");
      return;
    }
    setDirty(true);
    if (error instanceof ApiError && error.status === 409) {
      elements.conflictDialog.showModal();
    } else {
      showToast(error.message, "error");
    }
  } finally {
    setSaving(false);
  }
}

async function deleteFile() {
  if (!state.activeFile || state.saving || state.deleting) return;
  const file = state.activeFile;
  const warning = state.dirty
    ? `《${file.name}》还有未保存修改。删除会永久移除磁盘文件并丢弃这些修改，且无法撤销。确定删除吗？`
    : `确定永久删除《${file.name}》吗？此操作无法撤销。`;
  if (!window.confirm(warning)) return;

  state.deleting = true;
  syncActionAvailability();
  try {
    await requestJson("/api/file", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        path: file.path,
        expectedVersion: file.version,
      }),
    });
    state.activeFile = null;
    state.originalContent = "";
    elements.editorInput.value = "";
    elements.editorWorkspace.hidden = true;
    elements.editorEmpty.hidden = false;
    document.body.classList.remove("document-open");
    setDirty(false);
    syncViewState();
    await loadWorkspace();
    showToast(`已删除《${file.name}》`);
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    state.deleting = false;
    syncActionAvailability();
  }
}

async function searchWorkspace(query, sequence) {
  state.searching = true;
  renderTree();
  try {
    const result = await requestJson(
      `/api/search?q=${encodeURIComponent(query)}&scope=${encodeURIComponent(state.activeView)}`,
    );
    if (sequence !== state.searchSequence) return;
    state.searchResults = result.results;
    state.searchTruncation = result.truncated
      ? {
          ...(result.truncation || {
            byResults: true,
            byNodes: false,
            byDepth: false,
            byReadError: false,
          }),
          scanErrors: result.scanErrors || [],
          limits: result.limits,
        }
      : null;
  } catch (error) {
    if (sequence !== state.searchSequence) return;
    state.searchResults = [];
    state.searchTruncation = null;
    showToast(error.message, "error");
  } finally {
    if (sequence === state.searchSequence) {
      state.searching = false;
      renderTree();
    }
  }
}

function scheduleSearch() {
  window.clearTimeout(state.searchTimer);
  const query = state.filter.trim();
  state.searchSequence += 1;
  const sequence = state.searchSequence;
  if (!query) {
    state.searching = false;
    state.searchResults = [];
    state.searchTruncation = null;
    renderTree();
    return;
  }
  state.searching = true;
  renderTree();
  state.searchTimer = window.setTimeout(() => searchWorkspace(query, sequence), 180);
}

function setActiveView(view) {
  state.activeView = view;
  elements.archiveTabs.forEach((tab) => {
    const selected = tab.dataset.view === view;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
  });
  elements.treePanel.setAttribute(
    "aria-labelledby",
    view === "libraries" ? "librariesTab" : "projectsTab",
  );
  if (state.filter.trim()) {
    scheduleSearch();
  } else {
    renderTree();
  }
  syncViewState();
}

elements.archiveTabs.forEach((tab) => {
  tab.addEventListener("click", () => setActiveView(tab.dataset.view));
  tab.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const direction = event.key === "ArrowRight" ? 1 : -1;
    const current = elements.archiveTabs.indexOf(event.currentTarget);
    const next = elements.archiveTabs.at(
      (current + direction + elements.archiveTabs.length) % elements.archiveTabs.length,
    );
    setActiveView(next.dataset.view);
    next.focus();
  });
});

elements.treeSearch.addEventListener("input", (event) => {
  state.filter = event.currentTarget.value;
  scheduleSearch();
});

elements.treeSearch.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    event.currentTarget.value = "";
    state.filter = "";
    scheduleSearch();
  }
});

elements.refreshButton.addEventListener("click", () => loadWorkspace({ announce: true }));
elements.mobileBackButton.addEventListener("click", () => {
  document.body.classList.remove("document-open");
  window.requestAnimationFrame(() => elements.treeSearch.focus());
});
elements.saveButton.addEventListener("click", saveFile);
elements.deleteButton.addEventListener("click", deleteFile);

elements.editorInput.addEventListener("input", () => {
  setDirty(elements.editorInput.value !== state.originalContent);
  updateDocumentMeta();
  updateCursorPosition();
  scheduleLineNumbers();
});

elements.editorInput.addEventListener("scroll", () => {
  elements.lineNumbersGutter.scrollTop = elements.editorInput.scrollTop;
}, { passive: true });

elements.lineNumbersButton.addEventListener("click", () => {
  setLineNumbersVisible(!state.showLineNumbers);
});

new ResizeObserver(scheduleLineNumbers).observe(elements.editorInput);
document.fonts.ready.then(scheduleLineNumbers);

["click", "keyup", "select"].forEach((eventName) => {
  elements.editorInput.addEventListener(eventName, updateCursorPosition);
});

elements.modeButtons.forEach((button) => {
  button.addEventListener("click", () => setMode(button.dataset.mode));
});

elements.conflictDialog.addEventListener("close", () => {
  if (elements.conflictDialog.returnValue === "reload" && state.activeFile) {
    openFile(state.activeFile.path, { force: true });
  }
});

document.addEventListener("keydown", (event) => {
  const modifier = event.metaKey || event.ctrlKey;
  if (modifier && event.key.toLocaleLowerCase() === "s") {
    event.preventDefault();
    saveFile();
  }
  if (modifier && event.key.toLocaleLowerCase() === "k") {
    event.preventDefault();
    elements.treeSearch.focus();
    elements.treeSearch.select();
  }
});

window.addEventListener("beforeunload", (event) => {
  if (state.dirty) {
    event.preventDefault();
    event.returnValue = "";
  }
});

loadWorkspace();
