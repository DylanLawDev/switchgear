async function api(path, method = "GET", body = null) {
  const opts = { method };
  if (body !== null) {
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(path, opts);
  if (!r.ok) {
    let detail = `${method} ${path} -> ${r.status}`;
    try { detail = (await r.json()).detail || detail; } catch { /* keep default */ }
    throw new Error(detail);
  }
  return r.json();
}

function button(label, onClick) {
  const b = document.createElement("button");
  b.textContent = label;
  b.addEventListener("click", onClick);
  return b;
}

function truncate(text, n = 160) {
  return text.length > n ? text.slice(0, n) + "…" : text;
}

async function render() {
  const type = document.getElementById("filter-type").value;
  const status = document.getElementById("filter-status").value;
  const params = new URLSearchParams();
  if (type) params.set("type", type);
  if (status) params.set("status", status);
  const qs = params.toString();
  const memories = await api(`/api/memories${qs ? "?" + qs : ""}`);
  const ul = document.getElementById("memories");
  ul.replaceChildren();
  for (const m of memories) {
    const li = document.createElement("li");
    const text = document.createElement("p");
    text.textContent = truncate(m.text);
    text.title = m.text;
    const meta = document.createElement("span");
    const accessed = m.last_accessed_at
      ? new Date(m.last_accessed_at * 1000).toLocaleString() : "never";
    meta.textContent = `[${m.type} · ${m.status} · importance ${m.importance}`
      + ` · ${m.source} · last accessed ${accessed}]`;
    li.append(text, meta);
    if (m.status === "active") {
      li.append(button("Edit", async () => {
        const next = prompt("Memory text:", m.text);
        if (next === null) return;
        try {
          await api(`/api/memories/${encodeURIComponent(m.key)}`, "PUT", { text: next });
        } catch (e) {
          alert(e.message);
        }
        render();
      }));
      li.append(button("Archive", async () => {
        await api(`/api/memories/${encodeURIComponent(m.key)}/archive`, "POST");
        render();
      }));
    } else if (m.status === "archived") {
      li.append(button("Restore", async () => {
        await api(`/api/memories/${encodeURIComponent(m.key)}/restore`, "POST");
        render();
      }));
    }
    li.append(button("Delete", async () => {
      if (!confirm("Hard-delete this memory?")) return;
      await api(`/api/memories/${encodeURIComponent(m.key)}`, "DELETE");
      render();
    }));
    ul.appendChild(li);
  }
}

document.getElementById("create-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = document.getElementById("create-text").value;
  const type = document.getElementById("create-type").value;
  const importance =
    parseInt(document.getElementById("create-importance").value, 10) || 5;
  try {
    await api("/api/memories", "POST", { text, type, importance });
    document.getElementById("create-text").value = "";
    render();
  } catch (err) {
    alert(err.message);
  }
});
document.getElementById("filter-type").addEventListener("change", render);
document.getElementById("filter-status").addEventListener("change", render);
render();
