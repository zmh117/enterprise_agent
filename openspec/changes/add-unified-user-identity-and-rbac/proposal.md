## Why

当前 Web 管理接口依赖可伪造的 `x-admin-user-id`，钉钉入口又直接把 `senderStaffId` 当作权限主体，导致 Web 用户、钉钉用户、角色授权和 Agent 工具权限无法形成同一套可信身份链路。与此同时，Agent 的角色、模型、工具集合和业务指令仍主要由全局配置或代码决定，无法安全地通过 Web 管理、发布和回滚。

## What Changes

- 建立内部用户作为唯一权限主体，并通过通用外部身份表关联本地登录身份和钉钉企业用户身份。
- 第一版支持管理员在 Web 手工绑定钉钉 `tenant/corp + senderStaffId`；未绑定、已禁用或冲突身份默认拒绝进入 Agent。
- 增加本地用户名密码登录、服务端 session、退出、密码安全存储和当前用户接口，同时预留 OIDC/企业 SSO 与一次性钉钉绑定码扩展边界。
- 增加用户、角色、用户角色关系和统一 RBAC 求值器；用户直接策略、角色策略、平台数据范围、工具范围和显式 deny 共同决定最终权限。
- 让 Web 登录、钉钉入口、Agent job、工具调用、平台配置和工作流管理都使用同一个内部用户 ID，并在审计中保留安全的外部身份来源引用。
- 增加多 Agent 配置模型，支持 Agent 定义、草稿 revision、不可变发布快照、校验、发布和回滚；第一版 UI 只展示和管理一个预置的默认只读诊断 Agent。
- 默认诊断 Agent 可配置业务指令、模型策略、执行限制、只读工具分配、Skill 分配、默认项目和 Channel/Delivery 绑定；平台安全规则和写工具禁用边界不可由 Web 覆盖。
- Agent job 创建时解析并固定 `agent_id`、发布 revision 和配置 hash，worker 只读取该不可变发布快照，避免编辑中的草稿或后续发布改变已排队任务。
- 增加管理端 Web 基础框架与登录、用户、角色、钉钉身份绑定、默认诊断 Agent、工具分配、发布历史和有效配置预览页面。
- 对用户启停、角色授权、身份绑定、Agent 草稿修改、发布、回滚和权限拒绝写入审计。
- 第一版不支持 Web 动态创建任意 HTTP API、MCP、代码、Shell、写 SQL 或其他可执行工具；动态只读 HTTP API 工具作为后续独立 change。

## Capabilities

### New Capabilities

- `unified-user-identity`: 内部用户、本地登录身份、钉钉外部身份、绑定生命周期和跨入口统一主体解析。
- `web-admin-authentication`: 管理端本地登录、服务端 session、当前用户、退出、会话失效与可信 actor 注入。
- `role-based-access-control`: 用户角色、直接/角色策略、deny 优先、工具与平台数据范围的统一权限求值。
- `multi-agent-configuration`: 多 Agent 定义、草稿 revision、发布快照、回滚、默认诊断 Agent和运行时版本固定。
- `web-admin-console`: 第一版管理端 Web 外壳及用户、角色、钉钉绑定、默认 Agent、工具分配和发布历史页面。

### Modified Capabilities

- `agent-audit-permission`: job、工具和配置管理权限改为基于已解析的内部用户及其角色，并审计身份解析与绑定结果。
- `dingtalk-agent-ingress`: 钉钉 Stream 用户必须通过 tenant/corp 与 `senderStaffId` 解析到启用的内部用户后才能创建 job。
- `platform-config-api`: 写接口从调用方自报请求头 actor 改为可信管理端 session actor，并继续执行平台配置权限检查。
- `agent-job-lifecycle`: job 必须记录内部请求人以及固定的 Agent 发布版本和配置 hash。
- `claude-agent-runtime-integration`: Agent runtime 从固定发布快照读取可配置业务指令、模型策略、执行限制、Skill 和只读工具集合，同时保持不可编辑安全边界。
- `readonly-tool-platform`: 工具可用性同时受工具启用状态、Agent 工具分配、用户/角色工具权限和平台数据范围约束。

## Impact

- PostgreSQL 将新增用户、外部身份、登录凭证/session、角色关系、Agent 定义/revision/publication/绑定及安全审计相关表，并对 job 增加 Agent 版本固定字段。
- 钉钉 Stream ingress、Channel identity、权限服务、平台访问策略、工具 registry、job 创建、worker 和 AgentContextBuilder 将接入统一身份与 Agent 发布快照。
- 现有按原始钉钉 ID 保存的用户权限需要可审计迁移；历史 session/job/audit 保留原值或 legacy 映射，不破坏历史追溯。
- 平台配置和工作流 API 将使用认证 middleware 注入的内部 actor，不再信任公网请求直接提交的身份头。
- 仓库将新增独立前端工程及其 Compose/API 集成；第一版只开放默认诊断 Agent，但数据模型和 API 支持后续增加多个 Agent。
- 密钥继续通过现有 secret reference 与加密存储管理，Web、API、日志、session 和审计不得返回密码 hash、session token 或外部身份敏感载荷。
