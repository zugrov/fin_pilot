import path from "node:path";

import { expect, test } from "@playwright/test";

import { E2E_FIXTURES, loadSeedMeta } from "./fixtures/seed";
import { openAppShell, selectCompany } from "./helpers/auth";
import {
  countAuditForEntity,
  countCompanyRevenue,
  countMatchesForRevenue,
  countRevenueByDocument,
  latestMatchIdForRevenue,
  revenueEntryIdByDocument,
} from "./helpers/db";
import { commitImportPreview, uploadImportFile } from "./helpers/import";
import { loseFirstPostResponseAfterCommit } from "./helpers/network";
import { setOpeningBalance } from "./helpers/wallets";

test.describe("FA-R01.4 · C · unknown-result и replay", () => {
  test("revenue create: commit без ответа → запись до retry → replay без дубля", async ({ page }) => {
    const meta = loadSeedMeta();
    const doc = "IDEM-CREATE";
    const baselineTotal = countCompanyRevenue(meta.companyAId);
    expect(countRevenueByDocument(meta.companyAId, doc)).toBe(0);

    await openAppShell(page);
    await selectCompany(page, meta.companyAName);
    await page.getByRole("link", { name: "Продажи" }).click();

    await loseFirstPostResponseAfterCommit(page, "/revenue");
    await page.getByLabel("Дата признания").fill("2026-10-18");
    await page.getByLabel("Номер документа").fill(doc);
    await page.getByLabel("Сумма с НДС").fill("5.00");
    await page.getByLabel("Без НДС").fill("5.00");
    await page.getByLabel("НДС", { exact: true }).fill("0.00");
    await page.getByRole("button", { name: "Добавить продажу" }).click();
    await expect(page.getByRole("button", { name: "Повторить отправку" })).toBeVisible();

    expect(countRevenueByDocument(meta.companyAId, doc)).toBe(1);
    expect(countCompanyRevenue(meta.companyAId)).toBe(baselineTotal + 1);
    const entryId = revenueEntryIdByDocument(meta.companyAId, doc);
    expect(entryId).toBeTruthy();
    const auditBefore = countAuditForEntity("revenue_created", entryId!);
    expect(auditBefore).toBe(1);

    await page.getByRole("button", { name: "Повторить отправку" }).click();
    await expect(page.getByText(/18\.10\.2026: 5,00 ₽ без НДС/)).toHaveCount(1);

    expect(countRevenueByDocument(meta.companyAId, doc)).toBe(1);
    expect(countCompanyRevenue(meta.companyAId)).toBe(baselineTotal + 1);
    expect(countAuditForEntity("revenue_created", entryId!)).toBe(auditBefore);
  });

  test("revenue match: commit без ответа → связь до retry → replay без дубля", async ({ page }) => {
    const meta = loadSeedMeta();
    const saleDoc = "IDEM-MATCH-ONLY";

    await openAppShell(page);
    await selectCompany(page, meta.companyAName);

    await page.getByRole("link", { name: "Кошельки" }).click();
    await page.getByLabel("Название").fill("Расчётный");
    await page.getByLabel("Код (для импорта)").fill("idem");
    await page.getByRole("button", { name: "Создать счёт" }).click();
    await setOpeningBalance(page, "Расчётный (idem)", "2026-10-01", "1000.00");

    await page.getByRole("link", { name: "Импорт" }).click();
    await page.getByRole("button", { name: "Деньги" }).click();
    await uploadImportFile(page, path.join(E2E_FIXTURES, "cash_for_idem.csv"));
    await commitImportPreview(page);

    await page.getByRole("link", { name: "Продажи" }).click();
    await page.getByLabel("Дата признания").fill("2026-10-18");
    await page.getByLabel("Номер документа").fill(saleDoc);
    await page.getByLabel("Сумма с НДС").fill("4.00");
    await page.getByLabel("Без НДС").fill("4.00");
    await page.getByLabel("НДС", { exact: true }).fill("0.00");
    await page.getByRole("button", { name: "Добавить продажу" }).click();
    await expect(page.getByText(/18\.10\.2026: 4,00 ₽ без НДС/)).toBeVisible();

    const saleId = revenueEntryIdByDocument(meta.companyAId, saleDoc);
    expect(saleId).toBeTruthy();
    expect(countMatchesForRevenue(saleId!)).toBe(0);

    await page.getByLabel("Продажа").selectOption({ label: "18.10.2026 · остаток 4,00 ₽" });
    await page.getByLabel("Поступление (posted, in, RUB)").selectOption({
      label: "2026-10-10 · доступно 1500.00 — IDEM-IN-ONLY",
    });
    await page.getByLabel("Сумма связи").fill("0.50");

    await loseFirstPostResponseAfterCommit(page, "/revenue-cash-matches");
    const matchBtn = page.getByRole("button", { name: "Сопоставить" });
    await matchBtn.click();
    await expect(page.getByRole("button", { name: "Повторить сопоставление" })).toBeVisible();

    expect(countMatchesForRevenue(saleId!)).toBe(1);
    const matchId = latestMatchIdForRevenue(saleId!);
    expect(matchId).toBeTruthy();
    const matchAuditBefore = countAuditForEntity("revenue_matched", matchId!);
    expect(matchAuditBefore).toBe(1);

    await page.getByRole("button", { name: "Повторить сопоставление" }).click();
    const saleRow = page.locator("ul.mb-6 li").filter({ hasText: "18.10.2026: 4,00 ₽ без НДС" });
    await expect(saleRow.getByText(/остаток 3,50 ₽/)).toBeVisible({ timeout: 30_000 });
    await expect(saleRow.locator("ul.list-disc li")).toHaveCount(1);

    expect(countMatchesForRevenue(saleId!)).toBe(1);
    expect(countAuditForEntity("revenue_matched", matchId!)).toBe(matchAuditBefore);

    await matchBtn.dblclick();
    await expect(saleRow.locator("ul.list-disc li")).toHaveCount(1);
    expect(countMatchesForRevenue(saleId!)).toBe(1);
  });
});
