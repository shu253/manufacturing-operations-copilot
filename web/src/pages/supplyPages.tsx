import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import ReactECharts from "echarts-for-react";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Drawer,
  Form,
  Input,
  InputNumber,
  Select,
  Slider,
  Space,
  Table,
  Tag,
  Typography,
  message
} from "antd";
import { CalculatorOutlined, ExperimentOutlined, SearchOutlined, SwapOutlined } from "@ant-design/icons";
import { getApi, postApi } from "../api";
import { useAppContext } from "../appContext";
import { MetricCard, PageTitle, QueryState, RiskTag, SourceButton } from "../components";
import { formatCostQuantity, formatMoney, formatNumber, formatPercent, formatQuantity } from "../format";
import { quoteMarginPolicy } from "../quotePolicy";

const quoteCostColors: Record<string, string> = {
  material: "#1677ff",
  labor: "#13c2c2",
  outsource: "#722ed1",
  overhead: "#fa8c16",
  logistics: "#52c41a",
  urgency: "#f5222d",
  gross_profit: "#2f9e44"
};

const priceSourceLabels: Record<string, string> = {
  material_price_history: "月度平均采购价",
  "materials.standard_price": "物料标准价回退",
  scenario_override: "情景模拟价格"
};

function quoteInputSignature(values: any) {
  return JSON.stringify({
    product_code: values?.product_code || "",
    quantity: Number(values?.quantity || 0),
    target_margin: Number(values?.target_margin || 0),
    urgency: Number(values?.urgency || 0)
  });
}

export function SuppliersPage() {
  const { asOfDate } = useAppContext();
  const [sortBy, setSortBy] = useState("total");
  const [selected, setSelected] = useState<string>();
  const [recommendParams, setRecommendParams] = useState<{ material: string; quantity: number; date: string }>();
  const rankings = useQuery({
    queryKey: ["supplier-rankings", asOfDate, sortBy],
    queryFn: () => getApi<any>(`/api/v1/suppliers/rankings?sort_by=${sortBy}&order=desc&limit=50&as_of_date=${asOfDate}`)
  });
  const profile = useQuery({
    queryKey: ["supplier-profile", selected, asOfDate],
    queryFn: () => getApi<any>(`/api/v1/suppliers/${selected}?period=12&as_of_date=${asOfDate}`),
    enabled: Boolean(selected)
  });
  const recommendations = useQuery({
    queryKey: ["supplier-recommendations", recommendParams, asOfDate],
    queryFn: () => getApi<any>(
      `/api/v1/suppliers/recommendations?material_code=${recommendParams!.material}&quantity=${recommendParams!.quantity}&need_by_date=${recommendParams!.date}&as_of_date=${asOfDate}`
    ),
    enabled: Boolean(recommendParams)
  });
  return (
    <>
      <PageTitle title="供应商画像与推荐" subtitle="从价格、交付、质量、响应和稳定性综合评价供应商" extra={<SourceButton meta={rankings.data?.meta} />} />
      <div className="two-column">
        <Card title="供应商排行榜" extra={
          <Select
            value={sortBy}
            onChange={setSortBy}
            options={[
              ["total", "综合评分"], ["price", "价格竞争力"], ["delivery", "准时交付"],
              ["quality", "质量表现"], ["response", "响应速度"], ["stability", "合作稳定性"]
            ].map(([value, label]) => ({ value, label }))}
            style={{ width: 140 }}
          />
        }>
          <QueryState loading={rankings.isLoading} error={rankings.error}>
            <Table
              className="desktop-table"
              rowKey="supplier_code"
              size="middle"
              dataSource={rankings.data?.data.items || []}
              pagination={{ pageSize: 10 }}
              onRow={(row: any) => ({ onClick: () => setSelected(row.supplier_code), style: { cursor: "pointer" } })}
              columns={[
                { title: "排名", dataIndex: "rank", width: 70, render: value => value <= 3 ? <Tag color={value === 1 ? "gold" : "blue"}>TOP {value}</Tag> : value },
                { title: "供应商", dataIndex: "supplier_code", render: (value, row: any) => <div><Typography.Link>{value}</Typography.Link><br /><Typography.Text type="secondary">{row.supplier_name}</Typography.Text></div> },
                { title: "综合分", dataIndex: "total_score", sorter: (a: any, b: any) => a.total_score - b.total_score, render: value => <Typography.Text strong>{value}</Typography.Text> },
                { title: "等级", dataIndex: "grade", render: value => <Tag color={value === "A" ? "green" : value === "B" ? "blue" : "orange"}>{value}</Tag> },
                { title: "基础风险", dataIndex: "risk_level", render: value => <RiskTag level={value} /> }
              ]}
            />
          </QueryState>
        </Card>
        <Card title="替代供应商推荐">
          <Form
            layout="vertical"
            initialValues={{ material: "物料-0001", quantity: 450, date: "2026-08-08" }}
            onFinish={setRecommendParams}
          >
            <Form.Item name="material" label="目标物料" rules={[{ required: true }]}><Input /></Form.Item>
            <Form.Item name="quantity" label="采购数量" rules={[{ required: true }]}><InputNumber min={1} className="full-width" /></Form.Item>
            <Form.Item name="date" label="需求日期" rules={[{ required: true }]}><Input type="date" /></Form.Item>
            <Button type="primary" htmlType="submit" icon={<SearchOutlined />} block>推荐供应商</Button>
          </Form>
          <QueryState loading={recommendations.isFetching} error={recommendations.error}>
            {(recommendations.data?.data.items || []).map((item: any) => (
              <Card key={item.supplier_code} size="small" style={{ marginTop: 12 }} hoverable onClick={() => setSelected(item.supplier_code)}>
                <Space className="full-width" style={{ justifyContent: "space-between" }}>
                  <div><Tag color="blue">第{item.rank}名</Tag><strong>{item.supplier_name}</strong><br /><Typography.Text type="secondary">{item.supplier_code} · 预计{item.expected_arrival_date}到货</Typography.Text></div>
                  <Typography.Title level={4} style={{ margin: 0 }}>{item.recommendation_score}</Typography.Title>
                </Space>
                <div style={{ marginTop: 8 }}>{item.advantages.map((value: string) => <Tag color="green" key={value}>{value}</Tag>)}{item.risks.map((value: string) => <Tag color="orange" key={value}>{value}</Tag>)}</div>
              </Card>
            ))}
          </QueryState>
        </Card>
      </div>
      <Drawer width={640} title={`供应商画像 · ${selected || ""}`} open={Boolean(selected)} onClose={() => setSelected(undefined)}>
        <QueryState loading={profile.isLoading} error={profile.error}>
          {profile.data && (
            <>
              <Descriptions bordered column={1} size="small">
                <Descriptions.Item label="供应商">{profile.data.data.profile.supplier_name}</Descriptions.Item>
                <Descriptions.Item label="城市">{profile.data.data.profile.city}</Descriptions.Item>
                <Descriptions.Item label="基础风险"><RiskTag level={profile.data.data.profile.risk_level} /></Descriptions.Item>
                <Descriptions.Item label="统计周期">近{profile.data.data.metrics.period_months}个月</Descriptions.Item>
                <Descriptions.Item label="准时交付率">{formatPercent(profile.data.data.metrics.on_time_delivery_rate)}</Descriptions.Item>
                <Descriptions.Item label="质量合格率">{formatPercent(profile.data.data.metrics.quality_acceptance_rate)}</Descriptions.Item>
              </Descriptions>
              <Card title="五维评分" style={{ marginTop: 16 }} extra={<SourceButton meta={profile.data.meta} />}>
                <ReactECharts
                  className="chart"
                  option={{
                    radar: { indicator: ["价格", "交付", "质量", "响应", "稳定"].map(name => ({ name, max: 100 })) },
                    series: [{ type: "radar", data: [{ value: [
                      profile.data.data.metrics.scores.price,
                      profile.data.data.metrics.scores.delivery,
                      profile.data.data.metrics.scores.quality,
                      profile.data.data.metrics.scores.response,
                      profile.data.data.metrics.scores.stability
                    ], areaStyle: { opacity: .25 }, name: "供应商评分" }] }]
                  }}
                />
              </Card>
            </>
          )}
        </QueryState>
      </Drawer>
    </>
  );
}

