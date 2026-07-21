const CHANNEL = document.body.dataset.channel;
const BASE = `/api/channels/${encodeURIComponent(CHANNEL)}`;

async function api(path, method = "GET", body = null) {
  const opts = { method };
  if (body !== null) {
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `${method} ${path} -> ${r.status}`);
  return data;
}

function fmtTime(ts) {
  return ts ? new Date(ts * 1000).toLocaleString() : "never";
}

async function renderStatus() {
  const el = document.getElementById("status-line");
  try {
    const s = await api(BASE);
    el.textContent = `${s.address || "(no address)"} · `
      + `${s.active ? "active" : "inactive"} · cursor ${s.cursor || "(none)"}`
      + ` · last poll ${fmtTime(s.last_poll)}`;
  } catch (e) {
    el.textContent = e.message;
  }
}

document.getElementById("poll-now").addEventListener("click", async () => {
  const err = document.getElementById("status-error");
  try {
    await api(`${BASE}/poll`, "POST");
    err.textContent = "";
  } catch (e) {
    err.textContent = e.message;
  }
  renderStatus();
});

function fillForm(fn) {
  document.getElementById("fn-name").value = fn.name;
  document.getElementById("fn-description").value = fn.description;
  document.getElementById("fn-gate").value = fn.gate;
  document.getElementById("fn-rule-type").value = fn.recipient_rule.type;
  document.getElementById("fn-addresses").value =
    fn.recipient_rule.address || (fn.recipient_rule.addresses || []).join(", ");
  document.getElementById("fn-rate").value = fn.rate_limit_per_day;
  document.getElementById("fn-enabled").checked = fn.enabled;
  document.getElementById("fn-subject").value = fn.subject_template;
  document.getElementById("fn-body").value = fn.body_template;
  document.getElementById("fn-params").value =
    JSON.stringify(fn.params, null, 2);
}

function readForm() {
  const paramsText = document.getElementById("fn-params").value.trim();
  let params = {};
  if (paramsText) {
    try {
      params = JSON.parse(paramsText);
    } catch {
      throw new Error("params must be valid JSON");
    }
  }
  const ruleType = document.getElementById("fn-rule-type").value;
  const addresses = document.getElementById("fn-addresses").value
    .split(",").map((s) => s.trim()).filter(Boolean);
  let rule = { type: ruleType };
  if (ruleType === "fixed") rule = { type: "fixed", address: addresses[0] || "" };
  if (ruleType === "allowlist") rule = { type: "allowlist", addresses };
  return {
    name: document.getElementById("fn-name").value.trim(),
    description: document.getElementById("fn-description").value,
    params,
    subject_template: document.getElementById("fn-subject").value,
    body_template: document.getElementById("fn-body").value,
    recipient_rule: rule,
    gate: document.getElementById("fn-gate").value,
    rate_limit_per_day:
      parseInt(document.getElementById("fn-rate").value, 10) || 0,
    enabled: document.getElementById("fn-enabled").checked,
  };
}

async function renderFunctions() {
  const rows = await api(`${BASE}/send-functions`);
  const ul = document.getElementById("fn-list");
  ul.replaceChildren();
  for (const fn of rows) {
    const li = document.createElement("li");
    const head = document.createElement("strong");
    head.textContent = `${fn.name} `;
    const meta = document.createElement("span");
    meta.textContent = `[${fn.recipient_rule.type} · gate ${fn.gate}`
      + ` · ${fn.rate_limit_per_day}/day`
      + ` · ${fn.enabled ? "enabled" : "disabled"}]`;
    const edit = document.createElement("button");
    edit.textContent = "Edit";
    edit.addEventListener("click", () => fillForm(fn));
    const del = document.createElement("button");
    del.textContent = "Delete";
    del.addEventListener("click", async () => {
      await api(`${BASE}/send-functions/${encodeURIComponent(fn.name)}`,
                "DELETE");
      renderFunctions();
    });
    li.append(head, meta, edit, del);
    ul.appendChild(li);
  }
}

document.getElementById("fn-save").addEventListener("click", async () => {
  const err = document.getElementById("fn-error");
  try {
    const doc = readForm();
    await api(`${BASE}/send-functions/${encodeURIComponent(doc.name)}`,
              "PUT", doc);
    err.textContent = "";
    renderFunctions();
  } catch (e) {
    err.textContent = e.message;
  }
});

async function renderSuppression() {
  const rows = await api(`${BASE}/suppression`);
  const ul = document.getElementById("suppression-list");
  ul.replaceChildren();
  for (const row of rows) {
    const li = document.createElement("li");
    const span = document.createElement("span");
    span.textContent = `${row.address} `;
    const rm = document.createElement("button");
    rm.textContent = "Remove";
    rm.addEventListener("click", async () => {
      await api(`${BASE}/suppression/${encodeURIComponent(row.address)}`,
                "DELETE");
      renderSuppression();
    });
    li.append(span, rm);
    ul.appendChild(li);
  }
}

document.getElementById("suppress-add").addEventListener("click", async () => {
  const err = document.getElementById("suppression-error");
  const address = document.getElementById("suppress-address").value.trim();
  try {
    await api(`${BASE}/suppression/${encodeURIComponent(address)}`, "PUT");
    err.textContent = "";
    document.getElementById("suppress-address").value = "";
    renderSuppression();
  } catch (e) {
    err.textContent = e.message;
  }
});

// ---- flagged triage queue (email channel phase 3) ----
// textContent ONLY below: subjects/senders/reasons derive from attacker mail.

async function refileMessage(channel, key) {
  await fetch(`/api/channels/${encodeURIComponent(channel)}/messages/` +
              `${encodeURIComponent(key)}/refile`,
              {method: 'POST', headers: {'Content-Type': 'application/json'},
               body: JSON.stringify({route: 'file'})});
  await loadFlagged();
}

async function loadFlagged() {
  const section = document.getElementById('flagged-section');
  if (!section) return;
  const channel = section.dataset.channel;
  const resp = await fetch(`/api/channels/${encodeURIComponent(channel)}/flagged`);
  if (!resp.ok) return;
  const rows = await resp.json();
  const list = document.getElementById('flagged-list');
  list.replaceChildren();
  const empty = document.getElementById('flagged-empty');
  if (empty) empty.hidden = rows.length > 0;
  for (const row of rows) {
    const li = document.createElement('li');
    li.className = 'flagged-row';
    const cells = [
      ['flagged-subject', row.subject || '(no subject)'],
      ['flagged-sender', row.sender || ''],
      ['flagged-received',
       row.received_at ? new Date(row.received_at * 1000).toLocaleString() : ''],
      ['flagged-reason', row.triage_reason || ''],
    ];
    for (const [cls, text] of cells) {
      const span = document.createElement('span');
      span.className = cls;
      span.textContent = text;
      li.appendChild(span);
    }
    const btn = document.createElement('button');
    btn.textContent = 'File';
    btn.addEventListener('click', () => refileMessage(channel, row.key));
    li.appendChild(btn);
    list.appendChild(li);
  }
}

renderStatus();
renderFunctions();
renderSuppression();
loadFlagged();
