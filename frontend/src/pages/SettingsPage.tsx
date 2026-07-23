import { FormEvent, useEffect, useState } from "react";
import Button from "../components/Button";
import {
  useChangePassword,
  useLogout,
  useSaveUserSettings,
  useTestGateway,
  useUserSettings,
} from "../api/queries/settings";
import { UserSettings } from "../api/types";
import { MODEL_SUGGESTIONS } from "../lib/models";
import styles from "./SettingsPage.module.css";

type EditableSettings =
  Omit<UserSettings, "owner" | "gateway_api_key_set" | "smtp_password_set">;
type SettingKey = keyof EditableSettings;

interface FieldSpec {
  key: SettingKey;
  label: string;
  help: string;
  type?: "text" | "number";
  step?: string;
  list?: string;
}

const GROUPS: { title: string; fields: FieldSpec[] }[] = [
  {
    title: "models",
    fields: [
      { key: "model_chat", label: "Chat model", help: "Interactive conversations and tool use.", list: "model-suggestions" },
      { key: "model_bulk", label: "Bulk model", help: "Background scoring and high-volume tasks.", list: "model-suggestions" },
      { key: "model_writing", label: "Writing model", help: "Briefs, drafts, and polished content.", list: "model-suggestions" },
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
  const testGateway = useTestGateway();
  const [draft, setDraft] = useState<EditableSettings | null>(null);
  const [gatewayKey, setGatewayKey] = useState("");
  const [smtpPassword, setSmtpPassword] = useState("");

  useEffect(() => {
    if (data) {
      const { owner: _owner, gateway_api_key_set: _keySet,
              smtp_password_set: _pwSet, ...editable } = data;
      setDraft(editable);
    }
  }, [data]);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!draft) return;
    save.mutate({
      ...draft,
      ...(gatewayKey ? { gateway_api_key: gatewayKey } : {}),
      ...(smtpPassword ? { smtp_password: smtpPassword } : {}),
    }, { onSuccess: () => { setGatewayKey(""); setSmtpPassword(""); } });
  }

  if (isLoading || !draft || !data) return <div className="dim">loading settings…</div>;

  function update<K extends SettingKey>(key: K, value: EditableSettings[K]) {
    setDraft({ ...draft!, [key]: value });
    save.reset();
  }

  function updateField(spec: FieldSpec, value: string) {
    update(spec.key, (spec.type === "number" ? Number(value) : value) as
      EditableSettings[typeof spec.key]);
  }

  return (
    <div className={styles.page}>
      <h1>Settings</h1>
      <p className={styles.intro}>Runtime preferences are persisted and apply to new agent work immediately.</p>
      <form onSubmit={submit}>
        <section className={styles.section}>
          <h2>gateway</h2>
          <div className={styles.grid}>
            <label className={styles.field}>
              <span>Gateway base URL</span>
              <small>Any OpenAI-compatible endpoint.</small>
              <input aria-label="Gateway base URL" value={draft.gateway_base_url}
                     onChange={(e) => update("gateway_base_url", e.target.value)} />
            </label>
            <label className={styles.field}>
              <span>Gateway API key</span>
              <small>Write-only; leave blank to keep the current key.</small>
              <input aria-label="Gateway API key" type="password" value={gatewayKey}
                     placeholder={data.gateway_api_key_set ? "configured ✓ — enter to replace" : "not set"}
                     onChange={(e) => { setGatewayKey(e.target.value); save.reset(); }} />
            </label>
            <label className={styles.field}>
              <span>Timezone</span>
              <small>Used for schedules and digests.</small>
              <input aria-label="Timezone" list="timezones" value={draft.owner_timezone}
                     onChange={(e) => update("owner_timezone", e.target.value)} />
              <datalist id="timezones">
                {Intl.supportedValuesOf("timeZone").map((tz) => <option key={tz} value={tz} />)}
              </datalist>
            </label>
          </div>
          <div className={styles.actions}>
            <Button type="button" disabled={testGateway.isPending}
                    onClick={() => testGateway.mutate({
                      gateway_base_url: draft.gateway_base_url,
                      gateway_api_key: gatewayKey })}>
              Test connection
            </Button>
            {testGateway.data && (testGateway.data.ok
              ? <span className={styles.success}>connected — {testGateway.data.models} models</span>
              : <span className={styles.error}>{testGateway.data.detail}</span>)}
          </div>
        </section>
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
                    list={field.list}
                    value={String(draft[field.key])}
                    onChange={(event) => updateField(field, event.target.value)}
                  />
                </label>
              ))}
            </div>
          </section>
        ))}
        <datalist id="model-suggestions">
          {MODEL_SUGGESTIONS.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
        </datalist>
        <section className={styles.section}>
          <h2>email</h2>
          <div className={styles.grid}>
            <label className={styles.field}>
              <span>Email backend</span>
              <small>Console logs messages; SMTP delivers them.</small>
              <select aria-label="Email backend" value={draft.email_backend}
                      onChange={(e) => update("email_backend", e.target.value as "console" | "smtp")}>
                <option value="console">console</option>
                <option value="smtp">smtp</option>
              </select>
            </label>
            {draft.email_backend === "smtp" && (<>
              <label className={styles.field}>
                <span>SMTP host</span>
                <small>Mail server hostname.</small>
                <input aria-label="SMTP host" value={draft.smtp_host}
                       onChange={(e) => update("smtp_host", e.target.value)} />
              </label>
              <label className={styles.field}>
                <span>SMTP port</span>
                <small>Usually 587 with STARTTLS.</small>
                <input aria-label="SMTP port" type="number" value={draft.smtp_port}
                       onChange={(e) => update("smtp_port", Number(e.target.value))} />
              </label>
              <label className={styles.field}>
                <span>SMTP username</span>
                <small>Blank to skip authentication.</small>
                <input aria-label="SMTP username" value={draft.smtp_username}
                       onChange={(e) => update("smtp_username", e.target.value)} />
              </label>
              <label className={styles.field}>
                <span>SMTP password</span>
                <small>Write-only; leave blank to keep the current password.</small>
                <input aria-label="SMTP password" type="password" value={smtpPassword}
                       placeholder={data.smtp_password_set ? "configured ✓ — enter to replace" : "not set"}
                       onChange={(e) => { setSmtpPassword(e.target.value); save.reset(); }} />
              </label>
              <label className={styles.field}>
                <span>From address</span>
                <small>Sender for outbound mail.</small>
                <input aria-label="From address" value={draft.smtp_from}
                       onChange={(e) => update("smtp_from", e.target.value)} />
              </label>
              <label className={styles.field}>
                <span>STARTTLS</span>
                <small>Upgrade the connection to TLS.</small>
                <select aria-label="STARTTLS" value={String(draft.smtp_starttls)}
                        onChange={(e) => update("smtp_starttls", e.target.value === "true")}>
                  <option value="true">enabled</option>
                  <option value="false">disabled</option>
                </select>
              </label>
            </>)}
          </div>
        </section>
        <div className={styles.actions}>
          <Button type="submit" variant="primary" disabled={save.isPending}>Save settings</Button>
          {save.isSuccess && <span className={styles.success}>saved</span>}
          {save.error && <span className={styles.error}>{save.error.message}</span>}
        </div>
      </form>
      <section className={styles.section}>
        <h2>password</h2>
        <PasswordForm />
      </section>
      <section className={`${styles.section} ${styles.account}`}>
        <div className={styles.accountMeta}>
          <strong>Account</strong>
          {data.owner}
        </div>
        <Button variant="danger" onClick={() => logout.mutate()} disabled={logout.isPending}>Log out</Button>
        {logout.error && <span className={styles.error}>{logout.error.message}</span>}
      </section>
    </div>
  );
}

