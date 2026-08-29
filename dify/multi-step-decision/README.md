# 制造业多步骤决策分析工作流

本目录用于在现有 Dify Chatflow 中新增“多步骤决策分析”分支。业务数字继续来自现有 FastAPI 受控工具，模型仅做路由、证据组织和建议表达。

## 节点顺序

1. 开始节点：接收 `query`、`as_of_date`、`role`、`trace_id`、`conversation_context`。
2. LLM“路由与参数提取”：使用 `prompts/01_router_and_extractor.md` 和 `qwen-plus-2025-07-28`。
3. 参数 JSON 解析节点。
4. 条件分支：根据 `intent` 进入对应业务链。
5. 受控工具节点：按照 `node-config.yaml` 的 `branches` 调用现有 Swagger 工具。
6. Code“证据合并”：粘贴 `code/normalize_evidence.py`，将已经运行的工具输出绑定到对应入参。
7. 条件节点：`decision_ready == true` 才进入分析；否则返回工具失败或参数不足提示。
8. LLM“决策归纳”：使用 `prompts/02_decision_synthesis.md` 和 `qwen-max`，输入用户问题、实体 JSON、`evidence_json`、`source_refs` 和工具告警。
9. Code“数字与来源校验”：粘贴 `code/validate_decision.py`，输入 `decision_json` 与 `evidence_json`。
10. Answer 节点：输出 `final_json`。现有 FastAPI、网页和飞书会继续负责把 JSON 渲染成正文或卡片。

如果当前 Dify 分支直接生成面向用户的纯文本回答，不经过 JSON 校验节点，则使用
`prompts/02_decision_direct_reply_compact.md`。该版本保留数字和来源约束，但减少重复规则，并与现有“直接回复”节点的八段式输出一致。

## Dify 中需要填写

- 模型供应商：阿里云百炼/通义千问。
- 路由模型：`qwen-plus-2025-07-28`。
- 决策模型：`qwen-max`；如免费列表有 `qwen3.7-plus`，优先替换为该模型。
- 自定义工具认证：Bearer，值为本机 `.env` 中的 `AI_TOOL_TOKEN`。
- 工具地址：把 `../openapi-tools.yaml` 中的 `YOUR-TUNNEL` 替换为当前 Cloudflare 隧道地址后重新导入。
- 工作流版本：`stage7-v1`。

## 第一批演示问题

1. `销售-20260718-01为什么是高风险订单？请比较三个处理方案并给出执行优先级。`
2. `销售-20260718-01的缺料、采购迟交和生产进度之间有什么关系，应该先处理哪一项？`
3. `如果物料-0001价格上涨8%，对销售-20260718-01的成本和毛利有什么影响，应该采取什么措施？`
4. `销售-20260718-01当前是否还能按期交付？请给出恢复计划和需要管理层确认的事项。`
5. `针对物料-0001的供应风险，替代供应商方案需要满足哪些前置条件？`

## 验收标准

- 所有业务数字都能在工具原始 JSON 中找到。
- 所有指标和证据链条目都有 `source_ref`。
- 任一工具失败时不输出完整决策结论。
- 同一问题连续运行三次，关键数字和推荐方案保持稳定。
- 网页和飞书使用同一个 `answer/final_json`，不再分别生成摘要。
