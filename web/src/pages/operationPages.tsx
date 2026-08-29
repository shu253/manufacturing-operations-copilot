import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import ReactECharts from "echarts-for-react";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Descriptions,
  Divider,
  Drawer,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
  message
} from "antd";
import {
  CheckCircleOutlined,
  DownloadOutlined,
  EyeOutlined,
  FileTextOutlined,
  MessageOutlined,
  PlusOutlined,
  RobotOutlined,
  SendOutlined,
  ToolOutlined
} from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import { downloadReport, getApi, patchApi, postApi, streamAssistant } from "../api";
import { useAppContext } from "../appContext";
import { MetricCard, PageTitle, QueryState, RiskTag, SourceButton } from "../components";
import { formatMoney, formatPercent } from "../format";
import { roleLabels, rolePermissions, useRole } from "../rbac";
import type { Role } from "../types";

export function ReceivablesPage() {
  const { asOfDate } = useAppContext();
  const [customer, setCustomer] = useState("");
  const query = useQuery({
    queryKey: ["receivables", asOfDate, customer],
    queryFn: () => getApi<any>(`/api/v1/receivables?as_of_date=${asOfDate}${customer ? `&customer_code=${customer}` : ""}`)
  });
  const data = query.data?.data;
  const aging = useMemo(() => {
    const buckets: Record<string, number> = {};
    (data?.receivables || []).forEach((item: any) => {
      buckets[item.aging_bucket] = (buckets[item.aging_bucket] || 0) + Number(item.outstanding_amount);
    });
    return buckets;
  }, [data]);
  const option = {
    tooltip: { trigger: "item", formatter: "{b}: ¥{c}（{d}%）" },
    legend: { bottom: 0 },
    series: [{ type: "pie", radius: ["42%", "70%"], data: Object.entries(aging).map(([name, value]) => ({ name, value })) }]
  };
  return (
    <>
      <PageTitle title="应收账款与回款风险" subtitle="关联发货、开票、回款和账龄，形成催收优先级" extra={<SourceButton meta={query.data?.meta} />} />
      <QueryState loading={query.isLoading} error={query.error}>
        {data && (
          <>
            <div className="metric-grid">
              <MetricCard title="未收金额" value={formatMoney(data.total_outstanding_amount, true)} tone="orange" />
              <MetricCard title="逾期金额" value={formatMoney(data.total_overdue_amount, true)} tone="red" />
              <MetricCard title="未结应收" value={data.open_receivable_count} suffix="笔" />
              <MetricCard title="高风险应收" value={data.high_risk_count} suffix="笔" tone="red" />
              <MetricCard title="已发货未开票" value={data.shipped_not_invoiced_count} suffix="笔" tone="orange" />
            </div>
            <div className="content-grid">
              <Card title="应收账龄分布"><ReactECharts className="chart" option={option} /></Card>
              <Card title="催收建议">
                <Alert type="error" showIcon message="优先处理90天以上高风险应收" description="由财务与销售负责人联合确认回款承诺，并记录催收结果。" />
                <Alert style={{ marginTop: 12 }} type="warning" showIcon message="复核已发货未开票记录" description={`当前共有${data.shipped_not_invoiced_count}笔发货记录尚未开票。`} />
              </Card>
            </div>
            <Card title="应收账款明细">
              <div className="toolbar">
                <Input placeholder="输入客户编码筛选" value={customer} onChange={event => setCustomer(event.target.value)} allowClear style={{ maxWidth: 280 }} />
              </div>
              <Table
                className="desktop-table"
                rowKey="invoice_code"
                dataSource={data.receivables}
                pagination={{ pageSize: 12 }}
                columns={[
                  { title: "客户", dataIndex: "customer_code", render: (value, row: any) => <div><strong>{value}</strong><br /><Typography.Text type="secondary">{row.customer_name}</Typography.Text></div> },
                  { title: "订单", dataIndex: "sales_order_code" },
                  { title: "发票", dataIndex: "invoice_code" },
                  { title: "未收金额", dataIndex: "outstanding_amount", align: "right", sorter: (a: any, b: any) => a.outstanding_amount - b.outstanding_amount, render: formatMoney },
                  { title: "到期日", dataIndex: "due_date" },
                  { title: "逾期天数", dataIndex: "overdue_days", sorter: (a: any, b: any) => a.overdue_days - b.overdue_days, render: value => <Typography.Text type={value > 0 ? "danger" : undefined}>{value}</Typography.Text> },
                  { title: "账龄", dataIndex: "aging_bucket", filters: ["未到期", "1-30天", "31-60天", "61-90天", "90天以上"].map(text => ({ text, value: text })), onFilter: (value, row: any) => row.aging_bucket === value },
                  { title: "风险", dataIndex: "risk_level", render: value => <RiskTag level={value} /> }
                ]}
              />
            </Card>
          </>
        )}
      </QueryState>
    </>
  );
}

