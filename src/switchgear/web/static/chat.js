const messages = document.getElementById("messages");
const form = document.getElementById("composer");
const input = document.getElementById("input");
const params = new URLSearchParams(location.search);
const convId = params.get("c") || crypto.randomUUID();

function addMsg(role, text) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = text;
  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
  return div;
}

function addTool(name) {
  const d = document.createElement("details");
  d.className = "tool";
  const s = document.createElement("summary");
  s.textContent = `→ ${name}`;
  d.appendChild(s);
  messages.appendChild(d);
  return d;
}

async function loadHistory() {
  const res = await fetch(`/api/conversations/${convId}`);
  for (const m of await res.json()) addMsg(m.role, m.content);
  const convs = await (await fetch("/api/conversations")).json();
  const nav = document.getElementById("convs");
  nav.replaceChildren(...convs.map((c) => {
    const a = document.createElement("a");
    a.href = `/?c=${encodeURIComponent(c._id)}`;
    a.textContent = c.title;
    return a;
  }));
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  addMsg("user", text);
  const assistant = addMsg("assistant", "");
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ conversation_id: convId, message: text }),
  });
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const line = buf.slice(0, idx).trim();
      buf = buf.slice(idx + 2);
      if (!line.startsWith("data: ")) continue;
      const ev = JSON.parse(line.slice(6));
      if (ev.type === "text") assistant.textContent += ev.delta;
      else if (ev.type === "tool_call") addTool(ev.name);
      else if (ev.type === "error") addMsg("error", ev.reason);
    }
  }
});

loadHistory();
