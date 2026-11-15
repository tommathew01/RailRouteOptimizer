import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests against the real FastAPI backend (mock provider, in-memory stores, async
 * searches) and the production Next.js standalone build. Run `npm run build` first.
 * No RailKit key, PostgreSQL or Redis is needed.
 */
const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 3100);
const API_PORT = Number(process.env.E2E_API_PORT ?? 8100);

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 90_000,
  expect: { timeout: 20_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"], colorScheme: "dark" } },
  ],
  webServer: [
    {
      name: "api",
      cwd: "../../backend",
      command: `uv run uvicorn app.asgi:app --host 127.0.0.1 --port ${API_PORT} --no-proxy-headers`,
      url: `http://127.0.0.1:${API_PORT}/api/v1/health/live`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        ENVIRONMENT: "development",
        RAILWAY_PROVIDER: "mock",
        // Empty values override the developer's .env: in-memory persistence and store.
        DATABASE_URL: "",
        REDIS_URL: "",
        SEARCH_EXECUTION_MODE: "async",
        MOCK_LATENCY_MS: "80",
        SEARCH_MAX_AVAILABILITY_REQUESTS: "40",
        API_RATE_LIMIT_SEARCH_REQUESTS: "500",
        API_RATE_LIMIT_LOOKUP_REQUESTS: "5000",
        LOG_JSON: "false",
        LOG_LEVEL: "WARNING",
      },
    },
    {
      name: "web",
      command: "node scripts/start-standalone.mjs",
      url: `http://127.0.0.1:${WEB_PORT}/`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: {
        PORT: String(WEB_PORT),
        HOSTNAME: "127.0.0.1",
        BACKEND_INTERNAL_URL: `http://127.0.0.1:${API_PORT}`,
        NEXT_TELEMETRY_DISABLED: "1",
      },
    },
  ],
});
