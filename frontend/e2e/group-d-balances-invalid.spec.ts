import { expect, test } from "@playwright/test";

import { loadSeedMeta } from "./fixtures/seed";
import { openAppShell, selectCompany } from "./helpers/auth";
import { setOpeningBalance } from "./helpers/wallets";

const BAD_BALANCES = "wallet_code,as_of,balance,currency\nunknown,2026-10-01,1.00,RUB\n";

test.describe("FA-R01.4 · D · невалидный balances batch", () => {
  test("ошибка в preview; проведение заблокировано; opening не меняется", async ({ page }) => {
    const meta = loadSeedMeta();
    await openAppShell(page);
    await selectCompany(page, meta.companyAName);

    await page.getByRole("link", { name: "Кошельки" }).click();
    await page.getByLabel("Название").fill("Для balances D");
    await page.getByLabel("Код (для импорта)").fill("bdmain");
    await page.getByRole("button", { name: "Создать счёт" }).click();
    const walletCard = page.locator("li").filter({ hasText: "Для balances D" });
    await setOpeningBalance(page, "Для balances D (bdmain)", "2026-10-01", "500.00");
    await expect(walletCard.getByText(/Начальный остаток: 500\.00/)).toBeVisible();

    await page.getByRole("link", { name: "Импорт" }).click();
    await page.getByRole("button", { name: "Остатки" }).click();
    await page.getByRole("button", { name: "Создать источник" }).click();
    await expect(page.getByText(/Источник:/)).toBeVisible();
    await page.locator('input[type="file"]').setInputFiles({
      name: "bad-balances.csv",
      mimeType: "text/csv",
      buffer: Buffer.from(BAD_BALANCES),
    });
    await expect(page.getByText(/ошибок 1/)).toBeVisible();
    await expect(page.getByText(/unknown_wallet/)).toBeVisible();
    const commit = page.getByRole("button", { name: "Провести" });
    await commit.click();
    await expect(page.getByText(/ошибки строк/)).toBeVisible();

    await page.getByRole("link", { name: "Кошельки" }).click();
    await expect(walletCard.getByText(/Начальный остаток: 500\.00/)).toBeVisible();
  });
});
