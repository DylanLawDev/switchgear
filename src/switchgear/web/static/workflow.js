// workflow.js — one renderer for every workflow. The definition JSON drives
// everything: field TYPES pick renderers, statuses gate buttons. Fallback
// chain: RENDERERS[field.renderer] || RENDERERS[field.type] || RENDERERS.json
// — no value ever renders blank.

const DEF = JSON.parse(document.getElementById("wf-def").textContent);
const API = `/api/workflows/${encodeURIComponent(DEF.name)}`;
const ROOT = document.getElementById("wf-root");

async function api(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`GET ${path} -> ${r.status}`);
  return r.json();
}

async function post(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(`POST ${path} -> ${r.status}`);
  return data;
}

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = text;
  return n;
}

function extLink(href, text, cls) {
  if (!/^https?:\/\//i.test(href) && !/^\/(?!\/)/.test(href)) {
    return el("span", cls || "", text);
  }
  const a = el("a", cls || "", text);
  a.href = href;
  a.target = "_blank";
  a.rel = "noopener";
  return a;
}

function relTime(ts) {
  if (!ts) return "";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

function absTime(ts) {
  return ts ? new Date(ts * 1000).toLocaleString() : "";
}

// Minimal safe markdown: escape everything first, then transform a small
// subset (headings, bold, italic, inline code, http(s) links, ul lists).
function mdToHtml(src) {
  const escd = String(src).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const inline = (s) => s
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener">$1</a>');
  const out = [];
  let list = false;
  let para = [];
  const flush = () => {
    if (para.length) { out.push(`<p>${inline(para.join(" "))}</p>`); para = []; }
  };
  const endList = () => { if (list) { out.push("</ul>"); list = false; } };
  for (const line of escd.split("\n")) {
    const h = line.match(/^(#{1,3}) (.*)/);
    if (h) {
      flush(); endList();
      const lvl = h[1].length + 2; // h3..h5: stay under the page h2s
      out.push(`<h${lvl}>${inline(h[2])}</h${lvl}>`);
    } else if (/^[-*] /.test(line)) {
      flush();
      if (!list) { out.push("<ul>"); list = true; }
      out.push(`<li>${inline(line.slice(2))}</li>`);
    } else if (line.trim() === "") {
      flush(); endList();
    } else {
      para.push(line);
    }
  }
  flush(); endList();
  return out.join("\n");
}

function artifactNode(v, field) {
  if (!v) return el("span", "dim", "—");
  if (field.href_prefix) {
    return extLink(field.href_prefix + encodeURIComponent(v), v, "wf-chip");
  }
  return el("span", "wf-chip", v);
}

const STATUS_CLS = { approved: "ok", executed: "ok", submitted: "ok",
  failed: "warn", possibly_executed: "warn", expired: "warn",
  draft: "signal", executing: "signal" };

const RENDERERS = {
  text: {
    cell: (v) => el("span", "", v == null ? "" : String(v).slice(0, 60)),
    detail: (v) => el("span", "", v == null ? "" : String(v)),
  },
  markdown: {
    cell: (v) => el("span", "dim",
      v ? String(v).replace(/[#*`]/g, "").slice(0, 80) : ""),
    detail(v) {
      const d = el("div", "md");
      d.innerHTML = mdToHtml(v || "");
      return d;
    },
  },
  number: {
    cell: (v) => el("span", "num", v == null ? "" : String(v)),
    detail: (v) => el("span", "num", v == null ? "" : String(v)),
  },
  score: {
    cell(v) {
      if (v == null) return el("span", "dim", "—");
      return el("span", v >= 60 ? "score-chip" : "score-chip low", String(v));
    },
    detail(v) { return RENDERERS.score.cell(v); },
  },
  boolean: {
    cell: (v) => el("span", "num", v ? "✓" : "—"),
    detail: (v) => el("span", "num", v ? "yes" : "no"),
  },
  enum: {
    cell: (v) => (v ? el("span", "wf-badge", String(v)) : el("span")),
    detail: (v) => (v ? el("span", "wf-badge", String(v)) : el("span")),
  },
  status: {
    cell: (v) => el("span", `status ${STATUS_CLS[v] || ""}`.trim(), v || ""),
    detail: (v) => RENDERERS.status.cell(v),
  },
  timestamp: {
    cell(v) {
      const s = el("span", "num", relTime(v));
      if (v) s.title = absTime(v);
      return s;
    },
    detail: (v) => el("span", "num", absTime(v)),
  },
  url: {
    cell(v) {
      if (!v) return el("span");
      let label = v;
      try { label = new URL(v).host; } catch { /* keep raw */ }
      return extLink(v, label);
    },
    detail: (v) => (v ? extLink(v, v) : el("span")),
  },
  image: {
    cell: (v, f) => (v ? extLink((f.href_prefix || "/screenshots/") +
      encodeURIComponent(v), v, "wf-chip") : el("span")),
    detail(v, f) {
      if (!v) return el("span", "dim", "—");
      const src = (f.href_prefix || "/screenshots/") + encodeURIComponent(v);
      const a = extLink(src, "");
      const img = el("img", "shot");
      img.src = src;
      img.alt = v;
      a.appendChild(img);
      return a;
    },
  },
  artifact: { cell: artifactNode, detail: artifactNode },
  relation: {
    cell: (v) => el("span", "", v && v.title ? v.title : ""),
    detail: (v) => el("span", "", v && v.title ? v.title : ""),
  },
  json: {
    cell: (v) => el("span", "dim", v == null ? "" : "{…}"),
    detail(v) {
      const pre = el("pre", "json");
      pre.textContent = JSON.stringify(v, null, 2);
      return pre;
    },
  },
};

function renderer(field) {
  return RENDERERS[field.renderer] || RENDERERS[field.type] || RENDERERS.json;
}

function fieldLabel(name) {
  return name.replace(/_/g, " ");
}

// ---------- generic tables ----------

function buildSection(kindName, kdef, columns) {
  const section = el("section", "kind-section");
  section.id = `kind-${kindName}`;
  section.appendChild(el("h2", "", kdef.label_plural));
  const wrap = el("div", "table-wrap");
  const table = el("table");
  const thead = el("thead");
  const hr = el("tr");
  for (const col of columns) hr.appendChild(el("th", "", col));
  thead.appendChild(hr);
  table.appendChild(thead);
  const tbody = el("tbody");
  tbody.id = `${kindName}-body`;
  table.appendChild(tbody);
  wrap.appendChild(table);
  section.appendChild(wrap);
  const empty = el("p", "empty", `No ${kdef.label_plural} yet.`);
  empty.id = `${kindName}-empty`;
  empty.hidden = true;
  section.appendChild(empty);
  const detail = el("div", "detail");
  detail.id = `${kindName}-detail`;
  detail.hidden = true;
  section.appendChild(detail);
  return section;
}

function detailGrid(kdef, record) {
  const grid = el("div", "detail-grid");
  const names = kdef.detail_fields || Object.keys(kdef.fields);
  for (const name of names) {
    grid.appendChild(el("label", "", fieldLabel(name)));
    const field = kdef.fields[name];
    grid.appendChild(renderer(field).detail(record[name], field, record));
  }
  return grid;
}

function rawSection(kdef, record, extraKnown) {
  const known = new Set([...Object.keys(kdef.fields), kdef.key_field,
    ...(extraKnown || [])]);
  const unknown = {};
  for (const [k, v] of Object.entries(record)) {
    if (!known.has(k)) unknown[k] = v;
  }
  if (!Object.keys(unknown).length) return null;
  const details = el("details", "raw");
  details.appendChild(el("summary", "", "raw"));
  const pre = el("pre", "json");
  pre.textContent = JSON.stringify(unknown, null, 2);
  details.appendChild(pre);
  return details;
}

function miniList(title, rows, onClick) {
  const box = el("div", "mini-list");
  box.appendChild(el("h4", "", title));
  for (const row of rows) {
    const line = el("button", "mini-row", row.text);
    line.type = "button";
    line.addEventListener("click", () => onClick(row));
    box.appendChild(line);
  }
  return box;
}

// ---------- items ----------

async function renderItems() {
  const records = await api(`${API}/items`);
  const tbody = document.getElementById("items-body");
  tbody.replaceChildren();
  for (const rec of records) {
    const tr = el("tr");
    for (const name of DEF.items.list_fields) {
      const field = DEF.items.fields[name];
      const td = el("td", ["number", "score", "timestamp", "boolean"]
        .includes(field.type) ? "num" : "");
      td.appendChild(renderer(field).cell(rec[name], field, rec));
      tr.appendChild(td);
    }
    tr.style.cursor = "pointer";
    tr.addEventListener("click", () => showItemDetail(rec[DEF.items.key_field]));
    tbody.appendChild(tr);
  }
  document.getElementById("items-empty").hidden = records.length > 0;
}

async function showItemDetail(key) {
  const data = await api(`${API}/items/${encodeURIComponent(key)}`);
  const box = document.getElementById("items-detail");
  box.hidden = false;
  box.replaceChildren();
  box.appendChild(el("h3", "", data.record[DEF.items.title_field] || key));
  box.appendChild(detailGrid(DEF.items, data.record));
  const raw = rawSection(DEF.items, data.record);
  if (raw) box.appendChild(raw);

  const row = el("div", "btn-row");
  const note = el("span", "detail-error");
  if (DEF.generate) {
    const b = el("button", "", DEF.generate.label);
    b.addEventListener("click", async () => {
      b.disabled = true;
      note.textContent = "working…";
      try {
        const out = await post(`${API}/items/${encodeURIComponent(key)}/generate`);
        note.textContent = out.error || "done";
        await renderArtifacts();
        await showItemDetail(key);
      } catch (e) {
        note.textContent = String(e);
      } finally {
        b.disabled = false;
      }
    });
    row.appendChild(b);
  }
  if (DEF.actions) {
    const b = el("button", "", `Draft ${DEF.actions.label}`);
    b.addEventListener("click", async () => {
      b.disabled = true;
      note.textContent = "working…";
      try {
        const out = await post(`${API}/items/${encodeURIComponent(key)}/act`);
        note.textContent = out.error || "";
        await renderActions();
        if (out[DEF.actions.key_field] || out.key) {
          await showActionDetail(out[DEF.actions.key_field] || out.key);
        }
      } catch (e) {
        note.textContent = String(e);
      } finally {
        b.disabled = false;
      }
    });
    row.appendChild(b);
  }
  row.appendChild(note);
  box.appendChild(row);

  if (DEF.artifacts && data.artifacts.length) {
    box.appendChild(miniList(DEF.artifacts.label_plural, data.artifacts.map((a) => ({
      text: a[DEF.artifacts.title_field] || a[DEF.artifacts.key_field],
      key: a[DEF.artifacts.key_field],
    })), (r) => showArtifactDetail(r.key)));
  }
  if (DEF.actions && data.actions.length) {
    box.appendChild(miniList(DEF.actions.label_plural, data.actions.map((a) => ({
      text: `${a.status} · ${relTime(a.created_at)}`, key: a.key,
    })), (r) => showActionDetail(r.key)));
  }
  box.scrollIntoView({ block: "nearest" });
}

// ---------- artifacts ----------

async function renderArtifacts() {
  if (!DEF.artifacts) return;
  const records = await api(`${API}/artifacts`);
  const tbody = document.getElementById("artifacts-body");
  tbody.replaceChildren();
  for (const rec of records) {
    const tr = el("tr");
    for (const name of DEF.artifacts.list_fields) {
      const field = DEF.artifacts.fields[name];
      const td = el("td", ["number", "score", "timestamp", "boolean"]
        .includes(field.type) ? "num" : "");
      td.appendChild(renderer(field).cell(rec[name], field, rec));
      tr.appendChild(td);
    }
    tr.style.cursor = "pointer";
    tr.addEventListener("click",
      () => showArtifactDetail(rec[DEF.artifacts.key_field]));
    tbody.appendChild(tr);
  }
  document.getElementById("artifacts-empty").hidden = records.length > 0;
}

async function showArtifactDetail(key) {
  const data = await api(`${API}/artifacts/${encodeURIComponent(key)}`);
  const box = document.getElementById("artifacts-detail");
  box.hidden = false;
  box.replaceChildren();
  box.appendChild(el("h3", "",
    data.record[DEF.artifacts.title_field] || key));
  if (data.item && data.item.title) {
    box.appendChild(el("p", "dim", `for ${data.item.title}`));
  }
  box.appendChild(detailGrid(DEF.artifacts, data.record));
  const raw = rawSection(DEF.artifacts, data.record,
    [DEF.artifacts.item_ref_field]);
  if (raw) box.appendChild(raw);
  box.scrollIntoView({ block: "nearest" });
}

// ---------- actions ----------

const ACTION_COLUMNS = ["item", "status", "needs you", "created"];

async function renderActions() {
  if (!DEF.actions) return;
  const rows = await api(`${API}/actions`);
  const tbody = document.getElementById("actions-body");
  tbody.replaceChildren();
  for (const row of rows) {
    const tr = el("tr");
    tr.appendChild(el("td", "", row.item ? row.item.title : ""));
    const st = el("td");
    st.appendChild(RENDERERS.status.cell(row.status));
    tr.appendChild(st);
    tr.appendChild(el("td", "num", String(row.needs_you)));
    const created = el("td", "num", relTime(row.created_at));
    created.title = absTime(row.created_at);
    tr.appendChild(created);
    tr.style.cursor = "pointer";
    tr.addEventListener("click", () => showActionDetail(row.key));
    tbody.appendChild(tr);
  }
  document.getElementById("actions-empty").hidden = rows.length > 0;
}

// Buttons ship with the layer; `when` mirrors the server's state machine.
// The server re-checks every transition — this gating is convenience only.
const ACTION_BUTTONS = [
  { id: "save", label: "Save fields", when: ["draft", "failed"], run: saveFields },
  { id: "approve", label: "Approve", when: ["draft", "failed"], run: approveAction },
  { id: "reject", label: "Reject", when: ["draft", "failed", "approved"],
    run: rejectAction },
  { id: "execute", label: "Execute", when: ["approved"], confirm: true,
    run: executeAction },
  { id: "confirm-executed", label: "Mark executed", when: ["possibly_executed"],
    confirm: true, run: (k) => confirmAction(k, "executed") },
  { id: "confirm-failed", label: "Mark failed", when: ["possibly_executed"],
    run: (k) => confirmAction(k, "failed") },
];

async function showActionDetail(key) {
  const data = await api(`${API}/actions/${encodeURIComponent(key)}`);
  renderActionDetail(key, data);
}

function renderActionDetail(key, data) {
  const record = data.record;
  const editable = ["draft", "failed"].includes(record.status);
  const box = document.getElementById("actions-detail");
  box.hidden = false;
  box.replaceChildren();
  box.dataset.key = key;

  box.appendChild(el("h3", "", data.item && data.item.title
    ? data.item.title : key));
  const st = el("p");
  st.appendChild(RENDERERS.status.detail(record.status));
  box.appendChild(st);

  const fieldsDiv = el("div");
  fieldsDiv.id = "action-fields";
  for (const field of record.fields || []) {
    const isMultiline = field.kind === "multiline";
    const row = el("div", isMultiline ? "field-row multiline" : "field-row");
    row.dataset.selector = field.selector;
    row.appendChild(el("label", "",
      `${field.label || field.selector} (${field.source || ""})`));
    const input = isMultiline
      ? el("textarea", "field-value")
      : el("input", "field-value");
    if (!isMultiline) input.type = "text";
    else input.rows = 10;
    input.value = field.value || "";
    input.disabled = !editable;
    row.appendChild(input);
    const needsLabel = el("label");
    const cb = el("input", "field-needs-you");
    cb.type = "checkbox";
    cb.checked = !!field.needs_you;
    cb.disabled = !editable;
    needsLabel.appendChild(cb);
    needsLabel.appendChild(document.createTextNode(" needs you"));
    row.appendChild(needsLabel);
    fieldsDiv.appendChild(row);
  }
  box.appendChild(fieldsDiv);

  if (record.notes) box.appendChild(el("p", "dim", record.notes));
  if (record.rejected_comment) {
    box.appendChild(el("p", "dim", `rejected: ${record.rejected_comment}`));
  }
  for (const name of ["screenshot", "confirmation_screenshot"]) {
    if (record[name]) {
      const p = el("p");
      p.appendChild(RENDERERS.image.detail(record[name], {}));
      box.appendChild(p);
    }
  }

  const row = el("div", "btn-row");
  const note = el("span", "detail-error");
  note.id = "action-error";
  for (const btn of ACTION_BUTTONS) {
    const b = el("button", "", btn.label);
    b.disabled = !btn.when.includes(record.status);
    b.addEventListener("click", async () => {
      if (btn.confirm && !window.confirm(`${btn.label}?`)) return;
      note.textContent = "working…";
      try {
        await btn.run(key);
      } catch (e) {
        note.textContent = String(e);
      }
    });
    row.appendChild(b);
  }
  row.appendChild(note);
  box.appendChild(row);
  box.scrollIntoView({ block: "nearest" });
}

async function refreshAction(key, out) {
  const note = document.getElementById("action-error");
  if (out && out.error) {
    note.textContent = out.error;
    await renderActions();
    return;
  }
  await renderActions();
  await showActionDetail(key);
}

async function saveFields(key) {
  const fields = [];
  for (const row of document.querySelectorAll("#action-fields .field-row")) {
    fields.push({
      selector: row.dataset.selector,
      value: row.querySelector(".field-value").value,
      needs_you: row.querySelector(".field-needs-you").checked,
    });
  }
  const out = await post(`${API}/actions/${encodeURIComponent(key)}/fields`,
    { fields });
  await refreshAction(key, out);
}

async function approveAction(key) {
  const out = await post(`${API}/actions/${encodeURIComponent(key)}/approve`);
  await refreshAction(key, out);
}

async function rejectAction(key) {
  const comment = window.prompt("Why reject? (required)");
  if (!comment) return;
  const out = await post(`${API}/actions/${encodeURIComponent(key)}/reject`,
    { comment });
  await refreshAction(key, out);
}

async function executeAction(key) {
  const out = await post(`${API}/actions/${encodeURIComponent(key)}/execute`);
  await refreshAction(key, out);
}

async function confirmAction(key, outcome) {
  const out = await post(`${API}/actions/${encodeURIComponent(key)}/confirm`,
    { outcome });
  await refreshAction(key, out);
}

// ---------- boot ----------

ROOT.appendChild(buildSection("items", DEF.items,
  DEF.items.list_fields.map(fieldLabel)));
if (DEF.artifacts) {
  ROOT.appendChild(buildSection("artifacts", DEF.artifacts,
    DEF.artifacts.list_fields.map(fieldLabel)));
}
if (DEF.actions) {
  ROOT.appendChild(buildSection("actions", DEF.actions, ACTION_COLUMNS));
}

renderItems();
renderArtifacts();
renderActions();
