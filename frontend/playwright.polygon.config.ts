import { defineConfig, devices } from "@playwright/test";

const port = process.env.TEST_PG_PORT ?? "5432";

/** Изолированный E2E полигона: не трогает seed/clock основных group-a…d. */
export default defineConfig({
  testDir: "./e2e",
  testMatch: [/group-e-synthetic-polygon\.spec\.ts/],
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  timeout: 180_000,
  expect: { timeout: 30_000 },
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    { name: "polygon-setup", testMatch: /polygon\/auth\.setup\.ts/ },
    {
      name: "polygon-chromium",
      dependencies: ["polygon-setup"],
      use: {
        ...devices["Desktop Chrome"],
        storageState: "e2e/.auth/polygon-user.json",
      },
    },
  ],
  webServer: [
    {
      command:
        "bash -c 'cd ../backend && uv run python -m tests.e2e.prepare_polygon && uv run python -m tests.e2e.run_api_polygon'",
      url: "http://127.0.0.1:8000/health/ready",
      reuseExistingServer: false,
      timeout: 240_000,
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5173",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
  outputDir: "test-results-polygon",
  metadata: { testPgPort: port, suite: "synthetic-polygon" },
});
