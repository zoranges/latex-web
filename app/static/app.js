"use strict";

/* ================= 全局状态 ================= */
const S = {
  projects: [],
  slug: null,        // 当前项目 slug
  meta: null,        // 当前项目元数据
  files: [],         // 当前项目文件列表
  currentFile: null, // 编辑器当前文件路径
  editor: null,      // Monaco 实例
  loadingFile: false,
  pdfDoc: null,
  pageNum: 1,
  zoom: 1,            // 相对适宽的比例
  scale: 1,           // CSS 渲染比例（适宽 × zoom）
  renderScale: 1,     // 实际位图比例（含高分屏 dpr）
  pages: [],          // 连续滚动页：{pdfPage, baseW, baseH, el, canvas, rendered}
  marker: null,       // 正向定位标记 {page, x, y}（PDF 坐标，原点左下）
  _renderGen: 0,      // 渲染代数（忽略被取代的渲染）
  _pageObserver: null,
  _scrollSyncTimer: null,
  _skipScrollSync: false, // 反向定位引起的编辑器滚动，不再触发正向联动
  pdfScrollSync: true,    // 编辑器滚动 → PDF 联动
  errors: [],        // 编译错误 [{file, line, message}]
  errIdx: 0,
  labels: { labels: [], bibkeys: [] }, // \ref / \cite 补全数据
  labelsFor: null,   // 已加载补全数据的项目 slug
  lastLog: "",
  saveTimer: null,
  compileTimer: null,
  compileSeq: 0,
  dirty: 0,          // 未保存的变更计数（0 = 干净，切换项目/文件时无需保存）
  qsSel: 0,          // Ctrl+P 文件切换选中项
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

/* ================= API ================= */
async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}
const json = (method, body) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* 引用 index.html 中 <symbol> 定义的线性图标 */
const icon = (name) => `<svg class="icon"><use href="#i-${name}"/></svg>`;

/* ---------- 加载态工具 ---------- */
/* 按钮 / 迷你按钮进入 loading 态：图标换成旋转圆环，期间不可再点 */
function setBusy(el, busy) {
  if (!el) return;
  el.classList.toggle("loading", busy);
  if (busy && !el.querySelector(".spinner")) {
    const s = document.createElement("span");
    s.className = "spinner";
    el.prepend(s);
  }
}

/* 容器内显示「旋转圆环 + 文案」的加载占位（UL 里用 li，其余用 div） */
function showLoading(container, text) {
  container.innerHTML = "";
  const node = document.createElement(container.tagName === "UL" ? "li" : "div");
  node.className = "list-loading";
  const s = document.createElement("span");
  s.className = "spinner";
  node.append(s, document.createTextNode(text));
  container.appendChild(node);
}

function showPdfOverlay(text) {
  $("#pdf-overlay-text").textContent = text;
  $("#pdf-overlay").hidden = false;
}
function hidePdfOverlay() {
  $("#pdf-overlay").hidden = true;
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 3200);
}

function setStatus(text, kind = "") {
  const el = $("#status");
  el.textContent = text;
  el.className = "status " + kind;
}

/* ================= UI 状态持久化 ================= */
const LS_KEY = "latexweb.ui.v1";

function loadUI() {
  try {
    return JSON.parse(localStorage.getItem(LS_KEY)) || {};
  } catch {
    return {};
  }
}

function saveUI(patch) {
  const ui = Object.assign(loadUI(), patch);
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(ui));
  } catch { /* 隐私模式等场景静默失败 */ }
}

