import DOMPurify from "dompurify";
import { marked } from "marked";

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

const renderer = new marked.Renderer();
renderer.html = ({ text }) => escapeHtml(text);

// Render GitHub-flavored markdown, then sanitize the generated HTML. Mermaid blocks remain
// ordinary fenced code here; MarkdownView upgrades them after the safe DOM is mounted.
export function mdToHtml(src: string): string {
  const html = marked.parse(String(src), { async: false, gfm: true, breaks: true, renderer }) as string;
  const safe = DOMPurify.sanitize(html, { ADD_ATTR: ["target", "rel"] });
  const template = document.createElement("template");
  template.innerHTML = safe;
  template.content.querySelectorAll("a").forEach((link) => {
    if (!link.getAttribute("href")) {
      link.replaceWith(...link.childNodes);
      return;
    }
    link.target = "_blank";
    link.rel = "noopener noreferrer";
  });
  return template.innerHTML;
}
