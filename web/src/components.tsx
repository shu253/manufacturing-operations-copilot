import { useState, type ReactNode } from "react";
import { Alert, Button, Card, Drawer, Empty, Skeleton, Space, Tag, Typography } from "antd";
import { DatabaseOutlined, ReloadOutlined } from "@ant-design/icons";
import type { ApiMeta } from "./types";
import { riskColor } from "./format";

const sourceTableLabels: Record<string, string> = {
  sales_orders: "销售订单",
  sales_order_lines: "销售订单明细",
  production_orders: "生产订单",
  production_material_requirements: "生产物料需求",
  production_operations: "生产工序",
  materials: "物料主数据",
  inventory_balances: "库存余额",
  purchase_orders: "采购订单",
  purchase_order_lines: "采购订单明细",
  requirement_allocations: "物料需求分配",
  suppliers: "供应商主数据",
  supplier_materials: "供应商供货关系",
  supplier_score_snapshots: "供应商评分快照",
  material_price_history: "物料价格历史",
  bom_headers: "产品BOM",
  bom_lines: "BOM物料明细",
  products: "产品主数据",
  order_cost_snapshots: "订单成本快照",
  order_cost_details: "订单成本明细",
  quotations: "历史报价",
  shipments: "发货单",
  invoices: "销售发票",
  payments: "客户回款",
  payment_allocations: "回款核销",
  ar_snapshots: "应收账款快照",
  risk_events: "风险事件",
  risk_evidence: "风险证据",
  tasks: "风险任务",
  messages: "站内消息",
  simulation_results: "情景模拟结果",
  enterprise_knowledge: "企业制度知识库"
};

const sourceThemes: Record<string, { color: string; className: string }> = {
  production_material_requirements: { color: "orange", className: "source-material" },
  purchase_orders: { color: "purple", className: "source-purchase" },
  purchase_order_lines: { color: "purple", className: "source-purchase" },
  production_orders: { color: "cyan", className: "source-production" },
  production_operations: { color: "cyan", className: "source-production" },
  sales_orders: { color: "blue", className: "source-sales" },
  sales_order_lines: { color: "blue", className: "source-sales" },
  inventory_balances: { color: "green", className: "source-inventory" },
  invoices: { color: "gold", className: "source-finance" },
  payments: { color: "gold", className: "source-finance" },
  ar_snapshots: { color: "gold", className: "source-finance" }
};

function sourceTheme(sourceTable: string) {
  return sourceThemes[sourceTable] || { color: "default", className: "source-default" };
}

function formatEvidenceValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

const auditOperationLabels: Record<string, string> = {
  health_check: "系统健康检查",
  dashboard_summary: "经营驾驶舱汇总",
  dashboard_trends: "经营趋势查询",
  order_risk: "订单风险分析",
  order_risk_list: "订单风险列表查询",
  order_risk_detail: "订单风险详情查询",
  order_fulfillment: "订单齐套分析",
  order_lifecycle: "订单全流程查询",
  material_shortages: "缺料分析",
  purchase_price_anomalies: "采购价格异常分析",
  supplier_rankings: "供应商排行榜查询",
  supplier_profile: "供应商画像分析",
  supplier_recommendations: "供应商推荐",
  order_cost: "订单成本计算",
  product_list: "产品列表查询",
  quote_calculation: "报价建议计算",
  procurement_scenario: "采购情景模拟",
  receivables_analysis: "应收账款分析",
  report_generation: "经营报告生成",
  report_export: "经营报告导出",
  controlled_assistant_query: "受控经营问数",
  intelligent_assistant_query: "智能经营问数",
  assistant_action_confirmation: "智能体操作确认",
  task_list: "风险任务查询",
  task_detail: "风险任务详情查询",
  task_create: "风险任务创建",
  task_update: "风险任务更新",
  message_list: "站内消息查询",
  message_create: "站内消息创建",
  read: "查询",
  create: "创建",
  update: "更新",
  export: "导出",
  calculate: "计算",
  query: "查询",
  error: "异常处理"
};

export function PageTitle({ title, subtitle, extra }: { title: string; subtitle?: string; extra?: ReactNode }) {
  return (
    <div className="page-title">
      <div>
        <Typography.Title level={2}>{title}</Typography.Title>
        {subtitle && <Typography.Text type="secondary">{subtitle}</Typography.Text>}
      </div>
      {extra && <Space wrap>{extra}</Space>}
    </div>
  );
}

export function SourceButton({ meta }: { meta?: ApiMeta }) {
  const [open, setOpen] = useState(false);
  if (!meta) return null;
  return (
    <>
      <Button icon={<DatabaseOutlined />} onClick={() => setOpen(true)}>数据依据</Button>
      <Drawer title="数据来源与计算审计" open={open} onClose={() => setOpen(false)} width={520}>
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Card size="small">
            <p>计算日期：{meta.as_of_date || "—"}</p>
            <p>数据更新至：{meta.data_as_of_date || "—"}</p>
            <p>公式版本：{meta.formula_version || "—"}</p>
            <p>计算编号：{meta.calculation_id || "—"}</p>
            <p>操作：{auditOperationLabels[meta.audit?.operation || ""] || "业务数据查询"}</p>
          </Card>
          {meta.warnings?.map((warning, index) => <Alert key={index} type="warning" message={warning} showIcon />)}
          {meta.sources?.length ? meta.sources.map((source, index) => {
            const theme = sourceTheme(source.source_table);
            return (
              <Card
                key={`${source.source_table}-${source.record_code}-${index}`}
                size="small"
                className={`source-card ${theme.className}`}
              >
                <Tag color={theme.color}>{sourceTableLabels[source.source_table] || "业务数据"}</Tag>
                <Typography.Text strong>{source.record_code}</Typography.Text>
                {source.description && <p className="source-description">{source.description}</p>}
                {formatEvidenceValue(source.value) && (
                  <p className="source-value">
                    <Typography.Text type="secondary">依据值：</Typography.Text>
                    {formatEvidenceValue(source.value)}
                  </p>
                )}
              </Card>
            );
          }) : <Empty description="当前结果没有附加数据来源" />}
        </Space>
      </Drawer>
    </>
  );
}

export function RiskTag({ level }: { level?: string }) {
  return <Tag color={riskColor(level)}>{level || "未知"}</Tag>;
}

export function QueryState({
  loading,
  error,
  empty,
  onRetry,
  children
}: {
  loading: boolean;
  error?: Error | null;
  empty?: boolean;
  onRetry?: () => void;
  children: ReactNode;
}) {
  if (loading) return <Card><Skeleton active paragraph={{ rows: 8 }} /></Card>;
  if (error) return (
    <Alert
      type="error"
      showIcon
      message="数据加载失败"
      description={error.message}
      action={onRetry && <Button icon={<ReloadOutlined />} onClick={onRetry}>重试</Button>}
    />
  );
  if (empty) return <Card><Empty description="当前条件下暂无数据" /></Card>;
  return <>{children}</>;
}

export function MetricCard({
  title,
  value,
  suffix,
  tone = "blue",
  onClick
}: {
  title: string;
  value: ReactNode;
  suffix?: string;
  tone?: "blue" | "red" | "orange" | "green";
  onClick?: () => void;
}) {
  return (
    <Card className={`metric-card metric-${tone}`} hoverable={Boolean(onClick)} onClick={onClick}>
      <div className="metric-label-row">
        <Typography.Text type="secondary">{title}</Typography.Text>
        {onClick && <span className="metric-action-hint">查看</span>}
      </div>
      <div className="metric-value">{value}<small>{suffix}</small></div>
    </Card>
  );
}