export function CostPage() {
  const { asOfDate } = useAppContext();
  const [orderCode, setOrderCode] = useState("销售-20260718-01");
  const [activeOrder, setActiveOrder] = useState("销售-20260718-01");
  const query = useQuery({
    queryKey: ["order-cost", activeOrder, asOfDate],
    queryFn: () => getApi<any>(`/api/v1/orders/${activeOrder}/cost?as_of_date=${asOfDate}`)
  });
  const data = query.data?.data;
  const componentOption = data ? {
    tooltip: { trigger: "item", formatter: "{b}: ¥{c}（{d}%）" },
    legend: { bottom: 0 },
    series: [{
      type: "pie", radius: ["45%", "72%"], center: ["50%", "44%"],
      data: [
        ["材料", data.components.material], ["人工", data.components.labor],
        ["外协", data.components.outsource], ["制造费用", data.components.overhead],
        ["包装物流", data.components.logistics]
      ].map(([name, value]) => ({ name, value })),
      label: { formatter: "{b}\n{d}%" }
    }]
  } : {};
  return (
    <>
      <PageTitle title="成本穿透" subtitle="从订单总成本穿透至产品、成本组件和BOM物料明细" extra={<SourceButton meta={query.data?.meta} />} />
      <Card style={{ marginBottom: 16 }}>
        <Space.Compact style={{ width: "100%", maxWidth: 520 }}>
          <Input value={orderCode} onChange={event => setOrderCode(event.target.value)} placeholder="输入销售订单编号" />
          <Button type="primary" icon={<CalculatorOutlined />} onClick={() => setActiveOrder(orderCode)}>计算成本</Button>
        </Space.Compact>
      </Card>
      <QueryState loading={query.isLoading} error={query.error} onRetry={() => query.refetch()}>
        {data && (
          <>
            <div className="metric-grid">
              <MetricCard title="订单收入" value={formatMoney(data.sales_revenue, true)} />
              <MetricCard title="完整成本" value={formatMoney(data.components.total, true)} tone="orange" />
              <MetricCard title="毛利额" value={formatMoney(data.gross_profit, true)} tone={data.low_margin_warning ? "orange" : "green"} />
              <MetricCard title="毛利率" value={formatPercent(data.gross_margin_rate)} tone={data.low_margin_warning ? "red" : "green"} />
              <MetricCard title="BOM物料" value={data.material_details.length} suffix="项" />
            </div>
            <div className="content-grid">
              <Card title="成本构成"><ReactECharts option={componentOption} className="chart" /></Card>
              <Card title="成本平衡校验">
                <Descriptions column={1} bordered size="small">
                  <Descriptions.Item label="材料成本">{formatMoney(data.components.material)}</Descriptions.Item>
                  <Descriptions.Item label="人工成本">{formatMoney(data.components.labor)}</Descriptions.Item>
                  <Descriptions.Item label="外协成本">{formatMoney(data.components.outsource)}</Descriptions.Item>
                  <Descriptions.Item label="制造费用">{formatMoney(data.components.overhead)}</Descriptions.Item>
                  <Descriptions.Item label="包装物流">{formatMoney(data.components.logistics)}</Descriptions.Item>
                  <Descriptions.Item label="汇总成本"><strong>{formatMoney(data.components.total)}</strong></Descriptions.Item>
                </Descriptions>
                {data.low_margin_warning && <Alert style={{ marginTop: 14 }} type="warning" showIcon message="订单已进入低毛利预警区间" />}
              </Card>
            </div>
            <Card title="BOM材料成本明细">
              <Alert
                showIcon
                type="info"
                style={{ marginBottom: 16 }}
                message="成本数量口径"
                description="明细数量是按BOM用量、损耗率和订单数量计算的标准成本耗用量。件、套等离散单位出现小数时，不代表实际收发数量。"
              />
              <Table
                className="desktop-table"
                rowKey="material_code"
                dataSource={data.material_details}
                pagination={{ pageSize: 12 }}
                columns={[
                  { title: "物料编码", dataIndex: "material_code" },
                  { title: "物料名称", dataIndex: "material_name" },
                  { title: "标准成本耗用量", dataIndex: "quantity", align: "right", render: (value, row: any) => formatCostQuantity(value, row.unit) },
                  { title: "当前单价", dataIndex: "unit_price", align: "right", render: formatMoney },
                  { title: "材料金额", dataIndex: "amount", align: "right", sorter: (a: any, b: any) => a.amount - b.amount, render: formatMoney },
                  { title: "关键物料", dataIndex: "is_critical", render: value => <Tag color={value ? "red" : "default"}>{value ? "是" : "否"}</Tag> }
                ]}
              />
            </Card>
          </>
        )}
      </QueryState>
    </>
  );
}

