import { ReactNode } from "react";
import styles from "./Badge.module.css";

export type BadgeTone = "dim" | "signal" | "ok" | "warn";

export default function Badge({ tone = "dim", children }: { tone?: BadgeTone; children: ReactNode }) {
  return <span className={`${styles.badge} ${styles[tone]}`}>{children}</span>;
}
