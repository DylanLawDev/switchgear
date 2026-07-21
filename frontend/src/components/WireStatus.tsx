import { useSkills } from "../api/queries/skills";
import styles from "./AppShell.module.css";

export default function WireStatus() {
  const { data, isLoading, isError } = useSkills();
  const text = (() => {
    if (isLoading || isError || !data) return "agent on duty";
    const n = data.filter((s) => s.status === "active").length;
    return `agent on duty · ${n} skill${n === 1 ? "" : "s"}`;
  })();
  return <div className={styles.wire}>{text}</div>;
}
