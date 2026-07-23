import { FormEvent, useState } from "react";
import { useSearchParams } from "react-router-dom";
import Button from "../components/Button";
import { useClaim, useSetupStatus } from "../api/queries/setup";
import { useSaveUserSettings, useTestGateway, useUserSettings } from "../api/queries/settings";
import { CUSTOM_MODEL, MODEL_SUGGESTIONS } from "../lib/models";
import styles from "./SetupPage.module.css";

type Step = "claim" | "gateway" | "done";

export default function SetupPage() {
  const status = useSetupStatus();
  const [step, setStep] = useState<Step>("claim");

  if (status.data?.claimed && step === "claim") {
    window.location.assign("/");
    return null;
  }
  if (status.isLoading) return <div className="dim">loading…</div>;

  return (
    <div className={styles.page}>
      {step === "claim" && <ClaimStep onDone={() => setStep("gateway")} />}
      {step === "gateway" && <GatewayStep onDone={() => setStep("done")} />}
      {step === "done" && (
        <section className={styles.card}>
          <h1>You're all set</h1>
          <p>Switchgear is configured. You are logged in.</p>
          <div className={styles.actions}>
            <Button variant="primary" onClick={() => window.location.assign("/")}>
              Open Switchgear
            </Button>
          </div>
        </section>
      )}
    </div>
  );
}

function ClaimStep({ onDone }: { onDone: () => void }) {
  const [params] = useSearchParams();
  const claim = useClaim();
  const [token, setToken] = useState(params.get("token") ?? "");
  const [nickname, setNickname] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [localError, setLocalError] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    if (password !== confirm) {
      setLocalError("passwords do not match");
      return;
    }
    setLocalError("");
    claim.mutate(
      { token, password, nickname,
        owner_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone },
      { onSuccess: onDone },
    );
  }

  return (
    <form className={styles.card} onSubmit={submit}>
      <h1>Claim this instance</h1>
      <p>Use the setup token from the server logs (or your deploy configuration)
        to become the owner.</p>
      <label className={styles.field}>
        <span>Setup token</span>
        <input aria-label="Setup token" value={token}
               onChange={(e) => setToken(e.target.value)} required />
      </label>
      <label className={styles.field}>
        <span>Nickname</span>
        <small>How the agent should address you. No email needed.</small>
        <input aria-label="Nickname" value={nickname}
               onChange={(e) => setNickname(e.target.value)} required />
      </label>
      <label className={styles.field}>
        <span>Password</span>
        <small>At least 8 characters.</small>
        <input aria-label="Password" type="password" value={password} minLength={8}
               onChange={(e) => setPassword(e.target.value)} required />
      </label>
      <label className={styles.field}>
        <span>Confirm password</span>
        <input aria-label="Confirm password" type="password" value={confirm}
               onChange={(e) => setConfirm(e.target.value)} required />
      </label>
      <div className={styles.actions}>
        <Button type="submit" variant="primary" disabled={claim.isPending}>Claim</Button>
        {localError && <span className={styles.error}>{localError}</span>}
        {claim.error && <span className={styles.error}>{claim.error.message}</span>}
      </div>
    </form>
  );
}

function GatewayStep({ onDone }: { onDone: () => void }) {
  const { data } = useUserSettings();
  const save = useSaveUserSettings();
  const test = useTestGateway();
  const [baseUrl, setBaseUrl] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState<string | null>(null);
  const [customMode, setCustomMode] = useState(false);

  if (!data) return <div className="dim">loading…</div>;
  const effectiveBase = baseUrl ?? data.gateway_base_url;
  const effectiveModel = model ?? data.model_chat;
  const inList = MODEL_SUGGESTIONS.some((m) => m.id === effectiveModel);

  function submit(event: FormEvent) {
    event.preventDefault();
    const { owner: _o, gateway_api_key_set: _g, smtp_password_set: _s,
            ...editable } = data!;
    save.mutate(
      { ...editable, gateway_base_url: effectiveBase, model_chat: effectiveModel,
        ...(apiKey ? { gateway_api_key: apiKey } : {}) },
      { onSuccess: onDone },
    );
  }

  return (
    <form className={styles.card} onSubmit={submit}>
      <h1>Model gateway</h1>
      <p>Any OpenAI-compatible endpoint works. You can change this later in
        Settings.</p>
      <label className={styles.field}>
        <span>Base URL</span>
        <input aria-label="Base URL" value={effectiveBase}
               onChange={(e) => setBaseUrl(e.target.value)} required />
      </label>
      <label className={styles.field}>
        <span>API key</span>
        <input aria-label="API key" type="password" value={apiKey}
               onChange={(e) => setApiKey(e.target.value)} />
      </label>
      <label className={styles.field}>
        <span>Chat model</span>
        <small>Popular budget-friendly picks; prices are per million tokens.</small>
        <select aria-label="Chat model"
                value={customMode ? CUSTOM_MODEL : effectiveModel}
                onChange={(e) => {
                  if (e.target.value === CUSTOM_MODEL) {
                    setCustomMode(true);
                  } else {
                    setCustomMode(false);
                    setModel(e.target.value);
                  }
                }}>
          {!inList && !customMode && (
            <option value={effectiveModel}>{effectiveModel} (current)</option>
          )}
          {MODEL_SUGGESTIONS.map((m) => (
            <option key={m.id} value={m.id}>{m.label}</option>
          ))}
          <option value={CUSTOM_MODEL}>Custom model…</option>
        </select>
      </label>
      {customMode && (
        <label className={styles.field}>
          <span>Custom model</span>
          <small>Any model slug your gateway serves.</small>
          <input aria-label="Custom model" value={model ?? ""}
                 onChange={(e) => setModel(e.target.value)} required />
        </label>
      )}
      <div className={styles.actions}>
        <Button onClick={() => test.mutate({ gateway_base_url: effectiveBase,
                                             gateway_api_key: apiKey })}
                disabled={test.isPending} type="button">
          Test connection
        </Button>
        <Button type="submit" variant="primary" disabled={save.isPending}>
          Save and finish
        </Button>
        <Button type="button" onClick={onDone}>Skip for now</Button>
      </div>
      {test.data && (test.data.ok
        ? <span className={styles.success}>connected — {test.data.models} models</span>
        : <span className={styles.error}>
            {test.data.detail} (gateways without /models report failure here)
          </span>)}
      {save.error && <span className={styles.error}>{save.error.message}</span>}
    </form>
  );
}
