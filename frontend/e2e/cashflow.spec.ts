import { expect, test } from "@playwright/test";

import { loadSeedMeta } from "./fixtures/seed";
import { gotoSection, openAppShell, selectCompany } from "./helpers/auth";

function cashflowUrl(companyId: string): RegExp {
  return new RegExp(`/api/v1/companies/${companyId}/cashflow`);
}

test.describe("P4a · экран «Движение денег» без данных", () => {
  test("пустое состояние: нет нулей вместо данных", async ({ page }) => {
    const meta = loadSeedMeta();
    await openAppShell(page);
    await selectCompany(page, meta.companyAName);
    await gotoSection(page, "Деньги");

    await expect(page.getByRole("heading", { name: "Движение денег" })).toBeVisible();
    await expect(page.getByText(/движение денег, а не прибыль/i)).toBeVisible();

    // Состояние «Нет данных» — отдельная карточка, без таблицы и без нулей.
    await expect(page.getByText("Нет данных", { exact: true })).toBeVisible();
    await expect(page.getByText(/не загружено ни одной операции/)).toBeVisible();
    await expect(page.getByRole("link", { name: "Перейти к импорту" })).toBeVisible();

    await expect(page.getByRole("table")).toHaveCount(0);
    await expect(page.getByText("0,00 ₽")).toHaveCount(0);
    await expect(page.getByText("Итого по всем секциям")).toHaveCount(0);
  });

  test("период: начало позже конца блокирует отчёт", async ({ page }) => {
    const meta = loadSeedMeta();
    await openAppShell(page);
    await selectCompany(page, meta.companyAName);
    await gotoSection(page, "Деньги");

    const inputs = page.locator('input[type="date"]');
    await inputs.nth(0).fill("2026-10-31");
    await inputs.nth(1).fill("2026-10-01");
    await expect(page.getByText("Дата начала не может быть позже даты окончания.")).toBeVisible();
  });

  test("403 на чужую фирму: понятное сообщение без цифр", async ({ page }) => {
    const meta = loadSeedMeta();
    await page.route(cashflowUrl(meta.companyAId), async (route) => {
      await route.fulfill({
        status: 403,
        contentType: "application/json",
        body: JSON.stringify({ code: "forbidden", message: "Нет доступа" }),
      });
    });

    await openAppShell(page);
    await selectCompany(page, meta.companyAName);
    await gotoSection(page, "Деньги");

    const alert = page.getByRole("alert");
    await expect(alert).toBeVisible();
    await expect(alert).toContainText("Нет доступа к этой фирме");
    await expect(alert).not.toContainText("0,00");
  });

  test("клавиатура: период и раскрытие операций без мыши", async ({ page }) => {
    const meta = loadSeedMeta();
    await page.route(cashflowUrl(meta.companyAId), async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          company_id: meta.companyAId,
          as_of: "2026-10-18T12:00:00+00:00",
          date_from: "2026-10-01",
          date_to: "2026-10-31",
          input_revision: "test",
          quality_flags: ["unclassified_operations"],
          completeness: "preliminary",
          metric_basis: "cash",
          external_count: 2,
          net_external: "12800.00",
          sections: [
            {
              code: "operating",
              in: "15000.00",
              out: "2500.00",
              transaction_ids: ["tx-1", "tx-2"],
            },
            { code: "unmapped", in: "300.00", out: "0.00", transaction_ids: [] },
          ],
          drilldown_refs: { transaction_ids: ["tx-1", "tx-2"] },
        }),
      });
    });

    await openAppShell(page);
    await selectCompany(page, meta.companyAName);
    await gotoSection(page, "Деньги");

    await expect(page.getByRole("status")).toContainText("без категории");
    await expect(page.getByRole("link", { name: "Перейти к классификации" })).toBeVisible();

    const table = page.getByRole("table");
    await expect(table).toBeVisible();
    await expect(table.getByText("12 500,00 ₽")).toBeVisible();
    await expect(table.getByText("12 800,00 ₽")).toBeVisible();

    const toggle = table.getByRole("button", { name: /операции/i });
    await toggle.focus();
    await expect(toggle).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(table.getByText("tx-1")).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(table.getByText("tx-1")).toHaveCount(0);

    // Заголовки таблицы связаны с ячейками через scope.
    await expect(page.locator("th[scope='col']").first()).toHaveText("Вид деятельности");
  });

  test("мобильный вид: карточки секций вместо таблицы", async ({ page }) => {
    const meta = loadSeedMeta();
    await page.route(cashflowUrl(meta.companyAId), async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          company_id: meta.companyAId,
          as_of: "2026-10-18T12:00:00+00:00",
          date_from: "2026-10-01",
          date_to: "2026-10-31",
          input_revision: "test",
          quality_flags: ["unclassified_operations"],
          completeness: "preliminary",
          metric_basis: "cash",
          external_count: 2,
          net_external: "12800.00",
          sections: [
            { code: "operating", in: "15000.00", out: "2500.00", transaction_ids: ["tx-1"] },
            { code: "unmapped", in: "300.00", out: "0.00", transaction_ids: [] },
          ],
          drilldown_refs: { transaction_ids: ["tx-1"] },
        }),
      });
    });

    await page.setViewportSize({ width: 390, height: 844 });
    await openAppShell(page);
    await selectCompany(page, meta.companyAName);
    await gotoSection(page, "Деньги");

    await expect(page.getByRole("table")).toBeHidden();
    await expect(
      page.locator("li p").filter({ hasText: /^Не разнесено по видам деятельности$/ }),
    ).toBeVisible();
    const mobileTotals = page.locator("dl").last();
    await expect(mobileTotals).toContainText("Поступило всего");
    await expect(mobileTotals).toContainText("15 300,00 ₽");
    await expect(mobileTotals).toContainText("12 800,00 ₽");
  });
});
