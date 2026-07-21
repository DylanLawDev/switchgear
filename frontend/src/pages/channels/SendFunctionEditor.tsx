import { useState } from "react";
import Button from "../../components/Button";
import { SendFunctionInput, useDeleteSendFunction, useSaveSendFunction, useSendFunctions } from "../../api/queries/channels";
import { RecipientRule, SendFunction } from "../../api/types";
import styles from "./channels.module.css";

const RULE_TYPES: RecipientRule["type"][] = ["fixed", "reply_to_thread", "allowlist", "owner"];

interface FormState {
  name: string;
  description: string;
  gate: "approve" | "auto";
  ruleType: RecipientRule["type"];
  addresses: string;
  rate: string;
  enabled: boolean;
  subject: string;
  body: string;
  params: string;
}

const EMPTY_FORM: FormState = {
  name: "",
  description: "",
  gate: "approve",
  ruleType: "fixed",
  addresses: "",
  rate: "0",
  enabled: true,
  subject: "",
  body: "",
  params: "",
};

// Parity static/channels.js fillForm — field-for-field, including the params JSON round trip
// (JSON.stringify(fn.params, null, 2)) and the fixed/allowlist address-into-comma-list join.
function fillForm(fn: SendFunction): FormState {
  return {
    name: fn.name,
    description: fn.description,
    gate: fn.gate,
    ruleType: fn.recipient_rule.type,
    addresses: fn.recipient_rule.address || (fn.recipient_rule.addresses || []).join(", "),
    rate: String(fn.rate_limit_per_day),
    enabled: fn.enabled,
    subject: fn.subject_template,
    body: fn.body_template,
    params: JSON.stringify(fn.params, null, 2),
  };
}

// Parity static/channels.js readForm — throws "params must be valid JSON" synchronously (no
// request fires) on invalid JSON; splits the comma list back into fixed/allowlist shapes.
function readForm(form: FormState): SendFunctionInput {
  const paramsText = form.params.trim();
  let params: SendFunctionInput["params"] = {};
  if (paramsText) {
    try {
      params = JSON.parse(paramsText);
    } catch {
      throw new Error("params must be valid JSON");
    }
  }
  const addresses = form.addresses.split(",").map((s) => s.trim()).filter(Boolean);
  let rule: RecipientRule;
  if (form.ruleType === "fixed") rule = { type: "fixed", address: addresses[0] || "" };
  else if (form.ruleType === "allowlist") rule = { type: "allowlist", addresses };
  else rule = { type: form.ruleType };
  return {
    name: form.name.trim(),
    description: form.description,
    params,
    subject_template: form.subject,
    body_template: form.body,
    recipient_rule: rule,
    gate: form.gate,
    rate_limit_per_day: parseInt(form.rate, 10) || 0,
    enabled: form.enabled,
  };
}

export default function SendFunctionEditor() {
  const { data: fns = [] } = useSendFunctions();
  const save = useSaveSendFunction();
  const del = useDeleteSendFunction();
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [inlineError, setInlineError] = useState<string | null>(null);

  function patch(p: Partial<FormState>) {
    setForm((f) => ({ ...f, ...p }));
  }

  async function handleSave() {
    setInlineError(null);
    let doc: SendFunctionInput;
    try {
      doc = readForm(form);
    } catch (err) {
      setInlineError(err instanceof Error ? err.message : String(err));
      return;
    }
    try {
      await save.mutateAsync(doc);
      setForm(EMPTY_FORM);
    } catch (err) {
      setInlineError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleDelete(name: string) {
    try {
      await del.mutateAsync(name);
    } catch {
      // global mutation-cache sink already toasts; swallow to avoid an unhandled rejection.
    }
  }

  return (
    <div className={styles.editorWrap}>
      {fns.length === 0 && <p className={styles.oneLiner}>no send functions yet — add one below</p>}
      <ul className={styles.fnList}>
        {fns.map((fn) => (
          <li key={fn.name} className={styles.fnRow}>
            <strong>{fn.name}</strong>
            <span className={styles.fnMeta}>
              [{fn.recipient_rule.type} · gate {fn.gate} · {fn.rate_limit_per_day}/day ·{" "}
              {fn.enabled ? "enabled" : "disabled"}]
            </span>
            <Button
              variant="ghost"
              onClick={() => {
                setForm(fillForm(fn));
                setInlineError(null);
              }}
            >
              Edit
            </Button>
            <Button variant="danger" onClick={() => handleDelete(fn.name)}>
              Delete
            </Button>
          </li>
        ))}
      </ul>
      <div className={styles.fnForm}>
        <label className={styles.field}>
          <span>name</span>
          <input value={form.name} onChange={(e) => patch({ name: e.target.value })} aria-label="fn name" />
        </label>
        <label className={styles.field}>
          <span>description</span>
          <input
            value={form.description}
            onChange={(e) => patch({ description: e.target.value })}
            aria-label="fn description"
          />
        </label>
        <label className={styles.field}>
          <span>gate</span>
          <select
            value={form.gate}
            onChange={(e) => patch({ gate: e.target.value as "approve" | "auto" })}
            aria-label="fn gate"
          >
            <option value="approve">approve</option>
            <option value="auto">auto</option>
          </select>
        </label>
        <label className={styles.field}>
          <span>recipient rule</span>
          <select
            value={form.ruleType}
            onChange={(e) => patch({ ruleType: e.target.value as RecipientRule["type"] })}
            aria-label="fn rule type"
          >
            {RULE_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          <span>addresses (comma-separated)</span>
          <input
            value={form.addresses}
            onChange={(e) => patch({ addresses: e.target.value })}
            aria-label="fn addresses"
          />
        </label>
        <label className={styles.field}>
          <span>rate limit / day</span>
          <input value={form.rate} onChange={(e) => patch({ rate: e.target.value })} aria-label="fn rate limit" />
        </label>
        <label className={styles.checkField}>
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(e) => patch({ enabled: e.target.checked })}
            aria-label="fn enabled"
          />
          <span>enabled</span>
        </label>
        <label className={styles.field}>
          <span>subject template</span>
          <input value={form.subject} onChange={(e) => patch({ subject: e.target.value })} aria-label="fn subject" />
        </label>
        <label className={styles.field}>
          <span>body template</span>
          <textarea value={form.body} onChange={(e) => patch({ body: e.target.value })} aria-label="fn body" />
        </label>
        <label className={styles.field}>
          <span>params (json)</span>
          <textarea value={form.params} onChange={(e) => patch({ params: e.target.value })} aria-label="fn params" />
        </label>
        {inlineError && (
          <p className={styles.error} role="alert">
            {inlineError}
          </p>
        )}
        <Button variant="primary" onClick={handleSave} disabled={save.isPending}>
          Save
        </Button>
      </div>
    </div>
  );
}
