import { expect, test } from "@playwright/test";

import { loadSeedMeta } from "./fixtures/seed";
import { openAppShell, selectCompany } from "./helpers/auth";

test.describe("FA-R01.4 · B · две фирмы", () => {
  test("без выбора нет записи; переключение и reload; stale response", async ({ page }) => {
    const meta = loadSeedMeta();
    await openAppShell(page);

    await page.getByRole("link", { name: "Продажи" }).click();
    await page.getByLabel("Дата признания").fill("2026-10-18");
    await page.getByLabel("Сумма с НДС").fill("1.00");
    await page.getByLabel("Без НДС").fill("1.00");
    await page.getByLabel("НДС", { exact: true }).fill("0.00");
    const addBtn = page.getByRole("button", { name: "Добавить продажу" });
    await expect(addBtn).toBeDisabled();

    await selectCompany(page, meta.companyAName);
    await expect(addBtn).toBeEnabled();
    await page.getByLabel("Номер документа").fill("FIRM-A-MARKER");
    await addBtn.click();
    await expect(page.getByText(/2026-10-18: 1\.00 без НДС/)).toBeVisible();

    let resolveSlow: () => void = () => undefined;
    const slowGate = new Promise<void>((resolve) => {
      resolveSlow = resolve;
    });
    await page.route(`**/api/v1/companies/${meta.companyAId}/revenue**`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.continue();
        return;
      }
      await slowGate;
      await route.continue();
    });

    await selectCompany(page, meta.companyBName);
    await page.getByLabel("Номер документа").fill("FIRM-B-ONLY");
    await page.getByLabel("Сумма с НДС").fill("3.00");
    await page.getByLabel("Без НДС").fill("3.00");
    await page.getByRole("button", { name: "Добавить продажу" }).click();
    await expect(page.getByText(/2026-10-18: 3\.00 без НДС/)).toBeVisible();
    await expect(page.getByText(/2026-10-18: 1\.00 без НДС/)).not.toBeVisible();

    resolveSlow();
    await page.waitForTimeout(300);
    await expect(page.getByText(/2026-10-18: 1\.00 без НДС/)).not.toBeVisible();

    await page.reload();
    await page.getByRole("link", { name: "Продажи" }).click();
    await selectCompany(page, meta.companyBName);
    await expect(page.getByText(/2026-10-18: 3\.00 без НДС/)).toBeVisible();
  });
});
