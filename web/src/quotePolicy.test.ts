import { describe, expect, it } from "vitest";
import { quoteMarginPolicy } from "./quotePolicy";

describe("quote margin policy", () => {
  it("uses a neutral zero-to-sixty-percent comparison range", () => {
    expect(quoteMarginPolicy.min).toBe(0);
    expect(quoteMarginPolicy.max).toBe(60);
    expect(quoteMarginPolicy.defaultValue).toBe(25);
    expect(quoteMarginPolicy.presets).toEqual([0, 10, 20, 30, 40, 50, 60]);
    const labels = Object.values(quoteMarginPolicy.marks).join(" ");
    expect(labels).not.toContain("保底");
    expect(labels).not.toContain("高毛利");
    expect(labels).not.toContain("内部最低价");
  });
});
