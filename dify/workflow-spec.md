# Dify Cloud工作流配置说明

## 应用类型

创建Chatflow应用“华东某精工企业供应链决策助手”，不要使用自由Agent模式。

## 输入变量

| 变量 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `query` | 文本 | 是 | 用户问题 |
| `as_of_date` | 文本 | 是 | `YYYY-MM-DD` |
| `role` | 文本 | 是 | 当前演示角色 |
| `trace_id` | 文本 | 是 | FastAPI生成的调用追踪编号 |
| `workflow_version` | 文本 | 是 | 工作流版本 |

## 问题分类器

分类标签：

- `order_overview`
- `order_risk`
- `material_shortage`
- `purchase_delay`
- `production_progress`
- `supplier_analysis`
- `cost_analysis`
- `quote_analysis`
- `scenario_simulation`
- `receivables`
- `report_generation`
- `policy_qa`
- `unknown`

`unknown`分支不调用工具，要求用户补充业务对象。

## 参数提取

按意图提取：

- `order_code`
- `purchase_order_code`
- `material_code`
- `supplier_code`
- `product_code`
- `quantity`
- `need_by_date`
- `target_margin`
- `change_rate`
- `report_type`

所有编码和数值参数均设置为可空。进入工具节点前使用条件节点检查必填参数；缺失时进入追问回答节点。

采购交付问题可传`purchase_order_code`。为兼容既有工作流，若参数提取器把`采购-`编号写入
`order_code`，API也会自动识别为采购订单编号。

## 工具节点

从`dify/openapi-tools.yaml`导入自定义工具，认证方式选择Bearer，值使用服务端`AI_TOOL_TOKEN`。每次调用必须传递工作流输入`trace_id`和`as_of_date`。

## 多步骤订单风险分支

当问题同时包含“为什么、原因、怎么处理、如何处理”时依次调用：

1. `get_order_risk`
2. `get_order_fulfillment`
3. `get_purchase_delays`
4. `get_production_progress`

将四个工具结果共同传入LLM节点。涉及供应商替代且已取得物料、数量和需求日期时，再调用`recommend_suppliers`。

## 报告分支

先调用`generate_business_report`取得确定性指标，再由LLM生成管理摘要。LLM不得修改结构化指标。

## LLM节点

- 主模型：通义千问。
- 温度：0.1。
- 系统提示词：`dify/prompts/system.md`全文。
- 上下文：用户问题、分类结果、提取参数、全部工具原始JSON。
- 输出：JSON对象。

DeepSeek只配置为人工切换的备选模型，不配置自动失败转移。
