import { expect, test, type Page } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const output = resolve(import.meta.dirname, "../../runtime/browser");
const api = "/image-studio/api/v1";
const receipts: Record<string, unknown> = {};

async function login(page: Page, username = "demo_admin") {
  await page.goto("/image-studio/login");
  await page.getByLabel("账号", { exact: true }).fill(username);
  await page.getByLabel("密码", { exact: true }).fill("LocalDemo-2026!");
  await page.getByRole("button", { name: "登录工作台" }).click();
  await expect(page.getByRole("heading", { name: "创作工作台" })).toBeVisible();
}

async function readBatch(page: Page, id: string) {
  const response = await page.request.get(`${api}/generation-batches/${id}`);
  expect(response.status()).toBe(200);
  return (await response.json()).data;
}

async function prepare(page: Page, label: string) {
  await page.getByRole("combobox", { name: "当前商品" }).selectOption({ label });
  await page.getByRole("button", { name: /商品素材/ }).click();
  await expect(page.getByText("4 / 8 张", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "识别商品信息" }).click();
  await expect(page.getByRole("heading", { name: "确认商品信息" })).toBeVisible();
  await expect(page.getByRole("button", { name: "确认商品信息", exact: true })).toBeDisabled();
  await page.getByLabel("人工确认").last().check();
  await page.getByRole("button", { name: "确认商品信息", exact: true }).click();
  await expect(page.getByRole("heading", { name: "策划生图提示词" })).toBeVisible();
  await page.getByRole("button", { name: "5 张", exact: true }).click();
  await page.getByRole("button", { name: "生成提示词", exact: true }).click();
  await expect(page.getByText("1 个视觉方向 · 5 张图片")).toBeVisible();
  await page.getByRole("button", { name: "确认提示词并继续" }).click();
  await expect(page.getByRole("heading", { name: "生成商品图片" })).toBeVisible();
}

test.beforeEach(async ({ context }) => {
  await context.route("**/*", async route => {
    const url = new URL(route.request().url());
    if (["data:", "blob:", "about:"].includes(url.protocol) || (url.hostname === "127.0.0.1" && ["18140", "18160"].includes(url.port))) {
      await route.continue();
    } else {
      await route.abort();
      throw new Error("Unexpected external browser request");
    }
  });
});

test.beforeAll(async () => { await mkdir(output, { recursive: true }); });

test("four successes and one failure survive reload, then only failed item retries", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await login(page);
  await prepare(page, "虚构青绿随行杯 · DEMO-CUP-001");
  await page.getByLabel("Mock 演示场景").selectOption("partial_once");
  const createdResponse = page.waitForResponse(r => r.url().endsWith("/generation-batches") && r.request().method() === "POST");
  await page.getByRole("button", { name: "开始生成 5 张" }).click();
  const created = (await (await createdResponse).json()).data;
  await expect(page.getByText("已完成 4 · 失败 1 · 共 5 张", { exact: true })).toBeVisible();
  await expect(page.getByRole("img", { name: /结果/ })).toHaveCount(4);
  const initial = await readBatch(page, created.id);
  expect(initial.state).toBe("partial");
  expect(initial.items.map((item: any) => item.attempts)).toEqual([1,1,1,1,1]);
  await page.screenshot({ path: resolve(output, "partial-failure.png"), fullPage: true });

  await page.reload();
  await expect(page.getByText("已完成 4 · 失败 1 · 共 5 张", { exact: true })).toBeVisible();
  expect((await readBatch(page, created.id)).items).toEqual(initial.items);
  await page.getByRole("button", { name: "仅补生成失败图片" }).click();
  await expect(page.getByText("已完成 5 · 失败 0 · 共 5 张", { exact: true })).toBeVisible();
  await expect(page.getByRole("img", { name: /结果/ })).toHaveCount(5);
  const final = await readBatch(page, created.id);
  expect(final.state).toBe("completed");
  expect(final.items.map((item: any) => item.attempts)).toEqual([1,1,2,1,1]);
  for (const item of initial.items.filter((item: any) => item.image)) {
    expect(final.items.find((current: any) => current.id === item.id).image.id).toBe(item.image.id);
  }
  await page.screenshot({ path: resolve(output, "retry-completed.png"), fullPage: true });
  await page.getByLabel("选择结果 1", { exact: true }).check();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "下载所选" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/\.zip$/);
  await file.saveAs(resolve(output, "selected-results.zip"));
  expect(errors).toEqual([]);
  receipts.partial_retry = { initial, final, four_images_unchanged: true, reload_preserved_state: true, download: file.suggestedFilename(), uncaught_js_errors: errors };
});

