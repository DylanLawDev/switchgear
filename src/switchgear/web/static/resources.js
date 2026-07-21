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

let current = null;

async function showDetail(name) {
  const doc = await api(`/api/resources/${encodeURIComponent(name)}`);
  current = doc;
  document.getElementById("detail-title").textContent = doc.name;
  document.getElementById("detail-meta").textContent =
    `${doc.kind} · ${doc.size} bytes · ${doc.source}`
    + (doc.description ? ` · ${doc.description}` : "");
  document.getElementById("detail-content").value = doc.content;
  document.getElementById("detail-error").textContent = "";
  document.getElementById("detail").hidden = false;
}

async function render() {
  const resources = await api("/api/resources");
  const ul = document.getElementById("resources");
  ul.replaceChildren();
  for (const res of resources) {
    const li = document.createElement("li");
    const head = document.createElement("strong");
    head.textContent = `${res.name} `;
    const meta = document.createElement("span");
    meta.textContent = `[${res.kind} · ${res.size} B · ${res.source}]`;
    const desc = document.createElement("p");
    desc.textContent = res.description;
    const open = document.createElement("button");
    open.textContent = "Open";
    open.addEventListener("click", () => showDetail(res.name));
    li.append(head, meta, desc, open);
    ul.appendChild(li);
  }
}

document.getElementById("detail-save").addEventListener("click", async () => {
  if (!current) return;
  try {
    await api(`/api/resources/${encodeURIComponent(current.name)}`, "PUT", {
      kind: current.kind,
      description: current.description,
      content: document.getElementById("detail-content").value,
    });
    await render();
    await showDetail(current.name);
  } catch (e) {
    document.getElementById("detail-error").textContent = e.message;
  }
});

document.getElementById("detail-delete").addEventListener("click", async () => {
  if (!current) return;
  await api(`/api/resources/${encodeURIComponent(current.name)}`, "DELETE");
  current = null;
  document.getElementById("detail").hidden = true;
  render();
});

document.getElementById("create-save").addEventListener("click", async () => {
  const name = document.getElementById("create-name").value.trim();
  try {
    await api(`/api/resources/${encodeURIComponent(name)}`, "PUT", {
      kind: document.getElementById("create-kind").value,
      description: document.getElementById("create-description").value,
      content: document.getElementById("create-content").value,
    });
    document.getElementById("create-error").textContent = "";
    render();
  } catch (e) {
    document.getElementById("create-error").textContent = e.message;
  }
});

render();