export function ReportsPage() {
  const { asOfDate } = useAppContext();
  const [reportType, setReportType] = useState("daily");
  const [format, setFormat] = useState("markdown");
  const [downloading, setDownloading] = useState(false);
  const report = useMutation({
    mutationFn: () => postApi<any>("/api/v1/reports/generate", { report_type: reportType, format: "markdown", as_of_date: asOfDate }),
    onError: error => message.error(error.message)
  });
  const handleDownload = async (target: string) => {
    setDownloading(true);
    try {
      await downloadReport({ report_type: reportType, format: target, as_of_date: asOfDate });
      message.success(`${target.toUpperCase()}报告已生成`);
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setDownloading(false);
    }
  };
  return (
    <>
      <PageTitle title="经营报告中心" subtitle="生成日报、周报和月报，所有结论保留数据来源" extra={<SourceButton meta={report.data?.meta} />} />
      <div className="content-grid">
        <Card title="报告生成">
          <Form layout="vertical">
            <Form.Item label="报告类型">
              <Select value={reportType} onChange={setReportType} options={[
                { value: "daily", label: "经营日报" },
                { value: "weekly", label: "经营周报" },
                { value: "monthly", label: "经营月报" }
              ]} />
            </Form.Item>
            <Form.Item label="数据基准日"><Input value={asOfDate} disabled /></Form.Item>
            <Button type="primary" icon={<FileTextOutlined />} loading={report.isPending} onClick={() => report.mutate()} block>生成报告预览</Button>
          </Form>
          <Divider>下载格式</Divider>
          <Space wrap>
            {["markdown", "json", "docx", "pdf", "xlsx"].map(value => (
              <Button key={value} loading={downloading && format === value} icon={<DownloadOutlined />} onClick={() => { setFormat(value); handleDownload(value); }}>
                {value.toUpperCase()}
              </Button>
            ))}
          </Space>
        </Card>
        <QueryState loading={report.isPending} error={report.error}>
          <Card title="报告预览" className="report-preview">
            {report.data ? (
              <Typography>
                <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", lineHeight: 1.8 }}>{report.data.data.content}</pre>
              </Typography>
            ) : <Typography.Text type="secondary">选择报告类型并生成预览。</Typography.Text>}
          </Card>
        </QueryState>
      </div>
    </>
  );
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  result?: any;
  meta?: any;
  intent?: string;
  toolCalls?: any[];
  model?: any;
  confirmation?: any;
}

const suggestedQuestions = [
  "销售-20260718-01为什么是高风险订单，应该怎么处理？",
  "针对销售-20260718-01，铜材上涨8%会有什么影响？",
  "销售-20260718-01目前有哪些缺料？",
  "当前应收账款风险如何？",
  "生成今天的经营日报摘要。"
];

