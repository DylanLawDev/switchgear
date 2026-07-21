import Button from "../../components/Button";
import { usePollNow, useChannelStatus } from "../../api/queries/channels";
import { absTime } from "../../lib/format";
import styles from "./channels.module.css";

// Parity static/channels.js renderStatus: one text line, `(no address)` for the console
// transport, `(none)` cursor, `never` last-poll.
export default function ChannelStatusCard() {
  const { data: status } = useChannelStatus();
  const poll = usePollNow();

  if (!status) return null;

  const line =
    `${status.address || "(no address)"} · ${status.active ? "active" : "inactive"}` +
    ` · cursor ${status.cursor || "(none)"} · last poll ${status.last_poll ? absTime(status.last_poll) : "never"}`;

  return (
    <div className={styles.statusCard}>
      <span className={styles.statusLine}>{line}</span>
      <Button onClick={() => poll.mutate()} disabled={poll.isPending}>
        Poll now
      </Button>
    </div>
  );
}
