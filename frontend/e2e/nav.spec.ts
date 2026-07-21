import { test, expect } from "@playwright/test";

test("six-tab navigation", async ({ page }) => {
  await page.goto("/");
  for (const [label, path] of [["Skills", "/skills"], ["Workflows", "/workflows"],
      ["Channels", "/channels"], ["Resources", "/resources"], ["Memories", "/memories"],
      ["Chat", "/"]] as const) {
    // Rail nav labels are CSS text-transform: lowercase (opacity-hidden but present in the
    // a11y tree at the collapsed rail width) — match case-insensitively.
    await page.getByRole("link", { name: new RegExp(label, "i") }).click();
    await expect(page).toHaveURL(new RegExp(`${path}$`));
  }
  await expect(page.getByText(/agent on duty/)).toBeVisible();
});

test("digest deep link resolves", async ({ page }) => {
  await page.goto("/workflows/job-hunt");
  await expect(page.getByRole("heading", { name: /jobs/i })).toBeVisible();
});
