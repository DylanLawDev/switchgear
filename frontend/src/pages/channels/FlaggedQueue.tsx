import Button from "../../components/Button";
import { useFlagged, useRefile } from "../../api/queries/channels";
import { absTime } from "../../lib/format";
import styles from "./channels.module.css";

// Parity static/channels.js loadFlagged: subject/sender/reason render as `textContent` ONLY —
// they derive from attacker-controlled mail, so JSX's default text interpolation (never
// dangerouslySetInnerHTML) is the load-bearing safety property here.
export default function FlaggedQueue() {
  const { data: rows = [] } = useFlagged();
  const refile = useRefile();

  if (rows.length === 0) {
    return <p className={styles.oneLiner}>no flagged messages</p>;
  }

  return (
    <ul className={styles.flaggedList}>
      {rows.map((row) => (
        <li key={row.key} className={styles.flaggedRow}>
          <span className={styles.flaggedSubject}>{row.subject || "(no subject)"}</span>
          <span className={styles.flaggedSender}>{row.sender || ""}</span>
          <span className={styles.flaggedReceived}>{row.received_at ? absTime(row.received_at) : ""}</span>
          <span className={styles.flaggedReason}>{row.triage_reason || ""}</span>
          <Button variant="ghost" onClick={() => refile.mutate(row.key)}>
            File
          </Button>
        </li>
      ))}
    </ul>
  );
}
