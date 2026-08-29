# Governed DingTalk MCP

该服务是企业 Agent 的固定业务 MCP Server。MVP 只发布
`dingtalk_create_todo`：Agent 调用时只创建待确认 Action Intent，不直接调用钉钉
Provider；原用户在互动卡片中同意后，独立 Worker 才创建本人待办。

## MVP 边界

- 固定卡片模板：`0ad7c643-7e30-4797-8284-da5ef89d3841.schema`。
- 固定 Provider 操作：`POST /v1.0/todo/users/{unionId}/tasks`。
- 目标只能是当前 Job 对应的启用钉钉身份，Tool 参数不接受用户 ID、Union ID、URL、Header 或凭据。
- 卡片使用同一企业应用的 Stream 回调，`outTrackId` 等于 Action Intent ID，并禁止转发。
- 服务端强制校验 Runtime lease、Connector、corp、点击人、意图签名、revision 和状态；端侧按钮状态不构成授权。
- `agree` 才进入 Provider 执行队列；`reject` 永不执行；MVP 的 `revise` 只返回“不支持”卡片提示，不会生成新意图。
- Provider 写入结果不确定时进入 `FAILED_UNCERTAIN`，禁止自动重放，以免重复创建待办。

## 运行组件

- `dingtalk-mcp`：Principal JWT 鉴权、输入校验、Action Intent 准备与 MCP 审计。
- `dingtalk-runtime`：每个 Client ID 的唯一 Stream 生命周期，同时接收机器人消息和卡片回调。
- `api-server`：内部 `/api/admin/managed-channels/runtime/card-actions` 快速确认端点。
- `external-action-worker`：卡片 Outbox 和已批准 Provider 操作的 claim/执行/结果更新。

生产启用前必须通过管理端配置并验证钉钉企业、Stream Connector、当前用户外部身份和业务应用 Tool 授权。凭据只使用平台 Secret 引用；不要把 Client Secret、Access Token 或原始业务消息写入参数、日志、审计或此文档。

## 分阶段升级计划

1. 完成当前模板字段的真实环境合同验证、结果卡片细化和 `revise` 新 revision/重新确认流程。
2. 增加受治理的待办查询、详情和完成操作；每个 mutation 独立声明 `effect=mutation` 与 `external_action_card_v1`，不得复用只读授权绕过确认。
3. 扩展通讯录、文档、会话等能力；按企业与应用隔离身份，评估用户 OAuth，仅在确有用户级 Provider 权限语义时引入。
4. 为 ONES 新增修改/创建接口时复用同一 Action Intent、卡片确认、执行前重新授权和不确定结果边界；现有 ONES 只读 Tool 保持 `effect=read`、`confirmation_policy=none`。

真实 E2E 必须使用明确授权的测试用户和目标，覆盖 Job → 卡片 → 同意/拒绝 → 待办 → 结果卡片，并仅记录不含 Secret 与原始消息的证据。
