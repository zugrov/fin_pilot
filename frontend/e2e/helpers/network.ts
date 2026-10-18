import type { Page } from "@playwright/test";

/**
 * POST доходит до backend (commit), ответ клиенту не доставляется — UI unknown-result.
 */
export async function loseFirstPostResponseAfterCommit(page: Page, urlPart: string): Promise<void> {
  let dropped = false;
  await page.route(`**${urlPart}**`, async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    if (!dropped) {
      dropped = true;
      await route.fetch();
      await route.abort("failed");
      return;
    }
    await route.continue();
  });
}

/** Сетевой отказ до backend (не lost-response-after-commit). */
export async function abortFirstPostBeforeBackend(page: Page, urlPart: string): Promise<void> {
  let aborted = false;
  await page.route(`**${urlPart}**`, async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    if (!aborted) {
      aborted = true;
      await route.abort("failed");
      return;
    }
    await route.continue();
  });
}
