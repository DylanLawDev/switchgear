import { Link } from "react-router-dom";
import { ConversationSummary } from "../../api/types";
import styles from "../ChatPage.module.css";

export default function ConversationRail(props: {
  conversations: ConversationSummary[];
  currentId: string | null;
  onNewChat: () => void;
}) {
  return (
    <nav className={styles.rail} aria-label="conversations">
      <div className={styles.historyList}>
        {props.conversations.map((c) => (
          <Link
            key={c._id}
            to={`/?c=${encodeURIComponent(c._id)}`}
            className={c._id === props.currentId ? `${styles.railLink} ${styles.railLinkActive}` : styles.railLink}
          >
            {c.title ?? c._id}
          </Link>
        ))}
      </div>
      <button type="button" className={styles.newChat} onClick={props.onNewChat}>+ New chat</button>
    </nav>
  );
}
