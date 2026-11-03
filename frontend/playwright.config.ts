import { defineConfig, devices } from "@playwright/test";
import { resolve } from "node:path";

const python = process.env.PYTHON_EXECUTABLE || resolve(import.meta.dirname, "../.venv/bin/python");
const remoteBaseUrl = process.env.E2E_BASE_URL;

const localWebServers = [
  {
    command: `${python} -m uvicorn app.main:app --host 127.0.0.1 --port 8100`,
    cwd: resolve(import.meta.dirname, "../backend"),
    url: "http://127.0.0.1:8100/health/live",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      ENVIRONMENT: "test",
      DATABASE_URL: "sqlite:////tmp/image-studio-e2e.db",
      MEDIA_BACKEND: "local",
      MEDIA_ROOT: "/tmp/image-studio-e2e-media",
      QUEUE_MODE: "inline",
      SESSION_BACKEND: "memory",
      AI_MODE: "mock",
      ADMIN_USERNAME: "admin",
      ADMIN_PASSWORD: "test-password",
      SESSION_SECRET: "e2e-session-secret-with-at-least-32-characters",
    },
  },
  {
    command: "npm run dev -- --host 127.0.0.1",
    cwd: import.meta.dirname,
    url: "http://127.0.0.1:5174/image-studio/",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
];

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: process.env.CI ? "github" : "line",
  use: {
    baseURL: remoteBaseUrl || "http://127.0.0.1:5174",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: remoteBaseUrl ? undefined : localWebServers,
});
