import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

import {
  loadPolygonMeta,
  loadPolygonOracle,
  POLYGON_CLOCK_ISO,
} from "./fixtures/polygon-seed";
import { gotoSection, openAppShell, selectCompany } from "./helpers/auth";

const here = path.dirname(fileURLToPath(import.meta.url));

type AgingFixture = {
  total_balance: string;
  totals_by_bucket: Record<string, string>;
  rows: { orphan_return: boolean; balance: string }[];
  unallocated_receipts: { amount: string }[];
};

function loadFixture(name: string): AgingFixture {
  return JSON.parse(fs.readFileSync(path.join(here, "fixtures", name), "utf-8")) as AgingFixture;
}

const demoOracle = loadFixture("receivable-demo-oracle.json");
const orphanOracle = loadFixture("receivable-demo-orphan-oracle.json");

const ORACLE_TOTAL = "47 506,00 ₽";

test.describe("P4b · дебиторка на полигоне", () => {
  test.beforeEach(async ({ page, context }) => {
    await context.clock.install({ time: new Date(POLYGON_CLOCK_ISO) });
    await openAppShell(page);
  });

  test("receivable_demo: итог, корзины, контрагенты и поступления без привязки", async ({ page }) => {
    const meta = loadPolygonMeta();
    const oracle = loadPolygonOracle();
    const company = meta.companies.retail;

    expect(demoOracle.total_balance).toBe("47506.00");
    expect(demoOracle.totals_by_bucket).toEqual({
      "0-30": "32501.00",
      "31-60": "5002.00",
      "61-90": "5002.00",
      ">90": "5001.00",
    });

    // Ответ снят с реального API профиля receivable_demo; полигонный seed
    // не меняем, чтобы не задеть групповой ORACLE.
    await page.route(`**/api/v1/companies/${company.id}/reports/receivable-aging**`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...demoOracle, company_id: company.id }),
      });
    });

    await page.evaluate((id) => sessionStorage.setItem("fp_company_id", id), company.id);
    await selectCompany(page, company.name);
    await gotoSection(page, "Дебиторка");
    await page.getByLabel("Дата среза").fill("2026-10-31");

    await expect(page.getByText(ORACLE_TOTAL)).toBeVisible();
    await expect(page.getByTestId("bucket-0-30")).toContainText("32 501,00 ₽");
    await expect(page.getByTestId("bucket-31-60")).toContainText("5 002,00 ₽");
    await expect(page.getByTestId("bucket-61-90")).toContainText("5 002,00 ₽");
    await expect(page.getByTestId("bucket->90")).toContainText("5 001,00 ₽");

    await expect(page.getByTestId("bucket-0-30")).toContainText("68,4 %");
    await expect(page.getByTestId("bucket->90")).toContainText("10,5 %");

    // Три контрагента из ORACLE: два с ИНН и строка без контрагента.
    const table = page.getByTestId("debt-table");
    await expect(table.getByText(/7700000901/).first()).toBeVisible();
    await expect(table.getByText(/7700000902/).first()).toBeVisible();
    await expect(table.getByRole("rowheader", { name: "Контрагент не указан" })).toBeVisible();

    // Поступления без привязки — 15 000,00.
    await expect(page.getByText("Поступления без привязки к продаже")).toBeVisible();
    await expect(page.getByText("15 000,00 ₽").first()).toBeVisible();

    // Возвратов без продажи в этом сценарии нет.
    await expect(page.getByText("Возвраты без связанной продажи")).toHaveCount(0);

    // Дата среза из ORACLE видна в подписи.
    await expect(page.getByText("Долги на 31.10.2026")).toBeVisible();
    await expect(page.getByText(oracle.revenue_label)).toHaveCount(0);
  });

  test("orphan_return: возврат без продажи показан отдельно и с минусом", async ({ page }) => {
    const meta = loadPolygonMeta();
    const company = meta.companies.retail;

    expect(orphanOracle.rows.some((row) => row.orphan_return)).toBe(true);

    await page.route(`**/api/v1/companies/${company.id}/reports/receivable-aging**`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...orphanOracle, company_id: company.id }),
      });
    });

    await page.evaluate((id) => sessionStorage.setItem("fp_company_id", id), company.id);
    await selectCompany(page, company.name);
    await gotoSection(page, "Дебиторка");
    await page.getByLabel("Дата среза").fill("2026-10-31");

    await expect(page.getByText("Возвраты без связанной продажи")).toBeVisible();
    await expect(page.getByText(/продажа не найдена или отменена/i)).toBeVisible();
    await expect(page.getByText("−2 000,00 ₽").first()).toBeVisible();
    await expect(page.getByText("39 506,00 ₽").first()).toBeVisible();
  });

  test("rows_truncated: плашка о лимите", async ({ page }) => {
    const meta = loadPolygonMeta();
    const company = meta.companies.retail;

    await page.route(`**/api/v1/companies/${company.id}/reports/receivable-aging**`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...demoOracle, company_id: company.id, rows_truncated: true }),
      });
    });

    await page.evaluate((id) => sessionStorage.setItem("fp_company_id", id), company.id);
    await selectCompany(page, company.name);
    await gotoSection(page, "Дебиторка");
    await page.getByLabel("Дата среза").fill("2026-10-31");

    await expect(page.getByText("Показаны не все строки (лимит 500). Сузьте дату среза.")).toBeVisible();
  });

  test("missing_revenue_source: отдельное объяснение вместо нулей", async ({ page }) => {
    const meta = loadPolygonMeta();
    const company = meta.companies.retail;

    await page.route(`**/api/v1/companies/${company.id}/reports/receivable-aging**`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          company_id: company.id,
          as_of: "2026-10-31",
          completeness: "unavailable",
          quality_flags: ["missing_revenue_source"],
          total_balance: "0.00",
          totals_by_bucket: { "0-30": "0.00", "31-60": "0.00", "61-90": "0.00", ">90": "0.00" },
          totals_by_counterparty: [],
          unallocated_receipts: [],
          rows: [],
          rows_truncated: false,
        }),
      });
    });

    await page.evaluate((id) => sessionStorage.setItem("fp_company_id", id), company.id);
    await selectCompany(page, company.name);
    await gotoSection(page, "Дебиторка");
    await page.getByLabel("Дата среза").fill("2026-10-31");

    await expect(page.getByText("Нет данных о продажах", { exact: true })).toBeVisible();
    await expect(page.getByText(/Источник продаж не подключён/).first()).toBeVisible();
    await expect(page.getByText("0,00 ₽")).toHaveCount(0);
  });
});
