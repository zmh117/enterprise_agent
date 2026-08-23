# Business Application 控制面

## 职责边界

Business Application 是当前控制面装配、发布和路由单元：

```text
Business Application
  ├─ Agent Publication（必选，python-v1）
  ├─ Workflow Publication（可选）
  ├─ Trigger / Delivery Binding
  ├─ Session / Execution Policy
  ├─ Task File 与文档处理配置
  └─ MCP Tool 显式子集（必须属于 Agent Publication Envelope）
```

它不复制 Agent 或 Workflow 草稿，不保存 Connector 凭据，也不绑定 Resource
Revision。身份/RBAC 决定谁能管理和使用应用；Channel Connector 负责渠道边界；
`tool-mcp` 在调用时按目标和当前范围唯一解析 Published Resource Revision。

## 当前发布模型

- `business_application` 保存稳定身份、项目、负责人、生命周期和并发 revision。
- `business_application_revision` 是追加式草稿；旧 revision 不覆盖。
- revision 分别保存 Trigger、Delivery 与 MCP Tool 选择。
- `business_application_publication` 保存不可变 snapshot 与 SHA-256，并冻结 Agent、
  Workflow、Session/Execution Policy、文件能力、文档 Profile、Trigger、Delivery 和
  MCP Tool identifier/schema hash。
- `business_application_deployment` 只支持 `local` 环境，保存当前 Publication 指针。
- `business_application_active_route` 通过数据库唯一约束保证一个活动入口只归属一个应用。

发布和激活分离。保存草稿或创建 Publication 不会改变运行路径；只有显式激活后，
Resolver 才返回 `runtime_wired=true`。失败不会回退到另一个应用或全局默认 Agent。
历史 Publication 可以重新激活，但必须继续通过当前 Runtime、工具、文件和路由门禁。

## 功能开关

```dotenv
FEATURE_WEB_ADMIN=false
```

关闭时 API 不注册管理路由，Admin Web 容器也拒绝启动；公开钉钉/Webhook 入口、内部
Runtime 控制端点和服务 Principal 端点不因此自动消失。开启管理面不会自动激活任何
Application Publication，也不证明模型、MCP、Docling 或外部 Connector 已可用。

## 草稿契约

当前草稿可保存：

- `agent_publication_id`、可选 `workflow_publication_id`；
- `task_workspace_retention_period=DAY|WEEK|MONTH`；
- `document_processing_profile_code=NONE|docling-layout-ocr-v2`；
- `task_file_features` 四个有依赖顺序的布尔开关；
- `session_policy`、`execution_policy`；
- `triggers`、`deliveries` 和 `mcp_tools`。

文件开关依赖顺序为：

```text
workspace_enabled
  -> file_mcp_enabled
    -> runtime_file_edit_enabled
      -> default_file_delivery_enabled
```

启用工作区还要求连续会话和附件同时开启。草稿不接受 URL、DSN、SQL、LogQL、Shell、
Password、Secret、Token、Header 或数据库/Redis/Loki 连接配置。

示例只使用假标识：

```http
PUT /api/admin/business-applications/diagnostic-assistant/draft
Content-Type: application/json
X-CSRF-Token: <current-session-csrf>

{
  "expected_revision": 1,
  "agent_publication_id": "agent_publication_example_v1",
  "workflow_publication_id": "",
  "task_workspace_retention_period": "WEEK",
  "document_processing_profile_code": "NONE",
  "task_file_features": {
    "workspace_enabled": false,
    "file_mcp_enabled": false,
    "runtime_file_edit_enabled": false,
    "default_file_delivery_enabled": false
  },
  "session_policy": {
    "conversation_mode": "channel",
    "recent_message_limit": 20,
    "retention_days": 30,
    "continuous_conversation_enabled": false,
    "attachments_enabled": false
  },
  "execution_policy": {
    "max_turns": 12,
    "timeout_seconds": 300,
    "max_tool_calls": 30
  },
  "triggers": [],
  "deliveries": [],
  "mcp_tools": []
}
```

校验、发布和激活：

```http
POST /api/admin/business-applications/diagnostic-assistant/validate
{"revision_id":"business_app_revision_example"}

POST /api/admin/business-applications/diagnostic-assistant/publish
{"revision_id":"business_app_revision_example"}

POST /api/admin/business-applications/diagnostic-assistant/environments/local/activate
{"publication_id":"business_app_publication_example","expected_revision":0}
```

当前代码不接受 `test`、`staging` 或 `production` 作为 Business Application deployment
environment。停用同样只使用 `environments/local/deactivate` 和当前 expected revision。

## 安全与验收

- 所有管理写操作要求 Web Session、RBAC、可信 Origin、CSRF 和 revision 校验。
- 无具体应用读取权时按不存在处理，避免枚举。
- MCP Tool 必须属于 Agent Publication Envelope，并以相同 schema hash 冻结。
- Snapshot、Resolver、审计和前端不返回 Connector Secret、Token、密码或敏感 URL。
- 钉钉入口使用当前发送人；Webhook 使用已启用且受授权的内部服务账号。
- `runtime_wired=true` 只说明路由装配成立，不等于真实 Provider、MCP、文件处理或投递
  E2E 已完成。验收必须沿 Ingress/Outbox/Queue/Job/Runtime/MCP/Delivery 核对同一条证据链。
