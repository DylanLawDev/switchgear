import { useEffect, useState } from "react";
import { useWorkflowDefinition } from "../../api/queries/workflows";
import ItemsSection from "./ItemsSection";
import ArtifactsSection from "./ArtifactsSection";
import ActionsSection from "./ActionsSection";
import styles from "./workflows.module.css";

// One component tree renders every workflow from its definition JSON — parity workflow.js.
export default function RunsView({ workflowName }: { workflowName: string }) {
  const { data: definition } = useWorkflowDefinition(workflowName);
  const [itemKey, setItemKey] = useState<string | null>(null);
  const [artifactKey, setArtifactKey] = useState<string | null>(null);
  const [actionKey, setActionKey] = useState<string | null>(null);

  useEffect(() => {
    setItemKey(null);
    setArtifactKey(null);
    setActionKey(null);
  }, [workflowName]);

  if (!definition) return null;

  return (
    <div className={styles.runs}>
      <h1>{definition.name}</h1>
      {definition.description && <p className={styles.wfDesc}>{definition.description}</p>}
      {definition.items ? <ItemsSection
        workflowName={workflowName}
        definition={definition}
        selectedKey={itemKey}
        onSelect={setItemKey}
        onSelectArtifact={setArtifactKey}
        onSelectAction={setActionKey}
      /> : <p className={styles.wfDesc}>This workflow has no data-app collections. Execution runs appear in Scheduler.</p>}
      {definition.artifacts && (
        <ArtifactsSection
          workflowName={workflowName}
          definition={definition}
          selectedKey={artifactKey}
          onSelect={setArtifactKey}
        />
      )}
      {definition.actions && (
        <ActionsSection
          workflowName={workflowName}
          definition={definition}
          selectedKey={actionKey}
          onSelect={setActionKey}
        />
      )}
    </div>
  );
}
