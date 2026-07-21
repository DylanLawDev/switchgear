import styles from "./workflows.module.css";

export interface MiniListRow {
  text: string;
  key: string;
}

// Parity workflow.js miniList: a titled list of click-through rows (artifacts/actions
// belonging to the current item).
export default function MiniList({
  title,
  rows,
  onClick,
}: {
  title: string;
  rows: MiniListRow[];
  onClick: (key: string) => void;
}) {
  return (
    <div className={styles.miniList}>
      <h4>{title}</h4>
      {rows.map((row) => (
        <button key={row.key} type="button" className={styles.miniRow} onClick={() => onClick(row.key)}>
          {row.text}
        </button>
      ))}
    </div>
  );
}
