import { KindDef, WorkflowRecord } from "../api/types";
import FieldRenderer from "./FieldRenderer";
import styles from "./RecordTable.module.css";

// Parity workflow.js renderItems: these four field types render right-aligned.
const NUM_TYPES = new Set(["number", "score", "timestamp", "boolean"]);

export default function RecordTable({
  kind,
  records,
  onRowClick,
}: {
  kind: KindDef;
  records: WorkflowRecord[];
  onRowClick: (key: string) => void;
}) {
  if (records.length === 0) {
    return <p className={styles.empty}>No {kind.label_plural} yet.</p>;
  }
  return (
    <div className={styles.wrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            {kind.list_fields.map((name) => (
              <th
                key={name}
                className={styles.th}
                style={NUM_TYPES.has(kind.fields[name].type) ? { textAlign: "right" } : undefined}
              >
                {name.replace(/_/g, " ")}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {records.map((rec) => {
            const key = String(rec[kind.key_field]);
            return (
              <tr key={key} className={styles.row} onClick={() => onRowClick(key)}>
                {kind.list_fields.map((name) => {
                  const field = kind.fields[name];
                  return (
                    <td
                      key={name}
                      className={styles.td}
                      style={NUM_TYPES.has(field.type) ? { textAlign: "right" } : undefined}
                    >
                      <FieldRenderer field={field} value={rec[name]} mode="cell" record={rec} />
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
