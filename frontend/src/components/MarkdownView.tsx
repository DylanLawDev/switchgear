import { useEffect, useRef } from "react";
import { mdToHtml } from "../lib/markdown";
import styles from "./MarkdownView.module.css";

let diagramId = 0;

export default function MarkdownView({ source }: { source: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const html = mdToHtml(source);

  useEffect(() => {
    const root = ref.current;
    const blocks = root?.querySelectorAll<HTMLElement>("pre code.language-mermaid");
    if (!blocks?.length) return;
    let cancelled = false;
    void import("mermaid").then(async ({ default: mermaid }) => {
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: "strict",
        theme: document.documentElement.dataset.theme === "light" ? "default" : "dark",
      });
      for (const block of blocks) {
        if (cancelled || !block.isConnected) return;
        const pre = block.parentElement;
        if (!pre) continue;
        try {
          const { svg } = await mermaid.render(`switchgear-mermaid-${++diagramId}`, block.textContent ?? "");
          if (cancelled) return;
          const container = document.createElement("div");
          container.className = styles.mermaid;
          container.innerHTML = svg;
          pre.replaceWith(container);
        } catch {
          pre.setAttribute("title", "Unable to render Mermaid diagram");
        }
      }
    });
    return () => { cancelled = true; };
  }, [html]);

  return <div ref={ref} className={styles.md} dangerouslySetInnerHTML={{ __html: html }} />;
}
