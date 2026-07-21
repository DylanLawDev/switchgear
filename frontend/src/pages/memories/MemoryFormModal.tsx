import { FormEvent, useEffect, useState } from "react";
import Button from "../../components/Button";
import Modal from "../../components/Modal";
import RadioRow from "../../components/RadioRow";
import { Memory, MemoryType } from "../../api/types";
import styles from "./MemoryFormModal.module.css";

const MIN_IMPORTANCE = 1;
const MAX_IMPORTANCE = 10;

function clampImportance(raw: string): number {
  const n = parseInt(raw, 10);
  if (Number.isNaN(n)) return MIN_IMPORTANCE;
  return Math.min(MAX_IMPORTANCE, Math.max(MIN_IMPORTANCE, n));
}

export type MemoryFormValue =
  | { mode: "create"; text: string; type: MemoryType; importance: number }
  | { mode: "edit"; text: string };

export default function MemoryFormModal({
  open,
  onOpenChange,
  memory,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  memory: Memory | null;   // null => create mode; set => edit mode (PUT sends {text} only)
  onSubmit: (value: MemoryFormValue) => void;
}) {
  const mode = memory ? "edit" : "create";
  const [text, setText] = useState(memory?.text ?? "");
  const [type, setType] = useState<MemoryType>("episodic");
  const [importance, setImportance] = useState(5);

  useEffect(() => {
    if (open) {
      setText(memory?.text ?? "");
      setType("episodic");
      setImportance(5);
    }
  }, [open, memory]);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (mode === "edit") {
      onSubmit({ mode: "edit", text });
    } else {
      onSubmit({ mode: "create", text, type, importance });
    }
  }

  return (
    <Modal open={open} onOpenChange={onOpenChange} title={mode === "edit" ? "Edit memory" : "New memory"}>
      <form className={styles.form} onSubmit={handleSubmit}>
        <label className={styles.field}>
          <span className={styles.label}>Text</span>
          <textarea
            className={styles.textarea}
            value={text}
            onChange={(e) => setText(e.target.value)}
            required
          />
        </label>
        {mode === "create" && (
          <>
            <div className={styles.field}>
              <span className={styles.label}>Type</span>
              <RadioRow
                value={type}
                onValueChange={(v) => setType(v as MemoryType)}
                options={[
                  { value: "core", label: "core" },
                  { value: "episodic", label: "episodic" },
                ]}
              />
            </div>
            <label className={styles.field}>
              <span className={styles.label}>Importance</span>
              <input
                className={styles.number}
                type="number"
                min={MIN_IMPORTANCE}
                max={MAX_IMPORTANCE}
                value={importance}
                onChange={(e) => setImportance(clampImportance(e.target.value))}
              />
            </label>
          </>
        )}
        <div className={styles.actions}>
          <Button type="submit" variant="primary">{mode === "edit" ? "Save" : "Create"}</Button>
        </div>
      </form>
    </Modal>
  );
}
