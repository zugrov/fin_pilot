import { expect, test } from "@playwright/test";

import { loadSeedMeta } from "./fixtures/seed";
import { gotoSection, openAppShell, selectCompany } from "./helpers/auth";
import {
  completeDraftProfile,
  draftOrgProfile,
  installOrgProfileMock,
} from "./helpers/org-profile-mock";

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

  test("owner: баннер на Обзоре → подтверждение → баннер исчез", async ({ page }) => {
    const meta = loadSeedMeta();
    const state = draftOrgProfile(meta.companyAId);
    completeDraftProfile(state);
    await installOrgProfileMock(page, meta.companyAId, state);
    await openAppShell(page);
    await selectCompany(page, meta.companyAName);

    await gotoSection(page, "Обзор");
    await expect(page.getByTestId("org-profile-overview-banner")).toBeVisible();
    await page.getByRole("link", { name: "Настроить профиль" }).click();

    for (let step = 0; step < 5; step += 1) {
      await page.getByRole("button", { name: "Далее" }).click();
    }
    await page.getByRole("button", { name: "Сохранить и проверить" }).click();
    await expect(page.getByRole("button", { name: "Подтвердить профиль" })).toBeEnabled();
    await page.getByRole("button", { name: "Подтвердить профиль" }).click();

    await gotoSection(page, "Обзор");
    await expect(page.getByTestId("org-profile-overview-banner")).toHaveCount(0);
  });

  test("viewer: без кнопок записи и без CTA в баннере", async ({ page }) => {
    const meta = loadSeedMeta();
    const state = draftOrgProfile(meta.companyAId, false);
    await installOrgProfileMock(page, meta.companyAId, state);
    await openAppShell(page);
    await selectCompany(page, meta.companyAName);
    await gotoSection(page, "Обзор");
    await expect(page.getByTestId("org-profile-overview-banner")).toBeVisible();
    await expect(page.getByRole("link", { name: "Настроить профиль" })).toHaveCount(0);
    await expect(page.getByText(/Попросите владельца или бухгалтера/)).toBeVisible();
    await gotoSection(page, "Профиль организации");
    await expect(page.getByRole("button", { name: "Далее" })).toHaveCount(0);
  });

  test("подтверждённый профиль → новая версия с новым version_id", async ({ page }) => {
    const meta = loadSeedMeta();
    const state = draftOrgProfile(meta.companyAId);
    completeDraftProfile(state);
    state.profile.is_confirmed = true;
    state.profile.profile_unconfirmed = false;
    state.versions[0].is_confirmed = true;
    const firstVersionId = state.versions[0].version_id;
    await installOrgProfileMock(page, meta.companyAId, state);
    await openAppShell(page);
    await selectCompany(page, meta.companyAName);
    await gotoSection(page, "Профиль организации");
    await page.getByRole("button", { name: "Изменить режим с даты…" }).click();
    await page.getByPlaceholder("Кратко, без персональных данных").fill("смена режима");
    const createResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.url().includes("/organization-profile/versions"),
    );
    await page.getByRole("button", { name: "Создать версию" }).click();
    const response = await createResponse;
    expect(response.ok()).toBeTruthy();
    const body = (await response.json()) as { version_id: string };
    expect(body.version_id).toBeTruthy();
    expect(body.version_id).not.toBe(firstVersionId);
  });
});
