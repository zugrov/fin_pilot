import { expect, test, type Request } from "@playwright/test";

import {
  E2E_PASSWORD,
  loadPolygonMeta,
  loadPolygonOracle,
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

      await expect(page.getByText(`Начальный остаток: ${expected.opening_balance}`)).toBeVisible();
      await expect(page.getByText(`${oracle.revenue_label}: ${expected.revenue_net_ex_vat}`)).toBeVisible();
      await expect(page.getByText(`Операций: ${expected.operation_count}`)).toBeVisible();
      await expect(page.getByText(expected.cash_total)).toBeVisible();
    });
  }

  test("переключение фирм не смешивает выручку", async ({ page }) => {
    const meta = loadPolygonMeta();
    const oracle = loadPolygonOracle();

    await page.evaluate((id) => sessionStorage.setItem("fp_company_id", id), meta.companies.services.id);
    await selectCompany(page, meta.companies.services.name);
    await page.getByRole("link", { name: "Обзор" }).click();
    await expect(
      page.getByText(`${oracle.revenue_label}: ${oracle.companies.services.revenue_net_ex_vat}`),
    ).toBeVisible();

    await page.evaluate((id) => sessionStorage.setItem("fp_company_id", id), meta.companies.retail.id);
    await selectCompany(page, meta.companies.retail.name);
    await page.reload();
    await page.getByRole("link", { name: "Обзор" }).click();
    await expect(
      page.getByText(`${oracle.revenue_label}: ${oracle.companies.retail.revenue_net_ex_vat}`),
    ).toBeVisible();
    await expect(
      page.getByText(`${oracle.revenue_label}: ${oracle.companies.services.revenue_net_ex_vat}`),
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

    await page.evaluate((id) => sessionStorage.setItem("fp_company_id", id), meta.companies.services.id);
    await selectCompany(page, meta.companies.services.name);
    await page.getByRole("link", { name: "Обзор" }).click();
    await expect(page.getByText(plan.cash_total_unchanged)).toBeVisible();

    await page.getByRole("link", { name: "Прогноз" }).click();
    await expect(page.getByText(plan.forecast_unpaid_before)).toBeVisible();

    await page.getByRole("link", { name: "Календарь" }).click();
    const planRow = page.locator("li").filter({ hasText: plan.plan_marker_due }).first();
    const dueBefore = plan.plan_marker_due;
    const expectedBefore = plan.plan_marker_due;
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
    const planRowReloaded = page.locator("li").filter({ hasText: plan.plan_marker_due }).first();
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
    await expect(planRowReloaded.getByText(new RegExp(plan.calendar_expected_after))).toBeVisible();
    page.off("request", onPlanMovePatch);

    await page.getByRole("link", { name: "Прогноз" }).click();
    await expect(page.getByText(plan.forecast_unpaid_after)).toBeVisible();

    await page.getByRole("link", { name: "Обзор" }).click();
    await expect(page.getByText(plan.cash_total_unchanged)).toBeVisible();
  });
});
