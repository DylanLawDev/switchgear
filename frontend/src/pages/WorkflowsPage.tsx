import { useParams, useSearchParams } from "react-router-dom";
import { railWorkflows, useWorkflows } from "../api/queries/workflows";
import EmptyState from "../components/EmptyState";
import SegmentedToggle from "../components/SegmentedToggle";
import WorkflowRail from "./workflows/WorkflowRail";
import RunsView from "./workflows/RunsView";
import DefinitionView from "./workflows/DefinitionView";
import styles from "./workflows/workflows.module.css";

const VIEW_TOGGLE_OPTIONS = [
  { value: "runs", label: "Runs" },
  { value: "definition", label: "Definition" },
];

export default function WorkflowsPage() {
  const { name } = useParams<{ name?: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const view = searchParams.get("view") === "definition" ? "definition" : "runs";
  const { data: workflows = [] } = useWorkflows();
  const rail = railWorkflows(workflows);

  return (
    <div className={styles.page}>
      <WorkflowRail workflows={rail} selected={name ?? null} />
      <div className={styles.pane}>
        {name ? (
          <>
            <SegmentedToggle
              value={view}
              onValueChange={(v) => setSearchParams(v === "definition" ? { view: "definition" } : {})}
              options={VIEW_TOGGLE_OPTIONS}
            />
            {view === "definition" ? <DefinitionView workflowName={name} /> : <RunsView workflowName={name} />}
          </>
        ) : (
          <EmptyState
            heading="pick a workflow"
            body="A workflow app finds and stages items — jobs, drafts, digests — generates
              artifacts on request, and only takes gated actions after your explicit
              approval; nothing leaves the building without it. Pick one from the rail to
              see its items, artifacts, and pending actions."
          />
        )}
      </div>
    </div>
  );
}
