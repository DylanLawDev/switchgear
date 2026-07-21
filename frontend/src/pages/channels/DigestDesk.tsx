import { channelWorkflows, useWorkflows } from "../../api/queries/workflows";
import RunsView from "../workflows/RunsView";
import styles from "./channels.module.css";

// One embedded RunsView (Tasks 7-8, self-fetching) per workflow whose ui_home is "channels" —
// RunsView's internals are already tested; this just wires the filter.
export default function DigestDesk() {
  const { data: workflows = [] } = useWorkflows();
  const channel = channelWorkflows(workflows);

  if (channel.length === 0) return null;

  return (
    <div className={styles.digestDesk}>
      <h2>digest desk</h2>
      {channel.map((wf) => (
        <RunsView key={wf.name} workflowName={wf.name} />
      ))}
    </div>
  );
}
