import { ReactNode } from "react";
import styles from "./EmptyState.module.css";

export default function EmptyState(props: { heading: string; body?: string; action?: ReactNode }) {
  return (
    <div className={styles.empty}>
      <p className={styles.heading}><span className={styles.caret} aria-hidden>▮</span> {props.heading}</p>
      {props.body && <p className={styles.body}>{props.body}</p>}
      {props.action}
    </div>
  );
}
