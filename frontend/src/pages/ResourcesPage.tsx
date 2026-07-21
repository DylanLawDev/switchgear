import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import EmptyState from "../components/EmptyState";
import { useResources } from "../api/queries/resources";
import WriteModeControl from "./resources/WriteModeControl";
import ResourceList from "./resources/ResourceList";
import ResourceEditor from "./resources/ResourceEditor";
import ResourcesEmptyState from "./resources/ResourcesEmptyState";
import CreateResourceModal, { CreateResourceInitial, ResourceDraft } from "./resources/CreateResourceModal";
import styles from "./ResourcesPage.module.css";

export default function ResourcesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const selected = searchParams.get("r");
  const { data: resources = [] } = useResources();
  const [createOpen, setCreateOpen] = useState(false);
  const [createInitial, setCreateInitial] = useState<CreateResourceInitial | null>(null);
  const [draft, setDraft] = useState<ResourceDraft | null>(null);

  function select(name: string | null) {
    setSearchParams(name ? { r: name } : {});
  }

  function openCreateModal(initial: CreateResourceInitial | null = null) {
    setCreateInitial(initial);
    setCreateOpen(true);
  }

  return (
    <div className={styles.page}>
      <div className={styles.left}>
        <WriteModeControl />
        {resources.length === 0 ? (
          <ResourcesEmptyState onCreate={() => openCreateModal(null)} />
        ) : (
          <ResourceList
            resources={resources}
            selected={selected}
            onSelect={select}
            onCreate={() => openCreateModal(null)}
          />
        )}
      </div>
      <div className={styles.right}>
        {selected ? (
          <ResourceEditor
            key={selected}
            name={selected}
            draft={draft && draft.name === selected ? draft : null}
            onDraftSaved={() => setDraft(null)}
            onDeleted={() => {
              setDraft(null);
              select(null);
            }}
          />
        ) : (
          <EmptyState heading="select a resource" />
        )}
      </div>
      <CreateResourceModal
        open={createOpen}
        initial={createInitial ?? undefined}
        onOpenChange={(open) => {
          setCreateOpen(open);
          if (!open) setCreateInitial(null);
        }}
        onCreate={(d) => {
          setDraft(d);
          setCreateOpen(false);
          setCreateInitial(null);
          select(d.name);
        }}
      />
    </div>
  );
}
