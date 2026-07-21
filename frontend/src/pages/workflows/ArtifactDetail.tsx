import { WorkflowDefinition } from "../../api/types";
import { useWorkflowRecord } from "../../api/queries/workflows";
import DetailGrid from "./DetailGrid";
import RawDetails from "./RawDetails";
import styles from "./workflows.module.css";

// Parity workflow.js showArtifactDetail: title + "for <item.title>" line + detail grid + raw.
export default function ArtifactDetail({
  workflowName,
  definition,
  artifactKey,
}: {
  workflowName: string;
  definition: WorkflowDefinition;
  artifactKey: string;
}) {
  const kind = definition.artifacts;
  const { data } = useWorkflowRecord(workflowName, "artifacts", artifactKey);
  if (!kind || !data) return null;
  const { record, item } = data;
  const title = (record[kind.title_field] as string | undefined) ?? artifactKey;

  return (
    <div className={styles.detail}>
      <h3>{title}</h3>
      {item?.title && <p className="dim">for {item.title}</p>}
      <DetailGrid kind={kind} record={record} />
      <RawDetails kind={kind} record={record} extraKnown={kind.item_ref_field ? [kind.item_ref_field] : []} />
    </div>
  );
}