export function QuotePage() {
  const { asOfDate } = useAppContext();
  const [form] = Form.useForm();
  const [submittedSignature, setSubmittedSignature] = useState("");
  const products = useQuery({
    queryKey: ["products"],
    queryFn: () => getApi<any>("/api/v1/products")
  });
  const selectedProductCode = Form.useWatch("product_code", form);
  const selectedQuantity = Form.useWatch("quantity", form);
  const selectedTargetMargin = Form.useWatch("target_margin", form);
  const selectedUrgency = Form.useWatch("urgency", form);
  const selectedProduct = (products.data?.data.items || []).find(
    (item: any) => item.product_code === selectedProductCode
  );
  const quote = useMutation({
    mutationFn: (values: any) => postApi<any>("/api/v1/quotes/calculate", {
      product_code: values.product_code,
      quantity: values.quantity,
      target_margin: values.target_margin / 100,
      options: { urgency_surcharge_rate: values.urgency / 100 },
      as_of_date: asOfDate
    }),
    onSuccess: (_result, values) => setSubmittedSignature(quoteInputSignature(values)),
    onError: error => message.error(error.message)
  });
  const data = quote.data?.data;
  const currentSignature = quoteInputSignature({
    product_code: selectedProductCode,
    quantity: selectedQuantity,
    target_margin: selectedTargetMargin,
    urgency: selectedUrgency
  });
  const resultIsStale = Boolean(
    data && submittedSignature && submittedSignature !== currentSignature
  );
  const costBreakdownOption = useMemo(() => data ? ({
    tooltip: {
      trigger: "item",
      formatter: (params: any) => `${params.name}<br/>${formatMoney(params.value)}（${params.percent}%）`
    },
    legend: { show: false },
    color: data.cost_breakdown.map((item: any) => quoteCostColors[item.code]),
    series: [{
      type: "pie",
      radius: ["48%", "73%"],
      center: ["50%", "48%"],
      data: data.cost_breakdown.map((item: any) => ({
        name: item.label,
        value: item.amount,
        itemStyle: { color: quoteCostColors[item.code] }
      })),
      label: { formatter: "{b}\n{d}%" },
      labelLine: { length: 12, length2: 8 }
    }]
  }) : {}, [data]);
  const quoteCompositionOption = useMemo(() => data ? ({
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (params: any[]) => params
        .filter(item => item.value > 0)
        .map(item => `${item.marker}${item.seriesName}：${formatMoney(item.value)}`)
        .join("<br/>")
    },
    grid: { left: 12, right: 12, top: 32, bottom: 30, containLabel: true },
    xAxis: {
      type: "value",
      axisLabel: { formatter: (value: number) => `${(value / 10000).toFixed(0)}万` }
    },
    yAxis: { type: "category", data: ["本次目标报价"] },
    series: data.quote_composition.map((item: any) => ({
      name: item.label,
      type: "bar",
      stack: "quote",
      data: [item.amount],
      itemStyle: { color: quoteCostColors[item.code] },
      emphasis: { focus: "series" }
    }))
  }) : {}, [data]);
  const sortedMaterialDetails = useMemo(
    () => data ? [...data.material_details].sort((a: any, b: any) => b.amount - a.amount) : [],
    [data]
  );
  return (
    <>
      <PageTitle
        title="报价建议"
        subtitle="输入客户本次需求，系统先计算完整成本，再按目标毛利率倒推出对客报价"
        extra={<SourceButton meta={quote.data?.meta} />}
      />
      <Alert
        className="quote-intro"
        type="info"
        showIcon
        message="这页解决什么问题？"
        description="销售输入产品、客户需要的数量和目标毛利，系统自动计算绝对保本价和目标毛利测算价，并与历史相似报价比较。页面金额均为本次数量的整单金额，单套价格会单独标注。"
      />
      <div className="quote-steps">
        <div><span>1</span><strong>明确客户需求</strong><small>选择产品和本次采购数量</small></div>
        <div><span>2</span><strong>重算完整成本</strong><small>BOM材料、人工、外协和制造费用</small></div>
        <div><span>3</span><strong>倒推建议报价</strong><small>报价＝完整成本 ÷（1－目标毛利率）</small></div>
      </div>
      <div className="quote-layout">
        <Card title="第一步：填写本次报价条件">
          <Form form={form} layout="vertical" initialValues={{ product_code: "产品-001", quantity: 3, target_margin: quoteMarginPolicy.defaultValue, urgency: 0 }} onFinish={values => quote.mutate(values)}>
            <Form.Item
              name="product_code"
              label="给客户报哪一种产品？"
              extra="选择产品后，系统会读取该产品当前有效的BOM和标准制造成本。"
              rules={[{ required: true, message: "请选择产品" }]}
            >
              <Select
                showSearch
                loading={products.isLoading}
                optionFilterProp="label"
                placeholder="选择产品"
                options={(products.data?.data.items || []).map((item: any) => ({
                  value: item.product_code,
                  label: `${item.product_name}（${item.product_code}）`
                }))}
              />
            </Form.Item>
            <Form.Item
              name="quantity"
              label="客户本次需要多少？"
              extra={`这是本次报价覆盖的成品数量。右侧总价按该数量计算，不是单价。`}
              rules={[{ required: true, message: "请输入报价数量" }]}
            >
              <InputNumber min={1} precision={0} addonAfter={selectedProduct?.unit || "套"} className="full-width" />
            </Form.Item>
            <Form.Item
              name="target_margin"
              label="期望这笔订单达到多少毛利率？"
              extra="毛利率＝（报价－完整成本）÷报价，不等于在成本上直接加价。0%–60%仅是测算范围，不代表行业标准或企业审批政策。"
              rules={[{ required: true }]}
            >
              <Slider
                min={quoteMarginPolicy.min}
                max={quoteMarginPolicy.max}
                step={1}
                tooltip={{ formatter: value => `${value}%` }}
                marks={quoteMarginPolicy.marks}
              />
            </Form.Item>
            <div className="margin-presets">
              <Typography.Text type="secondary">快速选择：</Typography.Text>
              {quoteMarginPolicy.presets.map(value => (
                <Button key={value} size="small" onClick={() => form.setFieldValue("target_margin", value)}>{value}%</Button>
              ))}
            </div>
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 18 }}
              message="25%只是演示初始值"
              description="当前没有客户正式的最低毛利制度，页面中的比例仅用于测算，不构成企业审批规则。"
            />
            <Form.Item
              name="urgency"
              label="是否存在加急或特殊交付成本？"
              extra="如夜班赶工、特殊包装、紧急运输预计增加成本，请填写增幅；正常交付保持0%。"
            >
              <InputNumber min={0} max={20} precision={1} addonAfter="%" className="full-width" />
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={quote.isPending} icon={<CalculatorOutlined />} block>生成报价建议</Button>
          </Form>
        </Card>
        <QueryState loading={quote.isPending} error={quote.error}>
          {data ? (
            <Card title="第二步：查看报价测算" extra={<Tag color="blue">{data.product_name || data.product_code}</Tag>}>
              {resultIsStale && (
                <Alert
                  style={{ marginBottom: 14 }}
                  type="warning"
                  showIcon
                  message="报价条件已修改，请重新生成"
                  description="下方价格和成本依据仍对应上一次测算，重新生成后才会同步更新。"
                />
              )}
              <div className="cost-total quote-total">
                <Typography.Text type="secondary">目标毛利测算总额（{formatNumber(data.quantity)}{data.unit || "套"}）</Typography.Text>
                <Typography.Title level={2}>{formatMoney(data.target_price)}</Typography.Title>
                <Typography.Text strong>折合单{data.unit || "套"} {formatMoney(data.target_unit_price)}</Typography.Text>
                <Typography.Text type="secondary">按输入的目标毛利率 {formatPercent(data.target_margin_rate)} 测算</Typography.Text>
              </div>
              <div className="quote-price-levels">
                <div className="quote-level quote-level-danger">
                  <small>绝对保本价</small>
                  <strong>{formatMoney(data.break_even_price)}</strong>
                  <span>毛利0%，低于此价即亏损</span>
                </div>
                <div className="quote-level quote-level-primary">
                  <small>目标测算价</small>
                  <strong>{formatMoney(data.target_price)}</strong>
                  <span>对应本次输入毛利{formatPercent(data.target_margin_rate)}</span>
                </div>
                <div className="quote-level quote-level-warning">
                  <small>历史参考</small>
                  <strong>{data.historical_reference ? `${data.historical_reference.count}条相似报价` : "暂无历史数据"}</strong>
                  <span>
                    {data.historical_reference
                      ? `整单${data.historical_reference.range_method}：${formatMoney(data.historical_reference.total_price_low)}–${formatMoney(data.historical_reference.total_price_high)}`
                      : "未生成参考区间，不补造数字"}
                  </span>
                </div>
              </div>
              <Descriptions column={1} bordered size="small" style={{ marginTop: 16 }}>
                <Descriptions.Item label="基础完整成本">{formatMoney(data.base_cost ?? data.estimated_cost)}</Descriptions.Item>
                <Descriptions.Item label="特殊交付增加成本">{formatMoney(data.urgency_cost || 0)}（{formatPercent(data.urgency_surcharge_rate || 0)}）</Descriptions.Item>
                <Descriptions.Item label="报价采用的完整成本">{formatMoney(data.estimated_cost)}</Descriptions.Item>
                <Descriptions.Item label="目标毛利额">{formatMoney(data.target_gross_profit)}</Descriptions.Item>
                {data.historical_reference && (
                  <>
                    <Descriptions.Item label={`历史样本单${data.unit || "套"}价格`}>
                      {formatMoney(data.historical_reference.unit_price_low)} — {formatMoney(data.historical_reference.unit_price_high)}
                      （{data.historical_reference.range_method}，中位数{formatMoney(data.historical_reference.unit_price_median)}）
                    </Descriptions.Item>
                    <Descriptions.Item label="历史毛利分布">
                      最低{formatPercent(data.historical_reference.margin_min)}，中位数{formatPercent(data.historical_reference.margin_median)}，最高{formatPercent(data.historical_reference.margin_max)}
                    </Descriptions.Item>
                  </>
                )}
              </Descriptions>
              {!data.historical_reference && (
                <Alert
                  style={{ marginTop: 14 }}
                  type="warning"
                  showIcon
                  message="暂无相同产品、相近数量的历史报价"
                  description="系统未生成历史价格区间，请结合客户预算、竞争情况和企业报价制度人工判断。"
                />
              )}
              <Alert
                style={{ marginTop: 14 }}
                type="success"
                showIcon
                message="这些价格怎么用？"
                description="保本价只表示不亏损的理论底线；目标测算价由本次输入毛利率倒推；历史样本区间只用于比较，不代表行业标准或企业审批结论。"
              />
              <Alert style={{ marginTop: 10 }} type="info" showIcon message="计算依据" description={data.adjustment_reasons.join("；")} />
              <Typography.Paragraph type="secondary" style={{ margin: "12px 0 0" }}>
                真实项目应由客户配置毛利政策、审批红线、税率、付款条件、质保和风险溢价。当前历史样本数据仅用于Demo展示。
              </Typography.Paragraph>
            </Card>
          ) : (
            <Card title="第二步：查看报价测算" className="quote-empty-card">
              <Typography.Title level={4}>填写左侧条件后生成报价</Typography.Title>
              <Typography.Paragraph type="secondary">
                系统会清楚区分整单总价和单{selectedProduct?.unit || "套"}价格，并给出绝对保本价、目标毛利测算价和历史参考区间。
              </Typography.Paragraph>
              <Descriptions column={1} size="small">
                <Descriptions.Item label="当前产品">{selectedProduct?.product_name || "请选择产品"}</Descriptions.Item>
                <Descriptions.Item label="本次数量">{selectedQuantity || 0}{selectedProduct?.unit || "套"}</Descriptions.Item>
                <Descriptions.Item label="演示初始毛利">25%（不代表行业标准）</Descriptions.Item>
              </Descriptions>
            </Card>
          )}
        </QueryState>
      </div>
      {data && (
        <section className="quote-cost-evidence">
          <Card
            title="第三步：核对成本与报价依据"
            extra={
              <Space wrap>
                <Tag color="blue">{data.product_name}</Tag>
                <Tag>{formatNumber(data.quantity)}{data.unit}</Tag>
                <Tag color={resultIsStale ? "orange" : "green"}>
                  {resultIsStale ? "等待重新测算" : "与当前报价一致"}
                </Tag>
              </Space>
            }
          >
            {resultIsStale && (
              <Alert
                style={{ marginBottom: 16 }}
                type="warning"
                showIcon
                message="当前展示的是上一次生成的成本快照"
                description="产品、数量、目标毛利率或特殊交付成本已发生变化，请点击“生成报价建议”刷新全部图表和明细。"
              />
            )}
            {quote.data?.meta.warnings?.map((warning: string, index: number) => (
              <Alert
                key={`${warning}-${index}`}
                style={{ marginBottom: 12 }}
                type="warning"
                showIcon
                message={warning}
              />
            ))}
            <div className="quote-evidence-charts">
              <Card size="small" title="整单成本构成" data-testid="quote-cost-breakdown">
                <Typography.Paragraph type="secondary">
                  以下金额对应本次{formatNumber(data.quantity)}{data.unit}报价数量，不是单{data.unit}成本。
                </Typography.Paragraph>
                <ReactECharts option={costBreakdownOption} className="quote-evidence-chart" />
                <div className="quote-chart-legend">
                  {data.cost_breakdown.map((item: any) => (
                    <div key={item.code}>
                      <i style={{ background: quoteCostColors[item.code] }} />
                      <span>{item.label}</span>
                      <strong>{formatMoney(item.amount)}</strong>
                      <small>{formatPercent(item.share_of_base_cost)}</small>
                    </div>
                  ))}
                </div>
                <div className="quote-balance-line">
                  <span>五类成本合计</span>
                  <strong>{formatMoney(data.reconciliation.component_total)}</strong>
                  <Tag color={data.reconciliation.base_cost_difference === 0 ? "green" : "red"}>
                    差异{formatMoney(data.reconciliation.base_cost_difference)}
                  </Tag>
                </div>
              </Card>
              <Card size="small" title="目标报价组成">
                <Typography.Paragraph type="secondary">
                  展示完整成本、特殊交付增加成本和目标毛利如何形成最终报价。
                </Typography.Paragraph>
                <ReactECharts option={quoteCompositionOption} className="quote-evidence-chart" />
                <div className="quote-chart-legend quote-composition-legend">
                  {data.quote_composition.map((item: any) => (
                    <div key={item.code}>
                      <i style={{ background: quoteCostColors[item.code] }} />
                      <span>{item.label}</span>
                      <strong>{formatMoney(item.amount)}</strong>
                      <small>{formatPercent(item.share_of_target_price)}</small>
                    </div>
                  ))}
                </div>
                <div className="quote-formula">
                  <span>{formatMoney(data.estimated_cost)} 完整成本</span>
                  <b>＋</b>
                  <span>{formatMoney(data.target_gross_profit)} 目标毛利</span>
                  <b>＝</b>
                  <strong>{formatMoney(data.target_price)} 目标报价</strong>
                </div>
                <div className="quote-balance-line">
                  <span>报价组成合计</span>
                  <strong>{formatMoney(data.reconciliation.quote_component_total)}</strong>
                  <Tag color={data.reconciliation.target_price_difference === 0 ? "green" : "red"}>
                    差异{formatMoney(data.reconciliation.target_price_difference)}
                  </Tag>
                </div>
              </Card>
            </div>
            <Card size="small" title="本次成本计算口径" className="quote-basis-card">
              <Descriptions bordered size="small" column={{ xs: 1, sm: 2, lg: 3 }}>
                <Descriptions.Item label="产品">{data.product_name}（{data.product_code}）</Descriptions.Item>
                <Descriptions.Item label="报价数量">{formatNumber(data.quantity)}{data.unit}</Descriptions.Item>
                <Descriptions.Item label="价格基准日期">{data.cost_basis.price_as_of_date}</Descriptions.Item>
                <Descriptions.Item label="BOM版本">{data.cost_basis.bom_version}</Descriptions.Item>
                <Descriptions.Item label="BOM生效日期">{data.cost_basis.bom_effective_from}</Descriptions.Item>
                <Descriptions.Item label="BOM失效日期">{data.cost_basis.bom_effective_to || "长期有效"}</Descriptions.Item>
                <Descriptions.Item label={`单${data.unit}标准工时`}>{formatQuantity(data.cost_basis.standard_labor_hours)}小时</Descriptions.Item>
                <Descriptions.Item label="人工费率">{formatMoney(data.cost_basis.labor_rate)}/小时</Descriptions.Item>
                <Descriptions.Item label={`单${data.unit}标准外协成本`}>{formatMoney(data.cost_basis.standard_outsource_cost)}</Descriptions.Item>
                <Descriptions.Item label="制造费用率">{formatPercent(data.cost_basis.standard_overhead_rate)}</Descriptions.Item>
                <Descriptions.Item label="包装物流费率">{formatPercent(data.cost_basis.logistics_rate)}</Descriptions.Item>
                <Descriptions.Item label="公式版本">{quote.data?.meta.formula_version || "—"}</Descriptions.Item>
                <Descriptions.Item label="计算编号" span={3}>{quote.data?.meta.calculation_id || "—"}</Descriptions.Item>
              </Descriptions>
            </Card>
            <Card
              size="small"
              title={`BOM物料成本明细（共${sortedMaterialDetails.length}项）`}
              className="quote-material-card"
            >
              <Table
                className="desktop-table quote-material-table"
                rowKey="material_code"
                dataSource={sortedMaterialDetails}
                pagination={{ pageSize: 10, showSizeChanger: false }}
                rowClassName={(row: any) => row.is_critical ? "quote-critical-material" : ""}
                scroll={{ x: 1040 }}
                columns={[
                  {
                    title: "物料",
                    key: "material",
                    width: 230,
                    render: (_value, row: any) => (
                      <div>
                        <Typography.Text strong>{row.material_code}</Typography.Text>
                        <br />
                        <Typography.Text type="secondary">{row.material_name}</Typography.Text>
                      </div>
                    )
                  },
                  {
                    title: "用量",
                    dataIndex: "quantity",
                    width: 130,
                    align: "right",
                    render: (value, row: any) => formatCostQuantity(value, row.unit)
                  },
                  { title: "当前单价", dataIndex: "unit_price", width: 130, align: "right", render: formatMoney },
                  { title: "物料金额", dataIndex: "amount", width: 140, align: "right", render: (value: number) => <Typography.Text strong>{formatMoney(value)}</Typography.Text> },
                  { title: "占材料成本", dataIndex: "material_cost_share", width: 120, align: "right", render: (value: number) => formatPercent(value) },
                  {
                    title: "价格依据",
                    key: "price_source",
                    width: 190,
                    render: (_value, row: any) => (
                      <div>
                        <Tag color={row.price_source === "material_price_history" ? "blue" : "orange"}>
                          {priceSourceLabels[row.price_source] || row.price_source}
                        </Tag>
                        <br />
                        <Typography.Text type="secondary">{row.price_reference_date || "无历史价格月份"}</Typography.Text>
                      </div>
                    )
                  },
                  {
                    title: "关键物料",
                    dataIndex: "is_critical",
                    width: 100,
                    render: value => <Tag color={value ? "red" : "default"}>{value ? "是" : "否"}</Tag>
                  }
                ]}
              />
            </Card>
          </Card>
        </section>
      )}
    </>
  );
}

