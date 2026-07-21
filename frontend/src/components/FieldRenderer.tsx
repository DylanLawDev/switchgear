import { ReactNode } from "react";
import { FieldDef, ItemRef, WorkflowRecord } from "../api/types";
import { safeHref } from "../lib/links";
import { absTime, relTime } from "../lib/format";
import Badge from "./Badge";
import ScoreChip from "./ScoreChip";
import StatusChip from "./StatusChip";
import MarkdownView from "./MarkdownView";
import styles from "./FieldRenderer.module.css";

export type FieldRenderMode = "cell" | "detail";

// Direct TS port of static/workflow.js extLink: only http(s) or single-slash-relative hrefs
// render as anchors; everything else (javascript:, data:, //protocol-relative, ...) renders
// as inert text — same XSS posture as the parity renderer.
function ExtLink({ href, children, className }: { href: string; children: ReactNode; className?: string }) {
  const safe = safeHref(href);
  if (!safe) return <span className={className}>{children}</span>;
  return (
    <a href={safe} target="_blank" rel="noopener" className={className}>
      {children}
    </a>
  );
}

function hostLabel(v: string): string {
  try {
    return new URL(v).host;
  } catch {
    return v;
  }
}

function artifactNode(v: unknown, field: FieldDef): ReactNode {
  if (!v) return <span className="dim">—</span>;
  const s = String(v);
  if (field.href_prefix) {
    return (
      <ExtLink href={field.href_prefix + encodeURIComponent(s)} className={styles.chip}>
        {s}
      </ExtLink>
    );
  }
  return <span className={styles.chip}>{s}</span>;
}

interface RendererEntry {
  cell(value: unknown, field: FieldDef, record?: WorkflowRecord): ReactNode;
  detail(value: unknown, field: FieldDef, record?: WorkflowRecord): ReactNode;
}

const RENDERERS: Record<string, RendererEntry> = {
  text: {
    cell: (v) => <span>{v == null ? "" : String(v).slice(0, 60)}</span>,
    detail: (v) => <span>{v == null ? "" : String(v)}</span>,
  },
  markdown: {
    cell: (v) => <span className="dim">{v ? String(v).replace(/[#*`]/g, "").slice(0, 80) : ""}</span>,
    detail: (v) => <MarkdownView source={v ? String(v) : ""} />,
  },
  number: {
    cell: (v) => <span className="num">{v == null ? "" : String(v)}</span>,
    detail: (v) => <span className="num">{v == null ? "" : String(v)}</span>,
  },
  score: {
    cell: (v) => <ScoreChip value={typeof v === "number" ? v : null} />,
    detail: (v) => <ScoreChip value={typeof v === "number" ? v : null} />,
  },
  boolean: {
    cell: (v) => <span className="num">{v ? "✓" : "—"}</span>,
    detail: (v) => <span className="num">{v ? "yes" : "no"}</span>,
  },
  enum: {
    cell: (v) => (v ? <Badge tone="dim">{String(v)}</Badge> : <span />),
    detail: (v) => (v ? <Badge tone="dim">{String(v)}</Badge> : <span />),
  },
  status: {
    cell: (v) => <StatusChip status={v ? String(v) : ""} />,
    detail: (v) => <StatusChip status={v ? String(v) : ""} />,
  },
  timestamp: {
    cell: (v) => {
      const ts = typeof v === "number" ? v : null;
      return (
        <span className="num" title={ts ? absTime(ts) : undefined}>
          {relTime(ts)}
        </span>
      );
    },
    detail: (v) => <span className="num">{absTime(typeof v === "number" ? v : null)}</span>,
  },
  url: {
    cell: (v) => {
      if (!v) return <span />;
      const s = String(v);
      return <ExtLink href={s}>{hostLabel(s)}</ExtLink>;
    },
    detail: (v) => {
      if (!v) return <span />;
      const s = String(v);
      return <ExtLink href={s}>{s}</ExtLink>;
    },
  },
  image: {
    cell: (v, field) => {
      if (!v) return <span />;
      const s = String(v);
      const src = (field.href_prefix ?? "/screenshots/") + encodeURIComponent(s);
      return (
        <ExtLink href={src} className={styles.chip}>
          {s}
        </ExtLink>
      );
    },
    detail: (v, field) => {
      if (!v) return <span className="dim">—</span>;
      const s = String(v);
      const src = (field.href_prefix ?? "/screenshots/") + encodeURIComponent(s);
      return (
        <ExtLink href={src}>
          <img className={styles.shot} src={src} alt={s} />
        </ExtLink>
      );
    },
  },
  artifact: { cell: artifactNode, detail: artifactNode },
  relation: {
    cell: (v) => <span>{v && typeof v === "object" && (v as ItemRef).title ? (v as ItemRef).title : ""}</span>,
    detail: (v) => <span>{v && typeof v === "object" && (v as ItemRef).title ? (v as ItemRef).title : ""}</span>,
  },
  json: {
    cell: (v) => <span className="dim">{v == null ? "" : "{…}"}</span>,
    detail: (v) => <pre className="json">{JSON.stringify(v, null, 2)}</pre>,
  },
};

function pickRenderer(field: FieldDef): RendererEntry {
  const byRenderer = field.renderer ? RENDERERS[field.renderer] : undefined;
  return byRenderer ?? RENDERERS[field.type] ?? RENDERERS.json;
}

export default function FieldRenderer({
  field,
  value,
  mode,
  record,
}: {
  field: FieldDef;
  value: unknown;
  mode: FieldRenderMode;
  record?: WorkflowRecord;
}) {
  const renderer = pickRenderer(field);
  return <>{renderer[mode](value, field, record)}</>;
}
