# Capability 使用资格来自 Agent 与应用配置

本决定取代 ADR-0028。API Connection、API Capability、业务应用和个人凭据的管理权限仍采用操作级 RBAC，但运行时不再设置逐用户或逐角色 Capability Code `use` Grant。`ACTIVE` Capability Release 发布后进入 Agent 与应用配置候选目录；Agent Publication 按 ADR-0040 为每个 Capability Code 选择至多一个精确 Release 并冻结 Agent Capability Envelope，Application Publication 选择精确 Agent Publication 后只能从该上限中显式选择并冻结 Application Capability Allowlist，后端必须拒绝越过 Agent 上限的配置。Agent 或能力集合变化通过新 Agent Publication 交付，并按 ADR-0038 由应用显式升级。钉钉用户按 ADR-0039 取得业务应用访问权后，即取得该应用 Allowlist 的调用资格；应用未选、Agent 未选或 Release 不可用的 Capability 不得暴露或执行。每次 Tool 暴露和执行仍须校验应用访问、Agent 上限、应用子集、Release 状态以及当前用户自己的 ONES 身份、默认 Team 和有效 Token。

管理权限继续使用 `api_connections.read/manage/verify/publish`、`api_capabilities.read/manage/test/verify/publish`、既有 Agent 与应用编辑发布权限，以及 `external_credentials.self_manage/read/disable/unbind`；这些管理权限不能授予运行时应用访问。管理员 Verify/Test 只能使用自己的 ONES 身份和凭据。
