## Why

MCP 切换删除了旧 API/Internal Platform，也同步移除了人员、角色、身份、资源、凭据、调试和平台总览等高频治理页面，导致当前系统虽然保留安全运行事实，却缺少可维护、可复核的 Web 控制面。现在需要基于当前 MCP 与 TypeScript Agent Runtime 架构恢复完整治理控制台，同时避免把已经退役的 API Capability、Resource Mapping 和通用执行平台重新带回系统。

## What Changes

- 保留并验收当前多 Agent 与多 Application 工作区，覆盖 Agent Draft/校验/Publication/历史/回退，以及 Application Draft/校验/Publication/历史/环境激活与停用。
- 恢复认证后的真实总览、渠道与触发器、发起调试、Job/会话历史、人员与账号、角色与授权、本人外部身份、身份治理和未绑定钉钉用户页面；所有页面使用真实 API，不恢复静态 fixture。
- 将旧“平台治理”重构为“MCP 配置”，统一展示代码或 Compose 注册的受信 MCP Server 状态、MCP Tool 目录与 Publication、数据库/Redis/Loki Resource、凭据及安全使用关系。
- MCP Server 只允许从服务端固定受信注册表读取；Web 不得提交任意 Server URL、Transport、Tool 名、Schema、认证 Header 或动态 MCP 配置。
- Resource 页面只呈现“启用/停用”主状态以及新建、编辑、启用、停用操作；后端继续保留 Draft、验证、不可变 Revision、Deployment、Generation 和 Last Known Good，避免简化 UI 破坏运行安全。
- Data MCP Tool Publication 可以选择一个精确受治理 Resource Deployment；该绑定不提供字段映射、规则引擎、自由查询或 Application Resource Mapping。
- 恢复凭据中心，继续使用仓库外 Master Key 与 AES-256-GCM-AAD 加密数据库持久化；页面支持创建、轮换、停用和用途查看，但永不回显明文、密文、Master Key 或可复制的内部 Secret Ref。
- 恢复人员/账号、角色和外部身份治理，复用统一 `app_user`、RBAC 与外部身份事实；不新建第二套人员模型。角色只配置代码拥有的管理权限、Application 使用权限、成员和业务数据范围，不出现 API Capability 或 Resource Mapping。
- 恢复受限调试和运行历史，保持当前用户/授权范围、防枚举与敏感字段脱敏，不允许覆盖 Job 主体、Publication、Resource、Credential 或 MCP Server。
- OpenTelemetry 本次不实施；设计预留 W3C Trace Context 从 Python Worker 到 TypeScript Runtime 与 MCP 的传播边界，以及后续 OTLP Collector 接入点，禁止采集 Prompt、回复正文、Tool 参数/结果和凭据材料。
- **BREAKING** 旧 `/platform/api-capabilities`、Capability/Handler/Connection 页面与旧 Resource Mapping 继续保持退役；不得通过别名、隐藏路由、Feature Flag 或备份代码恢复。

## Capabilities

### New Capabilities

- `mcp-governance-console`: 认证 Web 中的受信 MCP Server、Tool Publication、Resource 与凭据统一治理工作区及其安全交互边界。

### Modified Capabilities

- `web-admin-console`: 从轻量用户门户恢复权限感知的完整 MCP 治理导航和页面，同时继续排除已退役 API Capability 与 Resource Mapping。
- `agent-control-plane-dashboard-prototype`: 将静态原型总览改为只读取真实安全聚合数据的 MCP 控制面总览。
- `admin-user-directory`: 恢复统一人员与账号的列表、详情、新建、编辑、启停、Session、角色和身份摘要管理。
- `role-authorization-admin-console`: 恢复角色列表、详情、成员、管理权限、Application 使用权限和数据范围配置，移除 API Capability 配置区。
- `role-authorization-model`: 角色授权只使用代码拥有的管理能力与 Application 访问事实，不再依赖 API Capability 或旧 Resource Mapping。
- `business-application-role-access`: 将角色的业务访问上限改为 Application 与其固定 MCP Tool/Resource 安全边界，不保存已退役 Capability 授权。
- `governed-tool-resource-management`: 在保留安全发布与运行生命周期的同时，将 Web 主状态和操作收敛为启用、停用、新建和编辑。
- `platform-secret-management`: 恢复凭据中心和资源表单安全凭据交互，继续使用加密数据库 Secret Provider 且永不回显 Secret。
- `channel-connector-configuration`: 恢复渠道与触发器治理入口，并只允许受信 Connector 类型及安全配置字段。
- `agent-job-debug-api`: 恢复权限受限的发起调试与运行历史页面，不允许客户端覆盖不可变运行主体和依赖。
- `unbound-dingtalk-identity-discovery`: 恢复候选列表、徽标、人员选择/新建和受信绑定流程。

## Impact

- 前端：重建导航、总览、MCP 配置、人员、角色、身份、渠道和调试上下文；从 `bak/frontend` 只选择交互与组件结构，不复制旧 API Client、Capability、Resource Mapping 或静态演示数据。
- 后端：恢复/重建人员、角色、身份发现、渠道、调试和聚合总览管理路由；为 MCP Resource 与凭据提供面向 Web 的安全 DTO 和编排 API；扩展代码拥有的管理权限目录。
- 数据库：复用现有 `app_user`、RBAC、外部身份、MCP Tool/Resource/Deployment、平台 Secret、Job 和审计表；不恢复已删除的 Capability/Handler/Connection/Mapping 表，不迁移旧数据。
- 运行时：Agent、Application、Job、MCP Token、Resource Generation、Secret 解析和 TypeScript Runtime 边界保持不变；控制面写操作继续使用 Session、CSRF、RBAC、expected revision、幂等键和审计。
- 依赖关系：本变更以 `simplify-platform-with-mcp` 和 `migrate-agent-runtime-to-typescript` 的当前 MCP/Publication 实现为前置基线，不从 `master` 回搬旧平台。
