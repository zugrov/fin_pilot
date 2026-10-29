import { expect, test, type Request } from "@playwright/test";

import {
  E2E_PASSWORD,
  labeledMoneyPattern,
  loadPolygonMeta,
  loadPolygonOracle,
  moneyPattern,
  POLYGON_CLOCK_ISO,
} from "./fixtures/polygon-seed";
import { openAppShell, selectCompany } from "./helpers/auth";

const API = "http://127.0.0.1:8000";

test.describe("Synthetic polygon · E2E (backend + UI)", () => {
  test.beforeEach(async ({ page, context }) => {
    await context.clock.install({ time: new Date(POLYGON_CLOCK_ISO) });
    await openAppShell(page);
  });

  for (const slug of ["services", "retail", "subscription"] as const) {
    test(`обзор ${slug}: остаток, выручка (net), операции`, async ({ page }) => {
      const meta = loadPolygonMeta();
      const oracle = loadPolygonOracle();
      const company = meta.companies[slug];
      const expected = oracle.companies[slug];

      await page.evaluate((id) => sessionStorage.setItem("fp_company_id", id), company.id);
      await selectCompany(page, company.name);
      await page.getByRole("link", { name: "Обзор" }).click();

      // Значение из oracle остаётся источником истины, а на экране оно
      // печатается через форматтер: 50000.00 → «50 000,00 ₽».
      await expect(
        page.getByText(labeledMoneyPattern("Начальный остаток", expected.opening_balance)),
      ).toBeVisible();
      await expect(
        page.getByText(labeledMoneyPattern(oracle.revenue_label, expected.revenue_net_ex_vat)),
      ).toBeVisible();
      await expect(page.getByText(`Операций: ${expected.operation_count}`)).toBeVisible();
      // Сумма на экране форматируется; исходное значение доступно в data-value.
      await expect(page.getByTestId("kpi-cash-total")).toHaveAttribute(
        "data-value",
        expected.cash_total,
      );
    });
  }

  test("переключение фирм не смешивает выручку", async ({ page }) => {
    const meta = loadPolygonMeta();
    const oracle = loadPolygonOracle();

    await page.evaluate((id) => sessionStorage.setItem("fp_company_id", id), meta.companies.services.id);
    await selectCompany(page, meta.companies.services.name);
    await page.getByRole("link", { name: "Обзор" }).click();
    await expect(
      page.getByText(
        labeledMoneyPattern(oracle.revenue_label, oracle.companies.services.revenue_net_ex_vat),
      ),
    ).toBeVisible();

    await page.evaluate((id) => sessionStorage.setItem("fp_company_id", id), meta.companies.retail.id);
    await selectCompany(page, meta.companies.retail.name);
    await page.reload();
    await page.getByRole("link", { name: "Обзор" }).click();
    await expect(
      page.getByText(
        labeledMoneyPattern(oracle.revenue_label, oracle.companies.retail.revenue_net_ex_vat),
      ),
    ).toBeVisible();
    await expect(
      page.getByText(
        labeledMoneyPattern(oracle.revenue_label, oracle.companies.services.revenue_net_ex_vat),
      ),
    ).not.toBeVisible();
  });

  test("group-summary: cash и revenue за октябрь 2026", async ({ request }) => {
    const meta = loadPolygonMeta();
    const oracle = loadPolygonOracle();
    const login = await request.post(`${API}/api/v1/auth/login`, {
      data: { email: meta.ownerEmail, password: E2E_PASSWORD },
    });
    expect(login.ok()).toBeTruthy();
    const auth = await login.json();
    const period = `date_from=${oracle.period_from}&date_to=${oracle.period_to}`;
    const summary = await request.get(
      `${API}/api/v1/workspaces/${meta.tenantId}/group-summary?${period}`,
      {
        headers: {
          "X-CSRF-Token": auth.csrf_token,
          "X-Tenant-Id": meta.tenantId,
        },
      },
    );
    expect(summary.ok()).toBeTruthy();
    const body = await summary.json();
    expect(body.metrics.cash_total).toBe(oracle.group.cash_total);
    expect(body.metrics.revenue).toBe(oracle.group.revenue);
    expect(body.metrics.revenue).not.toBe(body.metrics.cash_total);
  });

  test("план: перенос expected_date меняет прогноз, не деньги", async ({ page }) => {
    const meta = loadPolygonMeta();
    const oracle = loadPolygonOracle();
    const plan = oracle.plan_move_services;
    // Даты в UI печатаются как ДД.ММ.ГГГГ; в oracle они ISO.
    const displayDate = (iso: string) => iso.split("-").reverse().join(".");
    // «Неоплаченная выплата 4000.00 на 2026-11-01» → пользовательский вид.
    // formatMoney добавляет «₽», поэтому валюта в шаблоне необязательна.
    const displayUnpaid = (text: string): RegExp => {
      const match = /^(.*?)\s*(\d+\.\d{2})\s*на\s*(\d{4}-\d{2}-\d{2})$/.exec(text);
      const escape = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      if (!match) {
        return new RegExp(escape(text));
      }
      const [, label, amount, date] = match;
      return new RegExp(
        `${escape(label)} ${moneyPattern(amount)}(?:\\s*₽)? на ${displayDate(date)}`,
      );
    };

    await page.evaluate((id) => sessionStorage.setItem("fp_company_id", id), meta.companies.services.id);
    await selectCompany(page, meta.companies.services.name);
    await page.getByRole("link", { name: "Обзор" }).click();
    // Сумма на экране форматируется; исходное значение доступно в data-value.
    await expect(page.getByTestId("kpi-cash-total")).toHaveAttribute(
      "data-value",
      plan.cash_total_unchanged,
    );

    await page.getByRole("link", { name: "Прогноз" }).click();
    // В oracle строка в API-формате; на экране сумма и дата — через форматтеры.
    await expect(page.getByText(displayUnpaid(plan.forecast_unpaid_before))).toBeVisible();

    await page.getByRole("link", { name: "Календарь" }).click();
    // Значения в oracle остаются ISO (источник истины), на экране — ДД.ММ.ГГГГ.
    const dueBefore = displayDate(plan.plan_marker_due);
    const expectedBefore = dueBefore;
    const planRow = page.locator("li").filter({ hasText: dueBefore }).first();
    await expect(planRow).toContainText(`срок ${dueBefore}`);
    await expect(planRow).toContainText(`ожидание ${expectedBefore}`);

    let planMovePatches = 0;
    const patchBodies: string[] = [];
    const onPlanMovePatch = (req: Request) => {
      if (req.method() === "PATCH" && /\/api\/v1\/planned-cash\/[^/]+$/.test(req.url())) {
        planMovePatches += 1;
        patchBodies.push(req.postData() ?? "");
      }
    };
    page.on("request", onPlanMovePatch);

    await planRow.getByRole("button", { name: "Перенести ожидание" }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    expect(planMovePatches).toBe(0);

    await page.getByRole("dialog").getByLabel("Новая ожидаемая дата оплаты").fill("2026-12-01");
    await page.getByRole("button", { name: "Отмена" }).click();
    await expect(page.getByRole("dialog")).not.toBeVisible();
    expect(planMovePatches).toBe(0);
    await expect(planRow).toContainText(`ожидание ${expectedBefore}`);
    await expect(planRow).toContainText(`срок ${dueBefore}`);

    await page.reload();
    await page.evaluate((id) => sessionStorage.setItem("fp_company_id", id), meta.companies.services.id);
    await selectCompany(page, meta.companies.services.name);
    await page.getByRole("link", { name: "Календарь" }).click();
    const planRowReloaded = page.locator("li").filter({ hasText: dueBefore }).first();
    await expect(planRowReloaded).toContainText(`ожидание ${expectedBefore}`);
    await expect(planRowReloaded).toContainText(`срок ${dueBefore}`);

    const patchesBeforeSave = planMovePatches;
    await planRowReloaded.getByRole("button", { name: "Перенести ожидание" }).click();
    await page.getByRole("dialog").getByLabel("Новая ожидаемая дата оплаты").fill(plan.moved_expected);
    await page.getByRole("button", { name: "Сохранить перенос" }).click();
    expect(planMovePatches).toBe(patchesBeforeSave + 1);
    expect(patchBodies.length).toBeGreaterThan(0);
    const lastPatch = JSON.parse(patchBodies[patchBodies.length - 1] ?? "{}") as {
      expected_date?: string;
      due_date?: string;
    };
    expect(lastPatch.expected_date).toBe(plan.moved_expected);
    expect(lastPatch.due_date).toBeUndefined();

    await expect(planRowReloaded).toContainText(`срок ${dueBefore}`);
    await expect(planRowReloaded).toContainText(displayDate(plan.calendar_expected_after));
    page.off("request", onPlanMovePatch);

    await page.getByRole("link", { name: "Прогноз" }).click();
    await expect(page.getByText(displayUnpaid(plan.forecast_unpaid_after))).toBeVisible();

    await page.getByRole("link", { name: "Обзор" }).click();
    // Сумма на экране форматируется; исходное значение доступно в data-value.
    await expect(page.getByTestId("kpi-cash-total")).toHaveAttribute(
      "data-value",
      plan.cash_total_unchanged,
    );
  });
});
