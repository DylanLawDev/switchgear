import { useState } from "react";
import { useApprovalInbox } from "../api/queries/orchestration";
import { useApproval, useResolveApproval } from "../api/queries/approvals";
import Button from "../components/Button";
import DiffView from "../components/DiffView";
import styles from "./orchestration.module.css";

export default function InboxPage() {
  const { data: rows = [] } = useApprovalInbox(); const [selected, setSelected] = useState<{ kind: string; id: string; context?: string } | null>(null);
  const { data } = useApproval(selected || { kind: "", id: "" }); const resolve = useResolveApproval();
  return <div className={styles.page}><aside className={styles.rail}><div className={styles.railHead}><h1>Inbox</h1><span>{rows.length} pending</span></div>{rows.map((row) => <button key={`${row.kind}:${row.id}`} className={selected?.id === row.id ? styles.selected : ""} onClick={() => setSelected(row)}><strong>{row.title}</strong><small>{row.origin === "chat" ? "Chat" : "Background"} · {row.kind}</small></button>)}</aside><section className={styles.content}>{data ? <><div className={styles.toolbar}><h2>{data.title}</h2><Button variant="primary" onClick={() => resolve.mutate({ ref: data, action: "approve" }, { onSuccess: () => setSelected(null) })}>Approve</Button><Button variant="danger" onClick={() => resolve.mutate({ ref: data, action: "reject" }, { onSuccess: () => setSelected(null) })}>Reject</Button></div><DiffView oldContent={data.before} newContent={data.after} /></> : <p className={styles.hint}>Select a pending request to review its provenance and exact change.</p>}</section></div>;
}
