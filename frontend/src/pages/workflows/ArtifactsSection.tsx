import { WorkflowDefinition } from "../../api/types";
import { useWorkflowKind } from "../../api/queries/workflows";
import RecordTable from "../../components/RecordTable";
import ArtifactDetail from "./ArtifactDetail";
import styles from "./workflows.module.css";

export default function ArtifactsSection({
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
  const kind = definition.artifacts;
  const { data: records = [] } = useWorkflowKind(workflowName, "artifacts");
  if (!kind) return null;

  return (
    <section className={styles.kindSection}>
      <h2>{kind.label_plural}</h2>
      <RecordTable kind={kind} records={records} onRowClick={onSelect} />
      {selectedKey && <ArtifactDetail workflowName={workflowName} definition={definition} artifactKey={selectedKey} />}
    </section>
  );
}