export function AssistantPage() {
  const { asOfDate } = useAppContext();
  const { role } = useRole();
  const [question, setQuestion] = useState("");
  const [conversationId, setConversationId] = useState<string>();
  const [progressText, setProgressText] = useState("");
  const [draftAnswer, setDraftAnswer] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: "assistant", content: "您好，我是企业经营管理助手。我会理解您的业务问题并调用经过批准的业务工具；订单、成本、风险和应收数字全部来自业务计算引擎。" }
  ]);
  const ask = useMutation({
    mutationFn: (text: string) => streamAssistant<any>(
      "/api/v1/assistant/query/stream",
      {
        question: text,
        as_of_date: asOfDate,
        conversation_id: conversationId,
        user_id: "web-demo-user",
        role,
        response_mode: "streaming"
      },
      event => {
        if (event.event === "status") setProgressText(String(event.data));
        if (event.event === "token") setDraftAnswer(current => current + String(event.data));
      }
    ),
    onSuccess: response => {
      setConversationId(response.data.conversation_id);
      setMessages(current => [...current, {
        role: "assistant",
        content: response.data.answer,
        result: response.data.result,
        meta: response.meta,
        intent: response.data.intent,
        toolCalls: response.data.tool_calls,
        model: response.data.model,
        confirmation: response.data.confirmation
      }]);
      setProgressText("");
      setDraftAnswer("");
    },
    onError: error => {
      setProgressText("");
      setDraftAnswer("");
      setMessages(current => [...current, { role: "assistant", content: `无法回答：${error.message}` }]);
    }
  });
  const confirmAction = useMutation({
    mutationFn: (token: string) => postApi<any>("/api/v1/assistant/confirm", { confirmation_token: token }),
    onSuccess: response => setMessages(current => [...current, {
      role: "assistant",
      content: response.data.answer,
      result: response.data.result,
      meta: response.meta,
      intent: response.data.action_type
    }]),
    onError: error => message.error(error.message)
  });
  const submit = (text = question) => {
    const value = text.trim();
    if (!value || ask.isPending) return;
    setMessages(current => [...current, { role: "user", content: value }]);
    setQuestion("");
    setProgressText("正在连接智能体工作流");
    setDraftAnswer("");
    ask.mutate(value);
  };
  return (
    <>
      <PageTitle
        title="AI经营问数"
        subtitle="大模型理解问题组织答案，业务数字由确定性计算引擎提供"
        extra={conversationId ? <Tag color="blue">连续会话 {conversationId.slice(0, 8)}</Tag> : undefined}
      />
      <div className="chat-shell">
        <Card title="推荐问题">
          <Space direction="vertical" className="full-width">
            {suggestedQuestions.map(value => <Button key={value} block style={{ textAlign: "left", height: "auto", padding: "9px 12px", whiteSpace: "normal" }} onClick={() => submit(value)}>{value}</Button>)}
          </Space>
          <Alert
            style={{ marginTop: 16 }}
            type="info"
            showIcon
            message="可信边界"
            description="大模型不直接访问数据库、不执行用户SQL、不自行计算或补造业务数字；所有写操作都需要人工确认。"
          />
        </Card>
        <Card title={<Space><RobotOutlined />企业经营管理助手</Space>}>
          <div className="chat-messages">
            {messages.map((item, index) => (
              <div key={index} className={`chat-message ${item.role === "user" ? "chat-user" : "chat-assistant"}`}>
                {item.content}
                {item.toolCalls?.length ? (
                  <div className="assistant-tool-list">
                    <Typography.Text type="secondary"><ToolOutlined /> 本轮业务工具</Typography.Text>
                    {item.toolCalls.map((tool, toolIndex) => (
                      <Tag key={`${tool.tool_name}-${toolIndex}`} color={tool.status === "success" ? "green" : "red"}>
                        {tool.tool_name}{tool.duration_ms !== undefined ? ` · ${tool.duration_ms}ms` : ""}
                      </Tag>
                    ))}
                  </div>
                ) : null}
                {item.result?.risk_score !== undefined && <div style={{ marginTop: 10 }}><Tag color="red">风险分 {item.result.risk_score}</Tag><RiskTag level={item.result.risk_level} /></div>}
                {item.result?.cost_change !== undefined && <Descriptions size="small" column={1} style={{ marginTop: 10 }}><Descriptions.Item label="成本增加">{formatMoney(item.result.cost_change)}</Descriptions.Item><Descriptions.Item label="新毛利率">{formatPercent(item.result.new_margin_rate)}</Descriptions.Item></Descriptions>}
                {item.confirmation?.confirmation_required && (
                  <Card size="small" className="assistant-confirmation" title="需要人工确认">
                    <Descriptions size="small" column={1}>
                      {Object.entries(item.confirmation.action_preview || {}).map(([label, value]) => (
                        <Descriptions.Item key={label} label={label}>{String(value)}</Descriptions.Item>
                      ))}
                    </Descriptions>
                    <Alert type="warning" showIcon message="确认后才会写入业务系统；确认令牌只能使用一次。" />
                    <Button
                      type="primary"
                      danger
                      loading={confirmAction.isPending}
                      onClick={() => confirmAction.mutate(item.confirmation.confirmation_token)}
                      style={{ marginTop: 10 }}
                    >
                      确认执行
                    </Button>
                  </Card>
                )}
                {item.meta && <div style={{ marginTop: 8 }}><SourceButton meta={item.meta} /></div>}
              </div>
            ))}
            {ask.isPending && (
              <div className="chat-message chat-assistant">
                <Space direction="vertical" size={4}>
                  <Typography.Text>{draftAnswer || progressText || "正在理解问题并提取业务参数…"}</Typography.Text>
                  {!draftAnswer && <Typography.Text type="secondary">随后将调用经过批准的业务工具并核验数字来源。</Typography.Text>}
                </Space>
              </div>
            )}
          </div>
          <div className="chat-input">
            <Input.TextArea
              autoSize={{ minRows: 1, maxRows: 4 }}
              value={question}
              onChange={event => setQuestion(event.target.value)}
              onPressEnter={event => { if (!event.shiftKey) { event.preventDefault(); submit(); } }}
              placeholder="输入业务问题，例如：销售-20260718-01为什么有风险？"
            />
            <Button type="primary" icon={<SendOutlined />} loading={ask.isPending} onClick={() => submit()}>发送</Button>
          </div>
          <Typography.Text type="secondary" className="assistant-trust-note">
            本回答由大模型或受控本地规则组织，业务数字来自业务计算引擎；模型与工具调用均记录审计。
          </Typography.Text>
        </Card>
      </div>
    </>
  );
}

