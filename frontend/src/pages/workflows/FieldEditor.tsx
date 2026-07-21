import styles from "./workflows.module.css";

export interface FieldEditorRow {
  selector: string;
  label: string;
  source: string;
  kind: string;
  value: string;
  needs_you: boolean;
}

// Parity workflow.js renderActionDetail field rows: `kind: "multiline"` renders a 10-row
// textarea, everything else a text input; both the value input and the needs-you checkbox
// are disabled unless the action is in an editable status (draft/failed).
export default function FieldEditor({
  rows,
  editable,
  onChange,
}: {
  rows: FieldEditorRow[];
  editable: boolean;
  onChange: (selector: string, patch: Partial<Pick<FieldEditorRow, "value" | "needs_you">>) => void;
}) {
  return (
    <div className={styles.fieldEditor}>
      {rows.map((row) => {
        const isMultiline = row.kind === "multiline";
        const inputId = `field-value-${row.selector}`;
        const needsYouId = `field-needs-you-${row.selector}`;
        return (
          <div key={row.selector} className={isMultiline ? `${styles.fieldRow} ${styles.multiline}` : styles.fieldRow}>
            <label htmlFor={inputId}>{`${row.label || row.selector} (${row.source || ""})`}</label>
            {isMultiline ? (
              <textarea
                id={inputId}
                rows={10}
                value={row.value}
                disabled={!editable}
                onChange={(e) => onChange(row.selector, { value: e.target.value })}
              />
            ) : (
              <input
                id={inputId}
                type="text"
                value={row.value}
                disabled={!editable}
                onChange={(e) => onChange(row.selector, { value: e.target.value })}
              />
            )}
            <label htmlFor={needsYouId}>
              <input
                id={needsYouId}
                type="checkbox"
                aria-label={`${row.label || row.selector} needs you`}
                checked={row.needs_you}
                disabled={!editable}
                onChange={(e) => onChange(row.selector, { needs_you: e.target.checked })}
              />
              {" needs you"}
            </label>
          </div>
        );
      })}
    </div>
  );
}
