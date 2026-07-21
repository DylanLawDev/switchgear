import styles from "./ScoreChip.module.css";

export default function ScoreChip({ value }: { value: number | null }) {
  if (value == null) return <span className={styles.dim}>—</span>;
  return <span className={value >= 60 ? styles.signal : styles.low}>{value}</span>;
}
