import { useState } from "react";
import Button from "../../components/Button";
import DiffView from "../../components/DiffView";
import { useApproval, useResolveApproval } from "../../api/queries/approvals";
import { ApprovalRef } from "../../api/types";
import styles from "./ToolCallDetails.module.css";

type RecordValue = Record<string, unknown>;

function record(value: unknown): RecordValue | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as RecordValue
    : null;
}

function pretty(value: unknown): string {
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

function ApprovalPrompt({ approval }: { approval: ApprovalRef }) {
  const { data, isLoading, error } = useApproval(approval);
  const resolve = useResolveApproval();
  const [resolution, setResolution] = useState<"approved" | "rejected" | null>(null);

  if (resolution) return <div className={styles.approvalStatus}>Request {resolution}.</div>;
  if (isLoading) return <div className={styles.approvalStatus}>Checking approval status…</div>;
  if (error || !data) return <div className={styles.approvalStatus}>Approval is no longer available.</div>;
  if (data.status !== "pending") return <div className={styles.approvalStatus}>Request {data.status}.</div>;

  function act(action: "approve" | "reject") {
    resolve.mutate({ ref: approval, action }, {
      onSuccess: () => setResolution(action === "approve" ? "approved" : "rejected"),
    });
  }

  return (
    <section className={styles.approval} aria-label={`approval for ${data.title}`}>
      <div className={styles.approvalHead}>
        <strong>Approval required</strong> · {data.title}
      </div>
      <DiffView oldContent={data.before} newContent={data.after} />
      <div className={styles.approvalActions}>
        <Button variant="primary" onClick={() => act("approve")} disabled={resolve.isPending}>Approve</Button>
        <Button variant="danger" onClick={() => act("reject")} disabled={resolve.isPending}>Reject</Button>
      </div>
      {resolve.error && <div className={styles.approvalError}>{resolve.error.message}</div>}
    </section>
  );
}

export default function ToolCallDetails(props: { name: string; args: unknown; result?: unknown }) {
  const args = record(props.args);
  const result = record(props.result);
  const meta = [args?.op, args?.name].filter((value) => typeof value === "string").join(" · ");
  const rawApproval = record(result?.approval);
  const approval: ApprovalRef | null = rawApproval && typeof rawApproval.kind === "string"
    && typeof rawApproval.id === "string"
    ? { kind: rawApproval.kind, id: rawApproval.id,
        ...(typeof rawApproval.context === "string" ? { context: rawApproval.context } : {}) }
    : props.name === "resources" && result?.queued === true && typeof result.id === "string"
      ? { kind: "resource_write", id: result.id }
      : null;

  return (
    <div className={styles.wrap}>
      <details className={styles.details}>
        <summary>
          → {props.name}
          {meta && <span className={styles.summaryMeta}>{meta}</span>}
        </summary>
        <div className={styles.body}>
          <div className={styles.block}><h4>arguments</h4><pre>{pretty(props.args)}</pre></div>
          {props.result !== undefined && (
            <div className={styles.block}><h4>result</h4><pre>{pretty(props.result)}</pre></div>
          )}
        </div>
      </details>
      {approval && <ApprovalPrompt approval={approval} />}
    </div>
  );
}
