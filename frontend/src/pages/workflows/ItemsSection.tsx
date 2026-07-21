import { WorkflowDefinition } from "../../api/types";
import { useWorkflowKind } from "../../api/queries/workflows";
import EmptyState from "../../components/EmptyState";
import RecordTable from "../../components/RecordTable";
import ItemDetail from "./ItemDetail";
import PrerequisitePanel from "./PrerequisitePanel";
import styles from "./workflows.module.css";

export default function ItemsSection({
  workflowName,
  definition,
  selectedKey,
  onSelect,
  onSelectArtifact,
  onSelectAction,
}: {
  workflowName: string;
  definition: WorkflowDefinition;
  selectedKey: string | null;
  onSelect: (key: string) => void;
  onSelectArtifact?: (key: string) => void;
  onSelectAction?: (key: string) => void;
}) {
  // Do NOT default via destructuring (`data: records = []`) — that makes `records.length
  // === 0` true during the pending fetch too, so the job-hunt PrerequisitePanel would mount
  // (firing useResources + useSkillRuns) on every visit and then flash away once items
  // arrive. Render neither empty branch until the query has actually settled.
  const { data: records, isPending } = useWorkflowKind(workflowName, "items");
  const items = records ?? [];
  const itemsDef = definition.items;
  if (!itemsDef) return null;

  return (
    <section className={styles.kindSection}>
      <h2>{itemsDef.label_plural}</h2>
      {isPending ? null : items.length === 0 ? (
        // SPEC §5.8: job-hunt's empty-items state is the live PrerequisitePanel; every
        // other workflow gets a plain "no {label_plural} yet" + intake hint.
        workflowName === "job-hunt" ? (
          <PrerequisitePanel />
        ) : (
          <EmptyState
            heading={`no ${itemsDef.label_plural} yet`}
            body={
              definition.intake
                ? `populated by the ${definition.intake.skills.join(", ")} skill — see /skills for its run history`
                : undefined
            }
          />
        )
      ) : (
        <RecordTable kind={itemsDef} records={items} onRowClick={onSelect} />
      )}
      {selectedKey && (
        <ItemDetail
          workflowName={workflowName}
          definition={definition}
          itemKey={selectedKey}
          onSelectArtifact={onSelectArtifact}
          onSelectAction={onSelectAction}
        />
      )}
    </section>
  );
}
