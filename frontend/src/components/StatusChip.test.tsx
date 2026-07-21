import { render, screen } from "@testing-library/react";
import StatusChip from "./StatusChip";
import styles from "./StatusChip.module.css";

test.each([
  ["approved", "ok"],
  ["executed", "ok"],
  ["submitted", "ok"],
  ["failed", "warn"],
  ["possibly_executed", "warn"],
  ["expired", "warn"],
  ["draft", "signal"],
  ["executing", "signal"],
  ["rejected", "dim"],
  ["superseded", "dim"],
])("status %s maps to tone %s", (status, tone) => {
  render(<StatusChip status={status} />);
  const el = screen.getByText(status);
  expect(el.className).toContain(styles[tone]);
});
