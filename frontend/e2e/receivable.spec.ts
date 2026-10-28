import { expect, test } from "@playwright/test";

import { loadSeedMeta } from "./fixtures/seed";
import { openAppShell, selectCompany } from "./helpers/auth";

function agingUrl(companyId: string): RegExp {
  return new RegExp(`/api/v1/companies/${companyId}/reports/receivable-aging`);
}

test.describe("P4b · экран «Дебиторка» без данных", () => {
  test("пустое состояние: нет нулей вместо долга", async ({ page }) => {
    const meta = loadSeedMeta();
    await openAppShell(page);
    await selectCompany(page, meta.companyAName);
    await page.getByRole("link", { name: "Дебиторка" }).click();

    await expect(page.getByRole("heading", { name: "Дебиторка" })).toBeVisible();
    await expect(page.getByText(/задолженность покупателей.*не деньги на счёте/i)).toBeVisible();

    await expect(page.getByText("Нет данных о продажах", { exact: true })).toBeVisible();
    await expect(page.getByText(/Продажи за период не загружены/)).toBeVisible();

    await expect(page.getByTestId("debt-table")).toHaveCount(0);
    await expect(page.getByText("0,00 ₽")).toHaveCount(0);
    await expect(page.getByText("47 506,00 ₽")).toHaveCount(0);
  });

  test("дата среза по умолчанию — сегодня в поясе фирмы", async ({ page }) => {
    const meta = loadSeedMeta();
    await openAppShell(page);
    await selectCompany(page, meta.companyAName);
    await page.getByRole("link", { name: "Дебиторка" }).click();

    const field = page.getByLabel("Дата среза");
    await expect(field).toHaveValue(/^\d{4}-\d{2}-\d{2}$/);
  });

  test("403 на чужую фирму: понятное сообщение без цифр", async ({ page }) => {
    const meta = loadSeedMeta();
    await page.route(agingUrl(meta.companyAId), async (route) => {
      await route.fulfill({
        status: 403,
        contentType: "application/json",
        body: JSON.stringify({ code: "forbidden", message: "Нет доступа" }),
      });
    });

    await openAppShell(page);
    await selectCompany(page, meta.companyAName);
    await page.getByRole("link", { name: "Дебиторка" }).click();

    const alert = page.getByRole("alert");
    await expect(alert).toBeVisible();
    await expect(alert).toContainText("Нет доступа к этой фирме");
    await expect(alert).not.toContainText("0,00");
  });

  test("клавиатура: дата среза и семантика таблицы", async ({ page }) => {
    const meta = loadSeedMeta();
    await page.route(agingUrl(meta.companyAId), async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          company_id: meta.companyAId,
          as_of: "2026-10-31",
          completeness: "full",
          quality_flags: [],
          total_balance: "9500.00",
          totals_by_bucket: {
            "0-30": "6500.00",
            "31-60": "2000.00",
            "61-90": "500.00",
            ">90": "500.00",
          },
          totals_by_counterparty: [],
          unallocated_receipts: [],
          rows: [
            {
              recognition_date: "2026-10-05",
              counterparty: { inn: "7700000901", name: "Synth AR One" },
              document: { number: "RD-A", external_id: "rd-r-a" },
              balance: "9000.00",
              bucket: "0-30",
              age_days: 26,
              orphan_return: false,
            },
            {
              recognition_date: "2026-10-25",
              counterparty: null,
              document: { number: "RD-E", external_id: "rd-r-e" },
              balance: "500.00",
              bucket: "0-30",
              age_days: 6,
              orphan_return: false,
            },
          ],
          rows_truncated: false,
        }),
      });
    });

    await openAppShell(page);
    await selectCompany(page, meta.companyAName);
    await page.getByRole("link", { name: "Дебиторка" }).click();

    const field = page.getByLabel("Дата среза");
    await field.focus();
    await expect(field).toBeFocused();
    await field.fill("2026-10-31");

    const table = page.getByTestId("debt-table");
    await expect(table).toBeVisible();
    await expect(page.getByText("9 500,00 ₽").first()).toBeVisible();
    await expect(table.getByRole("rowheader", { name: "Контрагент не указан" })).toBeVisible();
    await expect(table.getByRole("rowheader", { name: "Synth AR One (ИНН 7700000901)" })).toBeVisible();

    // Доли корзин показаны текстом, а не только цветом.
    await expect(page.getByTestId("bucket-0-30")).toContainText("68,4 %");
    await expect(page.getByTestId("bucket-31-60")).toContainText("21 %");

    // Заголовки таблицы связаны с ячейками через scope.
    await expect(table.locator("th[scope='col']").first()).toHaveText("Дата");
    await expect(page.locator("caption").first()).toContainText("Задолженность покупателей");
  });

  test("мобильный вид: карточки вместо таблицы", async ({ page }) => {
    const meta = loadSeedMeta();
    await page.route(agingUrl(meta.companyAId), async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          company_id: meta.companyAId,
          as_of: "2026-10-31",
          completeness: "preliminary",
          quality_flags: ["missing_counterparty"],
          total_balance: "9000.00",
          totals_by_bucket: {
            "0-30": "9000.00",
            "31-60": "0.00",
            "61-90": "0.00",
            ">90": "0.00",
          },
          totals_by_counterparty: [],
          unallocated_receipts: [],
          rows: [
            {
              recognition_date: "2026-10-05",
              counterparty: { inn: "7700000901", name: "Synth AR One" },
              document: { number: "RD-A", external_id: "rd-r-a" },
              balance: "9000.00",
              bucket: "0-30",
              age_days: 26,
              orphan_return: false,
            },
          ],
          rows_truncated: false,
        }),
      });
    });

    await page.setViewportSize({ width: 390, height: 844 });
    await openAppShell(page);
    await selectCompany(page, meta.companyAName);
    await page.getByRole("link", { name: "Дебиторка" }).click();

    await expect(page.getByTestId("debt-table")).toBeHidden();
    const cards = page.getByTestId("debt-cards");
    await expect(cards).toBeVisible();
    await expect(cards.getByText("Synth AR One (ИНН 7700000901)")).toBeVisible();
    await expect(cards.getByText("9 000,00 ₽")).toBeVisible();
    await expect(page.getByTestId("bucket->90")).toContainText("0 %");
  });
});
