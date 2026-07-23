import styles from "../ChatPage.module.css";

export interface PlanTask {
  text: string;
  status: "pending" | "in_progress" | "done" | "skipped";
}

export interface PlanResult {
  title?: string;
  tasks: PlanTask[];
}

const GLYPHS: Record<PlanTask["status"], string> = {
  done: "✓",
  in_progress: "▸",
  pending: "○",
  skipped: "—",
};

export function parsePlanResult(result: unknown): PlanResult | null {
  if (typeof result !== "object" || result === null) return null;
  const candidate = result as { title?: unknown; tasks?: unknown };
  if (!Array.isArray(candidate.tasks) || candidate.tasks.length === 0) return null;
  const tasks: PlanTask[] = [];
  for (const task of candidate.tasks) {
    if (typeof task !== "object" || task === null) return null;
    const { text, status } = task as { text?: unknown; status?: unknown };
    if (typeof text !== "string" || typeof status !== "string" || !(status in GLYPHS)) {
      return null;
    }
    tasks.push({ text, status: status as PlanTask["status"] });
  }
  return { title: typeof candidate.title === "string" ? candidate.title : "", tasks };
}

export default function PlanChecklist(props: { plan: PlanResult }) {
  return (
    <div className={styles.planCard}>
      <strong>{props.plan.title || "Plan"}</strong>
      <ul className={styles.planTasks}>
        {props.plan.tasks.map((task, i) => (
          <li key={i} data-status={task.status} className={styles.planTask}>
            <span aria-hidden className={styles.planGlyph}>{GLYPHS[task.status]}</span>
            {task.text}
          </li>
        ))}
      </ul>
    </div>
  );
}
