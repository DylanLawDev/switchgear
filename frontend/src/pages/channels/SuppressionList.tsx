import { useState } from "react";
import Button from "../../components/Button";
import { useSuppress, useSuppression, useUnsuppress } from "../../api/queries/channels";
import { absTime } from "../../lib/format";
import styles from "./channels.module.css";

// Parity static/channels.js renderSuppression / suppress-add handler.
export default function SuppressionList() {
  const { data: rows = [] } = useSuppression();
  const suppress = useSuppress();
  const unsuppress = useUnsuppress();
  const [address, setAddress] = useState("");
  const [inlineError, setInlineError] = useState<string | null>(null);

  async function handleAdd() {
    setInlineError(null);
    const trimmed = address.trim();
    if (!trimmed) return;
    try {
      await suppress.mutateAsync(trimmed);
      setAddress("");
    } catch (err) {
      setInlineError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleRemove(addr: string) {
    try {
      await unsuppress.mutateAsync(addr);
    } catch {
      // global mutation-cache sink already toasts; swallow to avoid an unhandled rejection.
    }
  }

  return (
    <div className={styles.suppression}>
      {rows.length === 0 && <p className={styles.oneLiner}>no suppressed addresses yet — add one below</p>}
      <ul className={styles.suppressionList}>
        {rows.map((row) => (
          <li key={row.address} className={styles.suppressionRow}>
            <span>{row.address}</span>
            <span className={styles.suppressionMeta}>{absTime(row.added_at)}</span>
            <Button variant="ghost" onClick={() => handleRemove(row.address)}>
              Remove
            </Button>
          </li>
        ))}
      </ul>
      <div className={styles.suppressionAdd}>
        <input
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          placeholder="address to suppress"
          aria-label="suppress address"
        />
        <Button onClick={handleAdd}>Add</Button>
      </div>
      {inlineError && (
        <p className={styles.error} role="alert">
          {inlineError}
        </p>
      )}
    </div>
  );
}
