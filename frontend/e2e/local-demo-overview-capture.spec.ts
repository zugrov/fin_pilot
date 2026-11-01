/**
 * Локальная пересъёмка Обзора в var/demo-real-data (не входит в CI).
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { devices, expect, test } from "@playwright/test";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const demoDir = path.join(repoRoot, "var/demo-real-data");
const meta = JSON.parse(fs.readFileSync(path.join(demoDir, "demo-meta.json"), "utf-8")) as {
  password: string;
  months: Record<string, { ownerEmail: string; dateFrom: string; dateTo: string }>;
};

async function login(page: import("@playwright/test").Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Почта").fill(email);
  await page.getByLabel("Пароль").fill(meta.password);
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page).toHaveURL(/\/billing/, { timeout: 60_000 });
  await page.getByRole("link", { name: "В основное меню" }).click();
}

async function gotoSection(page: import("@playwright/test").Page, name: string) {
  const link = page.getByRole("link", { name, exact: true });
  const menu = page.getByRole("button", { name: "Меню", exact: true });
  if (await link.isVisible().catch(() => false)) {
    await link.click();
    return;
  }
  await menu.click();
  await link.click();
}

async function shotOverview(
  page: import("@playwright/test").Page,
  info: { dateFrom: string; dateTo: string },
) {
  await gotoSection(page, "Обзор");
  await page.locator("#fp-period-from").fill(info.dateFrom);
  await page.locator("#fp-period-to").fill(info.dateTo);
  await page.locator("#fp-period-to").blur();
  await expect(page.getByText(/^Загрузка$/)).toHaveCount(0, { timeout: 60_000 });
  await expect(page.getByTestId("kpi-cash-total")).toBeVisible();
}

for (const [monthKey, info] of Object.entries(meta.months)) {
  test(`${monthKey} overview desktop + mobile`, async ({ browser }) => {
    const desktopCtx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const desktop = await desktopCtx.newPage();
    await login(desktop, info.ownerEmail);
    await shotOverview(desktop, info);
    await desktop.screenshot({
      path: path.join(demoDir, monthKey, "overview-desktop.png"),
      fullPage: true,
    });
    const state = await desktopCtx.storageState();
    await desktopCtx.close();

    const mobileCtx = await browser.newContext({
      ...devices["iPhone 12"],
      storageState: state,
    });
    const mobile = await mobileCtx.newPage();
    await shotOverview(mobile, info);
    await mobile.screenshot({
      path: path.join(demoDir, monthKey, "overview-mobile.png"),
      fullPage: true,
    });
    await mobileCtx.close();
  });
}
