import { lazy, Suspense, useMemo, useState } from "react";
import { Layout, Menu, Button, Drawer, Select, DatePicker, Avatar, Space, Typography, Grid, Breadcrumb } from "antd";
import {
  ApartmentOutlined,
  BarChartOutlined,
  CalculatorOutlined,
  ControlOutlined,
  DashboardOutlined,
  DollarOutlined,
  FileTextOutlined,
  MenuOutlined,
  MessageOutlined,
  OrderedListOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  ShopOutlined,
  SlidersOutlined,
  TeamOutlined,
  ToolOutlined
} from "@ant-design/icons";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import dayjs from "dayjs";
import { roleLabels, useRole } from "./rbac";
import { useAppContext } from "./appContext";
const DashboardPage = lazy(() => import("./pages/corePages").then(module => ({ default: module.DashboardPage })));
const OrderDetailPage = lazy(() => import("./pages/corePages").then(module => ({ default: module.OrderDetailPage })));
const OrdersPage = lazy(() => import("./pages/corePages").then(module => ({ default: module.OrdersPage })));
const ShortagesPage = lazy(() => import("./pages/corePages").then(module => ({ default: module.ShortagesPage })));
const CostPage = lazy(() => import("./pages/supplyPages").then(module => ({ default: module.CostPage })));
const QuotePage = lazy(() => import("./pages/supplyPages").then(module => ({ default: module.QuotePage })));
const ScenarioPage = lazy(() => import("./pages/supplyPages").then(module => ({ default: module.ScenarioPage })));
const SuppliersPage = lazy(() => import("./pages/supplyPages").then(module => ({ default: module.SuppliersPage })));
const AssistantPage = lazy(() => import("./pages/operationPages").then(module => ({ default: module.AssistantPage })));
const ReceivablesPage = lazy(() => import("./pages/operationPages").then(module => ({ default: module.ReceivablesPage })));
const ReportsPage = lazy(() => import("./pages/operationPages").then(module => ({ default: module.ReportsPage })));
const SettingsPage = lazy(() => import("./pages/operationPages").then(module => ({ default: module.SettingsPage })));
const TasksPage = lazy(() => import("./pages/operationPages").then(module => ({ default: module.TasksPage })));

const { Header, Sider, Content } = Layout;

const menuConfig = [
  { key: "/dashboard", label: "经营驾驶舱", icon: <DashboardOutlined />, permission: "dashboard" },
  { key: "/orders", label: "订单风险", icon: <OrderedListOutlined />, permission: "orders" },
  { key: "/procurement", label: "缺料与预警", icon: <SafetyCertificateOutlined />, permission: "procurement" },
  { key: "/suppliers", label: "供应商分析", icon: <TeamOutlined />, permission: "suppliers" },
  { key: "/cost", label: "成本穿透", icon: <CalculatorOutlined />, permission: "cost" },
  { key: "/quote", label: "报价建议", icon: <DollarOutlined />, permission: "quote" },
  { key: "/scenario", label: "情景模拟", icon: <SlidersOutlined />, permission: "scenario" },
  { key: "/receivables", label: "应收与回款", icon: <BarChartOutlined />, permission: "receivables" },
  { key: "/reports", label: "经营报告", icon: <FileTextOutlined />, permission: "reports" },
  { key: "/assistant", label: "AI经营问数", icon: <MessageOutlined />, permission: "assistant" },
  { key: "/tasks", label: "风险任务", icon: <ToolOutlined />, permission: "tasks" },
  { key: "/settings", label: "系统设置", icon: <SettingOutlined />, permission: "settings" }
];

function ShellMenu({ onNavigate }: { onNavigate?: () => void }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { can } = useRole();
  const items = menuConfig.filter(item => can(item.permission));
  const selected = items.find(item => location.pathname.startsWith(item.key))?.key || "/dashboard";
  return (
    <Menu
      mode="inline"
      theme="dark"
      selectedKeys={[selected]}
      items={items}
      onClick={({ key }) => {
        navigate(key);
        onNavigate?.();
      }}
    />
  );
}

function AppLayout() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const screens = Grid.useBreakpoint();
  const navigate = useNavigate();
  const location = useLocation();
  const { role, setRole } = useRole();
  const { asOfDate, setAsOfDate } = useAppContext();
  const currentLabel = useMemo(
    () => menuConfig.find(item => location.pathname.startsWith(item.key))?.label || "业务详情",
    [location.pathname]
  );
  return (
    <Layout className="app-shell">
      {screens.lg ? (
        <Sider width={232} className="app-sider">
          <div className="brand">
            <div className="brand-mark"><ApartmentOutlined /></div>
            <div className="brand-copy"><strong>华东某精工</strong><span>企业经营管理智能体</span></div>
          </div>
          <div className="nav-caption">经营管理中枢</div>
          <ShellMenu />
        </Sider>
      ) : (
        <Drawer
          open={mobileOpen}
          onClose={() => setMobileOpen(false)}
          placement="left"
          width={260}
          styles={{ body: { padding: 0, background: "#06345f" }, header: { display: "none" } }}
        >
          <div className="brand">
            <div className="brand-mark"><ApartmentOutlined /></div>
            <div className="brand-copy"><strong>华东某精工</strong><span>企业经营管理智能体</span></div>
          </div>
          <div className="nav-caption">经营管理中枢</div>
          <ShellMenu onNavigate={() => setMobileOpen(false)} />
        </Drawer>
      )}
      <Layout>
        <Header className="app-header">
          <Space>
            {!screens.lg && <Button aria-label="打开导航菜单" type="text" icon={<MenuOutlined />} onClick={() => setMobileOpen(true)} />}
            <div className="header-title">
              <Typography.Text className="header-eyebrow">经营管理中枢</Typography.Text>
              <Typography.Text strong>企业经营管理中心</Typography.Text>
              <Typography.Text type="secondary">分析日期：{asOfDate}</Typography.Text>
            </div>
          </Space>
          <Space wrap className="header-actions">
            {screens.md && (
              <DatePicker
                allowClear={false}
                value={dayjs(asOfDate)}
                onChange={value => value && setAsOfDate(value.format("YYYY-MM-DD"))}
                className="header-date"
              />
            )}
            <Select
              value={role}
              onChange={setRole}
              options={Object.entries(roleLabels).map(([value, label]) => ({ value, label }))}
              className="role-select"
            />
            <Avatar className="user-avatar">{roleLabels[role].slice(0, 1)}</Avatar>
          </Space>
        </Header>
        <Content className="app-content">
          <Breadcrumb
            className="app-breadcrumb"
            items={[
              { title: <a onClick={() => navigate("/dashboard")}>华东某精工</a> },
              { title: currentLabel }
            ]}
          />
          <Suspense fallback={<div style={{ padding: 24 }}><Typography.Text type="secondary">正在加载业务页面…</Typography.Text></div>}>
          <Routes>
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/orders" element={<OrdersPage />} />
            <Route path="/orders/:orderCode" element={<OrderDetailPage />} />
            <Route path="/procurement" element={<ShortagesPage />} />
            <Route path="/suppliers" element={<SuppliersPage />} />
            <Route path="/cost" element={<CostPage />} />
            <Route path="/quote" element={<QuotePage />} />
            <Route path="/scenario" element={<ScenarioPage />} />
            <Route path="/receivables" element={<ReceivablesPage />} />
            <Route path="/reports" element={<ReportsPage />} />
            <Route path="/assistant" element={<AssistantPage />} />
            <Route path="/tasks" element={<TasksPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
          </Suspense>
        </Content>
      </Layout>
    </Layout>
  );
}

export default function App() {
  return <AppLayout />;
}
