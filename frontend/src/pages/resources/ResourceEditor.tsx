import { useEffect, useRef, useState } from "react";
import { useBlocker } from "react-router-dom";
import Badge from "../../components/Badge";
import Button from "../../components/Button";
import CodeTextarea from "../../components/CodeTextarea";
import ConfirmDialog from "../../components/ConfirmDialog";
import Modal from "../../components/Modal";
import { useDeleteResource, useResource, useSaveResource } from "../../api/queries/resources";
import { ResourceKind } from "../../api/types";
import styles from "./ResourceEditor.module.css";

interface Snapshot { description: string; content: string }

export default function ResourceEditor({
  name,
  draft,
  onDraftSaved,
  onDeleted,
}: {
  name: string;
  draft: { kind: ResourceKind; description: string; content?: string } | null;
  onDraftSaved: () => void;
  onDeleted: () => void;
}) {
  const isDraft = draft !== null;
  // Deleting (draft-discard or persisted-delete) intentionally navigates away from a
  // dirty editor; set before the parent unwinds `draft`/`selected` so a transient render
  // (draft cleared locally, URL not yet updated) can't flip `isDraft` false mid-teardown
  // and fire a stray GET for a name that's on its way out, and so the unsaved-changes
  // blocker below doesn't intercept that self-initiated navigation.
  const deletingRef = useRef(false);
  const { data: resource } = useResource(isDraft || deletingRef.current ? "" : name);
  const save = useSaveResource();
  const del = useDeleteResource();

  const baseline: { kind: ResourceKind; description: string; content: string } | null = isDraft
    ? { kind: draft.kind, description: draft.description, content: draft.content ?? "" }
    : resource
      ? { kind: resource.kind, description: resource.description, content: resource.content }
      : null;

  const [state, setState] = useState<Snapshot | null>(null);
  const [saved, setSaved] = useState<Snapshot | null>(null);
  const [kind, setKind] = useState<ResourceKind | null>(null);
  const [inlineError, setInlineError] = useState<string | null>(null);

  useEffect(() => {
    if (baseline && state === null) {
      setState({ description: baseline.description, content: baseline.content });
      setSaved({ description: baseline.description, content: baseline.content });
      setKind(baseline.kind);
    }
  }, [baseline, state]);

  const dirty =
    !!state &&
    !!saved &&
    (isDraft || state.description !== saved.description || state.content !== saved.content);

  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      dirty &&
      !deletingRef.current &&
      currentLocation.pathname + currentLocation.search !== nextLocation.pathname + nextLocation.search,
  );

  useEffect(() => {
    function handleBeforeUnload(e: BeforeUnloadEvent) {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    }
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [dirty]);

  if (!state || !saved || !kind) return null;

  async function handleSave() {
    setInlineError(null);
    try {
      await save.mutateAsync({ name, body: { kind: kind!, description: state!.description, content: state!.content } });
      setSaved({ description: state!.description, content: state!.content });
      if (isDraft) onDraftSaved();
    } catch (err) {
      setInlineError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleDelete() {
    // A draft never made it to the backend (never persisted) — a DELETE would 404.
    // Discard it locally instead of round-tripping to an API that has nothing to delete.
    if (isDraft) {
      deletingRef.current = true;
      onDeleted();
      return;
    }
    try {
      await del.mutateAsync(name);
      deletingRef.current = true;
      onDeleted();
    } catch {
      // global mutation-cache sink already toasts; swallow here to avoid
      // an unhandled-rejection warning without a second toast.
    }
  }

  return (
    <div className={styles.editor}>
      <div className={styles.meta}>
        <span className={styles.name}>{name}</span>
        <Badge>{kind}</Badge>
        <input
          className={styles.description}
          value={state.description}
          onChange={(e) => setState({ ...state, description: e.target.value })}
          placeholder="description"
          aria-label="description"
        />
        <ConfirmDialog
          trigger={<Button variant="danger">Delete</Button>}
          title={`Delete ${name}?`}
          body="This cannot be undone."
          confirmLabel="Delete"
          danger
          onConfirm={handleDelete}
        />
        <Button variant="primary" onClick={handleSave} disabled={!dirty || save.isPending}>
          Save
        </Button>
      </div>
      {inlineError && (
        <p className={styles.error} role="alert">{inlineError}</p>
      )}
      <CodeTextarea
        className={styles.textarea}
        value={state.content}
        onChange={(content) => setState({ ...state, content })}
        aria-label="content"
      />
      {blocker.state === "blocked" && (
        <Modal
          open
          onOpenChange={(next) => {
            if (!next) blocker.reset();
          }}
          title="Unsaved changes"
        >
          <p>You have unsaved changes to {name}. Leave without saving?</p>
          <div className={styles.blockerActions}>
            <Button onClick={() => blocker.reset()}>Stay</Button>
            <Button variant="danger" onClick={() => blocker.proceed()}>Leave without saving</Button>
          </div>
        </Modal>
      )}
    </div>
  );
}
