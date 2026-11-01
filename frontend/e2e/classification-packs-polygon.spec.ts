import { expect, test } from "@playwright/test";

import {
  E2E_PASSWORD,
  loadPolygonMeta,
  loadPolygonOracle,
  POLYGON_CLOCK_ISO,
} from "./fixtures/polygon-seed";
import { gotoSection, openAppShell, selectCompany } from "./helpers/auth";

const API = "http://127.0.0.1:8000";

test.describe("Classification packs · polygon retail", () => {
  test.beforeEach(async ({ page, context }) => {
    await context.clock.install({ time: new Date(POLYGON_CLOCK_ISO) });
    await openAppShell(page);
  });

  test("preview → install → apply → ОДДС без unmapped", async ({ page, request }) => {
    const meta = loadPolygonMeta();
    const oracle = loadPolygonOracle();
    const company = meta.companies.retail;

    await page.evaluate((id) => sessionStorage.setItem("fp_company_id", id), company.id);
    await selectCompany(page, company.name);
    await gotoSection(page, "Классификация");

    const packs = page.getByTestId("packs-block");
    await expect(packs).toBeVisible();

    const periodInputs = page.getByTestId("unclassified-block").locator('input[type="date"]');
    await periodInputs.nth(0).fill(oracle.period_from);
    await periodInputs.nth(1).fill(oracle.period_to);

    await packs.getByRole("button", { name: "Предпросмотр" }).click();
    await expect(packs.getByText(/Без категории после набора:/)).toBeVisible();

    await packs.getByRole("button", { name: "Установить" }).click();
    await expect(packs.getByText(/Установлено правил:/)).toBeVisible();

    await packs.getByRole("button", { name: "Применить" }).click();
    await expect(packs.getByText(/Размечено операций: [1-9]/)).toBeVisible();

    const period = `date_from=${oracle.period_from}&date_to=${oracle.period_to}`;
    const login = await request.post(`${API}/api/v1/auth/login`, {
      data: { email: meta.ownerEmail, password: E2E_PASSWORD },
    });
    const auth = await login.json();
    const cashflow = await request.get(
      `${API}/api/v1/companies/${company.id}/cashflow?${period}`,
      {
        headers: {
          "X-CSRF-Token": auth.csrf_token,
          "X-Tenant-Id": meta.tenantId,
        },
      },
    );
    expect(cashflow.ok()).toBeTruthy();
    const unmapped = (await cashflow.json()).sections.find(
      (item: { code: string }) => item.code === "unmapped",
    );
    expect(unmapped.in).toBe("0.00");
    expect(unmapped.out).toBe("0.00");

    await gotoSection(page, "Деньги");
    await page.locator('input[type="date"]').nth(0).fill(oracle.period_from);
    await page.locator('input[type="date"]').nth(1).fill(oracle.period_to);
    await expect(page.getByRole("status")).toHaveCount(0);
  });
});
