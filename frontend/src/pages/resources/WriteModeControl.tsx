import RadioRow from "../../components/RadioRow";
import { useSetWriteMode, useWriteMode } from "../../api/queries/resources";
import { WriteMode } from "../../api/types";
import styles from "./WriteModeControl.module.css";

const OPTIONS: { value: WriteMode; label: string; description?: string }[] = [
  { value: "read-only", label: "read-only", description: "agent resource writes are refused" },
  { value: "prompt", label: "prompt", description: "agent writes queue for owner approval" },
  { value: "full", label: "full", description: "agent writes apply immediately" },
];

export default function WriteModeControl() {
  const { data } = useWriteMode();
  const setMode = useSetWriteMode();
  const value = data?.write_mode ?? "prompt";

  return (
    <div className={styles.control}>
      <span className={styles.label}>agent write mode</span>
      <RadioRow value={value} onValueChange={(v) => setMode.mutate(v as WriteMode)} options={OPTIONS} />
    </div>
  );
}
