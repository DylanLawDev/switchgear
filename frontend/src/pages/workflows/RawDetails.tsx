import { KindDef, WorkflowRecord } from "../../api/types";
import styles from "./workflows.module.css";

// Parity workflow.js rawSection: undeclared keys (not in kind.fields/key_field/extraKnown)
// render under a collapsed <details> as pretty JSON. Renders nothing when there's nothing raw.
export default function RawDetails({
  kind,
  record,
  extraKnown,
}: {
  kind: KindDef;
  record: WorkflowRecord;
  extraKnown?: string[];
}) {
  const known = new Set([...Object.keys(kind.fields), kind.key_field, ...(extraKnown ?? [])]);
  const unknown: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(record)) {
    if (!known.has(k)) unknown[k] = v;
  }
  if (Object.keys(unknown).length === 0) return null;
  return (
    <details className={styles.raw}>
      <summary>raw</summary>
      <pre className="json">{JSON.stringify(unknown, null, 2)}</pre>
    </details>
  );
}
