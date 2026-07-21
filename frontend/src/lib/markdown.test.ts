import { mdToHtml } from "./markdown";

test("escapes html before transforming", () => {
  expect(mdToHtml('<img src=x onerror=alert(1)>')).toContain("&lt;img");
  expect(mdToHtml('<script>x</script>')).toContain("&lt;script&gt;");
});

test("subset renders", () => {
  expect(mdToHtml("# Title")).toContain("<h1>Title</h1>");
  expect(mdToHtml("**b** and `c`")).toContain("<strong>b</strong>");
  expect(mdToHtml("[t](https://x.dev)")).toContain('rel="noopener noreferrer"');
  expect(mdToHtml("[t](javascript:alert(1))")).not.toContain("<a");
  expect(mdToHtml("- a\n- b")).toContain("<ul>");
});

test("renders heading levels", () => {
  expect(mdToHtml("## Sub")).toContain("<h2>Sub</h2>");
  expect(mdToHtml("### Sub")).toContain("<h3>Sub</h3>");
});

test("italic and paragraphs", () => {
  expect(mdToHtml("*i*")).toContain("<em>i</em>");
  expect(mdToHtml("line one\nline two")).toContain("line one<br>line two");
});

test("keeps mermaid fences identifiable for client rendering", () => {
  expect(mdToHtml("```mermaid\ngraph TD\nA-->B\n```")).toContain('class="language-mermaid"');
});

test("asterisk list marker also produces a list", () => {
  expect(mdToHtml("* a\n* b")).toContain("<ul>");
  expect(mdToHtml("* a\n* b")).toContain("<li>a</li>");
});

test("blank line separates paragraphs and closes lists", () => {
  const html = mdToHtml("- a\n\npara");
  expect(html).toContain("</ul>");
  expect(html).toContain("<p>para</p>");
});
