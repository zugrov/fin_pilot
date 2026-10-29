import { expect, type Page } from "@playwright/test";

export async function openAppShell(page: Page): Promise<void> {
  await page.goto("/billing");
  await page.getByRole("link", { name: "В основное меню" }).click();
}

/** Переход в раздел: на мобильном меню живёт в бургере, на десктопе — в боковой панели. */
export async function gotoSection(page: Page, name: string): Promise<void> {
  const link = page.getByRole("link", { name, exact: true });
  const mobileTrigger = page.getByRole("button", { name: "Меню", exact: true });
  // Ждём либо ссылку (десктоп), либо кнопку меню (мобильный), затем действуем.
  await Promise.race([
    link.waitFor({ state: "visible", timeout: 15_000 }).catch(() => undefined),
    mobileTrigger.waitFor({ state: "visible", timeout: 15_000 }).catch(() => undefined),
  ]);
  if (await link.isVisible().catch(() => false)) {
    await link.click();
    return;
  }
  await mobileTrigger.click();
  await link.click();
}

export async function selectCompany(page: Page, companyName: string): Promise<void> {
  const firmPicker = page.getByLabel("Фирма");
  try {
    await firmPicker.waitFor({ state: "visible", timeout: 8_000 });
  } catch {
    await gotoSection(page, "Кошельки");
    await firmPicker.waitFor({ state: "visible" });
  }
  await firmPicker.selectOption({ label: companyName });
}
