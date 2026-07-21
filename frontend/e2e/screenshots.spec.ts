import { test } from "@playwright/test";
import { mkdirSync } from "node:fs";

// Screenshot deliverable (owner-requested, not a behavioral assertion): full-page PNGs of
// the four key views, in both themes. Saved outside frontend/ (gitignored, never
// committed) — see .superpowers/sdd/screens/.
const DIR = "../.superpowers/sdd/screens";

test("capture key views", async ({ page }) => {
  mkdirSync(DIR, { recursive: true });

  await page.goto("/workflows/job-hunt");
  // Pin the rail open so nav labels are visible (not just the collapsed 56px icon rail).
  await page.getByRole("button", { name: "pin sidebar open" }).click();

  async function captureAll(suffix: string) {
    await page.goto("/workflows/job-hunt");
    await page.screenshot({ path: `${DIR}/workflows-job-hunt-runs-${suffix}.png`, fullPage: true });

    await page.goto("/workflows/job-hunt?view=definition");
    await page.screenshot({ path: `${DIR}/workflows-job-hunt-definition-${suffix}.png`, fullPage: true });

    await page.goto("/");
    await page.screenshot({ path: `${DIR}/chat-${suffix}.png`, fullPage: true });

    await page.goto("/resources");
    await page.screenshot({ path: `${DIR}/resources-empty-${suffix}.png`, fullPage: true });
  }

  await captureAll("dark");
  await page.getByRole("button", { name: "toggle theme" }).click();
  await captureAll("light");
});
