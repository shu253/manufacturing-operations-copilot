# 飞书行动闭环

## 身份模型

服务端维护员工、部门、角色和飞书 `open_id` 的映射：

- `owner`：老板，可经营问数和发起消息。
- `plant_manager`：厂长，可经营问数和发起消息。
- `department_head`：部门负责人，可接收、回执和反馈。

权限根据飞书事件中的真实操作人判断，不能由前端自行声明角色。

## 消息流程

```text
POST /api/v1/messages/propose
→ 返回 action_preview 和 confirmation_token
→ 老板确认
→ POST /api/v1/assistant/confirm
→ 创建站内消息
→ 发送飞书卡片
→ 已收到 / 需要协调 / 文字反馈
→ 回传发起人并记录审计
```

确认令牌短期有效、只能使用一次，并绑定动作与发起人。

## 可靠性

- 发送失败先执行有限次数即时重试。
- 最终失败写入 SQLite 发件箱。
- Windows 计划任务可每 5 分钟运行补偿脚本。
- 已成功或已回执通知不会重复发送。

配置与操作命令见 `docs/ACTION_HUB_SETUP.md`。

