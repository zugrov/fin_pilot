import { expect, type Page } from "@playwright/test";

export async function uploadImportFile(page: Page, filePath: string): Promise<void> {
  await page.getByRole("button", { name: "Создать источник" }).click();
  await expect(page.getByText(/Источник:/)).toBeVisible();
  await page.locator('input[type="file"]').setInputFiles(filePath);
  await expect(page.getByText(/Новых/)).toBeVisible();
}

export async function commitImportPreview(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Провести" }).click();
  await expect(page.getByText(/^Статус: /)).toBeVisible();
}
