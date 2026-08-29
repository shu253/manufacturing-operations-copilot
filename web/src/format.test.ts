import { describe, expect, it } from "vitest";
import { formatCostQuantity, formatMoney, formatNumber, formatPercent, formatQuantity, riskColor } from "./format";

describe("business formatters", () => {
  it("formats money and compact values", () => {
    expect(formatMoney(14596.47)).toBe("¥14,596.47");
    expect(formatMoney(110000, true)).toBe("11万");
  });

  it("formats percentages without changing business values", () => {
    expect(formatPercent(0.165)).toBe("16.50%");
    expect(formatPercent(0.1518)).toBe("15.18%");
  });

  it("maps risk levels to stable colors", () => {
    expect(riskColor("高")).toBe("red");
    expect(riskColor("中")).toBe("orange");
    expect(riskColor("低")).toBe("green");
  });

  it("formats quantities with requested precision", () => {
    expect(formatNumber(1659.042, 3)).toBe("1,659.042");
    expect(formatQuantity(1, "件")).toBe("1");
    expect(formatQuantity(18.7783, "kg")).toBe("18.78");
  });

  it("formats standard cost consumption without hiding precision", () => {
    expect(formatCostQuantity(43.7789, "件")).toBe("43.7789件（标准成本耗用量）");
    expect(formatCostQuantity(16, "件")).toBe("16件");
    expect(formatCostQuantity(1659.042, "kg")).toBe("1,659.042 kg");
    expect(formatCostQuantity(8)).toBe("8（计量单位未返回）");
  });
});
