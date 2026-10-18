import { expect, type Page } from "@playwright/test";

export async function setOpeningBalance(
  page: Page,
  accountLabel: string,
  date: string,
  amount: string,
): Promise<void> {
  const accountSelect = page.locator('section:has(h2:has-text("Начальный остаток"))').getByLabel("Счёт");
  await accountSelect.selectOption({ label: accountLabel });
  await page.getByLabel("Дата").fill(date);
  await page.getByLabel("Сумма (RUB)").fill(amount);
  await page.getByRole("button", { name: "Проверить и подтвердить" }).click();
  await page.getByRole("button", { name: "Подтвердить", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Подтвердите начальный остаток" })).toBeHidden();
}
