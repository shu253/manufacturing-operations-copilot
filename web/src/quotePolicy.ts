export const quoteMarginPolicy = {
  min: 0,
  max: 60,
  defaultValue: 25,
  marks: { 0: "0%", 20: "20%", 40: "40%", 60: "60%" },
  presets: [0, 10, 20, 30, 40, 50, 60]
} as const;

