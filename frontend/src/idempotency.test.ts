import { describe, expect, it } from "vitest";
import { createIdempotencyKey } from "./idempotency";

describe("createIdempotencyKey", () => {
  it("uses native randomUUID when available", () => {
    expect(
      createIdempotencyKey(
        { randomUUID: () => "native-uuid" },
        123
      )
    ).toBe("native-uuid-123");
  });

  it("falls back when randomUUID is unavailable", () => {
    const key = createIdempotencyKey(undefined, 456, () => 0.5);

    expect(key).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}-456$/
    );
    expect(key.length).toBeGreaterThanOrEqual(16);
  });
});
