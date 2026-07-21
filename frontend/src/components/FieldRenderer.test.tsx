import { render, screen } from "@testing-library/react";
import { FieldDef } from "../api/types";
import FieldRenderer from "./FieldRenderer";
import scoreStyles from "./ScoreChip.module.css";
import statusStyles from "./StatusChip.module.css";

const NOW = 1_700_000_000; // fixed instant so relTime() is deterministic

function renderField(field: FieldDef, value: unknown, mode: "cell" | "detail" = "cell") {
  return render(<FieldRenderer field={field} value={value} mode={mode} />);
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW * 1000);
});
afterEach(() => vi.useRealTimers());

test("score >= 60 renders the signal-tinted chip", () => {
  renderField({ type: "score" }, 72);
  const chip = screen.getByText("72");
  expect(chip.className).toContain(scoreStyles.signal);
});

test("score < 60 renders the low/dim chip", () => {
  renderField({ type: "score" }, 41);
  const chip = screen.getByText("41");
  expect(chip.className).toContain(scoreStyles.low);
});

test("score null renders the dim dash", () => {
  renderField({ type: "score" }, null);
  expect(screen.getByText("—")).toBeInTheDocument();
});

test("timestamp cell shows relTime with title=absTime", () => {
  const ts = NOW - 3600; // 1h ago
  renderField({ type: "timestamp" }, ts);
  const el = screen.getByText("1h ago");
  expect(el).toHaveAttribute("title", new Date(ts * 1000).toLocaleString());
});

test("timestamp detail shows absTime", () => {
  const ts = NOW - 3600;
  renderField({ type: "timestamp" }, ts, "detail");
  expect(screen.getByText(new Date(ts * 1000).toLocaleString())).toBeInTheDocument();
});

test("url cell renders a host-label link with target=_blank rel=noopener for safe hrefs", () => {
  renderField({ type: "url" }, "https://a.dev/x");
  const link = screen.getByRole("link", { name: "a.dev" });
  expect(link).toHaveAttribute("href", "https://a.dev/x");
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveAttribute("rel", "noopener");
});

test("url detail renders plain text (no anchor) for an unsafe javascript: href", () => {
  renderField({ type: "url" }, "javascript:x", "detail");
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  expect(screen.getByText("javascript:x")).toBeInTheDocument();
});

test("url detail uses the full url as the label", () => {
  renderField({ type: "url" }, "https://a.dev/x", "detail");
  expect(screen.getByRole("link", { name: "https://a.dev/x" })).toBeInTheDocument();
});

test("json detail pretty-prints", () => {
  const { container } = renderField({ type: "json" }, { a: 1, b: [2, 3] }, "detail");
  const pre = container.querySelector("pre.json");
  expect(pre?.textContent).toBe(JSON.stringify({ a: 1, b: [2, 3] }, null, 2));
});

test("json cell shows the {…} placeholder", () => {
  renderField({ type: "json" }, { a: 1 });
  expect(screen.getByText("{…}")).toBeInTheDocument();
});

test("unknown field type falls back to the json renderer", () => {
  const weirdField = { type: "mystery" } as unknown as FieldDef;
  const { container } = renderField(weirdField, { z: 9 }, "detail");
  const pre = container.querySelector("pre.json");
  expect(pre?.textContent).toBe(JSON.stringify({ z: 9 }, null, 2));
});

test("renderer override wins over type when both resolve", () => {
  const field = { type: "text", renderer: "markdown" } as FieldDef;
  renderField(field, "**bold**", "cell");
  // markdown cell strips markup chars and truncates — "**bold**" -> "bold"
  expect(screen.getByText("bold")).toBeInTheDocument();
});

test("markdown detail escapes html (no script execution, tags shown as text)", () => {
  const { container } = renderField({ type: "markdown" }, "<script>alert(1)</script>", "detail");
  expect(container.querySelector("script")).not.toBeInTheDocument();
  expect(container.innerHTML).toContain("&lt;script&gt;");
});

test("markdown cell strips markdown punctuation and truncates to 80 chars", () => {
  const long = "#".repeat(5) + "*".repeat(5) + "`".repeat(5) + "x".repeat(90);
  renderField({ type: "markdown" }, long);
  const stripped = long.replace(/[#*`]/g, "").slice(0, 80);
  expect(screen.getByText(stripped)).toBeInTheDocument();
});

test("text cell truncates at 60 chars, detail shows the full string", () => {
  const long = "y".repeat(90);
  renderField({ type: "text" }, long, "cell");
  expect(screen.getByText(long.slice(0, 60))).toBeInTheDocument();
  renderField({ type: "text" }, long, "detail");
  expect(screen.getByText(long)).toBeInTheDocument();
});

test("number and boolean render right-aligned mono, boolean as check/dash", () => {
  renderField({ type: "number" }, 42);
  expect(screen.getByText("42")).toBeInTheDocument();
  renderField({ type: "boolean" }, true);
  expect(screen.getByText("✓")).toBeInTheDocument();
  renderField({ type: "boolean" }, false, "detail");
  expect(screen.getByText("no")).toBeInTheDocument();
});

test("enum renders a dim Badge when set, nothing when empty", () => {
  renderField({ type: "enum" }, "remote");
  expect(screen.getByText("remote")).toBeInTheDocument();
  const { container } = renderField({ type: "enum" }, null);
  expect(container.textContent).toBe("");
});

test("status renders StatusChip with the STATUS_CLS tone", () => {
  renderField({ type: "status" }, "approved");
  const chip = screen.getByText("approved");
  expect(chip.className).toContain(statusStyles.ok);
});

test("relation shows value.title", () => {
  renderField({ type: "relation" }, { key: "k1", title: "Some Job" });
  expect(screen.getByText("Some Job")).toBeInTheDocument();
});

test("image cell is a chip link under href_prefix, detail is an <img>", () => {
  renderField({ type: "image", href_prefix: "/screenshots/" }, "shot.png");
  const link = screen.getByRole("link", { name: "shot.png" });
  expect(link).toHaveAttribute("href", "/screenshots/shot.png");

  const { container } = renderField({ type: "image" }, "shot.png", "detail");
  const img = container.querySelector("img");
  expect(img).toHaveAttribute("src", "/screenshots/shot.png");
  expect(img).toHaveAttribute("alt", "shot.png");
});

test("artifact chip honors href_prefix, falls back to plain chip without it", () => {
  renderField({ type: "artifact", href_prefix: "/resumes/" }, "r.pdf");
  expect(screen.getByRole("link", { name: "r.pdf" })).toHaveAttribute("href", "/resumes/r.pdf");

  renderField({ type: "artifact" }, "r.pdf");
  expect(screen.queryAllByRole("link")).toHaveLength(1); // the href_prefix case only
  expect(screen.getAllByText("r.pdf").length).toBeGreaterThan(0);
});
