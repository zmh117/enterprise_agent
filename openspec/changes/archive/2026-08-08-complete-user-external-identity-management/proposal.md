## Why

后端已经具备内部用户、Web Session、RBAC、钉钉身份绑定和通用外部身份表，但管理 Web 仍没有可用的“用户与外部身份”工作区，ONES 身份也没有可信的验证绑定链路。现在需要只完成这一个管理模块，让管理员能够维护内部用户并把同一人员关联到钉钉和 ONES，其他控制面功能继续保持现状。

## What Changes

- 新增真实的用户列表、用户详情、新建、编辑、启用和停用界面，复用现有受 Session、CSRF 和 RBAC 保护的用户 API。
- 在用户详情中集中展示该用户的外部身份，并支持钉钉身份和 ONES 身份的绑定、启用、停用和解绑。
- 钉钉绑定继续使用受信 DingTalk Stream Connector 的 tenant 与 `senderStaffId`，保持 `provider + tenant + external_subject_id` 唯一且未知发送者不自动建用户。
- ONES 绑定通过服务端对受信 ONES 实例执行一次性登录验证，只保存 ONES 用户 UUID、显示名称和团队 UUID；邮箱、密码、返回 Token 和原始响应不得持久化、审计或返回前端。
- 外部身份记录保持 Provider 可扩展的数据模型，但第一版页面和写接口只开放 `dingtalk` 与 `ones`，不实现其它 Provider 的适配器或任意手工身份类型。
- 复用现有 `user:manage`、`identity:manage` 权限和统一认证，不新增功能开关，不重做登录、角色、权限、Session、审计日志页面。
- 使用现有独立 ONES Mock 完成开发与自动化验收；本变更不调用 ONES 需求、任务、缺陷接口，不为 Agent 暴露 ONES API Capability。
- 本 change 取代 `connect-admin-auth-and-external-identity-management` 中尚未实施的用户/外部身份范围；旧提案中的安全设置、自助验证、Connection 管理、冲突治理中心等扩大范围不在本次实施。

## Capabilities

### New Capabilities

- `admin-user-directory`: 认证管理员对内部自然人用户执行列表、查看、新建、编辑、启停，以及在用户详情中进入外部身份管理的行为契约。
- `dingtalk-ones-identity-binding`: 钉钉与 ONES 外部身份的可信绑定、唯一性、状态、解绑、ONES 一次性验证和敏感信息边界。

### Modified Capabilities

无。现有认证、RBAC、钉钉 Stream 入口、Agent Runtime 和业务应用控制面行为保持不变。

## Impact

- 数据库：复用现有 `user_external_identity`、`verified_at` 和受控 `metadata_json`，不新增 Claim/Connection 等治理表；保持现有唯一约束和钉钉绑定兼容。
- 后端：扩展 Identity Repository、应用服务和 `/api/admin` 用户/身份接口，增加固定协议的 ONES 身份验证适配器。
- 前端：新增 `contexts/users` 和完善 `contexts/external-identities`，接入真实管理 API，并启用“用户与外部身份”导航。
- 配置与测试：增加受信 ONES 身份验证端点的非敏感配置，复用 `docker-compose.ones-mock.yml`，补充后端、前端和浏览器端到端测试。
- 明确不影响：角色与授权、业务应用、Workflow、Agent Profile、Skill、API Capability、Channel 管理、运行中心和附件管理。
