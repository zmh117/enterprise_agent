## Why

当前 canonical baseline 合并了多个不同阶段的规格，部分旧条款已经被后续实现取代，或从未进入当前代码，导致同一规范同时描述互相矛盾的行为。需要以当前代码、migration、Compose 和可执行测试为事实依据，删除无实现的计划性合同并收敛仍然有效的运行边界。

## What Changes

- 修正 Agent Runtime 为仅可新建和执行 `python-v1`，保留历史 `typescript-v1` 事实只读；删除“新建 TypeScript Agent”和“双内置 Agent”合同。
- 将 Business Application 的装配事实收敛为 Agent/Workflow Publication、Trigger、Delivery、策略和代码 Manifest 的 MCP Tool 子集；删除旧 API Capability/Handler 引用及未实现的旧 Job 破坏性迁移合同。
- 将公共 Webhook 认证收敛为当前实现的强 Bearer Token，删除未实现的 HMAC 配置合同，并按当前代码区分钉钉 ingress 与 delivery connector 类型。
- 将 ONES 规范改为当前两个代码固定只读 Tool、代码拥有的 GraphQL/REST Operation，以及加密 Challenge/credential 生命周期；删除“仅一个 Tool”“不保存调用凭据”等旧事实。
- 删除没有 CLI、表、服务或测试实现的身份与授权全量重置合同，并把通用 Connection/Claim 模型收敛为当前 `provider + tenant_code + external_subject_id` 身份模型。
- 将 `tool-mcp` 身份边界改为当前 Job-context Header 和实时 Job/授权复核，不再描述已删除的 Internal API Bearer Token/Handler。
- 修正 Runtime 规格中的旧类名、旧 Capability/Handler 术语和固定单一 MCP Server 描述，使其与当前 Python Runtime 多固定 Server 装配一致。
- 修正 Compose 管理 Web 条款：当前默认 Compose 包含 `admin-web` 服务，但 `FEATURE_WEB_ADMIN=false` 时入口脚本退出且不得提供管理页面；不再声称当前使用 admin profile。
- 不新增代码、配置项、兼容分支、服务、API 或未来扩展点；未被代码明确反证的 canonical 条款保持不变。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `agent-model`: 收敛 Agent 创建、bootstrap 与历史 Runtime 合同。
- `business-application`: 收敛当前草稿/发布装配字段与真实运行状态。
- `channel-conversation`: 收敛 Webhook 认证和钉钉 Connector 方向。
- `governed-api-capability`: 对齐当前 ONES Tool、Operation 与加密 credential 行为。
- `identity-access`: 删除未实现的身份全量重置与 Claim/Connection 合同，并对齐当前身份、凭据和 Tool 授权。
- `builtin-tool-resource`: 对齐 `tool-mcp` 的 Job-context 调用身份与固定 MCP Server 集合。
- `execution-delivery`: 对齐当前 Python Runtime 类、MCP binding 和业务 Tool 术语。
- `platform-operations`: 对齐当前单 Runtime 状态和 Compose 管理 Web 失败关闭方式。

## Impact

仅修改 OpenSpec change artifacts 与上述八个 canonical spec。运行代码、migration、Compose、前端、测试、依赖和部署状态均不改变。`document-file-processing` 与 `task-file-workspace` 未发现需要本 change 修正的已确认冲突，因此不产生 delta。
