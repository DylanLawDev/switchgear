import { FormEvent, KeyboardEvent, useEffect, useLayoutEffect, useRef, useState } from "react";
import Button from "../../components/Button";
import styles from "../ChatPage.module.css";

export default function Composer(props: { disabled: boolean; onSend: (text: string) => void; autoFocus?: boolean }) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (props.autoFocus) textareaRef.current?.focus();
  }, [props.autoFocus]);

  useLayoutEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    const chatHeight = textarea.parentElement?.parentElement?.clientHeight ?? window.innerHeight;
    const maxHeight = chatHeight * 0.5;
    const height = Math.min(textarea.scrollHeight, maxHeight);
    textarea.style.height = `${height}px`;
    textarea.style.overflowY = textarea.scrollHeight > maxHeight ? "auto" : "hidden";
  }, [value]);

  function submit() {
    const text = value.trim();
    if (!text || props.disabled) return;
    props.onSend(text);
    setValue("");
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    submit();
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <form className={styles.composer} onSubmit={handleSubmit}>
      <textarea
        ref={textareaRef}
        className={styles.input}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={props.disabled}
        placeholder="message the agent…"
        rows={1}
      />
      <Button type="submit" variant="primary" disabled={props.disabled}>
        Send
      </Button>
    </form>
  );
}