const scenarioOptions = [
  { value: "material_price_change", label: "原材料价格涨跌" },
  { value: "supplier_switch", label: "供应商切换" },
  { value: "volume_discount", label: "采购量与批量折扣" },
  { value: "early_buy_lock", label: "提前采购与锁价" },
  { value: "exchange_rate_change", label: "汇率变化" },
  { value: "supplier_disruption", label: "供应商停供" },
  { value: "delivery_date_change", label: "订单交期调整" }
];

const scenarioFieldLabels: Record<string, string> = {
  scenario_type: "情景类型",
  sales_order_code: "销售订单编号",
  order_code: "销售订单编号",
  product_code: "产品编码",
  product_name: "产品名称",
  material_code: "物料编码",
  supplier_code: "供应商编码",
  disrupted_supplier_code: "停供供应商编码",
  currency: "币种",
  change_rate: "变化比例",
  discount_rate: "批量折扣率",
  lock_discount_rate: "锁价优惠率",
  original_cost: "原完整成本",
  new_cost: "模拟后完整成本",
  cost_change: "成本变化",
  cost_saving: "成本节省",
  price_saving: "锁价节省",
  holding_cost: "库存持有成本",
  net_benefit: "净收益",
  sales_revenue: "销售收入",
  gross_profit: "毛利额",
  gross_margin_rate: "原毛利率",
  original_margin_rate: "原毛利率",
  new_margin_rate: "模拟后毛利率",
  margin_change: "毛利率变化",
  low_margin_warning: "低毛利预警",
  balance_check: "成本平衡校验",
  lead_time_days: "供应商交货周期",
  old_delivery_date: "原交付日期",
  new_delivery_date: "调整后交付日期",
  shift_days: "交期调整天数",
  risk_direction: "风险变化方向"
};

