import { describe, expect, it } from "vitest";

import { appUrl, createRequestId, digestSha256 } from "./client";

describe("appUrl", () => {
  it("prefixes backend media paths with the deployed base path", () => {
    expect(appUrl("/api/v1/images/example/content", "/image-studio/")).toBe(
      "/image-studio/api/v1/images/example/content",
    );
  });

  it("preserves absolute COS URLs", () => {
    expect(appUrl("https://example.cos.test/object.webp")).toBe(
      "https://example.cos.test/object.webp",
    );
  });
});

describe("HTTP compatibility", () => {
  it("creates an idempotency key when randomUUID is unavailable", () => {
    const fallbackCrypto = {
      getRandomValues: (array: Uint8Array) => {
        array.fill(7);
        return array;
      },
    } as unknown as Crypto;

    expect(createRequestId(fallbackCrypto)).toMatch(
      /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/,
    );
  });

  it("calculates SHA-256 without Web Crypto subtle", async () => {
    const digest = await digestSha256(new TextEncoder().encode("abc").buffer, undefined);

    expect(digest).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  });
});
