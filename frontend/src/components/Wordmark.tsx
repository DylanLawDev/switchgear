import { Link } from "react-router-dom";
import styles from "./AppShell.module.css";

// Collapsed rail shows "a▮"; expanded (hover/focus-within/pinned) shows "switchgear▮".
// Both glyphs are purely decorative (aria-hidden) — the link's own static aria-label
// carries the accessible name so it survives regardless of collapsed/expanded state
// (the expanded form is toggled via `display: none`, which the collapsed form's
// aria-hidden alone would not have compensated for).
export default function Wordmark() {
  return (
    <Link to="/" className={styles.wordmark} aria-label="switchgear">
      <span className={styles.wordmarkMin} aria-hidden>
        a<span className={styles.caret}>▮</span>
      </span>
      <span className={styles.wordmarkFull} aria-hidden>
        switchgear<span className={styles.caret}>▮</span>
      </span>
    </Link>
  );
}
