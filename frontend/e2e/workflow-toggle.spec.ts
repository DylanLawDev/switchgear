import { test, expect } from "@playwright/test";

test("runs/definition toggle", async ({ page }) => {
  await page.goto("/workflows/job-hunt");
  await page.getByRole("tab", { name: "Definition" }).click();
  await expect(page).toHaveURL(/view=definition/);
  await expect(page.getByText("submit-application")).toBeVisible(); // executor chip
  await page.getByRole("tab", { name: "Runs" }).click();
  // SPEC §5.8: job-hunt's empty-items state is the live PrerequisitePanel, not a plain
  // "no jobs yet" copy — assert its intro line instead. Semantics preserved: empty items
  // copy is visible in Runs.
  await expect(page.getByText(/job-hunt needs two things/i)).toBeVisible();
});
