async function api(path, method = "GET") {
  const r = await fetch(path, { method });
  if (!r.ok) throw new Error(`${method} ${path} -> ${r.status}`);
  return r.json();
}

function button(label, onClick) {
  const b = document.createElement("button");
  b.textContent = label;
  b.addEventListener("click", onClick);
  return b;
}

async function showRuns(name) {
  const runs = await api(`/api/skills/${encodeURIComponent(name)}/runs`);
  document.getElementById("runs-title").textContent = `Runs: ${name}`;
  const list = document.getElementById("runs-list");
  list.replaceChildren();
  for (const run of runs) {
    const li = document.createElement("li");
    const when = new Date((run.at || 0) * 1000).toLocaleString();
    li.textContent = `${when} · ${run.ok ? "ok" : "FAILED"} · ${run.usage} tok`
      + (run.error ? ` · ${run.error}` : "");
    list.appendChild(li);
  }
  document.getElementById("runs").hidden = false;
}

async function render() {
  const skills = await api("/api/skills");
  const ul = document.getElementById("skills");
  ul.replaceChildren();
  for (const s of skills) {
    const li = document.createElement("li");
    const head = document.createElement("strong");
    head.textContent = `${s.name} `;
    const meta = document.createElement("span");
    meta.textContent = `[${s.status} · ${s.source}]`;
    const desc = document.createElement("p");
    desc.textContent = s.description;
    li.append(head, meta, desc);
    if (s.status === "pending") {
      li.append(button("Approve", async () => {
        await api(`/api/skills/${encodeURIComponent(s.name)}/approve`, "POST");
        render();
      }));
    }
    li.append(button("Run", async () => {
      await api(`/api/skills/${encodeURIComponent(s.name)}/run`, "POST");
      showRuns(s.name);
    }));
    li.append(button("View runs", () => showRuns(s.name)));
    ul.appendChild(li);
  }
}

render();
