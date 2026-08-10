# 治理控制台端到端矩阵

该矩阵是恢复顺序与验收入口。`待补` 表示当前代码没有满足本 change 的安全 API，不允许由静态数据替代。

| 页面 | 路由 | 后端 API/事实源 | 代码拥有权限 | Mutation 治理 | 审计动作 | 必须覆盖的负向授权 |
| --- | --- | --- | --- | --- | --- | --- |
| Dashboard | `/` | 待补 `/api/admin/dashboard` | `dashboard.read` | 只读、范围过滤 | `dashboard.view` 可选低风险记录 | 无权限不返回聚合；不可见对象不计数 |
| Agent | `/agent-profiles`、`/:agentCode` | `/api/admin/agent-profiles` | `agents.read/edit/publish` | CSRF、revision、幂等、校验、不可变 Publication | create/update/validate/publish/rollback | 跨范围不可枚举；并发 revision 冲突 |
| Application | `/applications`、`/:code` | `/api/admin/business-applications` | `applications.read/create/edit/publish/activate` | CSRF、revision、幂等、激活影响确认 | create/update/validate/publish/activate/deactivate | 不可见应用 404；未授权环境操作拒绝 |
| 渠道/触发器 | `/applications/channels` | `/api/admin/managed-channels` | `channels.read/manage/test` | CSRF、version、幂等、Credential ID、受控测试 | create/update/enable/disable/restart/test/delete | 禁止任意 adapter/Header/secret ref；跨企业拒绝 |
| Job/Session 历史 | `/operations/jobs`、详情、会话 | `/api/me/*`；管理员 API 待补 | `jobs.read/cancel`，本人只读为不可分配能力 | 取消需 CSRF、version、幂等 | job.view/cancel | 历史不可枚举；旧 Job 不跟随当前配置 |
| 发起调试 | `/operations/debug` | 管理 Debug API 待补 | `jobs.debug` | 服务端固定主体与运行边界、CSRF、幂等 | debug_job.create | 拒绝覆盖主体、Publication、Resource、Tool、投递目标 |
| 用户目录 | `/users`、`/:userId` | 管理用户 API 待补 | `users.read/manage/sessions.revoke` | CSRF、version、幂等、防最后管理员锁死 | user.create/update/enable/disable/session.revoke | 服务账号无 Web 权限；跨范围不可枚举；防自提权 |
| 角色授权 | `/users/roles`、`/:roleCode` | 角色授权 API 待补 | `roles.read/manage/simulate` | 原子授权区、expected revision、幂等 | role.create/update/members/access/scope | 显式拒绝优先；防自提权；无 API Capability 字段 |
| 身份治理 | `/users/identities`、`/users/dingtalk-discovery` | 当前 External Credential API；候选 API 待补 | `identities.read/manage` | 可信候选绑定；ONES 仅本人两阶段验证 | identity.bind/unbind/recover | 禁止管理员提交 ONES 密码/Token/user UUID 或任意钉钉 subject |
| MCP Server | `/mcp/servers` | `/api/admin/mcp/status` | `mcp_servers.read/check` | 仅固定健康检查；无 CRUD | mcp_server.health_check | 未知 Server、URL、Header、Auth 输入拒绝 |
| Tool Publication | `/mcp/tools` | `/api/admin/mcp/tools`、`/tool-publications` | `mcp_tools.read/manage` | CSRF、revision、幂等、精确 Resource Deployment | tool_publication.create/update/publish/disable/rollback | 伪造 Tool/Schema/Server、通配资源、错误 kind 拒绝 |
| Resource | `/mcp/resources`、`/:code` | `/api/admin/mcp/resources` | `mcp_resources.read/manage` | 服务端 Schema、CSRF、revision、验证、发布、LKG | resource.create/update/verify/enable/disable | 明文密码、任意驱动参数、跨范围绑定、停用依赖拒绝 |
| Credential | `/mcp/credentials`、`/:code` | `/api/platform/secrets`（收紧后） | `secrets.read/manage` | CSRF、version、幂等、依赖保护、仓库外 Master Key | credential.create/rotate/disable | 任何 secret ref/value/ciphertext/nonce/tag/key 泄漏均失败 |
| 账户安全 | `/account/security` | `/api/auth/password`、`/sessions` | 本人能力 | CSRF、当前密码/会话校验 | password.change/session.revoke/logout | 不得操作他人会话；错误不得泄漏 Hash/Token |

## 横切验收规则

1. 所有管理页面先经过登录 Gate，再经过代码拥有权限 Gate；仅隐藏导航不算授权。
2. 所有管理列表按当前用户对象范围过滤，使用稳定排序和分页；不可见详情与不存在详情保持相同语义。
3. 所有 mutation 使用 CSRF、幂等键和 expected revision/version，并在前端呈现中文冲突刷新路径。
4. 审计仅记录安全摘要、对象 ID、revision、结果与 correlation ID；不记录请求原文、Secret、Token、Tool 参数/结果或上游原始错误。
5. 浏览器不得接收或缓存 Secret Ref/Value/Ciphertext、Provider Token、MCP Authorization、数据库密码或连接敏感字段。

