import { expect, test } from "@playwright/test";

import { loadSeedMeta } from "./fixtures/seed";
import { gotoSection, openAppShell, selectCompany } from "./helpers/auth";
import { draftOrgProfile, installOrgProfileMock } from "./helpers/org-profile-mock";

test.describe("P3c · мастер профиля организации", () => {
  test("owner: баннер на Обзоре → подтверждение → баннер исчез", async ({ page }) => {
    const meta = loadSeedMeta();
    const state = draftOrgProfile(meta.companyAId);
    await installOrgProfileMock(page, meta.companyAId, state);
    await openAppShell(page);
    await selectCompany(page, meta.companyAName);

    await gotoSection(page, "Обзор");
    await expect(page.getByTestId("org-profile-overview-banner")).toBeVisible();
    await page.getByRole("link", { name: "Настроить профиль" }).click();

    await page.getByLabel("Организационно-правовая форма").selectOption("ooo");
    await page.getByRole("button", { name: "Далее" }).click();
    await page.getByLabel("Режим").selectOption("usn");
    await page.getByLabel("Объект УСН").selectOption("income");
    await page.getByRole("button", { name: "Далее" }).click();
    await page.getByLabel("Нет, НДС не применяется").check();
    await page.getByLabel("Новая организация (не было выручки в прошлом году)?").selectOption("yes");
    await page.getByRole("button", { name: "Далее" }).click();
    await page.getByLabel("Откуда будут выгрузки").selectOption("onec");
    await page.getByRole("button", { name: "Далее" }).click();
    await page.getByRole("checkbox", { name: "Банк" }).check();
    await page.getByLabel("Сфера деятельности").selectOption("trade");
    await page.getByRole("button", { name: "Далее" }).click();
    await page.getByLabel("Закрытие месяца в учёте").selectOption("calendar_month_end");
    await page.getByLabel("Признание выручки").selectOption("accrual");
    await page.getByRole("button", { name: "Сохранить и проверить" }).click();
    await page.getByRole("button", { name: "Подтвердить профиль" }).click();
    await expect(page.getByText("Подтверждён")).toBeVisible();

    await gotoSection(page, "Обзор");
    await expect(page.getByTestId("org-profile-overview-banner")).toHaveCount(0);
  });

  test("черновик шага 2 сохраняется при выходе", async ({ page }) => {
    const meta = loadSeedMeta();
    const state = draftOrgProfile(meta.companyAId);
    await installOrgProfileMock(page, meta.companyAId, state);
    await openAppShell(page);
    await selectCompany(page, meta.companyAName);
    await gotoSection(page, "Профиль организации");
    await page.getByLabel("Режим").selectOption("osno");
    await page.getByRole("button", { name: "Далее" }).click();
    await gotoSection(page, "Обзор");
    await gotoSection(page, "Профиль организации");
    await expect(page.getByLabel("Режим")).toHaveValue("osno");
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
    state.profile.org_form = "ooo";
    state.profile.tax_system = "usn";
    state.profile.accounting_source = "onec";
    state.profile.money_channels = ["bank"];
    state.profile.month_close_policy = "calendar_month_end";
    state.profile.revenue_recognition_method = "accrual";
    state.profile.is_confirmed = true;
    state.profile.profile_unconfirmed = false;
    state.profile.confirm_readiness = { ready: true, missing: [], field_errors: {} };
    state.versions[0].is_confirmed = true;
    const firstVersionId = state.versions[0].version_id;
    await installOrgProfileMock(page, meta.companyAId, state);
    await openAppShell(page);
    await selectCompany(page, meta.companyAName);
    await gotoSection(page, "Профиль организации");
    await page.getByRole("button", { name: "Изменить режим с даты…" }).click();
    await page.getByPlaceholder("Кратко, без персональных данных").fill("смена режима");
    await page.getByRole("button", { name: "Создать версию" }).click();
    await expect(page.getByText("Черновик")).toBeVisible();
    expect(state.versions.length).toBe(2);
    expect(state.versions[1].version_id).not.toBe(firstVersionId);
    expect(state.profile.tax_system).toBe("usn");
  });
});
