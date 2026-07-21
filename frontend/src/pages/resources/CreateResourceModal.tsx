import { useEffect, useState } from "react";
import Modal from "../../components/Modal";
import Button from "../../components/Button";
import { RESOURCE_NAME_RE } from "../../api/queries/resources";
import { ResourceKind } from "../../api/types";
import styles from "./CreateResourceModal.module.css";

const KINDS: ResourceKind[] = ["csv", "json", "md", "txt"];

export interface ResourceDraft { name: string; kind: ResourceKind; description: string; content?: string }

// Optional pre-fill for future shortcuts. Content editing happens in the resource editor
// after creation; when supplied, initial content is carried through to `onCreate`.
export interface CreateResourceInitial { name: string; kind: ResourceKind; description?: string; content?: string }

export default function CreateResourceModal({
  open,
  onOpenChange,
  onCreate,
  initial,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (draft: ResourceDraft) => void;
  initial?: CreateResourceInitial;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [kind, setKind] = useState<ResourceKind>(initial?.kind ?? "json");
  const [description, setDescription] = useState(initial?.description ?? "");

  useEffect(() => {
    if (open) {
      setName(initial?.name ?? "");
      setKind(initial?.kind ?? "json");
      setDescription(initial?.description ?? "");
    }
    // Re-seed whenever the modal (re)opens with a (possibly new) prefill; ignoring `initial`
    // identity changes while closed is intentional — only `open` should retrigger this.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const valid = RESOURCE_NAME_RE.test(name);

  function reset() {
    setName("");
    setKind("json");
    setDescription("");
  }

  function handleSubmit() {
    if (!valid) return;
    onCreate({ name, kind, description, content: initial?.content });
    reset();
  }

  return (
    <Modal
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
      title="New resource"
    >
      <div className={styles.form}>
        <label className={styles.field}>
          <span className={styles.fieldLabel}>name</span>
          <input
            className={styles.input}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="career-bank"
          />
          {name.length > 0 && !valid && (
            <span className={styles.hint}>lowercase letters, digits, hyphens — 2 to 64 chars</span>
          )}
        </label>
        <label className={styles.field}>
          <span className={styles.fieldLabel}>kind</span>
          <select className={styles.input} value={kind} onChange={(e) => setKind(e.target.value as ResourceKind)}>
            {KINDS.map((k) => (
              <option key={k} value={k}>{k}</option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          <span className={styles.fieldLabel}>description</span>
          <input
            className={styles.input}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>
        {initial?.content && (
          <div className={styles.field}>
            <span className={styles.fieldLabel}>content</span>
            <pre className={styles.skeletonPreview}>{initial.content}</pre>
          </div>
        )}
        <div className={styles.actions}>
          <Button variant="primary" disabled={!valid} onClick={handleSubmit}>Create</Button>
        </div>
      </div>
    </Modal>
  );
}
