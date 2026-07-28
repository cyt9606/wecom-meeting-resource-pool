import { describe, expect, it } from "vitest";
import { durationText } from "./date";

describe("durationText", () => {
  it("formats full hours", () => {
    expect(
      durationText("2026-07-28T08:00:00Z", "2026-07-28T10:00:00Z")
    ).toBe("2 小时");
  });

  it("formats partial hours as minutes", () => {
    expect(
      durationText("2026-07-28T08:00:00Z", "2026-07-28T08:30:00Z")
    ).toBe("30 分钟");
  });
});
