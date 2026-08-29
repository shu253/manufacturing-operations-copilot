# 系统架构

## 组件

| 层级 | 实现 | 职责 |
|---|---|---|
| 数据层 | SQLite Demo / 客户数据适配器 | 订单、BOM、库存、采购、生产、发货、应收 |
| 计算层 | Python business_engine | 确定性公式、金额精度、证据和告警 |
| 服务层 | FastAPI / Pydantic | API、工具白名单、参数校验和统一响应 |
| 编排层 | Dify | 意图分类、参数提取、工具编排和答案组织 |
| 交互层 | React / 飞书 | 驾驶舱、AI问数、卡片、回执和反馈 |

## 统一计算返回

```json
{
  "result": {},
  "as_of_date": "YYYY-MM-DD",
  "formula_version": "3.0.0",
  "calculation_id": "uuid",
  "evidence": [],
  "warnings": []
}
```

## 可替换边界

`business_engine/service.py` 提供稳定业务门面，Repository 隔离数据读取。Demo 使用 SQLite；客户部署时可新增 ERP API、数据库视图、数据仓库或 PostgreSQL 适配器，而不要求重写 Dify 的业务意图。

## 只读与写操作分离

经营查询默认只读。创建任务、发送消息和回执反馈作为独立操作服务，并通过服务端身份验证和人工确认执行。