/* ================= 编译错误标记 ================= */
/* latexmk -file-line-error 格式：./main.tex:12: LaTeX Error: ... */
function parseTexErrors(log) {
  const re = /^((?:\.\/)?[^\s:]+\.(?:tex|sty|cls|bib)):(\d+):(.*)$/;
  const out = [];
  const seen = new Set();
  for (const ln of log.split("\n")) {
    const m = ln.match(re);
    if (!m) continue;
    const key = m[1] + ":" + m[2];
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({
      file: m[1].replace(/^\.\//, ""),
      line: +m[2],
      message: m[3].trim() || "LaTeX 错误",
    });
    if (out.length >= 50) break;
  }
  return out;
}

function applyErrorMarkers(errors) {
  S.errors = errors;
  S.errIdx = 0;
  const badge = $("#sb-errors");
  badge.hidden = !errors.length;
  badge.textContent = `${errors.length} 个错误`;
  if (!window.monaco || !S.editor || !S.editor.getModel()) return;
  const model = S.editor.getModel();
  const mine = errors.filter((e) => e.file === S.currentFile);
  monaco.editor.setModelMarkers(
    model,
    "latex-errors",
    mine.map((e) => ({
      startLineNumber: e.line,
      startColumn: 1,
      endLineNumber: e.line,
      endColumn: 1,
      message: e.message,
      severity: monaco.MarkerSeverity.Error,
    }))
  );
}

async function gotoNextError() {
  if (!S.errors.length) {
    toast("没有编译错误");
    return;
  }
  const i = S.errIdx;
  S.errIdx = (S.errIdx + 1) % S.errors.length;
  const e = S.errors[i];
  if (e.file !== S.currentFile) await openFile(e.file);
  revealLine(e.line);
  toast(`${e.file}:${e.line}  ${e.message}`);
}

/* ================= 保存 / 编译 ================= */
function autoCompile() {
  return $("#auto-compile").checked;
}

function scheduleSave() {
  S.dirty++;
  updateDirtyDot();
  clearTimeout(S.saveTimer);
  setStatus("未保存…");
  S.saveTimer = setTimeout(saveNow, 1200);
}

async function saveNow(force = false) {
  if (!S.slug || !S.currentFile) return;
  // 没有未保存的变更时跳过（切换项目/文件时的例行保存不应产生
  // 空写入、空 git 提交，更不应连锁触发一次无意义的自动编译）
  if (!S.dirty && !force) return;
  const pending = S.dirty; // 本次保存对应的变更量
  const slug = S.slug;
  const filePath = S.currentFile;
  const content = S.editor.getValue();
  setStatus("保存中…", "busy");
  try {
    await api(
      `/api/projects/${slug}/file?path=${encodeURIComponent(filePath)}`,
      json("PUT", { content })
    );
    // 保存期间的新变更保留在计数里，其余视为已落盘
    S.dirty = Math.max(0, S.dirty - pending);
    updateDirtyDot();
    setStatus("已保存");
    if (S.slug === slug && autoCompile()) scheduleCompile(500, slug);
  } catch (e) {
    setStatus("保存失败: " + e.message, "error");
  }
}

function scheduleCompile(delay, slug = S.slug) {
  clearTimeout(S.compileTimer);
  // 触发时项目已切换走则放弃，避免编译错误的项目
  S.compileTimer = setTimeout(() => {
    if (S.slug === slug) compile();
  }, delay);
}

async function compile() {
  if (!S.slug) return;
  const seq = ++S.compileSeq;
  setStatus("编译中…", "busy");
  setBusy($("#btn-compile"), true);
  $("#btn-compile").disabled = true;
  showPdfOverlay("正在编译…");
  try {
    const r = await api(`/api/projects/${S.slug}/compile`, { method: "POST" });
    if (seq !== S.compileSeq) return;
    S.lastLog = r.log;
    if (r.success) {
      $("#log-drawer").hidden = true;
      applyErrorMarkers([]);
      showPdfOverlay("正在加载 PDF…");
      await loadPdf();
      ensureLabels(true); // 编译后 .aux 可能出现新标签
      setStatus(`已编译 · ${r.seconds}s`);
    } else {
      applyErrorMarkers(parseTexErrors(r.log));
      setStatus(`编译失败 · ${S.errors.length} 个错误`, "error");
      showLog(r.log);
    }
  } catch (e) {
    if (seq !== S.compileSeq) return;
    setStatus("编译出错: " + e.message, "error");
  } finally {
    if (seq === S.compileSeq) {
      hidePdfOverlay();
      $("#btn-compile").disabled = false;
      setBusy($("#btn-compile"), false);
    }
  }
}

/* \ref / \cite 补全数据（懒加载，编译后强制刷新） */
async function ensureLabels(force = false) {
  if (!S.slug) return;
  if (!force && S.labelsFor === S.slug) return;
  try {
    S.labels = await api(`/api/projects/${S.slug}/labels`);
    S.labelsFor = S.slug;
  } catch {
    S.labels = { labels: [], bibkeys: [] };
  }
}

/* ================= 项目列表 ================= */
async function loadProjects() {
  showLoading($("#project-list"), "加载项目…");
  try {
    S.projects = await api("/api/projects");
  } catch (e) {
    $("#project-list").innerHTML = "";
    toast("加载项目失败: " + e.message);
    return;
  }
  renderProjects();
  const ui = loadUI();
  const saved = ui.slug && S.projects.find((p) => p.slug === ui.slug);
  if (!S.slug && S.projects.length) {
    await openProject(saved ? saved.slug : S.projects[0].slug, ui.file);
  } else if (!S.projects.length) {
    S.slug = null;
    S.currentFile = null;
    $("#project-name").textContent = "未选择项目";
    $("#file-tree").innerHTML = "";
    $("#pdf-hint").hidden = false;
  }
}

function renderProjects() {
  const ul = $("#project-list");
  ul.innerHTML = "";
  for (const p of S.projects) {
    const li = document.createElement("li");
    li.className = "project-item" + (p.slug === S.slug ? " active" : "");
    const name = document.createElement("span");
    name.textContent = p.name;
    name.title = p.name;
    name.onclick = () => openProject(p.slug);
    const del = document.createElement("button");
    del.innerHTML = icon("x");
    del.title = "删除项目";
    del.onclick = async (e) => {
      e.stopPropagation();
      if (!confirm(`删除项目「${p.name}」？所有文件与历史将不可恢复！`)) return;
      try {
        await api(`/api/projects/${p.slug}`, { method: "DELETE" });
      } catch (err) {
        alert(err.message);
        return;
      }
      if (p.slug === S.slug) {
        S.slug = null;
        S.currentFile = null;
        S.pdfDoc = null;
      }
      await loadProjects();
    };
    li.append(name, del);
    ul.appendChild(li);
  }
}

/* ---------- 模板选择 ---------- */
S.tplList = [];
S.selectedTemplate = "article";

async function openTemplateModal() {
  $("#tpl-name").value = "";
  $("#template-modal").hidden = false;
  showLoading($("#tpl-grid"), "加载模板…");
  setTimeout(() => $("#tpl-name").focus(), 50);
  try {
    S.tplList = await api("/api/templates");
  } catch (e) {
    $("#tpl-grid").innerHTML = "";
    toast("加载模板失败: " + e.message);
    return;
  }
  S.selectedTemplate = S.tplList[0] ? S.tplList[0].id : "article";
  renderTemplates();
}

function renderTemplates() {
  const grid = $("#tpl-grid");
  grid.innerHTML = "";
  for (const t of S.tplList) {
    const card = document.createElement("div");
    card.className = "tpl-card" + (t.id === S.selectedTemplate ? " selected" : "");
    card.innerHTML =
      `<b>${icon("file")}${escapeHtml(t.name)}<span class="tpl-check">${icon("check")}</span></b>` +
      `<span>${escapeHtml(t.desc)}</span>` +
      `<span class="tpl-files">${t.files.length} 个文件</span>`;
    card.onclick = () => {
      S.selectedTemplate = t.id;
      renderTemplates();
    };
    grid.appendChild(card);
  }
}

async function createFromTemplate() {
  const name = $("#tpl-name").value.trim();
  if (!name) {
    toast("请输入项目名称");
    $("#tpl-name").focus();
    return;
  }
  const btn = $("#btn-template-create");
  setBusy(btn, true);
  try {
    const p = await api(
      "/api/projects",
      json("POST", { name, template: S.selectedTemplate })
    );
    $("#template-modal").hidden = true;
    await loadProjects();
    await openProject(p.slug);
    toast(`已用模板创建「${name}」`);
    scheduleCompile(0);
  } catch (e) {
    alert(e.message);
  } finally {
    setBusy(btn, false);
  }
}

async function openProject(slug, preferFile) {
  if (S.slug === slug) return;
  await saveNow();
  S.slug = slug;
  S.meta = S.projects.find((p) => p.slug === slug);
  S.currentFile = null;
  S.pdfDoc = null;
  S.pageNum = 1;
  S.marker = null;
  S.labelsFor = null;
  applyErrorMarkers([]);
  saveUI({ slug });
  renderProjects();
  $("#project-name").textContent = S.meta ? S.meta.name : "";
  $("#log-drawer").hidden = true;
  if (!S.meta) return;
  await refreshFiles();
  const start =
    preferFile && S.files.some((f) => f.path === preferFile)
      ? preferFile
      : S.meta.main_file;
  await openFile(start);
  await loadPdf(true);
  ensureLabels();
}

/* ================= 文件树 ================= */
async function refreshFiles() {
  showLoading($("#file-tree"), "加载文件…");
  try {
    S.files = await api(`/api/projects/${S.slug}/files`);
  } catch (e) {
    S.files = [];
  }
  renderTree();
}

function renderTree() {
  const ul = $("#file-tree");
  ul.innerHTML = "";
  if (!S.files.length) {
    const li = document.createElement("li");
    li.style.cssText = "padding:8px 10px;color:var(--text-dim);font-size:12px;";
    li.textContent = "暂无文件";
    ul.appendChild(li);
    return;
  }
  // 目录 → 直属文件（目录扁平展示，如 figures 与 figures/sub 各成节点）
  const dirs = new Map();
  const roots = [];
  for (const f of S.files) {
    const parts = f.path.split("/");
    if (parts.length === 1) roots.push(f);
    else {
      const dir = parts.slice(0, -1).join("/");
      if (!dirs.has(dir)) dirs.set(dir, []);
      dirs.get(dir).push(f);
    }
  }
  for (const f of roots) ul.appendChild(renderFileItem(f, 0));
  for (const [dir, files] of [...dirs.entries()].sort()) {
    const li = document.createElement("li");
    const head = document.createElement("div");
    head.className = "tree-dir";
    head.style.paddingLeft = "10px";
    head.innerHTML = icon("folder");
    head.appendChild(document.createTextNode(dir.split("/").pop()));
    li.appendChild(head);
    for (const f of files) li.appendChild(renderFileItem(f, 1));
    ul.appendChild(li);
  }
  updateDirtyDot();
}

/* 文件树当前文件旁的未保存圆点 */
function updateDirtyDot() {
  const active = $("#file-tree .file-item.active");
  if (active) active.classList.toggle("dirty", S.dirty > 0);
}

function renderFileItem(f, depth) {
  const li = document.createElement("li");
  li.className = "file-item" + (f.path === S.currentFile ? " active" : "");
  const span = document.createElement("div");
  span.className = "tree-file";
  span.style.paddingLeft = (10 + depth * 16) + "px";
  span.innerHTML = icon("file");
  span.appendChild(document.createTextNode(f.path.split("/").pop()));
  const dot = document.createElement("span");
  dot.className = "dirty-dot";
  dot.title = "有未保存的修改";
  span.title = f.path;
  span.onclick = () => openFile(f.path);
  const act = document.createElement("span");
  act.className = "file-actions";

  const rn = document.createElement("button");
  rn.innerHTML = icon("edit");
  rn.title = "重命名";
  rn.onclick = async (e) => {
    e.stopPropagation();
    const np = prompt("新路径（相对项目根）:", f.path);
    if (!np || np === f.path) return;
    try {
      await api(`/api/projects/${S.slug}/rename`, json("POST", { old: f.path, new: np }));
      if (f.path === S.meta.main_file) {
        await api(`/api/projects/${S.slug}/main`, json("PUT", { main_file: np }));
        S.meta.main_file = np;
      }
      if (f.path === S.currentFile) S.currentFile = np;
      await refreshFiles();
    } catch (err) {
      alert(err.message);
    }
  };

  const rm = document.createElement("button");
  rm.innerHTML = icon("x");
  rm.title = "删除";
  rm.onclick = async (e) => {
    e.stopPropagation();
    if (!confirm(`删除 ${f.path}？`)) return;
    try {
      await api(`/api/projects/${S.slug}/file?path=${encodeURIComponent(f.path)}`, { method: "DELETE" });
      await refreshFiles();
    } catch (err) {
      alert(err.message);
    }
  };

  act.append(rn, rm);
  li.append(span, dot, act);
  return li;
}

/* ================= 文件快速切换（Ctrl+P） ================= */
function openQuickSwitch() {
  if (!S.files.length) {
    toast("没有可打开的文件");
    return;
  }
  S.qsSel = 0;
  renderQsList("");
  $("#quick-switch").hidden = false;
  const inp = $("#qs-input");
  inp.value = "";
  setTimeout(() => inp.focus(), 30);
}

function closeQuickSwitch() {
  $("#quick-switch").hidden = true;
}

function renderQsList(query) {
  const q = query.trim().toLowerCase();
  const paths = S.files.map((f) => f.path)
    .filter((p) => p.toLowerCase().includes(q))
    .sort((a, b) => {
      const ai = a.toLowerCase().indexOf(q);
      const bi = b.toLowerCase().indexOf(q);
      return ai - bi || a.length - b.length;
    })
    .slice(0, 12);
  const ul = $("#qs-list");
  ul.innerHTML = "";
  if (!paths.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "没有匹配的文件";
    ul.appendChild(li);
    return;
  }
  S.qsSel = Math.min(S.qsSel, paths.length - 1);
  paths.forEach((p, i) => {
    const li = document.createElement("li");
    if (i === S.qsSel) li.classList.add("sel");
    li.innerHTML = icon("file");
    li.appendChild(document.createTextNode(p));
    li.onclick = () => {
      closeQuickSwitch();
      openFile(p);
    };
    ul.appendChild(li);
  });
}

function qsOpenSelected() {
  const sel = $("#qs-list li.sel");
  if (!sel) return;
  const path = sel.textContent;
  closeQuickSwitch();
  openFile(path);
}

/* ================= 编辑器 ================= */
async function openFile(path) {
  if (!S.slug || path === S.currentFile) return;
  await saveNow();
  try {
    const { content } = await api(
      `/api/projects/${S.slug}/file?path=${encodeURIComponent(path)}`
    );
    S.loadingFile = true;
    S.currentFile = path;
    S.editor.setValue(content);
    S.loadingFile = false;
    S.dirty = 0; // 刚从磁盘加载的内容视为干净
    clearTimeout(S.saveTimer);
    const lang = path.endsWith(".tex") ? "latex"
      : path.endsWith(".bib") ? "bibtex"
      : path.endsWith(".md") ? "markdown"
      : "plaintext";
    if (window.monaco && S.editor.getModel && S.editor.getModel()) {
      monaco.editor.setModelLanguage(S.editor.getModel(), lang);
    }
    $("#sb-file").textContent = path;
    updateCount();
    renderTree();
    applyErrorMarkers(S.errors); // 新文件的错误标记重新过滤
    saveUI({ file: path });
    if (isMobile()) setDrawer(false);
  } catch (e) {
    alert(e.message);
  }
}

function revealLine(line) {
  // 反向定位 / 错误跳转引发的编辑器滚动，不回触 PDF 联动
  S._skipScrollSync = true;
  S.editor.revealLineInCenter(line);
  S.editor.setPosition({ lineNumber: line, column: 1 });
  if (!window.monaco) return;
  const dec = S.editor.deltaDecorations([], [{
    range: new monaco.Range(line, 1, line, 1),
    options: { isWholeLine: true, className: "sync-highlight" },
  }]);
  setTimeout(() => S.editor.deltaDecorations(dec, []), 2500);
}

function updateCount() {
  const v = S.editor.getValue();
  $("#sb-count").textContent = `${v.length.toLocaleString()} 字符 · ${v.split("\n").length} 行`;
}

/* 拖拽调整编辑器 / PDF 分栏 */
function initResizer() {
  const resizer = $("#resizer");
  const editorHost = $("#editor-host");
  const main = document.querySelector(".main");
  const aside = document.querySelector("aside");
  let dragging = false;
  resizer.addEventListener("mousedown", (e) => {
    dragging = true;
    resizer.classList.add("active");
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
    e.preventDefault();
  });
  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const rect = main.getBoundingClientRect();
    const asideW = aside.getBoundingClientRect().width;
    const usable = rect.width - asideW;
    const x = e.clientX - rect.left - asideW;
    const frac = Math.min(0.85, Math.max(0.15, x / usable));
    S._splitFrac = frac;
    editorHost.style.flex = `0 0 ${(frac * 100).toFixed(2)}%`;
    if (S.pdfDoc) relayoutPdf();
  });
  window.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false;
    resizer.classList.remove("active");
    document.body.style.userSelect = "";
    document.body.style.cursor = "";
    if (S._splitFrac) saveUI({ split: S._splitFrac });
  });
}

