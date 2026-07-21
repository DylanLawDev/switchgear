import { useState } from "react";
import Badge from "../../components/Badge";
import Button from "../../components/Button";
import { groupResources } from "../../api/queries/resources";
import { ResourceSummary } from "../../api/types";
import { fmtBytes, relTime } from "../../lib/format";
import styles from "./ResourceList.module.css";

export default function ResourceList({
  resources,
  selected,
  onSelect,
  onCreate,
}: {
  resources: ResourceSummary[];
  selected: string | null;
  onSelect: (name: string) => void;
  onCreate: () => void;
}) {
  const [search, setSearch] = useState("");
  const filtered = resources.filter((r) => r.name.toLowerCase().includes(search.toLowerCase()));
  const groups = groupResources(filtered).filter((g) => g.items.length > 0);

  return (
    <div className={styles.list}>
      <div className={styles.toolbar}>
        <input
          className={styles.search}
          type="search"
          aria-label="search resources"
          placeholder="search resources"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <Button variant="primary" onClick={onCreate}>New resource</Button>
      </div>
      {groups.map((group) => (
        <div key={group.key} className={styles.group}>
          <h3 className={styles.groupLabel}>{group.label}</h3>
          {group.items.map((r) => (
            <button
              key={r.name}
              type="button"
              className={r.name === selected ? `${styles.row} ${styles.rowActive}` : styles.row}
              onClick={() => onSelect(r.name)}
            >
              <span className={styles.rowName}>{r.name}</span>
              <Badge>{r.kind}</Badge>
              {group.key === "agent" && <Badge tone="signal">agent</Badge>}
              <span className={styles.rowMeta}>{fmtBytes(r.size)} · {relTime(r.updated_at)}</span>
            </button>
          ))}
        </div>
      ))}
    </div>
  );
}
