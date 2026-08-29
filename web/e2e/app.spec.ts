import { expect, test } from "@playwright/test";

test("经营驾驶舱加载真实业务数据且页面不横向溢出", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { name: "经营驾驶舱" })).toBeVisible();
  await expect(page.getByText("高风险订单", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("今日管理动作")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  expect(overflow).toBeFalsy();
});

test("固定订单完整演示路径显示标准结果", async ({ page }) => {
  await page.goto("/orders/SO20260718");
  await expect(page.getByRole("heading", { name: "订单 SO20260718" })).toBeVisible();
  await expect(page.getByText("综合风险分")).toBeVisible();
  await expect(page.getByText("85", { exact: true }).first()).toBeVisible();
  await page.getByRole("tab", { name: "全流程追踪" }).click();
  await expect(page.getByText("业务时间线")).toBeVisible();
  await expect(page.getByText("订单与客户")).toBeVisible();
});

test("AI经营问数返回固定铜材情景结果和工具依据", async ({ page }) => {
  await page.goto("/assistant");
  await expect(page.getByRole("heading", { name: "AI经营问数" })).toBeVisible();
  await page.getByRole("button", { name: "针对SO20260718，铜材上涨8%会有什么影响？" }).click();
  await expect(page.getByText(/14,596.47元/)).toBeVisible();
  await expect(page.getByText(/15.18%/)).toBeVisible();
  await expect(page.getByText("run_procurement_scenario", { exact: false })).toBeVisible();
  await expect(page.getByText("本地受控编排", { exact: true })).toBeVisible();
});

test("AI写操作先展示人工确认而不直接创建", async ({ page }) => {
  await page.goto("/assistant");
  await page.getByRole("button", { name: "SO20260718为什么是高风险订单，应该怎么处理？" }).click();
  await expect(page.getByText(/综合风险分为85分/)).toBeVisible();
  const input = page.getByPlaceholder("输入业务问题，例如：SO20260718为什么有风险？");
  await input.fill("帮我创建处理任务");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByText("需要人工确认", { exact: true })).toBeVisible();
  await expect(page.getByText("任务尚未创建", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "确认执行" })).toBeVisible();
});

test("报价毛利率支持0%至60%且不使用无依据等级标签", async ({ page }) => {
  await page.goto("/quote");
  await expect(page.getByRole("heading", { name: "报价建议" })).toBeVisible();
  await expect(page.getByText("保底", { exact: true })).toHaveCount(0);
  await expect(page.getByText("高毛利", { exact: true })).toHaveCount(0);
  await expect(page.getByText("内部最低价", { exact: true })).toHaveCount(0);

  await page.getByRole("button", { name: "0%", exact: true }).click();
  await page.getByRole("button", { name: "生成报价建议" }).click();
  await expect(page.getByText("按输入的目标毛利率 0.00% 测算")).toBeVisible();

  await page.getByRole("button", { name: "60%", exact: true }).click();
  await page.getByRole("button", { name: "生成报价建议" }).click();
  await expect(page.getByText("按输入的目标毛利率 60.00% 测算")).toBeVisible();
  await expect(page.getByText(/模拟历史毛利分布/)).toBeVisible();
  await expect(page.getByText("第三步：核对成本与报价依据")).toBeVisible();
  await expect(page.getByText("整单成本构成")).toBeVisible();
  await expect(page.getByText("目标报价组成")).toBeVisible();
  await expect(page.getByText("本次成本计算口径")).toBeVisible();
  await expect(page.getByText("BOM物料成本明细（共21项）")).toBeVisible();
  await expect(
    page.getByTestId("quote-cost-breakdown").getByText("¥547,106.76", { exact: true })
  ).toBeVisible();
  await expect(page.getByText("M-CU-018", { exact: true })).toBeVisible();
  await expect(page.locator(".quote-evidence-chart canvas")).toHaveCount(2);

  await page.getByRole("button", { name: "50%", exact: true }).click();
  await expect(page.getByText("报价条件已修改，请重新生成")).toBeVisible();
  await page.getByRole("button", { name: "生成报价建议" }).click();
  await expect(page.getByText("报价条件已修改，请重新生成")).toHaveCount(0);
  await expect(page.getByText("与当前报价一致")).toBeVisible();

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1
  );
  expect(overflow).toBeFalsy();
});

test("角色切换影响菜单权限", async ({ page }) => {
  await page.goto("/settings");
  const selectors = page.locator(".role-select");
  await selectors.click();
  await page.getByText("生产人员", { exact: true }).last().click();
  if ((page.viewportSize()?.width || 0) < 992) {
    await page.getByRole("button", { name: "打开导航菜单" }).click();
  }
  await expect(page.getByText("成本穿透", { exact: true })).toHaveCount(0);
  await expect(page.getByText("缺料与预警", { exact: true })).toBeVisible();
});

test("阶段五全部13项功能页面均可访问", async ({ page }) => {
  const routes = [
    ["/dashboard", "经营驾驶舱"],
    ["/orders", "订单风险中心"],
    ["/orders/SO20260718", "订单 SO20260718"],
    ["/procurement", "缺料与采购预警"],
    ["/suppliers", "供应商画像与推荐"],
    ["/cost", "成本穿透"],
    ["/quote", "报价建议"],
    ["/scenario", "采购与经营情景模拟"],
    ["/receivables", "应收账款与回款风险"],
    ["/reports", "经营报告中心"],
    ["/assistant", "AI经营问数"],
    ["/tasks", "风险任务处理"],
    ["/settings", "用户、权限与系统设置"]
  ];
  for (const [path, heading] of routes) {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: heading })).toBeVisible();
  }
});
