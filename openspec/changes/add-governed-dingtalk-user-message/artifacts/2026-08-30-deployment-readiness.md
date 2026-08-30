## 2026-08-30 部署与 readiness 证据

### 范围

- 重建并部署 `api-server`、`dingtalk-mcp` 和 `external-action-worker`。
- 只记录 Tool/operation/handler 与容器健康状态；本文件不把代码部署描述为 Publication、角色授权、Job 可见性或真实外部发送成功。

### 结果

- `api-server`、`dingtalk-mcp`、`external-action-worker` 和其依赖的 `python-agent-runtime` 均为 healthy；API `/api/health` 返回 `status=ok`。
- 运行中 API Manifest 包含：
  - `dingtalk_send_robot_message`：schema hash `402f0f259941318877432487b3d6501339ec80958772acf532211406c6c82aca`，operation `dingtalk.robot.message.send`，target policy `current_source_conversation`。
  - `dingtalk_batch_send_message_to_users_by_robot`：schema hash `9ee9a3e064c1d66b1ee463440044927a88a3e4d62af1c9ffedfe057516e2734d`，operation `dingtalk.robot.batch_send_message_to_users`，target policy `explicit_enterprise_user_ids`。
- 运行中 DingTalk MCP mutation normalizer 同时注册旧当前来源 Tool 与新增用户批量 Tool。
- 运行中 external action worker dispatcher 同时注册 `dingtalk.robot.message.send` 与 `dingtalk.robot.batch_send_message_to_users`，初始化完整性检查通过。
- 旧 Tool 的模型描述、管理面名称和确认操作文案已明确为当前钉钉来源会话；identifier、输入 schema、operation、target policy 和 schema hash 未改变。

### 验证

- 定向 pytest：`97 passed`。
- Ruff：通过。
- `docker compose config --quiet`：通过。
- `openspec validate add-governed-dingtalk-user-message --strict`：通过。
- `git diff --check`：通过。

### 尚未证明

- 新 Agent/Application Publication、角色 grant 和全新 Job 中的新增 Tool 可见性。
- 单人/多人确认、取消、重复点击与真实钉钉外部收件结果。
- 旧 Job 不可见的现场证据。
