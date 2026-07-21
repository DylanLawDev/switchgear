import { KeyboardEvent, TextareaHTMLAttributes, useEffect, useRef, useState } from "react";
import { apiGet, apiSend } from "../api/client";
import { ReferenceSuggestion } from "../api/types";
import Button from "./Button";
import styles from "./SmartTextarea.module.css";

interface Props extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "value" | "onChange"> {
  value: string;
  onChange: (value: string) => void;
  assistPreset?: "prompt" | "workflow" | "parameters";
  workflow?: string;
}

interface Token { start: number; end: number; parent: string; query: string }

function tokenAt(value: string, caret: number): Token | null {
  const before = value.slice(0, caret);
  const at = before.lastIndexOf("@");
  if (at < 0 || (at > 0 && before[at - 1] === "@")) return null;
  const raw = before.slice(at);
  if (/\s/.test(raw)) return null;
  const dot = raw.lastIndexOf(".");
  return dot < 0
    ? { start: at, end: caret, parent: "", query: raw.slice(1) }
    : { start: at, end: caret, parent: raw.slice(0, dot), query: raw.slice(dot + 1) };
}

export default function SmartTextarea({ value, onChange, assistPreset, workflow = "", className, ...props }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [token, setToken] = useState<Token | null>(null);
  const [suggestions, setSuggestions] = useState<ReferenceSuggestion[]>([]);
  const [active, setActive] = useState(0);
  const [helpOpen, setHelpOpen] = useState(false);
  const [helpPrompt, setHelpPrompt] = useState("");
  const [helpResult, setHelpResult] = useState<string | null>(null);
  const [helpError, setHelpError] = useState<string | null>(null);
  const [helpBusy, setHelpBusy] = useState(false);

  useEffect(() => {
    if (!token) { setSuggestions([]); return; }
    const params = new URLSearchParams({ parent: token.parent, q: token.query });
    let live = true;
    apiGet<ReferenceSuggestion[]>(`/api/references/suggest?${params}`).then((rows) => {
      if (live) { setSuggestions(rows); setActive(0); }
    }).catch(() => { if (live) setSuggestions([]); });
    return () => { live = false; };
  }, [token?.parent, token?.query]);

  function refreshToken() {
    const el = ref.current;
    setToken(el ? tokenAt(value, el.selectionStart) : null);
  }

  function accept(row: ReferenceSuggestion) {
    if (!token) return;
    const suffix = row.has_children ? "." : "";
    const next = value.slice(0, token.start) + row.path + suffix + value.slice(token.end);
    onChange(next);
    const caret = token.start + row.path.length + suffix.length;
    requestAnimationFrame(() => {
      if (!ref.current) return;
      ref.current.focus(); ref.current.selectionStart = ref.current.selectionEnd = caret;
      setToken(row.has_children ? { start: token.start, end: caret, parent: row.path, query: "" } : null);
    });
  }

  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (suggestions.length) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        setActive((i) => (i + (event.key === "ArrowDown" ? 1 : -1) + suggestions.length) % suggestions.length);
        return;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        event.preventDefault(); accept(suggestions[active]); return;
      }
      if (event.key === "Escape") { event.preventDefault(); setToken(null); return; }
    }
    props.onKeyDown?.(event);
  }

  async function runHelp() {
    if (!assistPreset || !helpPrompt.trim()) return;
    setHelpBusy(true); setHelpError(null); setHelpResult(null);
    try {
      const result = await apiSend<{ ok: boolean; output?: unknown; error?: string }>("POST", `/api/assist/${assistPreset}`, {
        prompt: helpPrompt, draft: value, workflow,
      });
      if (!result.ok) throw new Error(result.error || "assistance failed");
      setHelpResult(typeof result.output === "string" ? result.output : JSON.stringify(result.output, null, 2));
    } catch (error) { setHelpError(error instanceof Error ? error.message : String(error)); }
    finally { setHelpBusy(false); }
  }

  return (
    <div className={styles.wrap}>
      <textarea
        {...props}
        ref={ref}
        className={[styles.textarea, className].filter(Boolean).join(" ")}
        value={value}
        onChange={(event) => {
          const next = event.target.value;
          onChange(next);
          setToken(tokenAt(next, event.target.selectionStart));
        }}
        onClick={refreshToken}
        onKeyUp={(event) => { if (!["ArrowDown", "ArrowUp", "Enter", "Tab", "Escape"].includes(event.key)) refreshToken(); props.onKeyUp?.(event); }}
        onKeyDown={keyDown}
      />
      {assistPreset && <button type="button" className={styles.star} aria-label="open embedded help" onClick={() => setHelpOpen((v) => !v)}>✦</button>}
      {suggestions.length > 0 && (
        <div className={styles.suggestions} role="listbox" aria-label="reference suggestions">
          {suggestions.map((row, i) => <button type="button" role="option" aria-selected={i === active}
            className={i === active ? styles.active : ""} key={row.path} onMouseDown={(e) => { e.preventDefault(); accept(row); }}>
            <strong>{row.label}</strong><span>{row.type}</span>{row.description && <small>{row.description}</small>}
          </button>)}
        </div>
      )}
      {helpOpen && <div className={styles.help}>
        <label>What should the helper produce?</label>
        <textarea aria-label="What should the helper produce?" value={helpPrompt} onChange={(e) => setHelpPrompt(e.target.value)} autoFocus />
        <div className={styles.helpActions}><Button onClick={runHelp} disabled={helpBusy}>{helpBusy ? "Working…" : "Generate"}</Button><Button variant="ghost" onClick={() => setHelpOpen(false)}>Close</Button></div>
        {helpError && <p role="alert" className={styles.error}>{helpError}</p>}
        {helpResult !== null && <><pre>{helpResult}</pre><div className={styles.helpActions}><Button variant="primary" onClick={() => { onChange(helpResult); setHelpOpen(false); }}>Replace</Button><Button onClick={() => { onChange(value + helpResult); setHelpOpen(false); }}>Insert</Button></div></>}
      </div>}
    </div>
  );
}
