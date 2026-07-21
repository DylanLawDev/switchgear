// safeHref — parity with static/workflow.js extLink's href gate: only http(s) URLs or
// single-slash relative paths are safe to render as anchors; everything else (javascript:,
// data:, protocol-relative //, mailto:, ...) is rejected.
export function safeHref(href: string): string | null {
  if (/^https?:\/\//i.test(href) || /^\/(?!\/)/.test(href)) return href;
  return null;
}
