import { expect, test } from "@playwright/test";

import { loadSeedMeta } from "./fixtures/seed";
import { gotoSection, openAppShell, selectCompany } from "./helpers/auth";
import {
  completeDraftProfile,
  confirmLatestInMock,
  draftOrgProfile,
  installOrgProfileMock,
} from "./helpers/org-profile-mock";

async function walkWizardToStep6(page: import("@playwright/test").Page) {
  for (let step = 0; step < 5; step += 1) {
    await page.getByRole("button", { name: "Далее" }).click();
  }
}

async function waitOrganizationProfileGet(
  page: import("@playwright/test").Page,
  companyId: string,
) {
  return page.waitForResponse((response) => {
    if (response.request().method() !== "GET") {
      return false;
    }
    const path = new URL(response.url()).pathname;
    return (
      path.startsWith(`/api/v1/companies/${companyId}/organization-profile`) &&
      !path.includes("/versions")
    );
  });
}

test.describe("P3c · мастер профиля организации", () => {
  test("черновик шага 2 сохраняется при выходе", async ({ page }) => {
    const meta = loadSeedMeta();
    await openAppShell(page);
    await selectCompany(page, meta.companyBName);
    await gotoSection(page, "Профиль организации");
    await expect(page.getByLabel("Организационно-правовая форма")).toBeVisible();
    await page.getByLabel("Организационно-правовая форма").selectOption("ooo");
    await page.getByRole("button", { name: "Далее" }).click();
    await page.getByLabel("Режим").selectOption("osno");
    await page.getByRole("button", { name: "Далее" }).click();
    await gotoSection(page, "Обзор");
    await gotoSection(page, "Профиль организации");
    await page.getByLabel("Организационно-правовая форма").selectOption("ooo");
    await page.getByRole("button", { name: "Далее" }).click();
    await expect(page.getByLabel("Режим")).toHaveValue("osno");
  });

  test("owner: баннер на Обзоре → подтверждение (текущий период) → баннер исчез", async ({
    page,
  }) => {
    const meta = loadSeedMeta();
    const state = draftOrgProfile(meta.companyAId);
    completeDraftProfile(state);
    await installOrgProfileMock(page, meta.companyAId, state);
    await openAppShell(page);
    await gotoSection(page, "Обзор");
    await selectCompany(page, meta.companyAName);
    await expect(page.getByTestId("org-profile-overview-banner")).toBeVisible();
    await page.getByRole("link", { name: "Настроить профиль" }).click();

    await walkWizardToStep6(page);
    await page.getByRole("button", { name: "Сохранить и проверить" }).click();
    const confirmResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" && response.url().includes("/confirm"),
    );
    await expect(page.getByRole("button", { name: "Подтвердить профиль" })).toBeEnabled();
    await page.getByRole("button", { name: "Подтвердить профиль" }).click();
    const confirm = await confirmResponse;
    expect(confirm.ok()).toBeTruthy();
    expect(confirm.url()).toContain(`/versions/${state.versions[0].version_id}/confirm`);

    await gotoSection(page, "Обзор");
    await expect(page.getByTestId("org-profile-overview-banner")).toHaveCount(0);
  });

  test("viewer: без кнопок записи и без CTA в баннере", async ({ page }) => {
    const meta = loadSeedMeta();
    const state = draftOrgProfile(meta.companyAId, false);
    await installOrgProfileMock(page, meta.companyAId, state);
    await openAppShell(page);
    await gotoSection(page, "Обзор");
    await selectCompany(page, meta.companyAName);
    await expect(page.getByTestId("org-profile-overview-banner")).toBeVisible();
    await expect(page.getByRole("link", { name: "Настроить профиль" })).toHaveCount(0);
    await expect(page.getByText(/Попросите владельца или бухгалтера/)).toBeVisible();
    await gotoSection(page, "Профиль организации");
    await expect(page.getByRole("button", { name: "Далее" })).toHaveCount(0);
  });

  test("подтверждённый профиль → будущая версия: ОСНО, confirm по новому id, карточка с УСН", async ({
    page,
  }) => {
    const meta = loadSeedMeta();
    const state = draftOrgProfile(meta.companyAId);
    completeDraftProfile(state);
    confirmLatestInMock(state);
    state.versions[0].is_confirmed = true;
    const firstVersionId = state.versions[0].version_id;
    await installOrgProfileMock(page, meta.companyAId, state);
    await openAppShell(page);
    await gotoSection(page, "Профиль организации");
    const profileResponse = waitOrganizationProfileGet(page, meta.companyAId);
    await selectCompany(page, meta.companyAName);
    const profileLoaded = await profileResponse;
    const profileBody = (await profileLoaded.json()) as {
      is_confirmed: boolean;
      version_id: string;
    };
    expect(profileBody.version_id).toBe(firstVersionId);
    expect(profileBody.is_confirmed).toBe(true);
    await expect(page.getByRole("heading", { name: "История версий" })).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByRole("button", { name: "Изменить режим с даты…" })).toBeVisible();
    await expect(page.locator("dd", { hasText: "УСН" })).toBeVisible();

    await page.getByRole("button", { name: "Изменить режим с даты…" }).click();
    await page.locator('input[type="month"]').fill("2027-04");
    await page.getByPlaceholder("Кратко, без персональных данных").fill("смена режима");
    const createResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.url().includes("/organization-profile/versions") &&
        !response.url().includes("/confirm"),
    );
    await page.getByRole("button", { name: "Создать версию" }).click();
    const created = await createResponse;
    expect(created.ok()).toBeTruthy();
    const createdBody = (await created.json()) as { version_id: string; tax_system: string };
    const newVersionId = createdBody.version_id;
    expect(newVersionId).not.toBe(firstVersionId);
    expect(createdBody.tax_system).toBe("usn");

    await page.getByRole("button", { name: "Далее" }).click();
    await page.getByLabel("Режим").selectOption("osno");
    await page.getByRole("button", { name: "Далее" }).click();
    await page.getByRole("radio", { name: "Да, общий порядок" }).check();
    await page.getByLabel("Цены в учёте с НДС?").selectOption("yes");
    for (let step = 0; step < 3; step += 1) {
      await page.getByRole("button", { name: "Далее" }).click();
    }
    await page.getByRole("button", { name: "Сохранить и проверить" }).click();
    await expect(page.getByRole("button", { name: "Подтвердить профиль" })).toBeEnabled();

    const confirmResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.url().includes(`/versions/${newVersionId}/confirm`),
    );
    await page.getByRole("button", { name: "Подтвердить профиль" }).click();
    const confirm = await confirmResponse;
    expect(confirm.ok()).toBeTruthy();

    await expect(page.getByTestId("org-profile-future-effective")).toContainText("2027");
    await expect(page.locator("dd", { hasText: "УСН" })).toBeVisible();
    await expect(page.locator("dd", { hasText: "ОСНО" })).toHaveCount(0);
  });
});
