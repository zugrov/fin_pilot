import { expect, test, type Request } from "@playwright/test";

import {
  E2E_PASSWORD,
  loadPolygonMeta,
  loadPolygonOracle,
  POLYGON_CLOCK_ISO,
} from "./fixtures/polygon-seed";
import { openAppShell, selectCompany } from "./helpers/auth";

const API = "http://127.0.0.1:8000";

test.describe("Classification screen · polygon retail", () => {
  test.beforeEach(async ({ page, context }) => {
    await context.clock.install({ time: new Date(POLYGON_CLOCK_ISO) });
    await openAppShell(page);
  });

  test("retail: preview без apply, apply, сводка и ОДДС", async ({ page, request }) => {
    const meta = loadPolygonMeta();
    const oracle = loadPolygonOracle();
    const company = meta.companies.retail;
    const period = `date_from=${oracle.period_from}&date_to=${oracle.period_to}`;

    await page.evaluate((id) => sessionStorage.setItem("fp_company_id", id), company.id);
    await selectCompany(page, company.name);
    await page.getByRole("link", { name: "Классификация" }).click();

    const periodInputs = page.getByTestId("unclassified-block").locator('input[type="date"]');
    await periodInputs.nth(0).fill(oracle.period_from);
    await periodInputs.nth(1).fill(oracle.period_to);

    const summary = page.getByTestId("unclassified-summary");
    await expect(summary).toContainText("7200.00");

    const createForm = page.locator("form").filter({ hasText: "Новое правило" });
    await createForm.getByLabel("Название").fill("Retail ClientBank operating in");
    await createForm.getByLabel("Текст в назначении").fill("Оплата");
    await createForm.getByLabel("ИНН контрагента").fill("7700000202");
    await createForm.getByLabel("Направление").selectOption("in");
    await createForm.getByLabel("Категория").selectOption("operating");
    await page.getByRole("button", { name: "Создать правило" }).click();
    await expect(page.getByText("Retail ClientBank operating in")).toBeVisible();

    let applyPosts = 0;
    const onRequest = (req: Request) => {
      if (req.method() === "POST" && req.url().includes("/apply")) {
        applyPosts += 1;
      }
    };
    page.on("request", onRequest);

    const ruleCard = page.locator("li").filter({ hasText: "Retail ClientBank operating in" });
    await ruleCard.getByRole("button", { name: "Проверить" }).click();
    await expect(page.getByText(/Совпадений: 1/)).toBeVisible();
    await ruleCard.getByRole("button", { name: "Проверить" }).click();
    await expect(page.getByText(/Совпадений: 1/)).toBeVisible();
    expect(applyPosts).toBe(0);

    await ruleCard.getByRole("button", { name: "Применить" }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.getByRole("button", { name: "Отмена" }).click();
    expect(applyPosts).toBe(0);

    await ruleCard.getByRole("button", { name: "Применить" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Применить" }).click();
    await expect(summary).toContainText("0 на 0.00");

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
    const body = await cashflow.json();
    const operating = body.sections.find((item: { code: string }) => item.code === "operating");
    const unmapped = body.sections.find((item: { code: string }) => item.code === "unmapped");
    expect(operating.in).toBe("22200.00");
    expect(unmapped.in).toBe("0.00");

    const group = await request.get(
      `${API}/api/v1/workspaces/${meta.tenantId}/group-summary?${period}`,
      {
        headers: {
          "X-CSRF-Token": auth.csrf_token,
          "X-Tenant-Id": meta.tenantId,
        },
      },
    );
    const groupBody = await group.json();
    expect(groupBody.metrics.cash_total).toBe(oracle.group.cash_total);
    expect(groupBody.metrics.revenue).toBe(oracle.group.revenue);
  });

  test("preview: устаревший ответ не перезаписывает более новый", async ({ page }) => {
    const meta = loadPolygonMeta();
    const oracle = loadPolygonOracle();
    await page.evaluate((id) => sessionStorage.setItem("fp_company_id", id), meta.companies.retail.id);
    await selectCompany(page, meta.companies.retail.name);
    await page.getByRole("link", { name: "Классификация" }).click();

    const periodInputs = page.getByTestId("unclassified-block").locator('input[type="date"]');
    await periodInputs.nth(0).fill(oracle.period_from);
    await periodInputs.nth(1).fill(oracle.period_to);

    const createForm = page.locator("form").filter({ hasText: "Новое правило" });
    await createForm.getByLabel("Название").fill("Slow preview rule");
    await createForm.getByLabel("Текст в назначении").fill("Оплата");
    await createForm.getByLabel("ИНН контрагента").fill("7700000202");
    await createForm.getByLabel("Направление").selectOption("in");
    await createForm.getByLabel("Категория").selectOption("operating");
    await page.getByRole("button", { name: "Создать правило" }).click();
    await createForm.getByLabel("Название").fill("Fast preview rule");
    await createForm.getByLabel("Текст в назначении").fill("Несуществующий текст XYZ");
    await createForm.getByLabel("ИНН контрагента").fill("");
    await createForm.getByLabel("Направление").selectOption("in");
    await createForm.getByLabel("Категория").selectOption("operating");
    await page.getByRole("button", { name: "Создать правило" }).click();
    await expect(page.getByText("Fast preview rule")).toBeVisible();

    const slowCard = page.locator("li").filter({ hasText: "Slow preview rule" });
    const fastCard = page.locator("li").filter({ hasText: "Fast preview rule" });

    let previewCalls = 0;
    await page.route("**/api/v1/rules/*/preview", async (route) => {
      previewCalls += 1;
      if (previewCalls === 1) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
      }
      await route.continue();
    });

    await slowCard.getByRole("button", { name: "Проверить" }).click();
    await fastCard.getByRole("button", { name: "Проверить" }).click();
    await expect(fastCard.getByText(/Совпадений: 0/)).toBeVisible({ timeout: 15_000 });
    await page.waitForTimeout(2500);
    await expect(fastCard.getByText(/Совпадений: 0/)).toBeVisible();
    await expect(slowCard.getByText(/Совпадений: 1/)).not.toBeVisible();
    expect(previewCalls).toBe(2);
  });

  test("скриншоты: загрузка, пусто, данные", async ({ page }) => {
    const meta = loadPolygonMeta();
    const oracle = loadPolygonOracle();
    await page.evaluate((id) => sessionStorage.setItem("fp_company_id", id), meta.companies.retail.id);
    await selectCompany(page, meta.companies.retail.name);
    await page.getByRole("link", { name: "Классификация" }).click();
    await page.screenshot({ path: "e2e/report-artifacts/classification-loading.png", fullPage: true });
    const periodInputs = page.getByTestId("unclassified-block").locator('input[type="date"]');
    await page.getByTestId("unclassified-loading").waitFor({ state: "detached" });
    await periodInputs.nth(0).fill(oracle.period_from);
    await periodInputs.nth(1).fill(oracle.period_to);
    await expect(page.getByTestId("unclassified-summary")).toBeVisible();
    await page.screenshot({ path: "e2e/report-artifacts/classification-ready.png", fullPage: true });

    await periodInputs.nth(0).fill("2020-01-01");
    await periodInputs.nth(1).fill("2020-01-31");
    await expect(page.getByTestId("unclassified-empty")).toBeVisible();
    await page.screenshot({ path: "e2e/report-artifacts/classification-empty.png", fullPage: true });

    await page.route("**/transactions/unclassified/summary*", (route) => route.abort());
    await periodInputs.nth(0).fill(oracle.period_from);
    await periodInputs.nth(1).fill(oracle.period_to);
    await expect(page.getByTestId("unclassified-error")).toBeVisible({ timeout: 15_000 });
    await page.screenshot({ path: "e2e/report-artifacts/classification-error.png", fullPage: true });
  });
});
