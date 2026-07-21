import Modal from "../../components/Modal";
import { useSkillRuns } from "../../api/queries/skills";
import { absTime } from "../../lib/format";
import styles from "./RunsDrawer.module.css";

// Row formatting is parity with static/skills.js showRuns(): "<time> · ok|FAILED · <usage> tok · <error?>".
export default function RunsDrawer({
  name,
  onOpenChange,
}: {
  name: string | null;
  onOpenChange: (open: boolean) => void;
}) {
  const { data: runs = [] } = useSkillRuns(name ?? "");

  return (
    <Modal open={name !== null} onOpenChange={onOpenChange} title={`Runs: ${name ?? ""}`}>
      {runs.length === 0 ? (
        <p className={styles.empty}>no runs yet</p>
      ) : (
        <ul className={styles.list}>
          {runs.map((run, i) => (
            <li key={`${run.at}-${i}`} className={styles.row}>
              {absTime(run.at)} · {run.ok ? "ok" : "FAILED"} · {run.usage} tok
              {run.error ? ` · ${run.error}` : ""}
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
}
