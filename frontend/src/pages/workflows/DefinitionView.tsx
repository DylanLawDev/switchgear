import { ReactNode, useEffect, useState } from "react";
import { useSaveWorkflowDefinition, useWorkflowDefinition } from "../../api/queries/workflows";
import { useSkills } from "../../api/queries/skills";
import { ActionsDef, FieldDef, KindDef, WorkflowDefinition } from "../../api/types";
import Badge from "../../components/Badge";
import MarkdownView from "../../components/MarkdownView";
import { fmtDuration } from "../../lib/format";
import tableStyles from "../../components/RecordTable.module.css";
import styles from "./workflows.module.css";
import Button from "../../components/Button";
import SmartTextarea from "../../components/SmartTextarea";

// Read-only render of the same definition JSON RunsView consumes — no new endpoint
// (SPEC §5.4.2).

function fieldExtras(field: FieldDef): string {
  const bits: string[] = [];
  if (field.max != null) bits.push(`max ${field.max}`);
  if (field.href_prefix) bits.push(field.href_prefix);
  return bits.join(" ");
}

function ChipRow({ label, values }: { label: string; values: string[] }) {
  if (values.length === 0) return null;
  return (
    <div className={styles.chipRow}>
      <span className={styles.chipRowLabel}>{label}</span>
      {values.map((v) => (
        <Badge key={v} tone="dim">
          {v}
        </Badge>
      ))}
    </div>
  );
}

function SchemaSection({ title, kind }: { title: string; kind: KindDef }) {
  return (
    <section className={styles.kindSection}>
      <h2>{title}</h2>
      <div className={tableStyles.wrap}>
        <table className={tableStyles.table}>
          <thead>
            <tr>
              <th className={tableStyles.th}>field</th>
              <th className={tableStyles.th}>type</th>
              <th className={tableStyles.th}>extras</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(kind.fields).map(([name, field]) => (
              <tr key={name}>
                <td className={tableStyles.td}>{name}</td>
                <td className={tableStyles.td}>{field.type}</td>
                <td className={tableStyles.td}>{fieldExtras(field)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ChipRow label="list fields" values={kind.list_fields} />
      <ChipRow label="sort" values={kind.sort} />
      <div className={styles.btnRow}>
        {kind.retention != null && <Badge tone="dim">retention {fmtDuration(kind.retention)}</Badge>}
        {kind.expected_update_period != null && (
          <Badge tone="dim">refresh {fmtDuration(kind.expected_update_period)}</Badge>
        )}
      </div>
    </section>
  );
}

function ActionsCard({ actions }: { actions: ActionsDef }) {
  return (
    <section className={styles.kindSection}>
      <h2>Actions</h2>
      <p className={styles.wfDesc}>{actions.label_plural}</p>
      <p>executor: {actions.executor}</p>
      <div className={styles.btnRow}>
        <Badge tone="dim">approval ttl {fmtDuration(actions.approval_ttl)}</Badge>
        <Badge tone="dim">draft ttl {fmtDuration(actions.draft_ttl)}</Badge>
      </div>
      {/* Static gate diagram, not derived from the record's live status — SPEC §5.4.2. */}
      <p className={styles.gateDiagram}>draft → approve → execute → confirm</p>
    </section>
  );
}

function IntakeSection({ definition, skills }: { definition: WorkflowDefinition; skills: { name: string; schedule: string | null }[] }) {
  if (!definition.intake) return null;
  return (
    <section className={styles.kindSection}>
      <h2>Intake</h2>
      <ul className={styles.intakeList}>
        {definition.intake.skills.map((name) => {
          const schedule = skills.find((s) => s.name === name)?.schedule;
          return (
            <li key={name}>
              {name}
              {schedule && <Badge tone="dim">{schedule}</Badge>}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function Section({ heading, children }: { heading: string; children: ReactNode }) {
  return (
    <section className={styles.kindSection}>
      <h2>{heading}</h2>
      {children}
    </section>
  );
}

export default function DefinitionView({ workflowName }: { workflowName: string }) {
  const { data: definition } = useWorkflowDefinition(workflowName);
  const { data: skills = [] } = useSkills();
  const save = useSaveWorkflowDefinition(workflowName);
  const [mode, setMode] = useState<"structured" | "raw">("structured");
  const [raw, setRaw] = useState("");
  useEffect(() => { if (definition?.text) setRaw(definition.text); }, [definition?.text]);

  if (!definition) return null;

  return (
    <div className={styles.runs}>
      <div className={styles.btnRow}><h1>{definition.name}</h1><Button onClick={() => setMode("structured")} disabled={mode === "structured"}>Structured</Button><Button onClick={() => setMode("raw")} disabled={mode === "raw"}>Raw manifest</Button></div>
      {mode === "raw" ? <><SmartTextarea value={raw} onChange={setRaw} assistPreset="workflow" className={styles.rawManifest} aria-label="workflow manifest" /><div className={styles.btnRow}><Button variant="primary" onClick={() => save.mutate(raw)}>Validate and save</Button>{save.error && <span className={styles.error}>{save.error.message}</span>}</div></> : <>
      <Section heading="About">
        {definition.description && <p className={styles.wfDesc}>{definition.description}</p>}
        {definition.body && <MarkdownView source={definition.body} />}
      </Section>
      <IntakeSection definition={definition} skills={skills} />
      {definition.execution && <Section heading="Execution"><p>Inputs and outputs are JSON Schema validated.</p><ol>{definition.execution.steps.map((step) => <li key={step.id}><Badge tone="dim">{step.type}</Badge> {step.id}{step.when ? " · conditional" : ""}</li>)}</ol></Section>}
      {definition.items && <SchemaSection title="Items schema" kind={definition.items} />}
      {definition.artifacts && <SchemaSection title="Artifacts schema" kind={definition.artifacts} />}
      {definition.actions && <ActionsCard actions={definition.actions} />}
      {definition.generate && (
        <Section heading="Generate">
          <Badge tone="signal">
            {definition.generate.plugin} — {definition.generate.label}
          </Badge>
        </Section>
      )}
      </>}
    </div>
  );
}