function PasswordForm() {
  const change = useChangePassword();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [localError, setLocalError] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    if (next !== confirm) {
      setLocalError("passwords do not match");
      return;
    }
    setLocalError("");
    change.mutate({ current_password: current, new_password: next },
                  { onSuccess: () => { setCurrent(""); setNext(""); setConfirm(""); } });
  }

  return (
    <form onSubmit={submit}>
      <div className={styles.grid}>
        <label className={styles.field}>
          <span>Current password</span>
          <small>Required to authorize the change.</small>
          <input aria-label="Current password" type="password" value={current}
                 onChange={(e) => setCurrent(e.target.value)} required />
        </label>
        <label className={styles.field}>
          <span>New password</span>
          <small>At least 8 characters.</small>
          <input aria-label="New password" type="password" value={next} minLength={8}
                 onChange={(e) => setNext(e.target.value)} required />
        </label>
        <label className={styles.field}>
          <span>Confirm new password</span>
          <small>Repeat the new password.</small>
          <input aria-label="Confirm new password" type="password" value={confirm}
                 onChange={(e) => setConfirm(e.target.value)} required />
        </label>
      </div>
      <div className={styles.actions}>
        <Button type="submit" disabled={change.isPending}>Change password</Button>
        {change.isSuccess && <span className={styles.success}>password changed</span>}
        {(localError || change.error) &&
          <span className={styles.error}>{localError || change.error?.message}</span>}
      </div>
    </form>
  );
}
