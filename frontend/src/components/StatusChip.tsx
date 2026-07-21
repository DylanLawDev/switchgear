import styles from "./StatusChip.module.css";

// Tone map — parity with static/workflow.js STATUS_CLS.
const STATUS_CLS: Record<string, "ok" | "warn" | "signal"> = {
  approved: "ok",
  executed: "ok",
  submitted: "ok",
  failed: "warn",
  possibly_executed: "warn",
  expired: "warn",
  draft: "signal",
  executing: "signal",
};

export default function StatusChip({ status }: { status: string }) {
  const tone = STATUS_CLS[status] ?? "dim";
  return <span className={`${styles.chip} ${styles[tone]}`}>{status}</span>;
}
