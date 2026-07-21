import * as Toast from "@radix-ui/react-toast";
import { useEffect, useState } from "react";
import { setQueryErrorSink } from "../api/queryClient";
import styles from "./Toaster.module.css";

type ToastTone = "error" | "info";
type ToastItem = { id: number; tone: ToastTone; message: string };
type Listener = (items: ToastItem[]) => void;

let items: ToastItem[] = [];
let nextId = 0;
const listeners = new Set<Listener>();

function emit() {
  for (const listener of listeners) listener(items);
}

function push(tone: ToastTone, message: string) {
  items = [...items, { id: ++nextId, tone, message }];
  emit();
}

function dismiss(id: number) {
  items = items.filter((item) => item.id !== id);
  emit();
}

function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  listener(items);
  return () => listeners.delete(listener);
}

export const toast = {
  error: (message: string) => push("error", message),
  info: (message: string) => push("info", message),
};

export default function Toaster() {
  const [visible, setVisible] = useState<ToastItem[]>([]);

  useEffect(() => {
    setQueryErrorSink(toast.error);
    return subscribe(setVisible);
  }, []);

  return (
    <Toast.Provider duration={5000} swipeDirection="right">
      {visible.map((item) => (
        <Toast.Root
          key={item.id}
          role="status"
          className={item.tone === "error" ? `${styles.toast} ${styles.error}` : styles.toast}
          onOpenChange={(open) => {
            if (!open) dismiss(item.id);
          }}
        >
          <Toast.Description className={styles.message}>{item.message}</Toast.Description>
          <Toast.Close className={styles.close} aria-label="dismiss">
            ×
          </Toast.Close>
        </Toast.Root>
      ))}
      <Toast.Viewport className={styles.viewport} />
    </Toast.Provider>
  );
}