/* ================= 移动端 ================= */
function isMobile() {
  return window.matchMedia("(max-width: 900px)").matches;
}

function setDrawer(open) {
  document.querySelector("aside").classList.toggle("open", open);
  $("#drawer-overlay").hidden = !open;
}

function setView(view) {
  document.body.classList.toggle("view-edit", view === "edit");
  document.body.classList.toggle("view-pdf", view === "pdf");
  $("#view-edit").classList.toggle("active", view === "edit");
  $("#view-pdf").classList.toggle("active", view === "pdf");
  if (view === "pdf" && S.pdfDoc) relayoutPdf(); // 手机端此前面板隐藏，宽度无效
  if (view === "edit" && S.editor) S.editor.layout();
}

function initMobile() {
  $("#btn-menu").addEventListener("click", () =>
    setDrawer(!document.querySelector("aside").classList.contains("open"))
  );
  $("#drawer-overlay").addEventListener("click", () => setDrawer(false));
  $("#view-edit").addEventListener("click", () => setView("edit"));
  $("#view-pdf").addEventListener("click", () => setView("pdf"));
  window.addEventListener("resize", () => {
    if (!isMobile()) setDrawer(false);
  });
}

/* ================= PDF：连续滚动多页渲染 ================= */
async function loadPdf(silent = false) {
  if (!S.slug) return;
  // 编译流程已带着遮罩进入时沿用，不重复显示
  const ownOverlay = $("#pdf-overlay").hidden;
  if (ownOverlay) showPdfOverlay("加载 PDF…");
  try {
    const url = `/api/projects/${S.slug}/pdf?t=${Date.now()}`;
    const task = pdfjsLib.getDocument({
      url,
      // CJK 等 CID 字体渲染必需
      cMapUrl: "/static/vendor/pdfjs/cmaps/",
      cMapPacked: true,
      standardFontDataUrl: "/static/vendor/pdfjs/standard_fonts/",
    });
    S.pdfDoc = await task.promise;
    S.marker = null;
    await buildPages();
    hidePdfOverlay();
    $("#pdf-hint").hidden = true;
  } catch (e) {
    S.pdfDoc = null;
    destroyPages();
    hidePdfOverlay();
    if (!silent) $("#pdf-hint").hidden = false;
  }
}

