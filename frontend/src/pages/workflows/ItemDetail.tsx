import { useState } from "react";
import { WorkflowDefinition } from "../../api/types";
import { useDraftAction, useGenerate, useWorkflowRecord } from "../../api/queries/workflows";
import Button from "../../components/Button";
import { relTime } from "../../lib/format";
import DetailGrid from "./DetailGrid";
import RawDetails from "./RawDetails";
import MiniList from "./MiniList";
import styles from "./workflows.module.css";

// Parity workflow.js showItemDetail: detail grid + raw + Generate/Draft buttons + artifacts
// and actions mini-lists.
export default function ItemDetail({
  workflowName,
  definition,
  itemKey,
  onSelectArtifact,
  onSelectAction,
}: {
  workflowName: string;
  definition: WorkflowDefinition;
  itemKey: string;
  onSelectArtifact?: (key: string) => void;
  onSelectAction?: (key: string) => void;
}) {
  const { data } = useWorkflowRecord(workflowName, "items", itemKey);
  const generate = useGenerate(workflowName);
  const draftAction = useDraftAction(workflowName);
  const [note, setNote] = useState<string | null>(null);

  const itemsDef = definition.items;
  if (!data || !itemsDef) return null;
  const { record, artifacts, actions } = data;
  const title = (record[itemsDef.title_field] as string | undefined) ?? itemKey;

  async function handleGenerate() {
    setNote("working…");
    try {
      const result = await generate.mutateAsync(itemKey);
      setNote(result.error ?? "done");
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e));
    }
  }

  // Parity workflow.js showItemDetail's Draft click handler: POST .../act, then — if a key
  // came back — open that action's detail (workflow.js:327: `out[key_field] ?? out.key`).
  async function handleDraft() {
    setNote("working…");
    try {
      const result = await draftAction.mutateAsync(itemKey);
      setNote(result.error ?? "");
      const actionsDef = definition.actions;
      const key = actionsDef ? (result[actionsDef.key_field] as string | undefined) ?? (result.key as string | undefined) : undefined;
      if (key) onSelectAction?.(key);
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className={styles.detail}>
      <h3>{title}</h3>
      <DetailGrid kind={itemsDef} record={record} />
      <RawDetails kind={itemsDef} record={record} />
      <div className={styles.btnRow}>
        {definition.generate && (
          <Button onClick={handleGenerate} disabled={generate.isPending}>
            {definition.generate.label}
          </Button>
        )}
        {definition.actions && (
          <Button onClick={handleDraft} disabled={draftAction.isPending}>
            {`Draft ${definition.actions.label}`}
          </Button>
        )}
        {note && <span className={styles.detailError}>{note}</span>}
      </div>
      {definition.artifacts && artifacts.length > 0 && (
        <MiniList
          title={definition.artifacts.label_plural}
          rows={artifacts.map((a) => ({
            text: String(
              (a[definition.artifacts!.title_field] as string | undefined) ?? a[definition.artifacts!.key_field],
            ),
            key: String(a[definition.artifacts!.key_field]),
          }))}
          onClick={(key) => onSelectArtifact?.(key)}
        />
      )}
      {definition.actions && actions.length > 0 && (
        <MiniList
          title={definition.actions.label_plural}
          rows={actions.map((a) => ({ text: `${a.status} · ${relTime(a.created_at)}`, key: a.key }))}
          onClick={(key) => onSelectAction?.(key)}
        />
      )}
    </div>
  );
}
