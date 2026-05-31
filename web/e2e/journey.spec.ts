import { test, expect } from "@playwright/test";

// Happy path: portfolio -> workspace journey -> blueprint stage shows
// the cockpit shell (rail, header, cost pill, agent console, evidence drawer).
test("navigate portfolio into a workspace journey", async ({ page }) => {
  await page.goto("/workspaces");
  await expect(page.getByText("Modernization Cockpit")).toBeVisible();
  await page.getByText("CardDemo").click();

  // landed in the journey; Journey Rail shows all 11 stages
  await expect(page.getByRole("navigation")).toContainText("Blueprint");
  await expect(page.getByText("Modernization Agent")).toBeVisible();

  // cost-vs-cap pill visible in the stage header
  await expect(page.getByText(/\$\d+(\.\d+)?\s*\/\s*\$\d+/)).toBeVisible();
});
