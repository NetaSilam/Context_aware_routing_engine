import { afterEach, describe, expect, it, vi } from "vitest";

import { createIdempotencyKey } from "./idempotencyKey";

const originalCrypto = globalThis.crypto;

afterEach(() => {
  Object.defineProperty(globalThis, "crypto", { configurable: true, value: originalCrypto });
  vi.restoreAllMocks();
});

describe("createIdempotencyKey", () => {
  it("uses randomUUID when the browser provides it", () => {
    Object.defineProperty(globalThis, "crypto", {
      configurable: true,
      value: { randomUUID: vi.fn(() => "uuid-from-browser"), getRandomValues: vi.fn() },
    });

    expect(createIdempotencyKey()).toBe("uuid-from-browser");
  });

  it("falls back to getRandomValues when randomUUID is unavailable", () => {
    Object.defineProperty(globalThis, "crypto", {
      configurable: true,
      value: {
        getRandomValues: vi.fn((bytes: Uint8Array) => {
          bytes.set([0x10, 0x32, 0x54, 0x76, 0x98, 0xba, 0xdc, 0xfe, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]);
          return bytes;
        }),
      },
    });

    expect(createIdempotencyKey()).toBe("10325476-98ba-4cfe-9122-334455667788");
  });

  it("fails clearly when no secure random generator exists", () => {
    Object.defineProperty(globalThis, "crypto", { configurable: true, value: undefined });

    expect(() => createIdempotencyKey()).toThrow("Secure random id generation is unavailable in this browser.");
  });
});