function destroyPages() {
  S._pageObserver?.disconnect();
  S._pageObserver = null;
  S.pages = [];
  // marker 平时挂在某个 .pdf-page 里，先移回滚动容器再清空，否则元素会被一并删掉
  const marker = $("#pdf-marker");
  if (marker) $("#pdf-scroll").appendChild(marker);
  $("#pdf-pages").innerHTML = "";
  if (marker) marker.hidden = true;
  $("#pdf-page-info").textContent = "0 / 0";
}

async function buildPages() {
  destroyPages();
  const wrap = $("#pdf-pages");
  const frag = document.createDocumentFragment();
  for (let i = 1; i <= S.pdfDoc.numPages; i++) {
    const pg = await S.pdfDoc.getPage(i);
    const vp = pg.getViewport({ scale: 1 });
    const el = document.createElement("div");
    el.className = "pdf-page";
    el.dataset.page = i;
    frag.appendChild(el);
    S.pages.push({
      pdfPage: pg,
      baseW: vp.width,
      baseH: vp.height,
      el,
      canvas: null,
      rendered: false,
    });
  }
  wrap.appendChild(frag);
  layoutPages();
  // 懒渲染：页面进入视口（含前后 600px 缓冲）才真正画 canvas
  S._pageObserver = new IntersectionObserver(
    (entries) => {
      for (const en of entries) {
        if (en.isIntersecting) renderPageEl(+en.target.dataset.page);
      }
    },
    { root: $("#pdf-scroll"), rootMargin: "600px 0px" }
  );
  S.pages.forEach((p) => S._pageObserver.observe(p.el));
  // 回到之前的页码（编译重载后不丢失阅读位置）
  if (S.pageNum > 1 && S.pages[S.pageNum - 1]) {
    $("#pdf-scroll").scrollTop = S.pages[S.pageNum - 1].el.offsetTop - 8;
  }
  updatePageInfo();
}

function layoutPages() {
  if (!S.pages.length) return;
  // 以第一页宽度适配容器，各页按自身尺寸排布
  const baseW = S.pages[0].baseW;
  S.scale = effectiveScale(baseW);
  // 高分屏（手机 dpr 常为 2-3）：按 dpr 提高实际渲染分辨率，CSS 尺寸不变
  const dpr = Math.min(window.devicePixelRatio || 1, 3);
  S.renderScale = Math.min(S.scale * dpr, 4); // 封顶防极端缩放下 canvas 过大
  for (const p of S.pages) {
    p.el.style.width = (p.baseW * S.scale) + "px";
    p.el.style.height = (p.baseH * S.scale) + "px";
  }
}

function effectiveScale(baseWidth) {
  const w = Math.max(200, $("#pdf-scroll").clientWidth - 36);
  return Math.max(0.2, (w / baseWidth) * S.zoom);
}

async function renderPageEl(i) {
  const p = S.pages[i - 1];
  if (!p || p.rendered) return;
  p.rendered = true; // 先占位防止同一页并发渲染
  try {
    const viewport = p.pdfPage.getViewport({ scale: S.renderScale });
    if (!p.canvas) {
      p.canvas = document.createElement("canvas");
      p.canvas.className = "pdf-canvas";
      p.canvas.addEventListener("click", onPdfClick);
      p.el.appendChild(p.canvas);
    }
    p.canvas.width = viewport.width;
    p.canvas.height = viewport.height;
    // CSS 尺寸由 .pdf-page 容器控制（width/height 100%），位图分辨率独立于显示尺寸
    await p.pdfPage.render({
      canvasContext: p.canvas.getContext("2d"),
      viewport,
    }).promise;
  } catch {
    p.rendered = false;
  }
}

/* 缩放 / 容器尺寸变化：重排所有页，可见页重渲染（不可见的保持旧位图，进入视口再更新） */
function relayoutPdf() {
  if (!S.pages.length) return;
  const host = $("#pdf-scroll");
  const frac = host.scrollTop / Math.max(1, host.scrollHeight);
  layoutPages();
  for (const p of S.pages) p.rendered = false;
  S._pageObserver?.disconnect();
  S.pages.forEach((p) => S._pageObserver.observe(p.el));
  host.scrollTop = frac * host.scrollHeight;
  placeMarker();
  updatePageInfo();
}

/* 滚动时跟踪当前页码（节流） */
function initPageTracking() {
  const host = $("#pdf-scroll");
  host.addEventListener("scroll", () => {
    clearTimeout(S._pageInfoTimer);
    S._pageInfoTimer = setTimeout(updatePageInfo, 120);
  });
}

function updatePageInfo() {
  if (!S.pages.length) {
    $("#pdf-page-info").textContent = "0 / 0";
    return;
  }
  const host = $("#pdf-scroll");
  const mid = host.scrollTop + host.clientHeight / 2;
  let best = 1;
  for (const p of S.pages) {
    if (p.el.offsetTop <= mid) best = +p.el.dataset.page;
    else break;
  }
  S.pageNum = best;
  $("#pdf-page-info").textContent = `${best} / ${S.pages.length}`;
}

function scrollToPage(n) {
  const p = S.pages[n - 1];
  if (!p) return;
  renderPageEl(n);
  $("#pdf-scroll").scrollTo({ top: Math.max(0, p.el.offsetTop - 8), behavior: "smooth" });
}

function pageStep(delta) {
  scrollToPage(Math.min(S.pages.length, Math.max(1, S.pageNum + delta)));
}

function placeMarker() {
  const m = $("#pdf-marker");
  if (!S.marker) {
    m.hidden = true;
    return;
  }
  const p = S.pages[S.marker.page - 1];
  if (!p) {
    m.hidden = true;
    return;
  }
  p.el.appendChild(m); // 标记跟随所在页
  m.hidden = false;
  // synctex CLI 输入/输出的 y 均为页面顶部原点，与页面容器一致
  m.style.left = (S.marker.x * S.scale - 13) + "px";
  m.style.top = (S.marker.y * S.scale - 13) + "px";
}

