import { defineConfig } from "@playwright/test";

/** Локальная пересъёмка Обзора в var/demo-real-data (не CI). */
export default defineConfig({
  testDir: "./e2e",
  testMatch: "local-demo-overview-capture.spec.ts",
  fullyParallel: false,
  workers: 1,
  timeout: 180_000,
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:5173", trace: "off" },
  projects: [{ name: "chromium", use: {} }],
});
