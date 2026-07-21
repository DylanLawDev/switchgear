import * as Dialog from "@radix-ui/react-dialog";
import { ReactNode } from "react";
import styles from "./Modal.module.css";

export default function Modal({
  open,
  onOpenChange,
  title,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: ReactNode;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content className={styles.content} aria-describedby={undefined}>
          <Dialog.Title className={styles.title}>{title}</Dialog.Title>
          <div className={styles.body}>{children}</div>
          <Dialog.Close asChild>
            <button type="button" className={styles.close} aria-label="close">
              ×
            </button>
          </Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