const scenarioMoneyFields = new Set([
  "original_cost", "new_cost", "cost_change", "cost_saving", "price_saving",
  "holding_cost", "net_benefit", "sales_revenue", "gross_profit"
]);
const scenarioPercentFields = new Set([
  "change_rate", "discount_rate", "lock_discount_rate", "gross_margin_rate",
  "original_margin_rate", "new_margin_rate", "margin_change"
]);

function formatScenarioField(key: string, value: unknown) {
  if (key === "scenario_type") {
    return scenarioOptions.find(option => option.value === value)?.label || String(value);
  }
  if (scenarioMoneyFields.has(key)) return formatMoney(value);
  if (scenarioPercentFields.has(key)) return formatPercent(value);
  if (key === "lead_time_days" || key === "shift_days") return `${formatNumber(value)}天`;
  if (typeof value === "boolean") return value ? "是" : "否";
  return String(value);
}

function scenarioParameters(type: string, values: any) {
  const common = { order_code: values.order_code || "销售-20260718-01" };
  switch (type) {
    case "material_price_change": return { ...common, material_code: values.material_code, change_rate: values.change_rate / 100 };
    case "supplier_switch": return { ...common, material_code: values.material_code, supplier_code: values.supplier_code };
    case "volume_discount": return { ...common, discount_rate: values.discount_rate / 100 };
    case "early_buy_lock": return { ...common, lock_discount_rate: values.lock_discount_rate / 100, holding_cost_rate: values.holding_cost_rate / 100 };
    case "exchange_rate_change": return { ...common, currency: "USD", change_rate: values.change_rate / 100, import_material_share: values.import_share / 100 };
    case "supplier_disruption": return { material_code: values.material_code, supplier_code: values.supplier_code, quantity: values.quantity, need_by_date: values.need_by_date };
    case "delivery_date_change": return { ...common, new_delivery_date: values.new_delivery_date };
    default: return common;
  }
}