async function showPdfAt(page, x, y, opts = {}) {
  if (!S.pdfDoc) {
    toast("请先编译出 PDF");
    return;
  }
  if (page < 1 || page > S.pages.length) return;
  const p = S.pages[page - 1];
  if (opts.marker !== false) {
    S.marker = { page, x, y };
    placeMarker();
  }
  await renderPageEl(page);
  const host = $("#pdf-scroll");
  // synctex 返回的 y 从页面顶部起算
  const top = p.el.offsetTop + y * S.scale;
  host.scrollTo({ top: Math.max(0, top - host.clientHeight / 2) });
  host.scrollLeft = Math.max(0, x * S.scale - host.clientWidth / 2);
}

/* 反向定位：点击 PDF → 源码 */
async function onPdfClick(e) {
  if (!S.pdfDoc || !S.slug) return;
  const pageEl = e.target.closest(".pdf-page");
  if (!pageEl) return;
  const p = S.pages[+pageEl.dataset.page - 1];
  if (!p) return;
  const rect = pageEl.getBoundingClientRect();
  const x = ((e.clientX - rect.left) / rect.width) * p.baseW;
  // synctex edit 的 y 也从页面顶部起算
  const y = ((e.clientY - rect.top) / rect.height) * p.baseH;
  const scroll = $("#pdf-scroll");
  scroll.classList.add("waiting");
  try {
    const r = await api(
      `/api/projects/${S.slug}/sync-backward`,
      json("POST", { page: +pageEl.dataset.page, x, y })
    );
    await openFile(r.file);
    if (r.line && r.line > 0) revealLine(r.line);
  } catch (err) {
    toast(err.message);
  } finally {
    scroll.classList.remove("waiting");
  }
}

/* 正向定位：光标 → PDF */
async function forwardSync() {
  if (!S.slug || !S.currentFile) return;
  const pos = S.editor.getPosition();
  if (!pos) return;
  const btn = $("#btn-sync");
  setBusy(btn, true);
  try {
    const r = await api(
      `/api/projects/${S.slug}/sync-forward`,
      json("POST", { file: S.currentFile, line: pos.lineNumber, col: pos.column })
    );
    await showPdfAt(r.page, r.x, r.y);
  } catch (e) {
    toast(e.message);
  } finally {
    setBusy(btn, false);
  }
}

/* 编辑器滚动 → PDF 联动（节流，防抖 600ms） */
function scheduleScrollSync() {
  if (!S.pdfScrollSync || S._skipScrollSync) {
    S._skipScrollSync = false;
    return;
  }
  clearTimeout(S._scrollSyncTimer);
  S._scrollSyncTimer = setTimeout(scrollSyncNow, 600);
}

async function scrollSyncNow() {
  if (!S.pdfScrollSync || !S.pdfDoc || !S.slug || !S.currentFile) return;
  if (!$("#pdf-scroll").offsetParent) return; // PDF 面板隐藏（手机编辑视图）
  const vis = S.editor.getVisibleRanges?.()?.[0];
  if (!vis) return;
  try {
    const r = await api(
      `/api/projects/${S.slug}/sync-forward`,
      json("POST", { file: S.currentFile, line: vis.startLineNumber, col: 0 })
    );
    if (!S.pdfScrollSync) return; // 等待期间被关闭
    await showPdfAt(r.page, r.x, r.y, { marker: false });
  } catch {
    /* 该行未出现在 PDF 中等情况，静默 */
  }
}

/* ================= 日志 ================= */
function showLog(log) {
  $("#log-content").textContent = log;
  $("#log-drawer").hidden = false;
}

/* ================= 历史版本 ================= */
async function openHistory() {
  if (!S.slug) return;
  const list = $("#history-list");
  $("#diff-view").textContent = "选择左侧的提交查看变更";
  $("#history-modal").hidden = false;
  showLoading(list, "加载历史记录…");
  let commits;
  try {
    commits = await api(`/api/projects/${S.slug}/history`);
  } catch (e) {
    list.innerHTML = "";
    $("#history-modal").hidden = true;
    toast(e.message);
    return;
  }
  list.innerHTML = "";
  for (const c of commits) {
    const li = document.createElement("li");
    li.className = "history-item";
    const info = document.createElement("div");
    info.className = "history-info";
    info.innerHTML = `<b>${escapeHtml(c.message)}</b><span>${c.short} · ${c.date}</span>`;
    info.onclick = () => showDiff(c.sha);
    const btn = document.createElement("button");
    btn.textContent = "恢复";
    btn.onclick = async () => {
      if (!confirm(`恢复到 ${c.short}（${c.message}）？\n当前内容将被该版本覆盖。`)) return;
      setBusy(btn, true);
      try {
        await api(`/api/projects/${S.slug}/history/${c.sha}/restore`, { method: "POST" });
        await refreshFiles();
        const cur = S.currentFile || S.meta.main_file;
        S.currentFile = null;
        await openFile(cur);
        scheduleCompile(0);
        $("#history-modal").hidden = true;
      } catch (err) {
        alert(err.message);
      } finally {
        setBusy(btn, false);
      }
    };
    li.append(info, btn);
    list.appendChild(li);
  }
}

async function showDiff(sha) {
  try {
    const { diff } = await api(`/api/projects/${S.slug}/history/${sha}`);
    $("#diff-view").textContent = diff;
  } catch (e) {
    toast(e.message);
  }
}

/* ================= 事件绑定 ================= */
/* ================= AI 排版 ================= */
/* 两阶段：analyze 返回排版方案（diff 预览）→ 用户确认 → apply 写盘 + 编译自愈 */
const AI = { content: null, path: null };

function renderAiDiff(diff) {
  const html = escapeHtml(diff || "(无差异)").split("\n").map((ln) => {
    if (ln.startsWith("+")) return `<span class="diff-add">${ln}</span>`;
    if (ln.startsWith("-")) return `<span class="diff-del">${ln}</span>`;
    if (ln.startsWith("@@")) return `<span class="diff-hunk">${ln}</span>`;
    return ln;
  }).join("\n");
  $("#ai-diff").innerHTML = html;
}

function closeAiModal() {
  $("#ai-modal").hidden = true;
  $("#btn-ai-apply").disabled = false;
  AI.content = null;
}

async function aiAnalyze() {
  if (!S.slug || !S.currentFile) { toast("请先打开项目中的文件"); return; }
  if (!S.currentFile.endsWith(".tex")) { toast("AI 排版目前仅支持 .tex 文件"); return; }
  if (S.dirty) await saveNow(); // 确保 AI 读到最新内容
  const style = $("#ai-style").value;
  const btn = $("#btn-ai");
  setBusy(btn, true);
  setStatus("AI 正在分析排版…", "busy");
  try {
    const r = await api(`/api/projects/${S.slug}/ai/analyze`,
      json("POST", { path: S.currentFile, style }));
    if (!r.changed) {
      setStatus("已分析");
      toast("AI 认为排版已良好：" + r.summary);
      return;
    }
    AI.content = r.content;
    AI.path = S.currentFile;
    $("#ai-summary").textContent = `【${r.style_name || style}】${r.summary}`;
    renderAiDiff(r.diff);
    $("#ai-status").textContent = "";
    $("#ai-status").className = "status";
    $("#btn-ai-apply").disabled = false;
    $("#ai-modal").hidden = false;
    setStatus(`等待确认 AI 排版方案 · ${r.style_name || style}`);
  } catch (e) {
    setStatus("AI 分析失败: " + e.message, "error");
    toast(e.message);
  } finally {
    setBusy(btn, false);
  }
}

