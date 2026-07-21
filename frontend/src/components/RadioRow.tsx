import * as RadioGroup from "@radix-ui/react-radio-group";
import styles from "./RadioRow.module.css";

export default function RadioRow({
  value,
  onValueChange,
  options,
}: {
  value: string;
  onValueChange: (value: string) => void;
  options: { value: string; label: string; description?: string }[];
}) {
  return (
    <RadioGroup.Root value={value} onValueChange={onValueChange} className={styles.root}>
      {options.map((opt) => (
        <label key={opt.value} className={styles.row} htmlFor={`radio-${opt.value}`}>
          <RadioGroup.Item value={opt.value} id={`radio-${opt.value}`} className={styles.item}>
            <RadioGroup.Indicator className={styles.indicator} />
          </RadioGroup.Item>
          <span className={styles.text}>
            <span className={styles.label}>{opt.label}</span>
            {opt.description && <span className={styles.description}>{opt.description}</span>}
          </span>
        </label>
      ))}
    </RadioGroup.Root>
  );
}
