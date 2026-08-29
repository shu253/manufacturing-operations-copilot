export const formatMoney = (value: unknown, compact = false) => {
  const number = Number(value || 0);
  if (compact && Math.abs(number) >= 10000) {
    return `${(number / 10000).toLocaleString("zh-CN", { maximumFractionDigits: 2 })}万`;
  }
  return `¥${number.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

export const formatNumber = (value: unknown, digits = 0) =>
  Number(value || 0).toLocaleString("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });

export const formatQuantity = (value: unknown, unit?: string) =>
  formatNumber(value, ["件", "个", "套", "台"].includes(unit || "") ? 0 : 2);

const discreteCostUnits = new Set(["件", "个", "套", "台", "只", "支", "根", "张", "盒"]);

export const formatCostQuantity = (value: unknown, unit?: string) => {
  const number = Number(value || 0);
  const normalizedUnit = unit || "";
  const maximumFractionDigits =
    discreteCostUnits.has(normalizedUnit) && Number.isInteger(number) ? 0 : 4;
  const display = number.toLocaleString("zh-CN", {
    minimumFractionDigits: 0,
    maximumFractionDigits
  });

  if (!normalizedUnit) return `${display}（计量单位未返回）`;
  if (discreteCostUnits.has(normalizedUnit) && !Number.isInteger(number)) {
    return `${display}${normalizedUnit}（标准成本耗用量）`;
  }
  return discreteCostUnits.has(normalizedUnit)
    ? `${display}${normalizedUnit}`
    : `${display} ${normalizedUnit}`;
};

export const formatPercent = (value: unknown, digits = 2) =>
  `${(Number(value || 0) * 100).toFixed(digits)}%`;

export const riskColor = (level?: string) =>
  level === "高" ? "red" : level === "中" ? "orange" : "green";
