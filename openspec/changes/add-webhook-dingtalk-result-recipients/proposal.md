## Why

Webhook 配置没有可用的钉钉群/用户接收人编辑器，当前单一 Delivery 路由无法可靠投递给多个对象，业务应用还会覆盖 Trigger 目标。停用错误地依赖入口健康，旧页面缓存也让用户持续看到已被替换的创建表单。

## What Changes

- 在 Webhook 配置中添加结果接收人列表：选择受管钉钉应用机器人，选择群或用户并填写稳定目标 ID，可配置多个对象；发送 Agent 终态结果或安全失败通知。
- 发布冻结接收人，业务应用显式选择使用 Webhook 结果配置，避免双重目标配置。每个对象独立创建 Delivery Outbox，独立重试和审计。
- 钉钉应用机器人增加受限的主动群/单聊结果投递能力，复用已有受管凭据及 Agent 授权，不把 Stream 入口变成任意 URL 投递器。
- 修复入口异常、未保存编辑阻止停用的问题，卡片直接提供停用入口；设置入口 HTML 缓存策略，使重新加载获取当前发布。

## Capabilities

### New Capabilities

无新增 canonical 领域。

### Modified Capabilities

- `channel-conversation`：Webhook 接收人 Web 配置与独立停用。
- `execution-delivery`：冻结目标列表、群/用户适配、逐目标幂等和独立重试。
- `business-application`：显式使用 Webhook 发布中的结果投递配置。
- `agent-model`：受管机器人结果投递的显式 Connector 授权。
- `platform-operations`：管理页面部署后的入口 HTML 缓存策略。

## Impact

依赖尚未提交的 `fix-webhook-first-use-management` 实现；不重写或补改其历史验收。涉及 Webhook、Channel、Agent/业务应用校验、Delivery Outbox 与 Web 表单、Nginx；需要变更 Outbox 唯一键以支持同一结果的多目标投递。测试只使用合成报文和假钉钉传输，不修改现有凭据，不向真实群或用户发送消息，不提交或推送代码。
