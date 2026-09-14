import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright E2E. Запускается против поднятого стека (localhost:3000/8000).
 * Браузеры: `npx playwright install chromium`.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: 1,
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
});