export function TasksPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [status, setStatus] = useState<string>();
  const [createOpen, setCreateOpen] = useState(false);
  const [messageTask, setMessageTask] = useState<string>();
  const [selectedTask, setSelectedTask] = useState<string>();
  const tasks = useQuery({
    queryKey: ["tasks", status],
    queryFn: () => getApi<any>(`/api/v1/tasks?limit=200${status ? `&status=${status}` : ""}`)
  });
  const taskDetail = useQuery({
    queryKey: ["task-detail", selectedTask],
    queryFn: () => getApi<any>(`/api/v1/tasks/${selectedTask}`),
    enabled: Boolean(selectedTask)
  });
  const createTask = useMutation({
    mutationFn: (values: any) => postApi<any>("/api/v1/tasks", { ...values, risk_event_id: Number(values.risk_event_id), owner_employee_id: Number(values.owner_employee_id) }),
    onSuccess: () => { message.success("风险任务已创建"); setCreateOpen(false); queryClient.invalidateQueries({ queryKey: ["tasks"] }); },
    onError: error => message.error(error.message)
  });
  const updateTask = useMutation({
    mutationFn: ({ code, next }: { code: string; next: string }) => patchApi<any>(`/api/v1/tasks/${code}`, { status: next }),
    onSuccess: () => {
      message.success("任务状态已更新");
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      queryClient.invalidateQueries({ queryKey: ["task-detail"] });
    },
    onError: error => message.error(error.message)
  });
  const createMessage = useMutation({
    mutationFn: (values: any) => postApi<any>("/api/v1/messages", { ...values, task_code: messageTask, recipient_employee_id: Number(values.recipient_employee_id), channel: "站内" }),
    onSuccess: () => {
      message.success("站内消息已创建");
      setMessageTask(undefined);
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      queryClient.invalidateQueries({ queryKey: ["task-detail"] });
    },
    onError: error => message.error(error.message)
  });
  const detail = taskDetail.data?.data;
  const sourceLabels: Record<string, string> = {
    sales_orders: "销售订单",
    production_orders: "生产订单",
    production_material_requirements: "生产物料需求",
    purchase_orders: "采购订单",
    purchase_order_lines: "采购订单明细",
    inventory_balances: "库存余额",
    risk_events: "风险事件"
  };
  return (
    <>
      <PageTitle
        title="风险任务处理"
        subtitle="风险分派、负责人确认、处理、关闭和站内消息留痕"
        extra={<><SourceButton meta={tasks.data?.meta} /><Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>创建任务</Button></>}
      />
      <Card>
        <div className="toolbar">
          <Select
            placeholder="任务状态"
            allowClear
            value={status}
            onChange={setStatus}
            options={["待处理", "处理中", "已完成", "已关闭"].map(value => ({ value, label: value }))}
            style={{ width: 150 }}
          />
          <Typography.Text type="secondary">所有写操作均需要人工确认</Typography.Text>
        </div>
        <QueryState loading={tasks.isLoading} error={tasks.error}>
          <Table
            className="desktop-table"
            rowKey="task_code"
            dataSource={tasks.data?.data.items || []}
            pagination={{ pageSize: 12 }}
            onRow={row => ({
              onClick: () => setSelectedTask(row.task_code),
              style: { cursor: "pointer" },
              title: `点击查看${row.task_code}详情`
            })}
            columns={[
              {
                title: "任务编号",
                dataIndex: "task_code",
                width: 145,
                render: value => (
                  <Button
                    type="link"
                    className="task-code-link"
                    icon={<EyeOutlined />}
                    onClick={event => {
                      event.stopPropagation();
                      setSelectedTask(value);
                    }}
                  >
                    {value}
                  </Button>
                )
              },
              {
                title: "任务内容",
                dataIndex: "display_title",
                width: 450,
                render: (_: unknown, row: any) => (
                  <Space direction="vertical" size={3}>
                    <Typography.Text strong>{row.display_title || row.task_title}</Typography.Text>
                    <Space size={6} wrap>
                      <Tag color="geekblue">{row.risk_type_name || "风险处理"}</Tag>
                      {row.entity_code && (
                        <Typography.Link
                          onClick={event => {
                            event.stopPropagation();
                            navigate(`/orders/${row.entity_code}`);
                          }}
                        >
                          {row.entity_code}
                        </Typography.Link>
                      )}
                      <Typography.Text type="secondary" ellipsis={{ tooltip: row.risk_summary }} style={{ maxWidth: 260 }}>
                        {row.risk_summary || "打开任务查看风险原因和处理依据"}
                      </Typography.Text>
                    </Space>
                  </Space>
                )
              },
              { title: "负责人", dataIndex: "employee_name" },
              { title: "截止日期", dataIndex: "due_date" },
              { title: "优先级", dataIndex: "priority", render: value => <Tag color={value === "高" ? "red" : value === "中" ? "orange" : "blue"}>{value}</Tag> },
              { title: "状态", dataIndex: "status", render: value => <Tag color={value === "已完成" || value === "已关闭" ? "green" : value === "处理中" ? "blue" : "orange"}>{value}</Tag> },
              {
                title: "操作", fixed: "right", render: (_: unknown, row: any) => (
                  <Space onClick={event => event.stopPropagation()}>
                    <Button size="small" icon={<EyeOutlined />} onClick={() => setSelectedTask(row.task_code)}>详情</Button>
                    {row.status === "待处理" && <Popconfirm title="确认开始处理该任务？" onConfirm={() => updateTask.mutate({ code: row.task_code, next: "处理中" })}><Button size="small">开始处理</Button></Popconfirm>}
                    {row.status === "处理中" && <Popconfirm title="确认任务已经完成？" onConfirm={() => updateTask.mutate({ code: row.task_code, next: "已完成" })}><Button size="small" type="primary" icon={<CheckCircleOutlined />}>完成</Button></Popconfirm>}
                    <Button size="small" icon={<MessageOutlined />} onClick={() => setMessageTask(row.task_code)}>消息</Button>
                  </Space>
                )
              }
            ]}
          />
        </QueryState>
      </Card>
      <Drawer
        title="风险任务详情"
        width={640}
        open={Boolean(selectedTask)}
        onClose={() => setSelectedTask(undefined)}
        extra={<SourceButton meta={taskDetail.data?.meta} />}
      >
        <QueryState loading={taskDetail.isLoading} error={taskDetail.error}>
          {detail && (
            <Space direction="vertical" size={16} className="full-width">
              <Card className="task-detail-hero">
                <Space direction="vertical" size={8} className="full-width">
                  <Space wrap>
                    <Tag color="geekblue">{detail.risk_type_name}</Tag>
                    <Tag color={detail.priority === "高" ? "red" : detail.priority === "中" ? "orange" : "blue"}>{detail.priority}优先级</Tag>
                    <Tag color={detail.status === "已完成" || detail.status === "已关闭" ? "green" : detail.status === "处理中" ? "blue" : "orange"}>{detail.status}</Tag>
                  </Space>
                  <Typography.Title level={4} style={{ margin: 0 }}>{detail.display_title}</Typography.Title>
                  <Alert type={Number(detail.risk_score) >= 60 ? "error" : "warning"} showIcon message={detail.risk_summary || "暂无风险摘要"} />
                </Space>
              </Card>
              <Descriptions bordered size="small" column={2}>
                <Descriptions.Item label="任务编号">{detail.task_code}</Descriptions.Item>
                <Descriptions.Item label="风险编号">{detail.risk_code || "—"}</Descriptions.Item>
                <Descriptions.Item label="关联订单">
                  {detail.entity_code ? <Typography.Link onClick={() => navigate(`/orders/${detail.entity_code}`)}>{detail.entity_code}</Typography.Link> : "—"}
                </Descriptions.Item>
                <Descriptions.Item label="风险评分"><Typography.Text type="danger" strong>{detail.risk_score ?? "—"}分</Typography.Text></Descriptions.Item>
                <Descriptions.Item label="潜在影响金额">{formatMoney(detail.potential_amount || 0)}</Descriptions.Item>
                <Descriptions.Item label="发现时间">{detail.detected_at || "—"}</Descriptions.Item>
                <Descriptions.Item label="负责人">{detail.employee_name || "未分派"}</Descriptions.Item>
                <Descriptions.Item label="截止日期">{detail.due_date || "—"}</Descriptions.Item>
              </Descriptions>
              <Card title={`数据依据（${detail.evidence?.length || 0}项）`} size="small">
                <List
                  dataSource={detail.evidence || []}
                  locale={{ emptyText: "该风险事件暂无明细依据" }}
                  renderItem={(item: any) => (
                    <List.Item>
                      <List.Item.Meta
                        title={<Space wrap><Tag>{sourceLabels[item.source_table] || item.source_table}</Tag><Typography.Text strong>{item.source_record_code}</Typography.Text></Space>}
                        description={item.evidence_value || "未记录依据说明"}
                      />
                    </List.Item>
                  )}
                />
              </Card>
              <Card title={`沟通记录（${detail.messages?.length || 0}条）`} size="small">
                <List
                  dataSource={detail.messages || []}
                  locale={{ emptyText: "暂无消息记录，可点击下方按钮发起沟通" }}
                  renderItem={(item: any) => (
                    <List.Item>
                      <List.Item.Meta
                        title={<Space><Typography.Text strong>{item.message_title}</Typography.Text><Tag>{item.read_status}</Tag></Space>}
                        description={<><div>{item.message_body}</div><Typography.Text type="secondary">接收人：{item.employee_name || "—"} · {item.sent_at}</Typography.Text></>}
                      />
                    </List.Item>
                  )}
                />
              </Card>
              <Space wrap>
                {detail.status === "待处理" && <Popconfirm title="确认开始处理该任务？" onConfirm={() => updateTask.mutate({ code: detail.task_code, next: "处理中" })}><Button type="primary">开始处理</Button></Popconfirm>}
                {detail.status === "处理中" && <Popconfirm title="确认任务已经完成？" onConfirm={() => updateTask.mutate({ code: detail.task_code, next: "已完成" })}><Button type="primary" icon={<CheckCircleOutlined />}>标记完成</Button></Popconfirm>}
                <Button icon={<MessageOutlined />} onClick={() => setMessageTask(detail.task_code)}>发送消息</Button>
                {detail.entity_code && <Button onClick={() => navigate(`/orders/${detail.entity_code}`)}>查看关联订单</Button>}
              </Space>
            </Space>
          )}
        </QueryState>
      </Drawer>
      <Modal title="创建风险任务" open={createOpen} onCancel={() => setCreateOpen(false)} footer={null} destroyOnClose>
        <Form layout="vertical" initialValues={{ risk_event_id: 1, owner_employee_id: 24, due_date: "2026-08-02", priority: "高", task_title: "跟进销售-20260718-01交付风险" }} onFinish={values => createTask.mutate(values)}>
          <Form.Item name="task_title" label="任务标题" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="risk_event_id" label="风险事件ID" rules={[{ required: true }]}><InputNumber min={1} className="full-width" /></Form.Item>
          <Form.Item name="owner_employee_id" label="负责人ID" rules={[{ required: true }]}><InputNumber min={1} className="full-width" /></Form.Item>
          <Form.Item name="due_date" label="截止日期" rules={[{ required: true }]}><Input type="date" /></Form.Item>
          <Form.Item name="priority" label="优先级"><Select options={["高", "中", "低"].map(value => ({ value, label: value }))} /></Form.Item>
          <Popconfirm title="确认创建并写入风险任务？" onConfirm={() => (document.querySelector("#create-task-submit") as HTMLButtonElement)?.click()}>
            <Button type="primary" block loading={createTask.isPending}>确认创建</Button>
          </Popconfirm>
          <button id="create-task-submit" type="submit" hidden />
        </Form>
      </Modal>
      <Modal title={`发送站内消息 · ${messageTask || ""}`} open={Boolean(messageTask)} onCancel={() => setMessageTask(undefined)} footer={null} destroyOnClose>
        <Form layout="vertical" initialValues={{ recipient_employee_id: 24, message_title: "风险任务提醒", message_body: "请及时处理并反馈任务进展。" }} onFinish={values => createMessage.mutate(values)}>
          <Form.Item name="recipient_employee_id" label="接收人ID" rules={[{ required: true }]}><InputNumber min={1} className="full-width" /></Form.Item>
          <Form.Item name="message_title" label="消息标题" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="message_body" label="消息内容" rules={[{ required: true }]}><Input.TextArea rows={4} /></Form.Item>
          <Popconfirm title="确认创建站内消息？" onConfirm={() => (document.querySelector("#create-message-submit") as HTMLButtonElement)?.click()}>
            <Button type="primary" block icon={<SendOutlined />}>确认发送</Button>
          </Popconfirm>
          <button id="create-message-submit" type="submit" hidden />
        </Form>
      </Modal>
    </>
  );
}

