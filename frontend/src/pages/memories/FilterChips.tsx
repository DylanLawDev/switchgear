import styles from "./FilterChips.module.css";

export type MemoryTypeFilter = "all" | "core" | "episodic";
export type MemoryStatusFilter = "all" | "active" | "archived" | "superseded";

const TYPE_OPTIONS: MemoryTypeFilter[] = ["all", "core", "episodic"];
const STATUS_OPTIONS: MemoryStatusFilter[] = ["all", "active", "archived", "superseded"];

// server-side filters (SPEC §5.7) — "all" omits the query param, both independent.
export default function FilterChips({
  type,
  status,
  onTypeChange,
  onStatusChange,
}: {
  type: MemoryTypeFilter;
  status: MemoryStatusFilter;
  onTypeChange: (value: MemoryTypeFilter) => void;
  onStatusChange: (value: MemoryStatusFilter) => void;
}) {
  return (
    <div className={styles.chips}>
      <div className={styles.group} role="group" aria-label="filter by type">
        {TYPE_OPTIONS.map((opt) => (
          <button
            key={opt}
            type="button"
            className={opt === type ? `${styles.chip} ${styles.active}` : styles.chip}
            aria-pressed={opt === type}
            onClick={() => onTypeChange(opt)}
          >
            {opt}
          </button>
        ))}
      </div>
      <div className={styles.group} role="group" aria-label="filter by status">
        {STATUS_OPTIONS.map((opt) => (
          <button
            key={opt}
            type="button"
            className={opt === status ? `${styles.chip} ${styles.active}` : styles.chip}
            aria-pressed={opt === status}
            onClick={() => onStatusChange(opt)}
          >
            {opt}
          </button>
        ))}
      </div>
    </div>
  );
}
