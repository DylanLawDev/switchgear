import { NavLink, useNavigate } from "react-router-dom";
import { WorkflowSummary } from "../../api/types";
import { usePendingCount } from "../../api/queries/workflows";
import styles from "./workflows.module.css";

function PendingBadge({ name }: { name: string }) {
  const { data } = usePendingCount(name);
  if (!data) return null;
  return <span className={styles.pendingBadge}>{data}</span>;
}

// Left rail: nav list ≥700px, <select> below that breakpoint (workflows.module.css toggles
// visibility — same pattern as AppShell's rail / ChatPage's conversation rail).
export default function WorkflowRail({
  workflows,
  selected,
}: {
  workflows: WorkflowSummary[];
  selected: string | null;
}) {
  const navigate = useNavigate();

  return (
    <div className={styles.rail}>
      <select
        className={styles.railSelect}
        aria-label="workflow"
        value={selected ?? ""}
        onChange={(e) => {
          if (e.target.value) navigate(`/workflows/${encodeURIComponent(e.target.value)}`);
        }}
      >
        <option value="" disabled>
          select a workflow…
        </option>
        {workflows.map((w) => (
          <option key={w.name} value={w.name}>
            {w.name}
          </option>
        ))}
      </select>
      <nav aria-label="workflows">
        {workflows.map((w) => (
          <NavLink
            key={w.name}
            to={`/workflows/${encodeURIComponent(w.name)}`}
            className={({ isActive }) => (isActive ? `${styles.railItem} ${styles.railItemActive}` : styles.railItem)}
          >
            <span className={styles.railName}>
              {w.name}
              <PendingBadge name={w.name} />
            </span>
            <span className={styles.railDesc}>{w.description}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