test("normal second product, product switching and other-user isolation", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await login(page);
  await prepare(page, "虚构桌面收纳盒 · DEMO-BOX-001");
  await page.getByLabel("Mock 演示场景").selectOption("success");
  const createdResponse = page.waitForResponse(r => r.url().endsWith("/generation-batches") && r.request().method() === "POST");
  await page.getByRole("button", { name: "开始生成 5 张" }).click();
  const created = (await (await createdResponse).json()).data;
  await expect(page.getByText("已完成 5 · 失败 0 · 共 5 张", { exact: true })).toBeVisible();
  const normal = await readBatch(page, created.id);
  expect(normal.items.map((item: any) => item.attempts)).toEqual([1,1,1,1,1]);
  await page.screenshot({ path: resolve(output, "normal-completed.png"), fullPage: true });
  await page.getByRole("combobox", { name: "当前商品" }).selectOption({ label: "虚构青绿随行杯 · DEMO-CUP-001" });
  await expect(page.getByText(/第 3 张首次失败演示/)).toBeVisible();
  await expect(page.getByText("已完成 5 · 失败 0 · 共 5 张", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "退出登录" }).click();
  await page.getByLabel("账号", { exact: true }).fill("demo_other");
  await page.getByLabel("密码", { exact: true }).fill("LocalDemo-2026!");
  await page.getByRole("button", { name: "登录工作台" }).click();
  await expect(page.getByRole("heading", { name: "新建第一个商品档案" })).toBeVisible();
  expect((await page.request.get(`${api}/products`)).status()).toBe(200);
  expect((await (await page.request.get(`${api}/products`)).json()).data).toEqual([]);
  expect((await page.request.get(`${api}/generation-batches/${normal.id}`)).status()).toBe(404);
  expect((await page.request.get(`${api}/images/${normal.items[0].image.id}/content`)).status()).toBe(404);
  await expect(page.locator("main")).not.toContainText("虚构桌面收纳盒");
  await page.screenshot({ path: resolve(output, "other-user.png"), fullPage: true });
  expect(errors).toEqual([]);
  receipts.normal_and_scope = { normal, product_switch_preserved_correct_batch: true, other_user_products: 0, cross_owner_batch: 404, cross_owner_image: 404, uncaught_js_errors: errors };
});

test("390px mobile layout restores persisted results", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await login(page);
  await page.getByRole("combobox", { name: "当前商品" }).selectOption({ label: "虚构青绿随行杯 · DEMO-CUP-001" });
  await expect(page.getByText("已完成 5 · 失败 0 · 共 5 张", { exact: true })).toBeVisible();
  const widths = await page.evaluate(() => ({ viewport: document.documentElement.clientWidth, content: document.documentElement.scrollWidth }));
  expect(widths.content).toBeLessThanOrEqual(widths.viewport);
  await page.screenshot({ path: resolve(output, "mobile.png"), fullPage: true });
  expect(errors).toEqual([]);
  receipts.mobile = { ...widths, restored_results: true, uncaught_js_errors: errors };
});

test.afterAll(async () => { await writeFile(resolve(output, "verification.json"), JSON.stringify(receipts, null, 2)); });
