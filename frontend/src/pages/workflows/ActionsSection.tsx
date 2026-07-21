import { WorkflowDefinition } from "../../api/types";
import { useWorkflowKind } from "../../api/queries/workflows";
import StatusChip from "../../components/StatusChip";
import { absTime, relTime } from "../../lib/format";
import tableStyles from "../../components/RecordTable.module.css";
import ActionDetail from "./ActionDetail";
import styles from "./workflows.module.css";

// Parity workflow.js ACTION_COLUMNS: item · status · needs you · created — fixed, not driven
// by kind.fields (actions rows are a projection, not the declared action record shape).
export default function ActionsSection({
  workflowName,
  definition,
  selectedKey,
  onSelect,
}: {
  workflowName: string;
  definition: WorkflowDefinition;
  selectedKey: string | null;
  onSelect: (key: string) => void;
}) {
  const kind = definition.actions;
  const { data: rows = [] } = useWorkflowKind(workflowName, "actions");
  if (!kind) return null;

  return (
    <section className={styles.kindSection}>
      <h2>{kind.label_plural}</h2>
      {rows.length === 0 ? (
        <p className={tableStyles.empty}>No {kind.label_plural} yet.</p>
      ) : (
        <div className={tableStyles.wrap}>
          <table className={tableStyles.table}>
            <thead>
              <tr>
                <th className={tableStyles.th}>item</th>
                <th className={tableStyles.th}>status</th>
                <th className={tableStyles.th} style={{ textAlign: "right" }}>
                  needs you
                </th>
                <th className={tableStyles.th} style={{ textAlign: "right" }}>
                  created
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.key} className={tableStyles.row} onClick={() => onSelect(row.key)}>
                  <td className={tableStyles.td}>{row.item?.title ?? ""}</td>
                  <td className={tableStyles.td}>
                    <StatusChip status={row.status} />
                  </td>
                  <td className={tableStyles.td} style={{ textAlign: "right" }}>
                    {row.needs_you}
                  </td>
                  <td className={tableStyles.td} style={{ textAlign: "right" }} title={absTime(row.created_at)}>
                    {relTime(row.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {selectedKey && <ActionDetail workflowName={workflowName} actionKey={selectedKey} />}
    </section>
  );
}
