import { expect, test } from "@playwright/test";

import {
  loadPolygonMeta,
  loadPolygonOracle,
  POLYGON_CLOCK_ISO,
} from "./fixtures/polygon-seed";
import { gotoSection, openAppShell, selectCompany } from "./helpers/auth";

test.describe("P4a · ОДДС на синтетическом полигоне", () => {
  test.beforeEach(async ({ page, context }) => {
    await context.clock.install({ time: new Date(POLYGON_CLOCK_ISO) });
    await openAppShell(page);
  });

  test("retail: секции, итог и баннер по неразнесённым операциям", async ({ page }) => {
    const meta = loadPolygonMeta();
    const oracle = loadPolygonOracle();
    const company = meta.companies.retail;

    await page.evaluate((id) => sessionStorage.setItem("fp_company_id", id), company.id);
    await selectCompany(page, company.name);
    await gotoSection(page, "Деньги");

    await page.locator('input[type="date"]').nth(0).fill(oracle.period_from);
    await page.locator('input[type="date"]').nth(1).fill(oracle.period_to);

    await expect(page.getByText("Состояние данных:")).toBeVisible();
    await expect(page.getByRole("strong")).toHaveText("Предварительно");

    const status = page.getByRole("status");
    await expect(status).toContainText("без категории");
    await expect(status.getByRole("link", { name: "Перейти к классификации" })).toBeVisible();

    const table = page.getByRole("table");
    await expect(table).toBeVisible();
    await expect(table.getByRole("rowheader", { name: /Операционная деятельность/ })).toBeVisible();
    await expect(table.getByText("Не разнесено по видам деятельности")).toBeVisible();
    await expect(table.getByText("15 000,00 ₽").first()).toBeVisible();
    await expect(table.getByText("7 200,00 ₽").first()).toBeVisible();
    await expect(table.getByRole("rowheader", { name: "Итого по всем секциям" })).toBeVisible();
    await expect(table.getByText("19 700,00 ₽").first()).toBeVisible();
  });

  test("services: секции без баннера неразнесённых операций", async ({ page }) => {
    const meta = loadPolygonMeta();
    const oracle = loadPolygonOracle();
    const company = meta.companies.services;

    await page.evaluate((id) => sessionStorage.setItem("fp_company_id", id), company.id);
    await selectCompany(page, company.name);
    await gotoSection(page, "Деньги");

    await page.locator('input[type="date"]').nth(0).fill(oracle.period_from);
    await page.locator('input[type="date"]').nth(1).fill(oracle.period_to);

    const table = page.getByRole("table");
    await expect(table).toBeVisible();
    await expect(table.getByRole("rowheader", { name: /Операционная деятельность/ })).toBeVisible();
    await expect(table.getByText("20 000,00 ₽").first()).toBeVisible();
    await expect(table.getByText("17 000,00 ₽").first()).toBeVisible();
    await expect(page.getByRole("status")).toHaveCount(0);
  });

  test("пять секций ОДДС отображаются как есть", async ({ page }) => {
    const meta = loadPolygonMeta();
    const company = meta.companies.retail;

    // Профиль cashflow_sections живёт в интеграционных фикстурах; здесь проверяем
    // отрисовку полного ответа с пятью секциями и сверку итога по секциям.
    await page.route(`**/api/v1/companies/${company.id}/cashflow**`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          company_id: company.id,
          as_of: "2026-11-01T06:00:00+00:00",
          date_from: "2026-10-01",
          date_to: "2026-10-31",
          input_revision: "polygon-sections",
          quality_flags: ["unclassified_operations", "partial_period"],
          completeness: "preliminary",
          metric_basis: "cash",
          external_count: 6,
          net_external: "13150.00",
          sections: [
            { code: "operating", in: "5000.00", out: "1200.00", transaction_ids: [] },
            { code: "investing", in: "0.00", out: "800.00", transaction_ids: [] },
            { code: "financing", in: "10000.00", out: "0.00", transaction_ids: [] },
            { code: "technical", in: "0.00", out: "150.00", transaction_ids: [] },
            { code: "unmapped", in: "300.00", out: "0.00", transaction_ids: [] },
          ],
          drilldown_refs: { transaction_ids: [] },
        }),
      });
    });

    await page.evaluate((id) => sessionStorage.setItem("fp_company_id", id), company.id);
    await selectCompany(page, company.name);
    await gotoSection(page, "Деньги");

    const table = page.getByRole("table");
    await expect(table).toBeVisible();

    await expect(table.getByRole("rowheader", { name: /Операционная деятельность/ })).toBeVisible();
    await expect(table.getByRole("rowheader", { name: /Инвестиционная деятельность/ })).toBeVisible();
    await expect(table.getByRole("rowheader", { name: /Финансовая деятельность/ })).toBeVisible();
    await expect(table.getByRole("rowheader", { name: /Технические операции/ })).toBeVisible();
    await expect(
      table.getByRole("rowheader", { name: /Не разнесено по видам деятельности/ }),
    ).toBeVisible();

    await expect(table.getByText("3 800,00 ₽").first()).toBeVisible();
    await expect(table.getByText("-800,00 ₽").first()).toBeVisible();
    await expect(table.getByText("10 000,00 ₽").first()).toBeVisible();
    await expect(table.getByText("-150,00 ₽").first()).toBeVisible();
    await expect(table.getByText("13 150,00 ₽").first()).toBeVisible();
    await expect(page.getByRole("status")).toContainText("без категории");
    await expect(page.getByText(/Итог по секциям не совпал/)).toHaveCount(0);
  });
});
