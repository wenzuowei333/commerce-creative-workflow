import { describe, expect, it } from "vitest";

import type { ProductWorkspace } from "../../types";
import { deriveWorkspaceStep } from "./steps";

function workspace(overrides: Partial<ProductWorkspace>): ProductWorkspace {
  return {
    product: {
      id: "p1",
      name: "商品",
      sku: "SKU",
      brand: "",
      status: "draft",
      profile: {},
      created_at: "2026-01-01",
      updated_at: "2026-01-01",
    },
    assets: [],
    latest_analysis: null,
    latest_prompt_plan: null,
    ...overrides,
  };
}

describe("deriveWorkspaceStep", () => {
  it("stays on assets until an image is available", () => {
    expect(deriveWorkspaceStep(workspace({}))).toBe(1);
  });

  it("resumes at product confirmation", () => {
    expect(
      deriveWorkspaceStep(
        workspace({
          assets: [{}] as ProductWorkspace["assets"],
          latest_analysis: { status: "awaiting_product_confirmation" } as never,
        }),
      ),
    ).toBe(2);
  });

  it("resumes at generation after the prompt is confirmed", () => {
    expect(
      deriveWorkspaceStep(
        workspace({
          assets: [{}] as ProductWorkspace["assets"],
          latest_analysis: { status: "confirmed" } as never,
          latest_prompt_plan: { state: "confirmed" } as never,
        }),
      ),
    ).toBe(4);
  });
});
