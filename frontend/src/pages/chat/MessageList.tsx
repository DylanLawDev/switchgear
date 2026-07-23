import { useEffect, useRef } from "react";
import MarkdownView from "../../components/MarkdownView";
import PlanChecklist, { parsePlanResult } from "./PlanChecklist";
import ToolCallDetails from "./ToolCallDetails";
import styles from "../ChatPage.module.css";

export type TranscriptItem =
  | { kind: "message"; id: number; role: "user" | "assistant" | "error"; content: string }
  | { kind: "tool"; id: number; name: string; args: unknown; result?: unknown };

export default function MessageList(props: { items: TranscriptItem[]; streaming: boolean }) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [props.items, props.streaming]);

  return (
    <div className={styles.messages} ref={scrollRef}>
      {props.items.map((item) =>
        item.kind === "message" ? (
          <div
            key={item.id}
            className={
              item.role === "user"
                ? `${styles.msg} ${styles.msgUser}`
                : item.role === "error"
                  ? `${styles.msg} ${styles.msgError}`
                  : `${styles.msg} ${styles.msgAssistant}`
            }
          >
            {item.role === "assistant" ? <MarkdownView source={item.content} /> : item.content}
          </div>
        ) : item.name === "plan" && parsePlanResult(item.result) ? (
          <PlanChecklist key={item.id} plan={parsePlanResult(item.result)!} />
        ) : (
          <ToolCallDetails key={item.id} name={item.name} args={item.args} result={item.result} />
        ),
      )}
      {props.streaming && (
        <span className={styles.caret} aria-hidden>
          ▮
        </span>
      )}
    </div>
  );
}
