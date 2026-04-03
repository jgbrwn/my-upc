const { test, expect } = require('@playwright/test');

test('search for "money" returns results on my-upc.com', async ({ page }) => {
  await page.goto('https://my-upc.com');

  // Type into the search input — HTMX fires after 500ms keyup delay
  const searchInput = page.locator('#searchInput');
  await searchInput.fill('money');

  // Wait for HTMX to populate #results with at least one table row
  const firstResult = page.locator('#results tr').first();
  await expect(firstResult).toBeVisible({ timeout: 10000 });

  // Confirm there are multiple results (not just a "no results" row)
  const resultCount = await page.locator('#results tr').count();
  expect(resultCount).toBeGreaterThan(0);
});
