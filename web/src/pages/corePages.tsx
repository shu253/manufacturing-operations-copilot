import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import ReactECharts from "echarts-for-react";
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Input,
  Progress,
  Row,
  Segmented,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Timeline,
  Typography
} from "antd";
import { ArrowRightOutlined, SearchOutlined } from "@ant-design/icons";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { getApi } from "../api";
import { useAppContext } from "../appContext";
import { MetricCard, PageTitle, QueryState, RiskTag, SourceButton } from "../components";
import { formatMoney, formatNumber, formatPercent, formatQuantity, riskColor } from "../format";

export function DashboardPage() {
  const navigate = useNavigate();
  const { asOfDate } = useAppContext();
  const dashboard = useQuery({
    queryKey: ["dashboard", asOfDate],
    queryFn: () => getApi<any>(`/api/v1/dashboard?as_of_date=${asOfDate}`)
  });
  const trends = useQuery({
    queryKey: ["dashboard-trends", asOfDate],
    queryFn: () => getApi<any>(`/api/v1/dashboard/trends?as_of_date=${asOfDate}&months=12`)
  });
  const data = dashboard.data?.data;
  const trend = trends.data?.data;
  const trendOption = trend ? {
    tooltip: { trigger: "axis", backgroundColor: "#143852", borderWidth: 0, textStyle: { color: "#f4ffff" } },
    legend: { data: ["销售订单", "采购金额"], top: 0, right: 0, icon: "roundRect", itemWidth: 14, itemHeight: 8, textStyle: { color: "#6c8495", fontSize: 12 } },
    grid: { left: 52, right: 22, top: 42, bottom: 34 },
    xAxis: { type: "category", data: trend.months, axisLine: { lineStyle: { color: "#cbdbe4" } }, axisLabel: { color: "#71899a", rotate: 35 } },
    yAxis: { type: "value", splitLine: { lineStyle: { color: "#e4edf2", type: "dashed" } }, axisLabel: { color: "#71899a", formatter: (value: number) => `${Math.round(value / 10000)}万` } },
    series: [
      { name: "销售订单", type: "line", smooth: true, symbolSize: 7, data: trend.series.sales_order_amount, lineStyle: { width: 3, color: "#116da8" }, areaStyle: { color: "#116da8", opacity: .08 }, itemStyle: { color: "#116da8", borderColor: "#fff", borderWidth: 2 } },
      { name: "采购金额", type: "bar", barMaxWidth: 22, data: trend.series.purchase_amount, itemStyle: { color: "#7ec9c1", borderRadius: [5, 5, 0, 0] } }
    ]
  } : {};
  return (
    <>
      <PageTitle
        title="经营驾驶舱"
        subtitle="订单交付、采购供应、成本利润与回款风险一屏掌握"
        extra={<SourceButton meta={dashboard.data?.meta} />}
      />
      <div className="dashboard-context-bar">
        <span className="dashboard-live-dot" />
        <span>数据基准日：{dashboard.data?.meta?.data_as_of_date || "—"}</span>
        <span className="dashboard-context-divider" />
        <span>业务数字来自确定性计算引擎</span>
      </div>
      <QueryState loading={dashboard.isLoading} error={dashboard.error} onRetry={() => dashboard.refetch()}>
        {data && (
          <>
            <div className="dashboard-section-label">核心风险信号</div>
            <div className="metric-grid">
              <MetricCard title="未来7天高风险订单" value={data.high_risk_order_count} suffix="张" tone="red" onClick={() => navigate("/orders?scope=upcoming_7d&risk_level=高")} />
              <MetricCard title="未来7天风险影响金额" value={formatMoney(data.risk_order_amount, true)} tone="orange" onClick={() => navigate("/orders?scope=upcoming_7d")} />
              <MetricCard title="当前缺料" value={data.shortage_count} suffix="项" tone="red" onClick={() => navigate("/procurement")} />
              <MetricCard title="采购价格异常" value={data.price_anomaly_count} suffix="项" tone="orange" onClick={() => navigate("/procurement")} />
              <MetricCard title="高风险应收" value={data.high_risk_receivable_count} suffix="笔" tone="orange" onClick={() => navigate("/receivables")} />
            </div>
            <div className="dashboard-section-label">经营态势与待办</div>
            <div className="content-grid">
              <Card title="近12个月订单与采购趋势" className="chart-card trend-card" extra={<Typography.Text className="dashboard-trend-meta">金额口径：元</Typography.Text>}>
                <QueryState loading={trends.isLoading} error={trends.error}>
                  <ReactECharts option={trendOption} className="chart" />
                </QueryState>
              </Card>
              <Card title="今日管理动作" className="dashboard-action-card" extra={<Button type="link" onClick={() => navigate("/tasks")}>全部任务</Button>}>
                {(data.top_actions || []).length ? <Timeline
                  items={(data.top_actions || []).map((item: any, index: number) => ({
                    color: item.priority <= 2 ? "red" : item.priority <= 4 ? "orange" : "blue",
                    children: <div className="dashboard-action-item">
                      <span className={`dashboard-action-index ${item.priority <= 2 ? "is-critical" : item.priority <= 4 ? "is-warning" : ""}`}>{index + 1}</span>
                      <div className="dashboard-action-copy"><Typography.Text strong className="dashboard-action-title">{item.action}</Typography.Text><Typography.Text className="dashboard-action-owner">责任部门：{item.owner}<span className="dashboard-action-priority">优先级 {item.priority ?? "—"}</span></Typography.Text></div>
                    </div>
                  }))}
                /> : <div className="dashboard-action-empty">当前没有待处理管理动作</div>}
              </Card>
            </div>
            <Card
              title="高风险订单"
              className="risk-orders-card"
              extra={<Button type="primary" onClick={() => navigate("/orders?scope=upcoming_7d&risk_level=高")}>查看未来7天 <ArrowRightOutlined /></Button>}
            >
              <Table
                className="desktop-table risk-orders-table"
                rowKey="sales_order_code"
                pagination={false}
                dataSource={data.high_risk_orders || []}
                onRow={(record: any) => ({ onClick: () => navigate(`/orders/${record.sales_order_code}`), style: { cursor: "pointer" } })}
                columns={[
                  { title: "订单编号", dataIndex: "sales_order_code", render: (value: string) => <Typography.Link>{value}</Typography.Link> },
                  { title: "交付日期", dataIndex: "promised_delivery_date" },
                  { title: "风险分", dataIndex: "risk_score", sorter: (a: any, b: any) => a.risk_score - b.risk_score, render: (value: number) => <Typography.Text strong style={{ color: "#d9363e" }}>{value}</Typography.Text> },
                  { title: "等级", dataIndex: "risk_level", render: (value: string) => <RiskTag level={value} /> },
                  { title: "缺料项", dataIndex: "shortage_line_count" },
                  { title: "影响金额", dataIndex: "potential_amount", align: "right", render: formatMoney }
                ]}
              />
              <div className="mobile-cards">
                {(data.high_risk_orders || []).map((row: any) => (
                  <div className="risk-order-mobile-card" key={row.sales_order_code} onClick={() => navigate(`/orders/${row.sales_order_code}`)} role="button" tabIndex={0}>
                    <div className="risk-order-mobile-head">
                      <span className="risk-order-mobile-code">{row.sales_order_code}</span>
                      <RiskTag level={row.risk_level} />
                    </div>
                    <div className="risk-order-mobile-meta">
                      <div><span>交付日期</span><strong>{row.promised_delivery_date}</strong></div>
                      <div><span>风险分</span><strong className="risk-order-mobile-score">{row.risk_score}</strong></div>
                      <div><span>缺料项</span><strong>{row.shortage_line_count} 项</strong></div>
                      <div><span>影响金额</span><strong>{formatMoney(row.potential_amount)}</strong></div>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          </>
        )}
      </QueryState>
    </>
  );
}

export function OrdersPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { asOfDate } = useAppContext();
  const [level, setLevel] = useState<string | undefined>(() => searchParams.get("risk_level") || undefined);
  const [scope, setScope] = useState(() => searchParams.get("scope") || "all");
  const [search, setSearch] = useState("");
  const query = useQuery({
    queryKey: ["order-risks", asOfDate, level, scope],
    queryFn: () => getApi<any>(`/api/v1/orders/risks?as_of_date=${asOfDate}&limit=100&scope=${scope}${level ? `&risk_level=${level}` : ""}`)
  });
  const updateFilters = (nextLevel: string | undefined, nextScope: string) => {
    setLevel(nextLevel);
    setScope(nextScope);
    const next = new URLSearchParams();
    if (nextLevel) next.set("risk_level", nextLevel);
    if (nextScope !== "all") next.set("scope", nextScope);
    setSearchParams(next, { replace: true });
  };
  const rows = useMemo(
    () => (query.data?.data.items || []).filter((row: any) => row.sales_order_code.toLowerCase().includes(search.toLowerCase())),
    [query.data, search]
  );
  return (
    <>
      <PageTitle title="订单风险中心" subtitle="识别交付风险、缺料、采购迟交和生产进度偏差" extra={<SourceButton meta={query.data?.meta} />} />
      <Card>
        <div className="toolbar">
          <Space wrap>
            <Input prefix={<SearchOutlined />} placeholder="搜索订单编号" value={search} onChange={event => setSearch(event.target.value)} allowClear />
            <Select
              placeholder="风险等级"
              allowClear
              value={level}
              onChange={value => updateFilters(value, scope)}
              options={["高", "中", "低"].map(value => ({ value, label: value }))}
              style={{ width: 130 }}
            />
            <Select
              value={scope}
              onChange={value => updateFilters(level, value)}
              options={[
                { value: "all", label: "全部交期" },
                { value: "upcoming_7d", label: "未来7天" }
              ]}
              style={{ width: 130 }}
            />
          </Space>
          <Typography.Text type="secondary">
            {scope === "upcoming_7d" ? "未来7天" : "全部范围"}：共 {rows.length} 张{level ? `${level}风险` : "风险"}订单
          </Typography.Text>
        </div>
        <QueryState loading={query.isLoading} error={query.error} empty={!rows.length} onRetry={() => query.refetch()}>
          <Table
            className="desktop-table"
            rowKey="sales_order_code"
            dataSource={rows}
            pagination={{ pageSize: 12, showSizeChanger: true }}
            onRow={(record: any) => ({ onClick: () => navigate(`/orders/${record.sales_order_code}`), style: { cursor: "pointer" } })}
            columns={[
              { title: "订单编号", dataIndex: "sales_order_code", render: (value: string) => <Typography.Link>{value}</Typography.Link> },
              { title: "风险分", dataIndex: "risk_score", sorter: (a: any, b: any) => a.risk_score - b.risk_score, render: (value: number) => <Progress percent={value} size="small" strokeColor={value >= 60 ? "#e24a4a" : "#ec922f"} format={() => value} /> },
              { title: "等级", dataIndex: "risk_level", filters: ["高", "中", "低"].map(text => ({ text, value: text })), onFilter: (value, record: any) => record.risk_level === value, render: (value: string) => <RiskTag level={value} /> },
              { title: "缺料项", dataIndex: "shortage_line_count", sorter: (a: any, b: any) => a.shortage_line_count - b.shortage_line_count },
              { title: "影响金额", dataIndex: "potential_amount", align: "right", render: formatMoney },
              { title: "操作", fixed: "right", render: (_: unknown, row: any) => <Button type="link" onClick={event => { event.stopPropagation(); navigate(`/orders/${row.sales_order_code}`); }}>查看详情</Button> }
            ]}
          />
        </QueryState>
      </Card>
    </>
  );
}

export function OrderDetailPage() {
  const { orderCode = "销售-20260718-01" } = useParams();
  const { asOfDate } = useAppContext();
  const risk = useQuery({ queryKey: ["risk", orderCode, asOfDate], queryFn: () => getApi<any>(`/api/v1/orders/${orderCode}/risk?as_of_date=${asOfDate}`) });
  const fulfillment = useQuery({ queryKey: ["fulfillment", orderCode, asOfDate], queryFn: () => getApi<any>(`/api/v1/orders/${orderCode}/fulfillment?as_of_date=${asOfDate}`) });
  const lifecycle = useQuery({ queryKey: ["lifecycle", orderCode, asOfDate], queryFn: () => getApi<any>(`/api/v1/orders/${orderCode}/lifecycle?as_of_date=${asOfDate}`) });
  const data = risk.data?.data;
  const flow = lifecycle.data?.data;
  return (
    <>
      <PageTitle
        title={`订单 ${orderCode}`}
        subtitle="从风险识别到生产、采购、发货和回款的全流程追踪"
        extra={<><RiskTag level={data?.risk_level} /><SourceButton meta={risk.data?.meta} /></>}
      />
      <QueryState loading={risk.isLoading || fulfillment.isLoading || lifecycle.isLoading} error={(risk.error || fulfillment.error || lifecycle.error) as Error}>
        {data && flow && (
          <>
            <div className="metric-grid">
              <MetricCard title="综合风险分" value={data.risk_score} suffix="分" tone="red" />
              <MetricCard title="订单金额" value={formatMoney(data.potential_amount, true)} tone="blue" />
              <MetricCard title="物料齐套率" value={formatPercent(fulfillment.data?.data.quantity_kitting_rate)} tone="orange" />
              <MetricCard title="缺料项" value={data.shortage_line_count} suffix="项" tone="red" />
              <MetricCard title="生产进度" value={`${flow.production[0]?.progress_rate || 0}%`} tone="orange" />
            </div>
            <Tabs
              defaultActiveKey="risk"
              items={[
                {
                  key: "risk",
                  label: "风险分析",
                  children: (
                    <div className="two-column">
                      <Card title="风险评分">
                        <div className="risk-score"><strong>{data.risk_score}</strong></div>
                        <div style={{ textAlign: "center", marginTop: 14 }}><RiskTag level={data.risk_level} /></div>
                      </Card>
                      <Card title="风险构成">
                        {(data.risk_components || []).map((item: any) => (
                          <Alert
                            key={item.rule_code}
                            type={item.score >= 40 ? "error" : "warning"}
                            showIcon
                            style={{ marginBottom: 10 }}
                            message={<Space><strong>+{item.score}分</strong>{item.reason}</Space>}
                          />
                        ))}
                      </Card>
                    </div>
                  )
                },
                {
                  key: "materials",
                  label: "齐套与缺料",
                  children: (
                    <Card>
                      <Table
                        className="desktop-table"
                        rowKey="material_code"
                        dataSource={fulfillment.data?.data.materials || []}
                        pagination={{ pageSize: 10 }}
                        columns={[
                          { title: "物料", dataIndex: "material_code", render: (value, row: any) => <div><strong>{value}</strong><br /><Typography.Text type="secondary">{row.material_name}</Typography.Text></div> },
                          { title: "需求量", dataIndex: "required_qty", render: (value, row: any) => `${formatQuantity(value, row.unit)} ${row.unit}` },
                          { title: "已领料", dataIndex: "issued_qty", render: (value, row: any) => `${formatQuantity(value, row.unit)} ${row.unit}` },
                          { title: "库存分配", dataIndex: "stock_allocated_qty", render: (value, row: any) => `${formatQuantity(value, row.unit)} ${row.unit}` },
                          { title: "短缺量", dataIndex: "shortage_qty", render: (value, row: any) => <Typography.Text type={value > 0 ? "danger" : undefined} strong>{formatQuantity(value, row.unit)} {row.unit}</Typography.Text> },
                          { title: "状态", dataIndex: "is_fully_kitted", render: value => <Tag color={value ? "green" : "red"}>{value ? "已齐套" : "缺料"}</Tag> }
                        ]}
                      />
                    </Card>
                  )
                },
                {
                  key: "flow",
                  label: "全流程追踪",
                  children: (
                    <div className="content-grid">
                      <Card title="业务时间线">
                        <Timeline
                          items={(flow.timeline || []).map((item: any) => ({
                            color: item.type === "采购" ? "orange" : item.type === "回款" ? "green" : "blue",
                            children: <div><strong>{item.title}</strong><br /><span className="timeline-code">{item.date} · {item.type} · {item.code}</span></div>
                          }))}
                        />
                      </Card>
                      <Space direction="vertical" size="middle" className="full-width">
                        <Card title="订单与客户">
                          <Descriptions column={1} size="small">
                            <Descriptions.Item label="客户">{flow.order.customer_name}</Descriptions.Item>
                            <Descriptions.Item label="工厂">{flow.order.plant_name}</Descriptions.Item>
                            <Descriptions.Item label="交付日">{flow.order.promised_delivery_date}</Descriptions.Item>
                            <Descriptions.Item label="状态">{flow.order.status}</Descriptions.Item>
                          </Descriptions>
                        </Card>
                        <Card title="流程单据统计">
                          <Row gutter={[12, 12]}>
                            {[
                              ["采购单", flow.purchases.length],
                              ["质检", flow.quality.length],
                              ["发货", flow.shipments.length],
                              ["发票", flow.invoices.length],
                              ["回款", flow.payments.length],
                              ["任务", flow.tasks.length]
                            ].map(([title, value]) => <Col span={12} key={String(title)}><Statistic title={title} value={value} /></Col>)}
                          </Row>
                        </Card>
                      </Space>
                    </div>
                  )
                }
              ]}
            />
          </>
        )}
      </QueryState>
    </>
  );
}

export function ShortagesPage() {
  const { asOfDate } = useAppContext();
  const [orderCode, setOrderCode] = useState("");
  const shortages = useQuery({
    queryKey: ["shortages", asOfDate, orderCode],
    queryFn: () => getApi<any>(`/api/v1/materials/shortages?as_of_date=${asOfDate}${orderCode ? `&order_code=${orderCode}` : ""}`)
  });
  const anomalies = useQuery({
    queryKey: ["price-anomalies", asOfDate],
    queryFn: () => getApi<any>(`/api/v1/procurement/price-anomalies?as_of_date=${asOfDate}`)
  });
  const rows = shortages.data?.data.items || [];
  return (
    <>
      <PageTitle title="缺料与采购预警" subtitle="追踪短缺物料、补齐日期、采购迟交和价格异常" extra={<SourceButton meta={shortages.data?.meta} />} />
      <div className="metric-grid">
        <MetricCard title="缺料总项" value={shortages.data?.data.count || 0} suffix="项" tone="red" />
        <MetricCard title="关键物料缺料" value={rows.filter((row: any) => row.is_critical).length} suffix="项" tone="red" />
        <MetricCard title="价格异常" value={anomalies.data?.data.count || 0} suffix="项" tone="orange" />
      </div>
      <Tabs
        items={[
          {
            key: "shortage",
            label: "缺料清单",
            children: (
              <Card>
                <div className="toolbar">
                  <Input
                    value={orderCode}
                    onChange={event => setOrderCode(event.target.value)}
                    placeholder="按订单编号筛选，如 销售-20260718-01"
                    allowClear
                    style={{ maxWidth: 320 }}
                  />
                </div>
                <QueryState loading={shortages.isLoading} error={shortages.error} empty={!rows.length}>
                  <Table
                    className="desktop-table"
                    rowKey={row => `${row.sales_order_code}-${row.material_code}`}
                    dataSource={rows}
                    pagination={{ pageSize: 12 }}
                    columns={[
                      { title: "影响订单", dataIndex: "sales_order_code", render: value => <Typography.Link href={`/orders/${value}`}>{value}</Typography.Link> },
                      { title: "物料", dataIndex: "material_code", render: (value, row: any) => <div><strong>{value}</strong><br /><Typography.Text type="secondary">{row.material_name}</Typography.Text></div> },
                      { title: "短缺数量", dataIndex: "shortage_qty", sorter: (a: any, b: any) => a.shortage_qty - b.shortage_qty, render: (value, row: any) => <Typography.Text type="danger" strong>{formatQuantity(value, row.unit)} {row.unit}</Typography.Text> },
                      { title: "需求日期", dataIndex: "required_date" },
                      { title: "预计补齐", dataIndex: "expected_recovery_date", render: value => value || <Tag color="red">尚未确认</Tag> },
                      { title: "关联采购单", dataIndex: "purchase_orders", render: (values: string[]) => values?.map(value => <Tag key={value}>{value}</Tag>) },
                      { title: "关键物料", dataIndex: "is_critical", render: value => <Tag color={value ? "red" : "default"}>{value ? "是" : "否"}</Tag> }
                    ]}
                  />
                </QueryState>
              </Card>
            )
          },
          {
            key: "price",
            label: `价格异常（${anomalies.data?.data.count || 0}）`,
            children: (
              <Card extra={<SourceButton meta={anomalies.data?.meta} />}>
                <QueryState loading={anomalies.isLoading} error={anomalies.error}>
                  <Table
                    className="desktop-table"
                    rowKey="material_code"
                    dataSource={anomalies.data?.data.items || []}
                    pagination={{ pageSize: 12 }}
                    columns={[
                      { title: "物料", dataIndex: "material_code", render: (value, row: any) => <div><strong>{value}</strong><br /><Typography.Text type="secondary">{row.material_name}</Typography.Text></div> },
                      { title: "最新价格", dataIndex: "latest_price", align: "right", render: value => formatMoney(value) },
                      { title: "环比", dataIndex: "month_over_month_rate", render: value => formatPercent(value) },
                      { title: "同比", dataIndex: "year_over_year_rate", render: value => <Typography.Text type={Math.abs(value) >= .1 ? "danger" : undefined}>{formatPercent(value)}</Typography.Text> },
                      { title: "市场偏差", dataIndex: "market_deviation_rate", render: value => formatPercent(value) },
                      { title: "异常原因", dataIndex: "triggers", render: (values: string[]) => values.map(value => <Tag color="orange" key={value}>{value}</Tag>) },
                      { title: "等级", dataIndex: "severity", render: value => <Tag color={riskColor(value)}>{value}</Tag> }
                    ]}
                  />
                </QueryState>
              </Card>
            )
          }
        ]}
      />
    </>
  );
}