async function aiApply() {
  if (!S.slug || !AI.content) return;
  const btn = $("#btn-ai-apply");
  btn.disabled = true;
  setBusy(btn, true);
  const st = $("#ai-status");
  st.textContent = "正在应用并编译…（编译失败会自动修复重试）";
  st.className = "status busy";
  try {
    const r = await api(`/api/projects/${S.slug}/ai/apply`,
      json("POST", { path: AI.path, content: AI.content, compile: true }));
    // 重新加载最终内容（自愈/回滚后可能与提案内容不同）
    const { content } = await api(
      `/api/projects/${S.slug}/file?path=${encodeURIComponent(AI.path)}`
    );
    S.loadingFile = true;
    S.editor.setValue(content);
    S.loadingFile = false;
    S.dirty = 0;
    updateCount();

    if (r.compile_unavailable) {
      st.textContent = "已应用。本机无法编译（未装 TeX Live），部署到服务器后请验证";
      st.className = "status";
      toast("AI 排版已应用（未编译）");
    } else if (r.success) {
      toast("AI 排版完成");
      $("#ai-modal").hidden = true;
      AI.content = null;
      applyErrorMarkers([]);
      showPdfOverlay("正在加载 PDF…");
      try { await loadPdf(); } finally { hidePdfOverlay(); }
      setStatus(r.rounds.length > 1
        ? `AI 排版完成 · 含 ${r.rounds.length - 1} 轮自动修复`
        : "AI 排版完成 · 编译一次通过");
    } else if (r.rolled_back) {
      st.textContent = "无法自动修复编译错误，已回滚到 AI 排版前的版本（详见「历史」）";
      st.className = "status error";
      toast("AI 排版失败，已回滚");
    }
  } catch (e) {
    st.textContent = "应用失败: " + e.message;
    st.className = "status error";
  } finally {
    setBusy(btn, false);
  }
}

function bindEvents() {
  $("#btn-compile").onclick = compile;
  $("#btn-sync").onclick = forwardSync;
  $("#btn-download").onclick = () => {
    if (S.slug) window.open(`/api/projects/${S.slug}/download-pdf`, "_blank");
  };
  $("#btn-history").onclick = openHistory;
  $("#btn-log-close").onclick = () => ($("#log-drawer").hidden = true);
  $("#btn-history-close").onclick = () => ($("#history-modal").hidden = true);
  $("#sb-errors").onclick = gotoNextError;
  $("#history-modal").onclick = (e) => {
    if (e.target === $("#history-modal")) $("#history-modal").hidden = true;
  };

  /* AI 排版 */
  $("#btn-ai").onclick = aiAnalyze;
  $("#btn-ai-cancel").onclick = closeAiModal;
  $("#btn-ai-close").onclick = closeAiModal;
  $("#btn-ai-apply").onclick = aiApply;
  $("#ai-modal").onclick = (e) => {
    if (e.target === $("#ai-modal")) closeAiModal();
  };
  $("#ai-style").onchange = () => saveUI({ aiStyle: $("#ai-style").value });

  $("#btn-new-project").onclick = openTemplateModal;
  $("#btn-template-close").onclick = () => ($("#template-modal").hidden = true);
  $("#template-modal").onclick = (e) => {
    if (e.target === $("#template-modal")) $("#template-modal").hidden = true;
  };
  $("#btn-template-create").onclick = createFromTemplate;

  $("#btn-new-file").onclick = async () => {
    if (!S.slug) {
      toast("请先创建项目");
      return;
    }
    const path = prompt("新文件路径（如 chapters/intro.tex）:");
    if (!path) return;
    const btn = $("#btn-new-file");
    setBusy(btn, true);
    try {
      await api(
        `/api/projects/${S.slug}/file?path=${encodeURIComponent(path)}`,
        json("PUT", { content: "" })
      );
      await refreshFiles();
      await openFile(path);
    } catch (e) {
      alert(e.message);
    } finally {
      setBusy(btn, false);
    }
  };

  $("#btn-upload").onclick = () => $("#upload-input").click();
  $("#upload-input").onchange = async (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file || !S.slug) return;
    const btn = $("#btn-upload");
    setBusy(btn, true);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("subdir", "");
    try {
      const res = await fetch(`/api/projects/${S.slug}/upload`, { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      await refreshFiles();
      toast(`已上传 ${data.path}`);
    } catch (err) {
      alert(err.message);
    } finally {
      setBusy(btn, false);
    }
  };

  /* PDF 工具栏 */
  $("#pdf-prev").onclick = () => pageStep(-1);
  $("#pdf-next").onclick = () => pageStep(1);
  const zoomBy = (f) => {
    S.zoom = Math.min(4, Math.max(0.3, S.zoom * f));
    saveUI({ zoom: S.zoom });
    relayoutPdf();
  };
  $("#pdf-zoom-in").onclick = () => zoomBy(1.25);
  $("#pdf-zoom-out").onclick = () => zoomBy(1 / 1.25);
  $("#pdf-fit").onclick = () => {
    S.zoom = 1;
    saveUI({ zoom: 1 });
    relayoutPdf();
  };
  $("#btn-sync-scroll").onclick = () => {
    S.pdfScrollSync = !S.pdfScrollSync;
    $("#btn-sync-scroll").classList.toggle("on", S.pdfScrollSync);
    saveUI({ syncScroll: S.pdfScrollSync });
    toast(S.pdfScrollSync ? "滚动同步已开启" : "滚动同步已关闭");
  };

  /* 文件快速切换 */
  const qsInput = $("#qs-input");
  qsInput.addEventListener("input", () => {
    S.qsSel = 0;
    renderQsList(qsInput.value);
  });
  qsInput.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      S.qsSel = Math.min(S.qsSel + 1, $("#qs-list li").length - 1);
      renderQsList(qsInput.value);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      S.qsSel = Math.max(S.qsSel - 1, 0);
      renderQsList(qsInput.value);
    } else if (e.key === "Enter") {
      e.preventDefault();
      qsOpenSelected();
    } else if (e.key === "Escape") {
      closeQuickSwitch();
    }
    e.stopPropagation(); // 不落到全局快捷键
  });
  $("#quick-switch").onclick = (e) => {
    if (e.target === $("#quick-switch")) closeQuickSwitch();
  };

  /* 全局快捷键 */
  document.addEventListener("keydown", (e) => {
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === "s") {
      e.preventDefault();
      saveNow(true);
    } else if (mod && e.key === "Enter") {
      e.preventDefault();
      compile();
    } else if (mod && e.key.toLowerCase() === "p") {
      e.preventDefault();
      openQuickSwitch();
    } else if (mod && (e.key === "=" || e.key === "+")) {
      e.preventDefault();
      zoomBy(1.25);
    } else if (mod && e.key === "-") {
      e.preventDefault();
      zoomBy(1 / 1.25);
    } else if (mod && e.key === "0") {
      e.preventDefault();
      S.zoom = 1;
      saveUI({ zoom: 1 });
      relayoutPdf();
    } else if (e.key === "F8") {
      e.preventDefault();
      gotoNextError();
    } else if (e.key === "Escape") {
      if (!$("#quick-switch").hidden) closeQuickSwitch();
    } else if (e.key === "PageDown" || e.key === "PageUp") {
      // 焦点在编辑器/输入框时保留原生翻页
      if (e.target.closest?.(".monaco-editor, textarea, input, #quick-switch")) return;
      e.preventDefault();
      pageStep(e.key === "PageDown" ? 1 : -1);
    }
  });

  /* 窗口尺寸变化 → PDF 重排（防抖） */
  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      if (S.pdfDoc) relayoutPdf();
    }, 200);
  });

  initPageTracking();
}

