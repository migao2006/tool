import { defineConfig, devices } from "@playwright/test";

const port = Number.parseInt(process.env.PLAYWRIGHT_PORT ?? "4180", 10);
const baseURL = `http://127.0.0.1:${port}`;
const mobileUse = Object.freeze({
  viewport: { width: 390, height: 844 },
  deviceScaleFactor: 3,
  hasTouch: true,
  isMobile: true,
});

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 2,
  reporter: process.env.CI ? [["line"], ["html", { open: "never" }]] : "list",
  outputDir: "artifacts/playwright-results",
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "iphone-chromium",
      use: {
        ...mobileUse,
        browserName: "chromium",
      },
    },
    {
      name: "iphone-webkit",
      testMatch: /(?:auth-mobile-accessibility|mobile-visual-audit)\.spec\.mjs/,
      use: {
        ...devices["iPhone 13"],
        browserName: "webkit",
      },
    },
  ],
  webServer: {
    command: `uv run python tests/support/frontend_api_fixture_server.py --port ${port}`,
    url: `${baseURL}/contract-test`,
    reuseExistingServer: !process.env.CI,
    stdout: "pipe",
    stderr: "pipe",
    timeout: 30_000,
  },
});
