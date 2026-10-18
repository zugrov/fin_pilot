import { expect, type Page } from "@playwright/test";

export async function openAppShell(page: Page): Promise<void> {
  await page.goto("/billing");
  await page.getByRole("link", { name: "В основное меню" }).click();
}

export async function selectCompany(page: Page, companyName: string): Promise<void> {
  const firmPicker = page.getByLabel("Фирма");
  try {
    await firmPicker.waitFor({ state: "visible", timeout: 8_000 });
  } catch {
    await page.getByRole("link", { name: "Кошельки" }).click();
    await firmPicker.waitFor({ state: "visible" });
  }
  await firmPicker.selectOption({ label: companyName });
}