/* ================= Monaco 增强注册 ================= */
/* 常用命令补全（label 展示 / 插入体 / 说明） */
const TEX_CMDS = [
  ["\\section{}", "section{$0}", "节"],
  ["\\subsection{}", "subsection{$0}", "小节"],
  ["\\subsubsection{}", "subsubsection{$0}", "子小节"],
  ["\\textbf{}", "textbf{$0}", "粗体"],
  ["\\textit{}", "textit{$0}", "斜体"],
  ["\\emph{}", "emph{$0}", "强调"],
  ["\\underline{}", "underline{$0}", "下划线"],
  ["\\frac{}{}", "frac{$1}{$2}", "分式"],
  ["\\dfrac{}{}", "dfrac{$1}{$2}", "分式（展示型）"],
  ["\\sqrt{}", "sqrt{$0}", "根号"],
  ["\\sum_{}^{}", "sum_{$1}^{$2}", "求和"],
  ["\\int_{}^{}", "int_{$1}^{$2}", "积分"],
  ["\\lim_{}", "lim_{$1}", "极限"],
  ["\\cdot", "cdot", "居中点"],
  ["\\ldots", "ldots", "省略号"],
  ["\\label{}", "label{$0}", "标签（供 \\ref 引用）"],
  ["\\ref{}", "ref{$0}", "交叉引用"],
  ["\\eqref{}", "eqref{$0}", "公式引用"],
  ["\\cite{}", "cite{$0}", "文献引用"],
  ["\\footnote{}", "footnote{$0}", "脚注"],
  ["\\item", "item", "列表项"],
  ["\\usepackage{}", "usepackage{$0}", "引入宏包"],
  ["\\includegraphics{}", "includegraphics[width=$1\\textwidth]{$2}", "插图"],
  ["\\title{}", "title{$0}", "标题"],
  ["\\author{}", "author{$0}", "作者"],
  ["\\maketitle", "maketitle", "生成标题页"],
  ["\\tableofcontents", "tableofcontents", "目录"],
  ["\\newcommand", "newcommand{\\${1:cmd}}[${2:0}]{$0}", "自定义命令"],
];

const TEX_ENVS = [
  "itemize", "enumerate", "description", "center", "flushleft", "flushright",
  "figure", "table", "equation", "equation*", "align", "align*", "gather",
  "cases", "matrix", "pmatrix", "bmatrix", "tabular", "quote", "quotation",
  "verbatim", "abstract", "proof", "thebibliography",
];

