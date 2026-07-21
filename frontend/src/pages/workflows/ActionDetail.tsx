import { useEffect, useState } from "react";
import { FieldDef } from "../../api/types";
import { ACTION_BUTTONS, ActionVerbName, useActionVerb, useWorkflowRecord } from "../../api/queries/workflows";
import Button from "../../components/Button";
import ConfirmDialog from "../../components/ConfirmDialog";
import FieldRenderer from "../../components/FieldRenderer";
import StatusChip from "../../components/StatusChip";
import FieldEditor, { FieldEditorRow } from "./FieldEditor";
import RejectDialog from "./RejectDialog";
import styles from "./workflows.module.css";

// Parity workflow.js EDITABLE / renderActionDetail's `editable` flag: fields (and their
// needs-you checkboxes) are only writable while the action is draft/failed.
const EDITABLE_STATUSES = new Set(["draft", "failed"]);

// screenshot/confirmation_screenshot aren't declared kind fields — they're rendered with the
// same image renderer + href_prefix convention as declared image fields (parity RENDERERS.image).
const SCREENSHOT_FIELD: FieldDef = { type: "image", href_prefix: "/screenshots/" };

export default function ActionDetail({ workflowName, actionKey }: { workflowName: string; actionKey: string }) {
  const { data } = useWorkflowRecord(workflowName, "actions", actionKey);
  const verb = useActionVerb(workflowName);
  const [rows, setRows] = useState<FieldEditorRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Scoped to actionKey ONLY (not `data`): the actions-list invalidate on a verb call
  // prefix-matches this detail query too, so a background refetch can land here with a
  // structurally-different-but-still-valid record (e.g. a bumped updated_at) — if that
  // reset the error, it would clobber the inline refusal message the user just triggered.
  // Only switching to a different action should clear it (parity workflow.js's stable,
  // never-auto-cleared `#action-error` node).
  useEffect(() => {
    setError(null);
  }, [actionKey]);

  useEffect(() => {
    if (!data) {
      setRows([]);
      return;
    }
    setRows(
      (data.record.fields || []).map((f) => ({
        selector: f.selector,
        label: f.label,
        source: f.source,
        kind: f.kind,
        value: f.value ?? "",
        needs_you: !!f.needs_you,
      })),
    );
  }, [data]);

  if (!data) return null;
  const { record, item } = data;
  const editable = EDITABLE_STATUSES.has(record.status);

  function updateRow(selector: string, patch: Partial<Pick<FieldEditorRow, "value" | "needs_you">>) {
    setRows((prev) => prev.map((r) => (r.selector === selector ? { ...r, ...patch } : r)));
  }

  async function runVerb(verbName: ActionVerbName, body?: unknown) {
    setError(null);
    try {
      const result = await verb.mutateAsync({ key: actionKey, verb: verbName, body });
      if (result.error) setError(result.error); // 200-domain-refusal — inline, no toast (SPEC §5.4.1)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function handleSave() {
    return runVerb("fields", { fields: rows.map(({ selector, value, needs_you }) => ({ selector, value, needs_you })) });
  }

  return (
    <div className={styles.detail}>
      <h3>{item?.title ?? actionKey}</h3>
      <p>
        <StatusChip status={record.status} />
      </p>
      <FieldEditor rows={rows} editable={editable} onChange={updateRow} />
      {record.notes && <p className="dim">{record.notes}</p>}
      {record.rejected_comment && <p className="dim">{`rejected: ${record.rejected_comment}`}</p>}
      {(["screenshot", "confirmation_screenshot"] as const).map((name) => {
        const value = record[name];
        if (!value) return null;
        return (
          <p key={name}>
            <FieldRenderer field={SCREENSHOT_FIELD} value={value} mode="detail" />
          </p>
        );
      })}
      <div className={styles.btnRow}>
        {ACTION_BUTTONS.map((btn) => {
          const enabled = (btn.when as readonly string[]).includes(record.status);
          if (btn.id === "execute") {
            return (
              <ConfirmDialog
                key={btn.id}
                trigger={<Button disabled={!enabled}>{btn.label}</Button>}
                title={`${btn.label}?`}
                confirmLabel={btn.label}
                onConfirm={() => runVerb("execute")}
              />
            );
          }
          if (btn.id === "confirm-executed") {
            return (
              <ConfirmDialog
                key={btn.id}
                trigger={<Button disabled={!enabled}>{btn.label}</Button>}
                title={`${btn.label}?`}
                confirmLabel={btn.label}
                onConfirm={() => runVerb("confirm", { outcome: "executed" })}
              />
            );
          }
          if (btn.id === "reject") {
            return (
              <RejectDialog
                key={btn.id}
                trigger={<Button disabled={!enabled}>{btn.label}</Button>}
                onConfirm={(comment) => runVerb("reject", { comment })}
              />
            );
          }
          return (
            <Button
              key={btn.id}
              disabled={!enabled}
              onClick={() => {
                if (btn.id === "save") return handleSave();
                if (btn.id === "approve") return runVerb("approve");
                if (btn.id === "confirm-failed") return runVerb("confirm", { outcome: "failed" });
                return undefined;
              }}
            >
              {btn.label}
            </Button>
          );
        })}
        {error && (
          <span className={styles.detailError} role="alert">
            {error}
          </span>
        )}
      </div>
    </div>
  );
}
