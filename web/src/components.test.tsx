import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { QueryState, SourceButton } from "./components";

describe("shared business components", () => {
  it("renders a recoverable API error", () => {
    const retry = vi.fn();
    render(
      <QueryState loading={false} error={new Error("接口暂时不可用")} onRetry={retry}>
        content
      </QueryState>
    );
    expect(screen.getByText("接口暂时不可用")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /重试/ }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("opens traceable evidence and audit details", () => {
    render(
      <SourceButton
        meta={{
          calculation_id: "calc-1",
          as_of_date: "2026-08-05",
          formula_version: "3.0.0",
          warnings: [],
          sources: [
            { source_table: "sales_orders", record_code: "销售-20260718-01", description: "固定演示订单" },
            { source_table: "production_material_requirements", record_code: "34502", description: "铜材存在短缺" },
            { source_table: "purchase_orders", record_code: "采购-20260703-01", description: "采购预计迟交" },
            {
              source_table: "production_orders",
              record_code: "生产-002000",
              description: "计划进度与实际进度比较",
              value: "理论进度57.14%；实际进度52.00%；偏差-5.14个百分点；状态：落后"
            }
          ],
          audit: { operation: "order_risk", actor: "test", request_path: "/orders", read_only: true, timestamp: "2026-08-05" }
        }}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /数据依据/ }));
    expect(screen.getByText("销售订单")).toBeInTheDocument();
    expect(screen.getByText("生产物料需求")).toBeInTheDocument();
    expect(screen.getByText("采购订单")).toBeInTheDocument();
    expect(screen.getByText("生产订单")).toBeInTheDocument();
    expect(screen.getByText(/理论进度57.14%/)).toBeInTheDocument();
    expect(screen.getByText((_, element) => element?.textContent === "操作：订单风险分析")).toBeInTheDocument();
    expect(screen.getByText("销售-20260718-01")).toBeInTheDocument();
    expect(screen.getByText("固定演示订单")).toBeInTheDocument();
    expect(document.querySelectorAll(".source-material")).toHaveLength(1);
    expect(document.querySelectorAll(".source-purchase")).toHaveLength(1);
    expect(document.querySelectorAll(".source-production")).toHaveLength(1);
  });
});

