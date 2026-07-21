import { useState } from "react";
import Button from "../../components/Button";
import ConfirmDialog from "../../components/ConfirmDialog";
import { absTime } from "../../lib/format";
import { Memory } from "../../api/types";
import styles from "./MemoryCard.module.css";

const TRUNCATE_AT = 160;   // parity with static/memories.js truncate()

export default function MemoryCard({
  memory,
  onEdit,
  onArchive,
  onRestore,
  onDelete,
}: {
  memory: Memory;
  onEdit: (memory: Memory) => void;
  onArchive: (key: string) => void;
  onRestore: (key: string) => void;
  onDelete: (key: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const isLong = memory.text.length > TRUNCATE_AT;
  const shown = expanded || !isLong ? memory.text : `${memory.text.slice(0, TRUNCATE_AT)}…`;
  const accessed = memory.last_accessed_at ? absTime(memory.last_accessed_at) : "never";

  return (
    <article className={styles.card}>
      <p
        className={styles.text}
        onClick={isLong ? () => setExpanded((v) => !v) : undefined}
        role={isLong ? "button" : undefined}
        tabIndex={isLong ? 0 : undefined}
      >
        {shown}
      </p>
      <span className={styles.meta}>
        [{memory.type} · {memory.status} · importance {memory.importance} · {memory.source} · last accessed {accessed}]
      </span>
      <div className={styles.actions}>
        {memory.status === "active" && (
          <>
            <Button onClick={() => onEdit(memory)}>Edit</Button>
            <Button variant="ghost" onClick={() => onArchive(memory.key)}>Archive</Button>
          </>
        )}
        {memory.status === "archived" && (
          <Button variant="ghost" onClick={() => onRestore(memory.key)}>Restore</Button>
        )}
        <ConfirmDialog
          trigger={<Button variant="danger">Delete</Button>}
          title="Hard-delete this memory?"
          body="This permanently removes the memory. This cannot be undone."
          confirmLabel="Hard-delete"
          danger
          onConfirm={() => onDelete(memory.key)}
        />
      </div>
    </article>
  );
}
