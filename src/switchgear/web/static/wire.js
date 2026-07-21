(async () => {
  const text = document.getElementById("wire-text");
  if (!text) return;
  try {
    const r = await fetch("/api/skills");
    if (!r.ok) return;
    const skills = await r.json();
    const n = skills.filter((s) => s.status === "active").length;
    text.textContent = `agent on duty · ${n} skill${n === 1 ? "" : "s"} active`;
  } catch {
    /* keep the static text */
  }
})();
