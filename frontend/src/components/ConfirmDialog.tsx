import * as AlertDialog from "@radix-ui/react-alert-dialog";
import { ReactNode } from "react";
import Button from "./Button";
import styles from "./ConfirmDialog.module.css";

export default function ConfirmDialog({
  trigger,
  title,
  body,
  confirmLabel,
  danger,
  onConfirm,
}: {
  trigger?: ReactNode;
  title: string;
  body?: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  onConfirm: () => void;
}) {
  return (
    <AlertDialog.Root>
      {trigger && <AlertDialog.Trigger asChild>{trigger}</AlertDialog.Trigger>}
      <AlertDialog.Portal>
        <AlertDialog.Overlay className={styles.overlay} />
        <AlertDialog.Content
          className={styles.content}
          {...(!body && { "aria-describedby": undefined })}
        >
          <AlertDialog.Title className={styles.title}>{title}</AlertDialog.Title>
          {body && <AlertDialog.Description className={styles.body}>{body}</AlertDialog.Description>}
          <div className={styles.actions}>
            <AlertDialog.Cancel asChild>
              <Button variant="default">Cancel</Button>
            </AlertDialog.Cancel>
            <AlertDialog.Action asChild>
              <Button variant={danger ? "danger" : "primary"} onClick={onConfirm}>
                {confirmLabel}
              </Button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
