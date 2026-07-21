import { diffLines } from "diff";
import styles from "./DiffView.module.css";

type LineType = "add" | "remove" | "same";
interface DiffLine { type: LineType; text: string }

// null old/new is treated as "" for diffLines — the whole content lands in a single
// added/removed hunk, which already satisfies "null old -> all-added, null new -> all-removed".
function toLines(oldContent: string | null, newContent: string | null): DiffLine[] {
  const parts = diffLines(oldContent ?? "", newContent ?? "");
  const lines: DiffLine[] = [];
  for (const part of parts) {
    const type: LineType = part.added ? "add" : part.removed ? "remove" : "same";
    const raw = part.value.split("\n");
    if (raw.length > 0 && raw[raw.length - 1] === "") raw.pop();
    for (const text of raw) lines.push({ type, text });
  }
  return lines;
}

const GUTTER: Record<LineType, string> = { add: "+", remove: "−", same: " " };

export default function DiffView({
  oldContent,
  newContent,
}: {
  oldContent: string | null;
  newContent: string | null;
}) {
  const lines = toLines(oldContent, newContent);
  return (
    <div className={styles.diff}>
      {lines.map((line, i) => (
        <div
          key={i}
          data-line-type={line.type}
          className={[styles.row, line.type === "add" && styles.add, line.type === "remove" && styles.remove]
            .filter(Boolean)
            .join(" ")}
        >
          <span className={styles.gutter} aria-hidden>{GUTTER[line.type]}</span>
          <span className={styles.text}>{line.text}</span>
        </div>
      ))}
    </div>
  );
}
