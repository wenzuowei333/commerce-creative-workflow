import { defineConfig, devices } from "@playwright/test";
import { resolve } from "node:path";

const baseURL = process.env.E2E_BASE_URL || "http://127.0.0.1:18140";
const target = new URL(baseURL);
if (target.hostname !== "127.0.0.1" || target.port !== "18140") {
  throw new Error("Browser checks only target the dedicated local stage-four demo on port 18140");
}

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["line"], ["json", { outputFile: resolve(import.meta.dirname, "../runtime/browser/results.json") }]],
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    viewport: { width: 1440, height: 1000 },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], channel: process.env.E2E_BROWSER_CHANNEL || "chrome" } }],
  outputDir: resolve(import.meta.dirname, "../runtime/browser/artifacts"),
});
