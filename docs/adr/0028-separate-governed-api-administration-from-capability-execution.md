---
status: superseded by ADR-0037
---

# API 治理管理权限与 Capability 执行授权分离

API Connection 使用 `api_connections.read`、`api_connections.manage`、`api_connections.verify` 和 `api_connections.publish`；API 能力配置使用 `api_capabilities.read`、`api_capabilities.manage`、`api_capabilities.test`、`api_capabilities.verify` 和 `api_capabilities.publish`。`test` 只发起受控调用，`verify` 才能在成功后改变 Draft 生命周期状态。业务应用继续使用既有编辑和发布权限，运行时另以具体 Capability Code 的 `use` 操作授权，三层权限互不隐含。个人凭据通过 `external_credentials.self_manage` 由本人绑定、重新验证或解绑，接口必须从认证会话取得本人身份；管理员只可使用 `external_credentials.read`、`external_credentials.disable` 和 `external_credentials.unbind` 查看元数据或执行应急治理，不能查看 Token、代输密码、代为绑定或重新验证。管理员 Verify/Test 即使拥有凭据治理权限，也只能使用自己的 ONES 身份、默认 Team 和 Token。