const permissionLabels: Record<string, string> = {
  dashboard: "驾驶舱", orders: "订单", procurement: "采购预警", suppliers: "供应商",
  cost: "成本", quote: "报价", scenario: "情景模拟", receivables: "应收",
  reports: "报告", assistant: "AI问数", tasks: "任务", settings: "系统设置"
};

export function SettingsPage() {
  const { role, setRole } = useRole();
  const { asOfDate, setAsOfDate } = useAppContext();
  const [compact, setCompact] = useState(localStorage.getItem("compact-mode") === "true");
  return (
    <>
      <PageTitle title="用户、权限与系统设置" subtitle="阶段五演示配置：用于菜单和操作演示，不替代真实身份认证" />
      <Alert type="warning" showIcon message="当前为演示RBAC" description="真实账号、密码、JWT、SSO和后端权限强校验将在安全与部署阶段完成。" style={{ marginBottom: 16 }} />
      <div className="settings-grid">
        <Card title="当前演示用户">
          <Space direction="vertical" className="full-width">
            <Typography.Title level={4}>{roleLabels[role]}</Typography.Title>
            <Select value={role} onChange={setRole} options={Object.entries(roleLabels).map(([value, label]) => ({ value, label }))} className="full-width" />
            <Typography.Text type="secondary">切换角色后，左侧菜单会立即按权限调整。</Typography.Text>
          </Space>
        </Card>
        <Card title="角色权限矩阵">
          <Table
            className="desktop-table"
            rowKey="role"
            pagination={false}
            dataSource={(Object.keys(roleLabels) as Role[]).map(value => ({ role: value, label: roleLabels[value] }))}
            columns={[
              { title: "角色", dataIndex: "label", fixed: "left" },
              ...Object.entries(permissionLabels).map(([key, label]) => ({
                title: label,
                width: 90,
                align: "center" as const,
                render: (_: unknown, row: { role: Role }) => <Checkbox checked={rolePermissions[row.role].includes("*") || rolePermissions[row.role].includes(key)} disabled />
              }))
            ]}
            scroll={{ x: 1200 }}
          />
        </Card>
      </div>
      <Card title="系统偏好" style={{ marginTop: 16 }}>
        <Descriptions bordered column={{ xs: 1, sm: 1, md: 2 }}>
          <Descriptions.Item label="API地址">{import.meta.env.VITE_API_BASE_URL || "同源 /api"}</Descriptions.Item>
          <Descriptions.Item label="企业名称">华东某精工装备有限公司</Descriptions.Item>
          <Descriptions.Item label="默认计算日期"><Input type="date" value={asOfDate} onChange={event => setAsOfDate(event.target.value)} style={{ maxWidth: 180 }} /></Descriptions.Item>
          <Descriptions.Item label="金额单位">人民币（CNY）</Descriptions.Item>
          <Descriptions.Item label="高风险阈值">60分及以上</Descriptions.Item>
          <Descriptions.Item label="紧凑显示"><Switch checked={compact} onChange={value => { setCompact(value); localStorage.setItem("compact-mode", String(value)); }} /></Descriptions.Item>
        </Descriptions>
      </Card>
    </>
  );
}
