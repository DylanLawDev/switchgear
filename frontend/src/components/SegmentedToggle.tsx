import * as Tabs from "@radix-ui/react-tabs";
import styles from "./SegmentedToggle.module.css";

export default function SegmentedToggle({
  value,
  onValueChange,
  options,
}: {
  value: string;
  onValueChange: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <Tabs.Root value={value} onValueChange={onValueChange} className={styles.root}>
      <Tabs.List className={styles.list} aria-label="toggle">
        {options.map((opt) => (
          <Tabs.Trigger key={opt.value} value={opt.value} className={styles.trigger}>
            {opt.label}
          </Tabs.Trigger>
        ))}
      </Tabs.List>
    </Tabs.Root>
  );
}
