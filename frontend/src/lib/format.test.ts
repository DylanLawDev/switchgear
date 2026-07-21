import { relTime, fmtBytes, fmtDuration } from "./format";
test("relTime buckets", () => {
  const now = Date.now() / 1000;
  expect(relTime(now - 120)).toBe("2m ago");
  expect(relTime(now - 7200)).toBe("2h ago");
  expect(relTime(now - 172800)).toBe("2d ago");
  expect(relTime(null)).toBe("");
});
test("fmtBytes", () => { expect(fmtBytes(900)).toBe("900 B"); expect(fmtBytes(2048)).toBe("2.0 KB"); });
test("fmtDuration", () => { expect(fmtDuration(604800)).toBe("7d"); expect(fmtDuration(180)).toBe("3m"); });
