import OperationsStrip from "./channels/OperationsStrip";
import DigestDesk from "./channels/DigestDesk";
import styles from "./channels/channels.module.css";

// SPEC §5.5: operations strip (status/flagged always visible, settings collapsed) plus the
// embedded digest desk for any workflow whose ui_home is "channels".
export default function ChannelsPage() {
  return (
    <div className={styles.page}>
      <OperationsStrip />
      <DigestDesk />
    </div>
  );
}
