# AI 应用开发视角

## 主要技术实现

- 使用 Python 将齐套、迟交、进度、风险、成本、报价、应收和报告封装为确定性计算函数。
- 使用只读 Repository 和服务门面隔离数据库，统一金额精度、异常和计算信封。
- 使用 FastAPI/Pydantic 暴露 39 个业务接口和 15 个 AI 白名单工具。
- 使用 Dify 完成意图分类、参数提取、条件路由、多工具调用和答案组织。
- 编写代码节点进行证据合并、明细裁剪和答案数字核验。
- 使用 React、TypeScript、Ant Design 和 ECharts 实现 12 个经营管理模块。
- 使用飞书开放平台实现长连接机器人、交互卡片、身份映射、人工确认和反馈。
- 实现 Dify 网络重试、飞书失败发件箱、定时补偿、Token/费用和操作审计。
- 使用 Python unittest、Vitest 和 Playwright 覆盖业务引擎、API、AI工作流和多端页面。

## 关键代码入口

- `business_engine/fulfillment.py`：齐套、缺料、采购迟交、生产进度和订单风险。
- `business_engine/procurement.py`：价格异常、供应商评分与推荐。
- `business_engine/costing.py`：完整成本、报价和七类情景模拟。
- `business_engine/finance.py`：应收风险与经营报告。
- `api/ai_tools.py`：受控工具网关。
- `api/assistant_service.py`：Dify代理、重试、问数和数字控制。
- `api/action_hub.py`：身份、确认、通知、重试和回执。
- `channels/feishu_core.py`：飞书事件和卡片通道。
- `web/src/`：Web应用。

## 一句话介绍

我实现了一个FastAPI、React、Dify和飞书组成的制造业AI应用，将业务数字固定在可测试的确定性引擎中，通过受控工具、数字核验和审计解决大模型经营问数中的幻觉与可追溯问题。

