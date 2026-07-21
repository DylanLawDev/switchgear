import { useEffect, useState } from "react";
import { AgentProfile } from "../api/types";
import { useAgent, useAgents, useDeleteAgent, useSaveAgent, useTestAgent } from "../api/queries/orchestration";
import Button from "../components/Button";
import SmartTextarea from "../components/SmartTextarea";
import styles from "./orchestration.module.css";

type AccessMode = "all" | "selected";
type Guided = { description: string; tier: "chat" | "bulk" | "writing"; prompt: string;
  toolMode: AccessMode; tools: string; resourceMode: AccessMode; resources: string;
  skillMode: AccessMode; skills: string; outputSchema: string };

const initialGuided = (): Guided => ({ description: "A focused reusable agent", tier: "chat",
  prompt: "Complete the assigned task carefully and return a concise result.\n",
  toolMode: "all", tools: "", resourceMode: "all", resources: "", skillMode: "all", skills: "", outputSchema: "" });
const csv = (value: string) => value.split(",").map((item) => item.trim()).filter(Boolean);
const yamlList = (values: string) => JSON.stringify(csv(values));
function manifest(name: string, value: Guided): string {
  const lines = ["---", "schema_version: 1", `name: ${name}`, `description: ${JSON.stringify(value.description)}`,
    `model_tier: ${value.tier}`];
  if (value.toolMode === "selected") lines.push(`tools: ${yamlList(value.tools)}`);
  if (value.resourceMode === "selected") lines.push(`resources: ${yamlList(value.resources)}`);
  if (value.skillMode === "selected") lines.push(`skills: ${yamlList(value.skills)}`);
  if (value.outputSchema.trim()) lines.push(`output_schema: ${value.outputSchema.trim()}`);
  return `${lines.join("\n")}\n---\n${value.prompt}`;
}
function fromProfile(profile: AgentProfile): Guided {
  return { description: profile.description, tier: profile.model_tier, prompt: profile.prompt,
    toolMode: profile.tools === null ? "all" : "selected", tools: (profile.tools || []).join(", "),
    resourceMode: profile.resources === null ? "all" : "selected", resources: (profile.resources || []).join(", "),
    skillMode: profile.skills === null ? "all" : "selected", skills: (profile.skills || []).join(", "),
    outputSchema: profile.output_schema ? JSON.stringify(profile.output_schema) : "" };
}

export default function AgentsPage() {
  const { data: agents = [] } = useAgents();
  const [selected, setSelected] = useState("");
  const { data } = useAgent(selected);
  const save = useSaveAgent(); const del = useDeleteAgent(); const test = useTestAgent();
  const [name, setName] = useState("new-agent"); const [text, setText] = useState("");
  const [guided, setGuided] = useState<Guided>(initialGuided); const [raw, setRaw] = useState(false);
  const [testPrompt, setTestPrompt] = useState("");
  useEffect(() => { if (data) { setName(data.name); setText(data.text); setGuided(fromProfile(data)); } }, [data]);

  function create() { const next = initialGuided(); setSelected(""); setName("new-agent"); setGuided(next); setText(manifest("new-agent", next)); setRaw(false); }
  function patch(next: Partial<Guided>) { setGuided((current) => ({ ...current, ...next })); }
  function toggleRaw() { if (!raw) setText(manifest(name, guided)); setRaw((value) => !value); }
  return <div className={styles.page}>
    <aside className={styles.rail}><div className={styles.railHead}><h1>Agents</h1><Button onClick={create}>New</Button></div>
      {agents.map((agent) => <button key={agent.name} className={selected === agent.name ? styles.selected : ""} onClick={() => { setSelected(agent.name); setRaw(false); }}><strong>{agent.name}</strong><small>{agent.description}</small></button>)}
    </aside>
    <section className={styles.content}>
      <div className={styles.toolbar}><input aria-label="profile name" value={name} onChange={(e) => setName(e.target.value)} /><Button onClick={toggleRaw}>{raw ? "Guided editor" : "Raw AGENT.md"}</Button><Button variant="primary" disabled={!name || save.isPending} onClick={() => save.mutate({ name, text: raw ? text : manifest(name, guided) })}>Save profile</Button>{selected && <Button variant="danger" onClick={() => del.mutate(selected, { onSuccess: create })}>Delete</Button>}</div>
      {raw ? <SmartTextarea className={styles.manifest} value={text} onChange={setText} aria-label="agent manifest" /> : <div className={styles.formGrid}>
        <label>Description<input value={guided.description} onChange={(e) => patch({ description: e.target.value })} /></label>
        <label>Model tier<select value={guided.tier} onChange={(e) => patch({ tier: e.target.value as Guided["tier"] })}><option value="chat">Chat</option><option value="bulk">Bulk</option><option value="writing">Writing</option></select></label>
        {(["tool", "resource", "skill"] as const).map((kind) => { const modeKey = `${kind}Mode` as "toolMode" | "resourceMode" | "skillMode"; const valuesKey = `${kind}s` as "tools" | "resources" | "skills"; return <label key={kind}>{kind[0].toUpperCase() + kind.slice(1)} access<select value={guided[modeKey]} onChange={(e) => patch({ [modeKey]: e.target.value as AccessMode })}><option value="all">All available</option><option value="selected">Selected only</option></select>{guided[modeKey] === "selected" && <input aria-label={`${kind} allowlist`} placeholder="comma-separated; blank means none" value={guided[valuesKey]} onChange={(e) => patch({ [valuesKey]: e.target.value })} />}</label>; })}
        <label>Output JSON Schema (optional)<SmartTextarea value={guided.outputSchema} onChange={(outputSchema) => patch({ outputSchema })} aria-label="agent output schema" /></label>
        <label>Agent instructions<SmartTextarea value={guided.prompt} onChange={(prompt) => patch({ prompt })} assistPreset="prompt" aria-label="agent instructions" /></label>
      </div>}
      <section className={styles.panel}><h2>Test profile</h2><SmartTextarea value={testPrompt} onChange={setTestPrompt} assistPreset="prompt" aria-label="test prompt" /><Button onClick={() => test.mutate({ name, prompt: testPrompt })} disabled={!selected || !testPrompt || test.isPending}>Run test</Button>{test.data && <pre>{JSON.stringify(test.data.output ?? test.data.error, null, 2)}</pre>}</section>
    </section>
  </div>;
}