function registerLatexExtras() {
  if (!window.monaco || !monaco.languages) return;

  /* 本项目内置的精简 Monaco 未带 latex 语言包，setMonarchTokensProvider 前必须先注册，
     否则 setModelLanguage 静默失败、高亮/补全/折叠全部不生效 */
  if (!monaco.languages.getLanguages().some((l) => l.id === "latex")) {
    monaco.languages.register({ id: "latex" });
    monaco.languages.setMonarchTokensProvider("latex", {
      control: /[\\][a-zA-Z@]+\*?/,
      tokenizer: {
        root: [
          [/%.*$/, "comment"],
          [/\\(?:begin|end)\b/, { token: "keyword", next: "@envname" }],
          [/[\\][a-zA-Z@]+\*?/, "keyword"],
          [/\\[\\{}$&#^_~%]/, "operator"],
          [/\$\$/, { token: "string", next: "@mathdisplay" }],
          [/\$/, { token: "string", next: "@mathinline" }],
          [/[{}]/, "delimiter.curly"],
          [/[[\]]/, "delimiter.square"],
          [/[&~^_]/, "operator"],
        ],
        envname: [
          [/[a-zA-Z*]+/, "type.identifier"],
          [/\}/, { token: "delimiter.curly", next: "@pop" }],
          [/\{/, "delimiter.curly"],
        ],
        mathinline: [
          [/\\[a-zA-Z@]+/, "keyword"],
          [/\$/, { token: "string", next: "@pop" }],
          [/./, "variable"],
        ],
        mathdisplay: [
          [/\\[a-zA-Z@]+/, "keyword"],
          [/\$\$/, { token: "string", next: "@pop" }],
          [/./, "variable"],
        ],
      },
    });
    monaco.languages.setLanguageConfiguration("latex", {
      comments: { lineComment: "%" },
      brackets: [["{", "}"], ["[", "]"], ["(", ")"]],
      autoClosingPairs: [
        { open: "{", close: "}" },
        { open: "[", close: "]" },
        { open: "(", close: ")" },
        { open: "`", close: "'" },
      ],
      surroundingPairs: [
        { open: "{", close: "}" },
        { open: "[", close: "]" },
        { open: "(", close: ")" },
        { open: "$", close: "$" },
      ],
    });
  }

  const K = monaco.languages.CompletionItemKind;
  const R = monaco.Range;

  monaco.languages.registerCompletionItemProvider("latex", {
    triggerCharacters: ["\\", "{"],
    provideCompletionItems(model, position) {
      const line = model.getLineContent(position.lineNumber).slice(0, position.column - 1);
      const col = position.column;

      // \ref 家族 → .aux 标签
      let m = line.match(/\\(?:eq|page|auto|v|c|C)?ref\{([^{}]*)$/);
      if (m) {
        const partial = m[1].split(",").pop();
        return { suggestions: S.labels.labels.map((name) => ({
          label: name,
          insertText: name,
          kind: K.Reference,
          detail: "\\ref 标签",
          range: new R(position.lineNumber, col - partial.length, position.lineNumber, col),
        })) };
      }
      // \cite 家族 → .bib 条目
      m = line.match(/\\[a-zA-Z]*cite[a-zA-Z]*\{([^{}]*)$/);
      if (m) {
        const partial = m[1].split(",").pop();
        return { suggestions: S.labels.bibkeys.map((name) => ({
          label: name,
          insertText: name,
          kind: K.Reference,
          detail: "文献条目",
          range: new R(position.lineNumber, col - partial.length, position.lineNumber, col),
        })) };
      }
      // \begin{ → 环境（自动带 \end）
      m = line.match(/\\begin\{([^{}]*)$/);
      if (m) {
        return { suggestions: TEX_ENVS.map((env) => ({
          label: env,
          insertText: `${env}\n\t${"$"}0\n\\end{${env}}`,
          insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
          kind: K.Snippet,
          detail: "环境（自动闭合）",
          range: new R(position.lineNumber, col - m[1].length, position.lineNumber, col),
        })) };
      }
      // \ 命令补全
      m = line.match(/\\([a-zA-Z]*)$/);
      if (m) {
        const items = TEX_CMDS.map(([label, insert, detail]) => ({
          label,
          insertText: insert,
          insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
          kind: K.Snippet,
          detail,
          range: new R(position.lineNumber, col - m[1].length, position.lineNumber, col),
        }));
        items.push({
          label: "\\begin{...}",
          insertText: `begin{${"${1|itemize,enumerate,center,equation,align,figure,table,quote,verbatim|}"}}\n\t${"$"}0\n\\end{${"$"}1}`,
          insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
          kind: K.Snippet,
          detail: "环境（自动闭合）",
          range: new R(position.lineNumber, col - m[1].length, position.lineNumber, col),
        });
        return { suggestions: items };
      }
      return { suggestions: [] };
    },
  });

  /* 按 \section 层级与 \begin...\end 边界折叠 */
  const SEC_LEVELS = { part: 0, chapter: 1, section: 2, subsection: 3, subsubsection: 4, paragraph: 5 };
  monaco.languages.registerFoldingRangeProvider("latex", {
    provideFoldingRanges(model) {
      const ranges = [];
      const stack = []; // {line, kind:"sec"|"env", lvl?}
      const secRe = /^\\(part|chapter|section|subsection|subsubsection|paragraph)\*?\s*[{[]/;
      const beginRe = /^\\begin\{/;
      const endRe = /^\\end\{/;
      const total = model.getLineCount();
      const Region = monaco.languages.FoldingRangeKind.Region;
      for (let n = 1; n <= total; n++) {
        const t = model.getLineContent(n).trimStart();
        if (t.startsWith("%")) continue;
        const s = t.match(secRe);
        if (s) {
          const lvl = SEC_LEVELS[s[1]];
          while (stack.length && stack[stack.length - 1].kind === "sec" && stack[stack.length - 1].lvl >= lvl) {
            const st = stack.pop();
            if (n - 1 > st.line) ranges.push({ start: st.line, end: n - 1, kind: Region });
          }
          stack.push({ line: n, kind: "sec", lvl });
        } else if (beginRe.test(t)) {
          stack.push({ line: n, kind: "env" });
        } else if (endRe.test(t)) {
          let idx = -1;
          for (let i = stack.length - 1; i >= 0; i--) {
            if (stack[i].kind === "env") { idx = i; break; }
          }
          if (idx >= 0) {
            const st = stack[idx];
            if (n > st.line) ranges.push({ start: st.line, end: n, kind: Region });
            stack.length = idx;
          }
        }
      }
      for (const st of stack) {
        if (total > st.line) ranges.push({ start: st.line, end: total, kind: Region });
      }
      return ranges;
    },
  });

  /* Ctrl+Shift+I 格式化文档 → 后端 latexindent */
  monaco.languages.registerDocumentFormattingEditProvider("latex", {
    async provideDocumentFormattingEdits(model, options, token) {
      if (!S.slug || !S.currentFile || model !== S.editor?.getModel()) return null;
      try {
        const r = await api(
          `/api/projects/${S.slug}/format`,
          json("POST", { content: model.getValue() })
        );
        return [{ range: model.getFullModelRange(), text: r.content }];
      } catch (e) {
        toast("格式化失败: " + e.message);
        return null;
      }
    },
  });
}

/* ================= 编辑器初始化（含降级） ================= */
function initMonacoEditor() {
  S.editor = monaco.editor.create(document.getElementById("editor-host"), {
    value: "",
    language: "latex",
    theme: "vs",
    fontSize: 14,
    // 文泉驿等宽覆盖拉丁+中文+全角标点，放最前避免 Monaco 逐字回退缺字
    fontFamily: "'WenQuanYi Zen Hei Mono', 'DejaVu Sans Mono', monospace",
    fontLigatures: true,
    minimap: { enabled: false },
    automaticLayout: true,
    wordWrap: "on",
    scrollBeyondLastLine: false,
    fixedOverflowWidgets: true,
    renderLineHighlight: "all",
    cursorBlinking: "smooth",
    smoothScrolling: true,
    padding: { top: 12, bottom: 12 },
    // LaTeX 嵌套组深，彩虹括号提升可读性
    bracketPairColorization: { enabled: true },
    folding: true,
    // 中文全角标点会被默认当作"歧义字符"加黄框，写中文必须关掉
    unicodeHighlight: {
      ambiguousCharacters: false,
      invisibleCharacters: false,
    },
  });
  S.editor.onDidChangeModelContent(() => {
    if (S.loadingFile) return;
    updateCount();
    scheduleSave();
  });
  S.editor.onDidChangeCursorPosition((e) => {
    $("#sb-pos").textContent = `Ln ${e.position.lineNumber}, Col ${e.position.column}`;
  });
  S.editor.onDidScrollChange(() => scheduleScrollSync());
  registerLatexExtras();
}

/* Monaco 加载/初始化失败时的纯文本降级，保证编辑与按钮可用 */
function initFallbackEditor() {
  const host = document.getElementById("editor-host");
  host.innerHTML = "";
  const ta = document.createElement("textarea");
  ta.id = "fallback-editor";
  ta.spellcheck = false;
  host.appendChild(ta);
  S.editor = {
    getValue: () => ta.value,
    setValue: (v) => { ta.value = v; },
    getPosition: () => ({ lineNumber: 1, column: 1 }),
    setPosition: () => {},
    revealLineInCenter: () => {},
    layout: () => {},
    deltaDecorations: () => [],
    setModelLanguage: () => {},
    getModel: () => null,
    getVisibleRanges: () => [],
  };
  ta.addEventListener("input", () => {
    if (S.loadingFile) return;
    updateCount();
    scheduleSave();
  });
}

/* 按钮绑定 / 数据加载与 Monaco 解耦，确保任何情况下按钮都有响应 */
function bootstrap() {
  const ui = loadUI();
  // 恢复上次的分栏比例 / PDF 缩放 / 滚动同步开关
  if (ui.split) {
    S._splitFrac = ui.split;
    $("#editor-host").style.flex = `0 0 ${(ui.split * 100).toFixed(2)}%`;
  }
  if (ui.zoom) S.zoom = Math.min(4, Math.max(0.3, ui.zoom));
  S.pdfScrollSync = ui.syncScroll !== false;
  $("#btn-sync-scroll").classList.toggle("on", S.pdfScrollSync);

  // 恢复上次选择的 AI 排版标准，并与服务端同步可选标准
  if (ui.aiStyle) $("#ai-style").value = ui.aiStyle;
  api("/api/ai/styles").then((styles) => {
    if (!Array.isArray(styles) || !styles.length) return;
    const sel = $("#ai-style");
    const cur = sel.value;
    sel.innerHTML = styles.map((s) =>
      `<option value="${escapeHtml(s.id)}">${escapeHtml(s.name)}</option>`).join("");
    if ([...sel.options].some((o) => o.value === cur)) sel.value = cur;
  }).catch(() => {});

  initResizer();
  initMobile();
  bindEvents();
  loadProjects();
  // 调试/自动化测试钩子
  window.LW = S;
}

/* ================= 启动 ================= */
pdfjsLib.GlobalWorkerOptions.workerSrc = "/static/vendor/pdfjs/pdf.worker.min.js";

if (typeof require !== "undefined") {
  require.config({ paths: { vs: "/static/vendor/monaco" } });
  require(["vs/editor/editor.main"], function () {
    try {
      initMonacoEditor();
    } catch (e) {
      console.error("Monaco 初始化失败，降级为文本框:", e);
      initFallbackEditor();
    }
    bootstrap();
  }, function (err) {
    console.error("Monaco 加载失败，降级为文本框:", err);
    initFallbackEditor();
    bootstrap();
  });
  // 兜底：若 8 秒内仍未启动（脚本卡住），强制降级启动
  setTimeout(() => {
    if (!window.LW) {
      if (!S.editor) initFallbackEditor();
      bootstrap();
    }
  }, 8000);
} else {
  initFallbackEditor();
  bootstrap();
}