export function ScenarioPage() {
  const { asOfDate } = useAppContext();
  const [type, setType] = useState("material_price_change");
  const mutation = useMutation({
    mutationFn: (values: any) => postApi<any>("/api/v1/scenarios/run", {
      scenario_type: type,
      parameters: scenarioParameters(type, values),
      as_of_date: asOfDate
    }),
    onError: error => message.error(error.message)
  });
  const result = mutation.data?.data.result;
  return (
    <>
      <PageTitle title="采购与经营情景模拟" subtitle="比较不同决策对成本、毛利、交付、库存和供应风险的影响" extra={<SourceButton meta={mutation.data?.meta} />} />
      <div className="content-grid">
        <Card title="模拟参数">
          <Form
            key={type}
            layout="vertical"
            initialValues={{
              order_code: "销售-20260718-01", material_code: "物料-0001",
              supplier_code: "供应商-0004", change_rate: 8, discount_rate: 5,
              lock_discount_rate: 3, holding_cost_rate: 1, import_share: 30,
              quantity: 450, need_by_date: "2026-08-08", new_delivery_date: "2026-08-10"
            }}
            onFinish={values => mutation.mutate(values)}
          >
            <Form.Item label="情景类型">
              <Select value={type} onChange={setType} options={scenarioOptions} />
            </Form.Item>
            {!["supplier_disruption"].includes(type) && <Form.Item name="order_code" label="订单编号" rules={[{ required: true }]}><Input /></Form.Item>}
            {["material_price_change", "supplier_switch", "supplier_disruption"].includes(type) && <Form.Item name="material_code" label="物料编码" rules={[{ required: true }]}><Input /></Form.Item>}
            {["supplier_switch", "supplier_disruption"].includes(type) && <Form.Item name="supplier_code" label="供应商编码" rules={[{ required: true }]}><Input /></Form.Item>}
            {["material_price_change", "exchange_rate_change"].includes(type) && <Form.Item name="change_rate" label="变化比例（%）"><InputNumber className="full-width" /></Form.Item>}
            {type === "volume_discount" && <Form.Item name="discount_rate" label="批量折扣（%）"><InputNumber min={0.1} max={49} className="full-width" /></Form.Item>}
            {type === "early_buy_lock" && <>
              <Form.Item name="lock_discount_rate" label="锁价优惠（%）"><InputNumber className="full-width" /></Form.Item>
              <Form.Item name="holding_cost_rate" label="持有成本（%）"><InputNumber className="full-width" /></Form.Item>
            </>}
            {type === "exchange_rate_change" && <Form.Item name="import_share" label="进口物料占比（%）"><InputNumber min={0} max={100} className="full-width" /></Form.Item>}
            {type === "supplier_disruption" && <>
              <Form.Item name="quantity" label="需求数量"><InputNumber min={1} className="full-width" /></Form.Item>
              <Form.Item name="need_by_date" label="需求日期"><Input type="date" /></Form.Item>
            </>}
            {type === "delivery_date_change" && <Form.Item name="new_delivery_date" label="调整后交期"><Input type="date" /></Form.Item>}
            <Button type="primary" htmlType="submit" loading={mutation.isPending} icon={<ExperimentOutlined />} block>运行情景模拟</Button>
          </Form>
        </Card>
        <QueryState loading={mutation.isPending} error={mutation.error}>
          {result ? (
            <Card title="模拟结果" extra={<Tag color="blue">{scenarioOptions.find(item => item.value === type)?.label}</Tag>}>
              {result.cost_change !== undefined && (
                <div className="scenario-metric-grid">
                  <MetricCard title="成本变化" value={formatMoney(result.cost_change)} tone={result.cost_change > 0 ? "red" : "green"} />
                  <MetricCard title="新毛利率" value={formatPercent(result.new_margin_rate)} tone={result.new_margin_rate < .16 ? "red" : "green"} />
                </div>
              )}
              {result.original_margin_rate !== undefined && (
                <Alert
                  type={result.low_margin_warning ? "warning" : "success"}
                  showIcon
                  message={`毛利率由${formatPercent(result.original_margin_rate)}变化至${formatPercent(result.new_margin_rate)}`}
                  description={result.low_margin_warning ? "模拟方案进入低毛利预警，需要同步调整报价或采购策略。" : "模拟方案毛利仍处于安全区间。"}
                />
              )}
              {result.alternatives && <Alert type="info" showIcon message={`找到${result.alternatives.length}家替代供应商`} description={`影响订单${result.impacted_orders.length}张`} />}
              <Descriptions bordered column={1} size="small" style={{ marginTop: 16 }}>
                {Object.entries(result).filter(([, value]) => ["string", "number", "boolean"].includes(typeof value)).map(([key, value]) => (
                  <Descriptions.Item key={key} label={scenarioFieldLabels[key] || key}>
                    {formatScenarioField(key, value)}
                  </Descriptions.Item>
                ))}
              </Descriptions>
            </Card>
          ) : <Card><Typography.Text type="secondary">选择情景、设置参数并运行模拟，系统将对比基准和模拟方案。</Typography.Text></Card>}
        </QueryState>
      </div>
    </>
  );
}
