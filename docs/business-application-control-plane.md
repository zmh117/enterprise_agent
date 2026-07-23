# Business Application 控制面

## 职责边界

Business Application 是控制面装配和发布单元：

```text
Business Application
  ├─ Agent Publication（必选）
  ├─ Workflow Publication（可选）
  ├─ Trigger Binding
  ├─ Delivery Binding
  ├─ Session / Execution Policy
  └─ API Capability Reference（目录接入前必须为空）
```

它不复制 Agent 或 Workflow 草稿，不保存 Connector 凭据，也不访问数据库、
Redis 或 Loki。Identity/RBAC 决定谁能管理应用；Channel Connector 继续持有渠道
边界；未来 Capability Catalog 只提供受治理的业务 API 能力。

当前所有 API 响应都返回：

```json
{
  "runtime_wired": false
}
```

这表示发布和激活只更新控制面，不会切换钉钉、Webhook、RabbitMQ、Agent Job、
只读工具或 Delivery 的现有执行路径。

## 功能开关

默认关闭：

```dotenv
FEATURE_BUSINESS_APPLICATION_CONTROL_PLANE=false
```

关闭时真实管理写入口返回
`business_application_control_plane_disabled`。测试环境确认权限、迁移和回退后再开启。

## 数据模型

- `business_application`：稳定编码、项目、负责人、生命周期和并发 revision。
- `business_application_revision`：追加式草稿，旧修订不覆盖。
- `business_application_revision_trigger`：入口与确定性路由键。
- `business_application_revision_delivery`：非敏感投递引用。
- `business_application_revision_capability`：未来 Capability 引用。
- `business_application_publication`：不可变 canonical snapshot 和 SHA-256。
- `business_application_deployment`：环境级当前 publication 指针。
- `business_application_active_route`：数据库唯一约束保护的活动路由投影。

发布与激活分离。发布不会自动影响任何环境；历史 publication 可以显式重新激活。

## 本地 Seed

本地 seed 先建立平台管理员的以下权限：

```text
business_application.read
business_application.create
business_application.edit
business_application.publish
business_application.activate
```

依赖默认 Agent Publication 存在后，可以幂等创建未激活草稿：

```bash
FEATURE_BUSINESS_APPLICATION_CONTROL_PLANE=true \
  .venv/bin/python -m app.cli.seed_default_business_application
```

命令不会创建 deployment，也不会修改现有 Agent、Workflow 或 Job。

## 管理 API 示例

以下均为假标识。

创建：

```http
POST /api/admin/business-applications
Content-Type: application/json
X-CSRF-Token: <current-session-csrf>

{
  "code": "diagnostic-assistant",
  "name": "生产诊断助手",
  "description": "只读诊断控制面",
  "project_code": "default",
  "owner_user_id": "user_example_admin"
}
```

保存草稿：

```http
PUT /api/admin/business-applications/diagnostic-assistant/draft
Content-Type: application/json
X-CSRF-Token: <current-session-csrf>

{
  "expected_revision": 1,
  "agent_publication_id": "agent_publication_example_v1",
  "workflow_publication_id": "",
  "session_policy": {
    "conversation_mode": "channel",
    "recent_message_limit": 20,
    "retention_days": 30
  },
  "execution_policy": {
    "max_turns": 12,
    "timeout_seconds": 300,
    "max_tool_calls": 30
  },
  "triggers": [],
  "deliveries": [],
  "capabilities": []
}
```

校验与发布：

```http
POST /api/admin/business-applications/diagnostic-assistant/validate
{"revision_id":"business_app_revision_example"}
```

```http
POST /api/admin/business-applications/diagnostic-assistant/publish
{"revision_id":"business_app_revision_example"}
```

激活、历史回退与停用都使用 deployment 的 `expected_revision`：

```http
POST /api/admin/business-applications/diagnostic-assistant/environments/test/activate
{"publication_id":"business_app_publication_example","expected_revision":0}
```

```http
POST /api/admin/business-applications/diagnostic-assistant/environments/test/deactivate
{"expected_revision":1}
```

## 安全边界

- 所有写操作要求 Web Session、RBAC 和 CSRF。
- 具体应用无读取权限时按不存在处理，避免枚举。
- 草稿拒绝 URL、DSN、SQL、LogQL、Shell、Password、Secret、Token、Header、
  数据库、Redis 和 Loki 配置。
- Capability Catalog 未接入时，非空 Capability 可以留在草稿，但阻止发布。
- Snapshot、Resolver、审计和前端不返回 Connector Secret、Token、密码或完整敏感 URL。
- Webhook 只能使用已启用内部服务账号；钉钉入口使用当前发送人。

## 后续数据面接线前置清单

数据面接线必须使用单独 OpenSpec 变更，并全部满足：

1. 将现有入口 binding 显式迁移到 Business Application，禁止隐式全局切换。
2. 增加按 connector 和 routing key 的灰度开关。
3. 保留原默认 Agent 路径作为可操作回退。
4. 验证 Resolver 失败不会回退到其他业务应用。
5. 验证 actor 上下文由平台注入，模型不能修改。
6. 完成钉钉私聊、群聊、Webhook、RabbitMQ、只读工具和 Delivery 端到端测试。
7. 完成历史 publication 回退与入口 routing 回退演练。
8. 明确 `runtime_wired=true` 的唯一切换位置和审计事件。
