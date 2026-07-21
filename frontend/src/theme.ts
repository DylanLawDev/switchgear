export type Theme = "dark" | "light";
const KEY = "switchgear-theme";
export function getTheme(): Theme {
  return (document.documentElement.dataset.theme as Theme) || "dark";
}
export function setTheme(t: Theme): void {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem(KEY, t); } catch { /* private mode */ }
}
export function toggleTheme(): Theme {
  const next: Theme = getTheme() === "dark" ? "light" : "dark";
  setTheme(next);
  return next;
}
