import { useMemo, useState } from "react";
import Button from "../components/Button";
import EmptyState from "../components/EmptyState";
import { toast } from "../components/Toaster";
import {
  useArchiveMemory,
  useCreateMemory,
  useDeleteMemory,
  useMemories,
  useRestoreMemory,
  useUpdateMemory,
} from "../api/queries/memories";
import { Memory } from "../api/types";
import FilterChips, { MemoryStatusFilter, MemoryTypeFilter } from "./memories/FilterChips";
import MemoryCard from "./memories/MemoryCard";
import MemoryFormModal, { MemoryFormValue } from "./memories/MemoryFormModal";
import styles from "./MemoriesPage.module.css";

function messageOf(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

// create-mode target is the sentinel "new"; edit-mode target is the memory being edited; null == closed.
type FormTarget = Memory | "new" | null;

export default function MemoriesPage() {
  const [typeFilter, setTypeFilter] = useState<MemoryTypeFilter>("all");
  const [statusFilter, setStatusFilter] = useState<MemoryStatusFilter>("all");
  const [search, setSearch] = useState("");
  const [formTarget, setFormTarget] = useState<FormTarget>(null);

  const { data: memories = [] } = useMemories({
    type: typeFilter === "all" ? undefined : typeFilter,
    status: statusFilter === "all" ? undefined : statusFilter,
  });

  const createMemory = useCreateMemory();
  const updateMemory = useUpdateMemory();
  const archiveMemory = useArchiveMemory();
  const restoreMemory = useRestoreMemory();
  const deleteMemory = useDeleteMemory();

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return q ? memories.filter((m) => m.text.toLowerCase().includes(q)) : memories;
  }, [memories, search]);

  async function handleArchive(key: string) {
    try {
      await archiveMemory.mutateAsync(key);
    } catch (err) {
      toast.error(messageOf(err));
    }
  }

  async function handleRestore(key: string) {
    try {
      await restoreMemory.mutateAsync(key);
    } catch (err) {
      toast.error(messageOf(err));
    }
  }

  async function handleDelete(key: string) {
    try {
      await deleteMemory.mutateAsync(key);
    } catch (err) {
      toast.error(messageOf(err));
    }
  }

  async function handleSubmit(value: MemoryFormValue) {
    try {
      if (value.mode === "edit" && formTarget && formTarget !== "new") {
        await updateMemory.mutateAsync({ key: formTarget.key, text: value.text });
      } else if (value.mode === "create") {
        await createMemory.mutateAsync({ text: value.text, type: value.type, importance: value.importance });
      }
      setFormTarget(null);
    } catch (err) {
      toast.error(messageOf(err));
    }
  }

  const newMemoryButton = (
    <Button variant="primary" onClick={() => setFormTarget("new")}>New memory</Button>
  );

  return (
    <div className={styles.page}>
      <div className={styles.toolbar}>
        <FilterChips
          type={typeFilter}
          status={statusFilter}
          onTypeChange={setTypeFilter}
          onStatusChange={setStatusFilter}
        />
        <input
          className={styles.search}
          type="search"
          placeholder="search memories…"
          aria-label="search memories"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {newMemoryButton}
      </div>

      {visible.length === 0 ? (
        <EmptyState heading="nothing remembered yet" action={newMemoryButton} />
      ) : (
        <div className={styles.list}>
          {visible.map((memory) => (
            <MemoryCard
              key={memory.key}
              memory={memory}
              onEdit={setFormTarget}
              onArchive={handleArchive}
              onRestore={handleRestore}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}

      <MemoryFormModal
        open={formTarget !== null}
        onOpenChange={(open) => !open && setFormTarget(null)}
        memory={formTarget === "new" || formTarget === null ? null : formTarget}
        onSubmit={handleSubmit}
      />
    </div>
  );
}
