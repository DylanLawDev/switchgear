import ChannelStatusCard from "./ChannelStatusCard";
import FlaggedQueue from "./FlaggedQueue";
import SendFunctionEditor from "./SendFunctionEditor";
import SuppressionList from "./SuppressionList";
import styles from "./channels.module.css";

// SPEC §5.5: status + flagged are daily ops, always visible; send-function editing and
// suppression management are settings, tucked behind collapsed <details> panels.
export default function OperationsStrip() {
  return (
    <div className={styles.strip}>
      <ChannelStatusCard />
      <section className={styles.panel}>
        <h2>flagged</h2>
        <FlaggedQueue />
      </section>
      <details className={styles.settingsPanel}>
        <summary>send functions</summary>
        <SendFunctionEditor />
      </details>
      <details className={styles.settingsPanel}>
        <summary>suppression list</summary>
        <SuppressionList />
      </details>
    </div>
  );
}
