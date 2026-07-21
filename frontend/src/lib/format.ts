export function relTime(ts: number | null | undefined): string {
  if (!ts) return "";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}
export function absTime(ts: number | null | undefined): string {
  return ts ? new Date(ts * 1000).toLocaleString() : "";
}
export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
export function fmtDuration(seconds: number): string {   // 604800 -> "7d" (ttl chips)
  for (const [unit, div] of [["d", 86400], ["h", 3600], ["m", 60]] as const) {
    if (seconds % div === 0 && seconds >= div) return `${seconds / div}${unit}`;
  }
  return `${seconds}s`;
}
