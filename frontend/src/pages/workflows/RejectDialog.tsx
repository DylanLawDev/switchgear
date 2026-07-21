import * as AlertDialog from "@radix-ui/react-alert-dialog";
import { ReactNode, useState } from "react";
import Button from "../../components/Button";
import styles from "../../components/ConfirmDialog.module.css";

// Parity workflow.js rejectAction: a required comment (window.prompt there; a real form
// field here) — confirm stays disabled until the comment is non-blank.
export default function RejectDialog({
  trigger,
  onConfirm,
}: {
  trigger: ReactNode;
  onConfirm: (comment: string) => void;
}) {
  const [comment, setComment] = useState("");

  return (
    <AlertDialog.Root
      onOpenChange={(open) => {
        if (!open) setComment("");
      }}
    >
      <AlertDialog.Trigger asChild>{trigger}</AlertDialog.Trigger>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className={styles.overlay} />
        <AlertDialog.Content className={styles.content}>
          <AlertDialog.Title className={styles.title}>Reject?</AlertDialog.Title>
          <AlertDialog.Description className={styles.body}>
            <label htmlFor="reject-comment">Why reject? (required)</label>
            <textarea
              id="reject-comment"
              rows={4}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
          </AlertDialog.Description>
          <div className={styles.actions}>
            <AlertDialog.Cancel asChild>
              <Button variant="default">Cancel</Button>
            </AlertDialog.Cancel>
            <AlertDialog.Action asChild>
              <Button
                variant="danger"
                disabled={comment.trim().length === 0}
                onClick={() => onConfirm(comment.trim())}
              >
                Reject
              </Button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
