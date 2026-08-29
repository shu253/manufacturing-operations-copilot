# 阶段六FastAPI与Dify智能体网关

## 启动

项目要求Python 3.9及以上。

```powershell
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

启动后访问：

- Swagger UI：`http://127.0.0.1:8000/docs`
- ReDoc：`http://127.0.0.1:8000/redoc`
- OpenAPI：`http://127.0.0.1:8000/openapi.json`
- 健康检查：`http://127.0.0.1:8000/api/v1/health`

## 接口清单

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/v1/health` | 健康检查 |
| GET | `/api/v1/dashboard` | 驾驶舱汇总 |
| GET | `/api/v1/dashboard/trends` | 近12个月订单、采购、毛利和应收趋势 |
| GET | `/api/v1/orders/risks` | 订单风险列表 |
| GET | `/api/v1/orders/{order_code}/risk` | 订单风险详情 |
| GET | `/api/v1/orders/{order_code}/fulfillment` | 订单齐套率 |
| GET | `/api/v1/orders/{order_code}/lifecycle` | 订单全流程聚合时间线 |
| GET | `/api/v1/materials/shortages` | 缺料和受影响订单 |
| GET | `/api/v1/procurement/price-anomalies` | 采购价格异常 |
| GET | `/api/v1/suppliers/{supplier_code}` | 供应商画像与评分 |
| GET | `/api/v1/suppliers/rankings` | 多维度供应商排行榜 |
| GET | `/api/v1/suppliers/recommendations` | 替代供应商推荐 |
| GET | `/api/v1/orders/{order_code}/cost` | 成本穿透 |
| POST | `/api/v1/quotes/calculate` | 报价计算 |
| POST | `/api/v1/scenarios/run` | 七类采购情景模拟 |
| GET | `/api/v1/metrics/query` | 受控经营指标查询 |
| GET | `/api/v1/receivables` | 应收账款和回款风险 |
| POST | `/api/v1/reports/generate` | 日报、周报和月报 |
| POST | `/api/v1/reports/export` | Markdown、JSON、Word、PDF和Excel导出 |
| POST | `/api/v1/assistant/query` | Dify/本地受控智能问数统一入口 |
| POST | `/api/v1/assistant/query/stream` | 流式状态与答案输出 |
| POST | `/api/v1/assistant/confirm` | 一次性令牌人工确认写操作 |
| POST | `/api/v1/ai-tools/{tool_name}` | Dify专用受控业务工具网关 |
| GET/POST | `/api/v1/tasks` | 任务查询与创建 |
| PATCH | `/api/v1/tasks/{task_code}` | 任务处理和关闭 |
| GET/POST | `/api/v1/messages` | 消息查询与创建 |

## Dify与受控工具

将项目根目录`.env.example`复制为`.env`，填写：

- `DIFY_APP_API_KEY`
- `AI_TOOL_TOKEN`
- `QWEN_MODEL_NAME`
- `DEEPSEEK_MODEL_NAME`

未填写Dify密钥时，智能问数会明确进入`controlled-local`受控编排模式；填写并重启后切换为`dify-cloud`。

受控工具只允许调用`api/ai_tools.py`中的白名单业务能力，拒绝SQL、数据库路径、表名和任意URL。所有工具调用都记录在`ai_tool_calls`审计表。

创建任务等写操作先返回操作预览和一次性确认令牌，只有调用`/api/v1/assistant/confirm`后才写入。

## 受控经营指标

`/api/v1/metrics/query`只允许查询白名单指标：

- `sales_order_summary`
- `procurement_summary`
- `production_summary`
- `receivables_summary`
- `supplier_summary`

接口不会接收或执行用户提交的SQL。

## 统一响应

成功响应包含：

- `request_id`
- `data`
- `meta.calculation_id`
- `meta.as_of_date`
- `meta.formula_version`
- `meta.sources`
- `meta.warnings`
- `meta.audit`

失败响应包含统一错误编码、错误信息、请求编号和审计字段。

## 自动测试

API测试使用正式数据库的临时副本，任务和消息测试不会写入正式演示库。

```powershell
python scripts/run_api_tests.py
```

测试结果写入`data/api_test_report.json`。
