import { expect, test } from "@playwright/test";
import { resolve } from "node:path";

const adminPassword = process.env.E2E_ADMIN_PASSWORD || "test-password";
const runId = Date.now().toString(36);

async function login(page: import("@playwright/test").Page) {
  await page.goto("/image-studio/login");
  await page.getByLabel("账号").fill("admin");
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "登录工作台" }).click();
  await expect(page.getByRole("heading", { name: "创作工作台" })).toBeVisible();
}

test("completes the core product-image workflow without paid providers", async ({ page }) => {
  await login(page);

  await page.getByRole("button", { name: "新建商品" }).first().click();
  await page.getByLabel("商品名称").fill(`CI 保湿乳 ${runId}`);
  await page.getByLabel("SKU").fill(`CI-SKU-${runId}`);
  await page.getByLabel("品牌").fill("CI 品牌");
  await page.getByRole("button", { name: "创建商品" }).click();
  await expect(
    page.getByRole("combobox", { name: "当前商品" }).locator("option:checked"),
  ).toContainText(runId);

  await page.locator('input[type="file"]').setInputFiles(
    resolve(import.meta.dirname, "../public/login-studio.png"),
  );
  await expect(page.getByText("1 / 8 张")).toBeVisible();

  await page.getByRole("button", { name: "识别商品信息" }).click();
  await expect(page.getByRole("heading", { name: "确认商品信息" })).toBeVisible();
  await page.getByRole("button", { name: "确认商品信息" }).click();

  await expect(page.getByRole("heading", { name: "策划生图提示词" })).toBeVisible();
  await page.getByRole("button", { name: "5 张", exact: true }).click();
  await page.getByRole("button", { name: "生成提示词" }).click();
  await expect(page.getByText("1 个视觉方向 · 5 张图片")).toBeVisible();
  await page.getByRole("button", { name: "确认提示词并继续" }).click();

  await expect(page.getByRole("heading", { name: "生成商品图片" })).toBeVisible();
  await page.getByRole("button", { name: "开始生成 5 张" }).click();
  await expect(page.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
  await expect(page.getByRole("img", { name: /结果/ })).toHaveCount(5);
  await expect(page.getByText("已完成", { exact: true })).toBeVisible();
});

test("mobile workbench has no horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);

  const widths = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    content: document.documentElement.scrollWidth,
  }));
  expect(widths.content).toBeLessThanOrEqual(widths.viewport);
});
