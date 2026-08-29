# 华东某精工装备经营决策智能体 Web 产品

## 本地启动

在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_demo.ps1
```

访问：

- Web 产品：`http://127.0.0.1:5173`
- FastAPI 文档：`http://127.0.0.1:8000/docs`

停止服务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\stop_demo.ps1
```

首次运行前应在 `web/` 目录安装依赖。前端 API 地址可通过 `VITE_API_BASE_URL` 配置，默认使用 `/api/v1` 并由 Vite 代理到本机 FastAPI。

## 功能页面

产品包含经营驾驶舱、订单风险与全流程、缺料采购预警、供应商画像、成本穿透、报价建议、七类情景模拟、应收风险、经营报告、AI经营问数、风险任务和系统设置共 12 个模块。

演示角色包括管理员、管理层、采购、生产、销售和财务。阶段五角色控制仅用于产品演示，真实登录、JWT、SSO 和后端权限强校验留待安全阶段。

AI经营问数通过FastAPI服务端代理连接大模型工作流，支持连续会话、工具执行状态、流式答案、来源查看和写操作人工确认。未配置大模型工作流时会明确显示“本地受控编排”。所有业务金额、风险分和毛利率均来自FastAPI业务计算引擎，大模型不能直接访问数据库或执行用户SQL。

## 测试

```powershell
cd web
pnpm run build
pnpm run test:report
pnpm run test:e2e
```

端到端测试覆盖 1440px 桌面、768px 平板和 375px 手机三种视口。
