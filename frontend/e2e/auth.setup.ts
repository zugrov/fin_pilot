import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test as setup } from "@playwright/test";

import { E2E_PASSWORD, loadSeedMeta } from "./fixtures/seed";

const authFile = path.join(path.dirname(fileURLToPath(import.meta.url)), ".auth/user.json");

setup("authenticate", async ({ page }) => {
  const meta = loadSeedMeta();
  await page.goto("/login");
  await page.getByLabel("Почта").fill(meta.ownerEmail);
  await page.getByLabel("Пароль").fill(E2E_PASSWORD);
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page).toHaveURL(/\/billing/, { timeout: 60_000 });
  fs.mkdirSync(path.dirname(authFile), { recursive: true });
  await page.context().storageState({ path: authFile });
});
