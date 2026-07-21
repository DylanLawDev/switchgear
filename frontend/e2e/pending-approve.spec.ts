import { test, expect } from "@playwright/test";

// Route-intercepted (SPEC §10 decision 8: no public API creates pending edits; the real
// path is the main session's E2E gate).
test("pending edit approve flow", async ({ page }) => {
  let pending = [{ id: "pe1", resource_name: "career-bank", op: "update",
    old_content: "old\n", new_content: "new\n", created_at: "2026-07-12T00:00:00Z",
    status: "pending" }];
  await page.route("**/api/resources/pending", (r) => r.fulfill({ json: pending }));
  await page.route("**/api/resources/pending/pe1/approve", (r) => {
    pending = [];
    return r.fulfill({ json: { ok: true } });
  });
  await page.goto("/resources");
  await expect(page.getByText("career-bank")).toBeVisible();
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText(/pending/i)).toHaveCount(0);
});
