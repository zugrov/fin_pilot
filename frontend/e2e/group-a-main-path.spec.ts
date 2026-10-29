import path from "node:path";

import { expect, test, type Request } from "@playwright/test";

import { E2E_FIXTURES, FIXTURES, loadSeedMeta } from "./fixtures/seed";
import { openAppShell, selectCompany } from "./helpers/auth";
import { commitImportPreview, uploadImportFile } from "./helpers/import";
import { setOpeningBalance } from "./helpers/wallets";

test.describe("FA-R01.4 · A · основной путь одной фирмы", () => {
  test("wallet → opening → cash/balances import → sale/plan → partial matches", async ({ page }) => {
    const meta = loadSeedMeta();
    await openAppShell(page);
    await selectCompany(page, meta.companyAName);

    await page.getByRole("link", { name: "Кошельки" }).click();
    await page.getByLabel("Название").fill("Расчётный");
    await page.getByLabel("Код (для импорта)").fill("main");
    await page.getByRole("button", { name: "Создать счёт" }).click();
    await setOpeningBalance(page, "Расчётный (main)", "2026-10-01", "1000.00");
    await expect(page.getByText(/Начальный остаток: 1000\.00/)).toBeVisible();

    await page.getByRole("link", { name: "Импорт" }).click();
    await page.getByRole("button", { name: "Деньги" }).click();
    await uploadImportFile(page, path.join(E2E_FIXTURES, "cash_for_path.csv"));
    await commitImportPreview(page);

    await page.getByRole("button", { name: "Остатки" }).click();
    await uploadImportFile(page, path.join(FIXTURES, "balances_ok.csv"));
    await expect(page.getByText(/Счёт main/)).toBeVisible();
    await commitImportPreview(page);

    await page.getByRole("link", { name: "Продажи" }).click();
    await page.getByLabel("Дата признания").fill("2026-10-18");
    await page.getByLabel("Номер документа").fill("E2E-REV");
    await page.getByLabel("Внешний ID (не ключ идемпотентности)").fill("E2E-EXT-001");
    await page.getByLabel("Сумма с НДС").fill("2.00");
    await page.getByLabel("Без НДС").fill("2.00");
    await page.getByLabel("НДС", { exact: true }).fill("0.00");
    await page.getByRole("button", { name: "Добавить продажу" }).click();
    await expect(page.getByText(/2026-10-18: 2\.00 без НДС/)).toBeVisible();

    await page.getByLabel("Продажа").selectOption({ index: 1 });
    await page.getByLabel("Поступление (posted, in, RUB)").selectOption({ label: "2026-10-10 · доступно 1500.00 — Поступление" });
    await page.getByLabel("Сумма связи").fill("0.50");
    await page.getByRole("button", { name: "Сопоставить" }).click();
    await expect(page.locator("ul.mb-6").getByText(/остаток 1\.50/)).toBeVisible();

    await page.getByRole("link", { name: "Календарь" }).click();
    await expect(page.getByLabel("Сумма, ₽")).toHaveValue("");
    await expect(page.getByLabel("Срок оплаты")).toHaveValue("");
    await expect(page.getByLabel("Ожидаемая дата оплаты")).toHaveValue("");
    const planEventsBefore = await page.locator("ul.mb-6 > li").count();
    let planCreatePosts = 0;
    const onPlanCreate = (req: Request) => {
      if (req.method() === "POST" && /\/api\/v1\/companies\/[^/]+\/planned-cash(?:\?|$)/.test(req.url())) {
        planCreatePosts += 1;
      }
    };
    page.on("request", onPlanCreate);
    await page.getByRole("button", { name: "Добавить в план" }).click();
    await expect(page.getByText("Сумма в формате 1234.56")).toBeVisible();
    expect(planCreatePosts).toBe(0);
    await expect(page.locator("ul.mb-6 > li")).toHaveCount(planEventsBefore);
    page.off("request", onPlanCreate);

    await page.getByLabel("Сумма, ₽").fill("2.00");
    await page.getByLabel("Срок оплаты").fill("2026-10-25");
    await page.getByLabel("Ожидаемая дата оплаты").fill("2026-10-27");
    await page.getByRole("button", { name: "Добавить в план" }).click();
    await expect(page.locator("ul.mb-6").getByText(/2026-10-27.*остаток 2\.00/)).toBeVisible();

    await page.getByLabel("Плановая выплата").selectOption({ index: 1 });
    await page.getByLabel("Фактическая операция").selectOption({
      label: "2026-10-11 · доступно 800.00 — Комиссия",
    });
    await page.getByLabel("Сумма связи, ₽").fill("0.50");
    await page.getByRole("button", { name: "Связать с операцией" }).click();
    await expect(page.locator("ul.mb-6").getByText(/остаток 1\.50/)).toBeVisible();

    await page.reload();
    await selectCompany(page, meta.companyAName);
    await expect(page.locator("ul.mb-6").getByText(/остаток 1\.50/)).toBeVisible();

    await page.getByRole("link", { name: "Обзор" }).click();
    await expect(page.getByText(/Выручка без НДС: 2\.00/)).toBeVisible();
    await expect(page.getByText(/Операций: 3/)).toBeVisible();
    // Суммы на экране печатаются с разделителями: 3200.00 -> «3 200,00 ₽».
    await expect(page.getByText(/3[\s\u00a0]200,00/).first()).toBeVisible();
  });
});
