import { KeyboardEvent, TextareaHTMLAttributes } from "react";
import styles from "./CodeTextarea.module.css";

export interface CodeTextareaProps
  extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "value" | "onChange"> {
  value: string;
  onChange: (value: string) => void;
}

export default function CodeTextarea({ value, onChange, className, onKeyDown, ...rest }: CodeTextareaProps) {
  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Tab") {
      event.preventDefault();
      const target = event.currentTarget;
      const { selectionStart, selectionEnd } = target;
      const next = `${value.slice(0, selectionStart)}  ${value.slice(selectionEnd)}`;
      onChange(next);
      requestAnimationFrame(() => {
        target.selectionStart = target.selectionEnd = selectionStart + 2;
      });
    }
    onKeyDown?.(event);
  };

  return (
    <textarea
      className={[styles.textarea, className].filter(Boolean).join(" ")}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={handleKeyDown}
      spellCheck={false}
      {...rest}
    />
  );
}
