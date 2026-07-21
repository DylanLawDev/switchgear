import { useEffect, useMemo, useState } from "react";
import { useAgents, useDeleteSchedule, useRunSchedule, useSaveSchedule, useScheduleRuns, useScheduleState, useSchedules } from "../api/queries/orchestration";
import { useWorkflows } from "../api/queries/workflows";
import { WorkflowSchedule } from "../api/types";
import Button from "../components/Button";
import SmartTextarea from "../components/SmartTextarea";
import styles from "./orchestration.module.css";

type Draft = { name: string; workflow: string; enabled: boolean; timing: "cron" | "once"; cron: string; runAt: string; timezone: string; mode: "direct" | "prompt"; values: string; prompt: string; resolver: string; overlap: boolean };
const blank = (): Draft => ({ name: "", workflow: "", enabled: true, timing: "cron", cron: "0 9 * * *", runAt: "", timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "Etc/UTC", mode: "direct", values: "{}", prompt: "", resolver: "", overlap: false });

function fromSchedule(s: WorkflowSchedule): Draft { return { name: s.name, workflow: s.workflow, enabled: s.enabled, timing: s.trigger.kind, cron: s.trigger.kind === "cron" ? s.trigger.cron : "0 9 * * *", runAt: s.trigger.kind === "once" ? s.trigger.run_at : "", timezone: s.trigger.timezone, mode: s.input.mode, values: s.input.mode === "direct" ? JSON.stringify(s.input.values, null, 2) : "{}", prompt: s.input.mode === "prompt" ? s.input.prompt : "", resolver: s.input.mode === "prompt" ? s.input.resolver_agent || "" : "", overlap: s.allow_overlap }; }

export default function SchedulerPage() {
  const { data: schedules = [] } = useSchedules(); const { data: workflows = [] } = useWorkflows(); const { data: agents = [] } = useAgents();
  const save = useSaveSchedule(); const del = useDeleteSchedule(); const run = useRunSchedule(); const state = useScheduleState();
  const [selected, setSelected] = useState(""); const [draft, setDraft] = useState<Draft>(blank); const [error, setError] = useState("");
  const current = useMemo(() => schedules.find((s) => s.id === selected), [schedules, selected]);
  const { data: runs = [] } = useScheduleRuns(selected);
  useEffect(() => { if (current) setDraft(fromSchedule(current)); }, [current]);
  function patch(next: Partial<Draft>) { setDraft((d) => ({ ...d, ...next })); setError(""); }
  function submit() { let values: Record<string, unknown> = {}; try { if (draft.mode === "direct") values = JSON.parse(draft.values); } catch { setError("Direct parameters must be valid JSON."); return; }
    const body = { name: draft.name, workflow: draft.workflow, enabled: draft.enabled, allow_overlap: draft.overlap,
      trigger: draft.timing === "cron" ? { kind: "cron" as const, cron: draft.cron, timezone: draft.timezone } : { kind: "once" as const, run_at: draft.runAt, timezone: draft.timezone },
      input: draft.mode === "direct" ? { mode: "direct" as const, values } : { mode: "prompt" as const, prompt: draft.prompt, resolver_agent: draft.resolver } };
    save.mutate({ id: selected || undefined, body }, { onSuccess: (s) => setSelected(s.id), onError: (e) => setError(e.message) }); }
  return <div className={styles.page}>
    <aside className={styles.rail}><div className={styles.railHead}><h1>Scheduler</h1><Button onClick={() => { setSelected(""); setDraft(blank()); }}>New</Button></div>{schedules.map((s) => <button key={s.id} className={selected === s.id ? styles.selected : ""} onClick={() => setSelected(s.id)}><strong>{s.name}</strong><small>{s.workflow} · {s.enabled ? "enabled" : "paused"}</small></button>)}</aside>
    <section className={styles.content}><div className={styles.formGrid}>
      <label>Name<input value={draft.name} onChange={(e) => patch({ name: e.target.value })} /></label>
      <label>Workflow<select value={draft.workflow} onChange={(e) => patch({ workflow: e.target.value })}><option value="">Select…</option>{workflows.map((w) => <option key={w.name} value={w.name}>{w.name}</option>)}</select></label>
      <label>Timing<select value={draft.timing} onChange={(e) => patch({ timing: e.target.value as Draft["timing"] })}><option value="cron">Recurring</option><option value="once">One time</option></select></label>
      {draft.timing === "cron" ? <label>Cron<input value={draft.cron} onChange={(e) => patch({ cron: e.target.value })} /></label> : <label>Run at<input type="datetime-local" value={draft.runAt} onChange={(e) => patch({ runAt: e.target.value })} /></label>}
      <label>Timezone<input value={draft.timezone} onChange={(e) => patch({ timezone: e.target.value })} /></label>
      <label>Input mode<select value={draft.mode} onChange={(e) => patch({ mode: e.target.value as Draft["mode"] })}><option value="direct">Direct parameters</option><option value="prompt">Resolver prompt</option></select></label>
    </div>
    {draft.mode === "direct" ? <div><h2>Parameters</h2><SmartTextarea value={draft.values} onChange={(values) => patch({ values })} assistPreset="parameters" workflow={draft.workflow} aria-label="schedule parameters" /></div> : <div><h2>Resolver prompt</h2><SmartTextarea value={draft.prompt} onChange={(prompt) => patch({ prompt })} assistPreset="prompt" aria-label="schedule prompt" /><label>Agent profile<select value={draft.resolver} onChange={(e) => patch({ resolver: e.target.value })}><option value="">Full-access default</option>{agents.map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}</select></label></div>}
    <div className={styles.checks}><label><input type="checkbox" checked={draft.overlap} onChange={(e) => patch({ overlap: e.target.checked })} /> Allow overlapping runs</label><label><input type="checkbox" checked={draft.enabled} onChange={(e) => patch({ enabled: e.target.checked })} /> Enabled</label></div>
    {error && <p className={styles.error}>{error}</p>}<div className={styles.toolbar}><Button variant="primary" onClick={submit} disabled={!draft.name || !draft.workflow || save.isPending}>Save schedule</Button>{current && <><Button onClick={() => run.mutate(current.id)}>Run now</Button><Button onClick={() => state.mutate({ id: current.id, enabled: !current.enabled })}>{current.enabled ? "Pause" : "Resume"}</Button><Button variant="danger" onClick={() => del.mutate(current.id, { onSuccess: () => { setSelected(""); setDraft(blank()); } })}>Delete</Button></>}</div>
    {current && <section className={styles.panel}><h2>Recent runs</h2>{runs.length === 0 ? <p className={styles.hint}>No runs yet.</p> : runs.slice(0, 10).map((item) => <div key={item.id}><strong>{item.status}</strong> · {new Date(item.created_at * 1000).toLocaleString()}{item.error && <small> · {item.error}</small>}</div>)}</section>}
    {run.data?.run && <pre>{JSON.stringify(run.data.run, null, 2)}</pre>}</section>
  </div>;
}
