# 阶段六Dify Cloud配置

1. 在Dify Cloud创建Chatflow应用。
2. 在“设置—模型供应商”中配置通义千问，选择`qwen-plus`；再配置DeepSeek但不设自动切换。
3. 复制`.env.example`为`.env`并填写`DIFY_APP_API_KEY`和随机`AI_TOOL_TOKEN`。
4. 启动本地FastAPI。
5. 执行`scripts/start_dify_tunnel.ps1`，获得`https://*.trycloudflare.com`地址。
6. 将`dify/openapi-tools.yaml`中的`https://YOUR-TUNNEL.example.com`替换成隧道地址。
7. 在Dify“工具—自定义工具”中导入该OpenAPI文件，认证选择Bearer并填写`AI_TOOL_TOKEN`。
8. 按`workflow-spec.md`创建分类、参数提取、工具、LLM和回答节点。
9. 发布应用，把Dify生成的App API Key填入服务端`.env`。
10. 重启FastAPI，`GET /api/v1/health`中的`assistant_mode`应为`dify-cloud`。

## 阶段七：多步骤决策分析

在现有 Chatflow 中新增多步骤决策分支时，使用
[`multi-step-decision/README.md`](multi-step-decision/README.md)中的节点顺序、模型分工、提示词和 Code 节点代码。第一版路由模型使用`qwen-plus-2025-07-28`，最终决策模型使用`qwen-max`，业务数字仍全部来自受控工具。

注意：Dify密钥和工具令牌都不得写入`web/.env`或任何`VITE_`变量。
