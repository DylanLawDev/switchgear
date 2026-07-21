import { test, expect } from "@playwright/test";

// Resources onboarding + job-hunt prerequisites. Route interception keeps the spec
// deterministic regardless of real backend contents (fresh boot happens to already be
// empty here — see the harness's ../.state-e2e wipe — but this doesn't rely on that).
test("resources onboarding + job-hunt prerequisites", async ({ page }) => {
  await page.route("**/api/resources", (r) => r.fulfill({ json: [] }));
  await page.goto("/resources");
  await expect(page.getByText(/career bank/i)).toBeVisible();
  await page.route("**/api/skills/job-search/runs", (r) => r.fulfill({ json: [] }));
  await page.goto("/workflows/job-hunt");
  // job-hunt Runs' empty-items state (PrerequisitePanel) checks career-bank presence and
  // job-search intake history — both prerequisite rows are visible here.
  await expect(page.getByText(/career bank/i)).toBeVisible();
  await expect(page.getByText(/job-search/i)).toBeVisible();
});
