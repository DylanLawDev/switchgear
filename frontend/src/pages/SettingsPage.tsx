import { FormEvent, useEffect, useState } from "react";
import Button from "../components/Button";
import { useLogout, useSaveUserSettings, useUserSettings } from "../api/queries/settings";
import { UserSettings } from "../api/types";
import styles from "./SettingsPage.module.css";

type EditableSettings = Omit<UserSettings, "owner_email">;
type SettingKey = keyof EditableSettings;

interface FieldSpec {
  key: SettingKey;
  label: string;
  help: string;
  type?: "text" | "number";
  step?: string;
}

const GROUPS: { title: string; fields: FieldSpec[] }[] = [
  {
    title: "models",
    fields: [
      { key: "model_chat", label: "Chat model", help: "Interactive conversations and tool use." },
      { key: "model_bulk", label: "Bulk model", help: "Background scoring and high-volume tasks." },
      { key: "model_writing", label: "Writing model", help: "Briefs, drafts, and polished content." },
    ],
  },
  {
    title: "agent",
    fields: [
      { key: "run_token_budget", label: "Run token budget", help: "Maximum tokens available to one agent run.", type: "number" },
      { key: "max_loop_iterations", label: "Maximum loop iterations", help: "Maximum tool/reasoning turns per run.", type: "number" },
    ],
  },
  {
    title: "memory",
    fields: [
      { key: "memory_max_chars", label: "Memory length", help: "Maximum characters in one memory.", type: "number" },
      { key: "memory_core_max_chars", label: "Core-memory context", help: "Maximum core-memory characters injected into a run.", type: "number" },
      { key: "memory_recall_k", label: "Recall count", help: "Maximum related memories recalled per message.", type: "number" },
      { key: "memory_recall_floor", label: "Recall threshold", help: "Minimum similarity score from 0 to 1.", type: "number", step: "0.01" },
      { key: "memory_supersede_threshold", label: "Supersede threshold", help: "Similarity score at which a memory replaces an older one.", type: "number", step: "0.01" },
      { key: "memory_recency_half_life_days", label: "Recency half-life (days)", help: "How quickly older memories lose ranking weight.", type: "number", step: "0.1" },
      { key: "memory_reflection_min_interval", label: "Reflection interval (seconds)", help: "Minimum time between conversation reflection passes.", type: "number" },
    ],
  },
  {
    title: "resources & channels",
    fields: [
      { key: "resource_max_bytes", label: "Maximum resource bytes", help: "Largest resource that can be stored.", type: "number" },
      { key: "resource_read_chars", label: "Resource read limit", help: "Maximum resource characters returned to the agent.", type: "number" },
      { key: "channel_body_max_chars", label: "Channel body limit", help: "Maximum inbound message body characters.", type: "number" },
      { key: "channel_backfill_max", label: "Channel backfill limit", help: "Maximum messages processed during backfill.", type: "number" },
      { key: "channel_reply_rate_per_day", label: "Daily reply limit", help: "Maximum automatic channel replies per day.", type: "number" },
    ],
  },
];

export default function SettingsPage() {
  const { data, isLoading } = useUserSettings();
  const save = useSaveUserSettings();
  const logout = useLogout();
  const [draft, setDraft] = useState<EditableSettings | null>(null);

  useEffect(() => {
    if (data) {
      const { owner_email: _ownerEmail, ...editable } = data;
      setDraft(editable);
    }
  }, [data]);

  function updateField(spec: FieldSpec, value: string) {
    if (!draft) return;
    setDraft({ ...draft, [spec.key]: spec.type === "number" ? Number(value) : value });
    save.reset();
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (draft) save.mutate(draft);
  }

  if (isLoading || !draft || !data) return <div className="dim">loading settings…</div>;

  return (
    <div className={styles.page}>
      <h1>Settings</h1>
      <p className={styles.intro}>Runtime preferences are persisted and apply to new agent work immediately.</p>
      <form onSubmit={submit}>
        {GROUPS.map((group) => (
          <section className={styles.section} key={group.title}>
            <h2>{group.title}</h2>
            <div className={styles.grid}>
              {group.fields.map((field) => (
                <label className={styles.field} key={field.key}>
                  <span>{field.label}</span>
                  <small>{field.help}</small>
                  <input
                    aria-label={field.label}
                    type={field.type ?? "text"}
                    step={field.step}
                    value={draft[field.key]}
                    onChange={(event) => updateField(field, event.target.value)}
                  />
                </label>
              ))}
            </div>
          </section>
        ))}
        <div className={styles.actions}>
          <Button type="submit" variant="primary" disabled={save.isPending}>Save settings</Button>
          {save.isSuccess && <span className={styles.success}>saved</span>}
          {save.error && <span className={styles.error}>{save.error.message}</span>}
        </div>
      </form>
      <section className={`${styles.section} ${styles.account}`}>
        <div className={styles.accountMeta}>
          <strong>Account</strong>
          {data.owner_email}
        </div>
        <Button variant="danger" onClick={() => logout.mutate()} disabled={logout.isPending}>Log out</Button>
        {logout.error && <span className={styles.error}>{logout.error.message}</span>}
      </section>
    </div>
  );
}
