# dingtalk-ones-identity-binding Specification

## Purpose
TBD - created by archiving change complete-user-external-identity-management. Update Purpose after archive.
## Requirements
### Requirement: 外部身份提供方范围固定

系统 SHALL 在本阶段仅允许管理员为人类用户管理 `dingtalk` 和 `ones` 两类外部身份，并 SHALL 拒绝任意自定义提供方写入。

#### Scenario: 获取可用身份提供方

- **WHEN** 管理员打开用户的外部身份区域
- **THEN** 系统 SHALL 返回钉钉和 ONES 两个受支持提供方及其可配置字段

#### Scenario: 请求不支持的提供方

- **WHEN** 客户端尝试创建非 `dingtalk` 或 `ones` 的外部身份
- **THEN** 系统 SHALL 拒绝请求且不得写入身份记录

### Requirement: 管理员绑定钉钉身份

系统 SHALL 允许具备 `identity:manage` 权限的管理员使用受信任的钉钉连接器、租户和 `senderStaffId` 为人类用户绑定钉钉身份。

#### Scenario: 绑定有效钉钉身份

- **WHEN** 管理员选择已配置的钉钉连接器并提交租户和有效 `senderStaffId`
- **THEN** 系统 SHALL 创建启用的钉钉身份、记录验证来源，并在用户详情中显示绑定结果

#### Scenario: 连接器和租户不匹配

- **WHEN** 管理员提交的钉钉租户不属于所选受信任连接器
- **THEN** 系统 SHALL 拒绝绑定，且不得创建身份记录

#### Scenario: 同一用户重复提交相同钉钉身份

- **WHEN** 相同钉钉身份已绑定到目标用户
- **THEN** 系统 SHALL 幂等返回现有绑定，不得创建重复记录

#### Scenario: 钉钉身份已属于其他用户

- **WHEN** 相同租户和 `senderStaffId` 已绑定到另一个用户
- **THEN** 系统 SHALL 返回冲突错误，不得自动覆盖或迁移绑定

### Requirement: ONES 身份通过服务端登录验证

系统 SHALL 使用服务端配置的受信任 ONES 实例和固定登录端点验证管理员输入的 ONES 邮箱与一次性密码，并 SHALL 使用响应中的用户 UUID 作为外部身份标识。

#### Scenario: ONES 凭据验证成功

- **WHEN** 管理员为目标用户提交 ONES 邮箱和有效的一次性密码
- **THEN** 系统 SHALL 调用固定的 `/project/api/project/auth/login` 端点，校验响应结构，并保存 ONES 用户 UUID、显示名称、实例编码、团队 UUID 列表和验证时间

#### Scenario: ONES 凭据无效

- **WHEN** ONES 登录接口拒绝邮箱或密码
- **THEN** 系统 SHALL 返回安全且可理解的验证失败结果，不得创建候选或失败身份记录

#### Scenario: 管理员尝试手工填写 ONES UUID

- **WHEN** 绑定请求包含手工指定的 ONES 用户 UUID、令牌、团队或目标 URL
- **THEN** 系统 SHALL 拒绝这些客户端控制的可信字段，身份数据必须来自受信任 ONES 登录响应

#### Scenario: 同一 ONES 身份重复绑定

- **WHEN** 经验证的 ONES UUID 已绑定到目标用户
- **THEN** 系统 SHALL 幂等更新允许更新的展示信息和验证时间，不得创建重复记录

#### Scenario: ONES 身份已属于其他用户

- **WHEN** 经验证的 ONES UUID 已绑定到另一个系统用户
- **THEN** 系统 SHALL 返回冲突错误，不得自动覆盖或迁移绑定

### Requirement: ONES 验证网络边界受控

系统 SHALL 从服务端配置读取 ONES 实例地址，并 MUST 对网络目标、协议、重定向、超时、响应大小和响应结构实施限制。

#### Scenario: 生产环境使用非 HTTPS 地址

- **WHEN** 生产环境配置了非 HTTPS 的 ONES 身份地址
- **THEN** 系统 SHALL 拒绝启动或拒绝执行 ONES 身份验证

#### Scenario: 本地 Mock 使用 HTTP

- **WHEN** 开发测试环境明确启用本地非安全协议且目标属于允许主机
- **THEN** 系统 MAY 使用 HTTP 调用 ONES Mock

#### Scenario: ONES 返回重定向或超大响应

- **WHEN** ONES 登录端点返回重定向或超过配置上限的响应
- **THEN** 系统 SHALL 中止验证并返回安全错误，不得跟随重定向或继续解析超大响应

#### Scenario: ONES 响应结构不符合约定

- **WHEN** 登录响应缺少用户 UUID 或响应字段类型不正确
- **THEN** 系统 SHALL 视为验证失败且不得创建或更新身份

### Requirement: ONES 凭据和令牌不得持久化

系统 MUST NOT 将 ONES 明文密码、登录响应令牌或原始登录响应保存到数据库、缓存、日志、审计详情、错误信息或前端状态持久层。

#### Scenario: ONES 登录成功并返回令牌

- **WHEN** ONES 登录响应包含用户令牌
- **THEN** 系统 SHALL 在当前验证请求内丢弃令牌，仅保留允许的身份字段

#### Scenario: ONES 登录失败

- **WHEN** 网络调用或登录验证失败
- **THEN** 日志和审计事件 SHALL 仅包含脱敏错误分类、目标实例编码和请求追踪信息，不得包含邮箱密码、令牌或原始响应

#### Scenario: 绑定对话框关闭

- **WHEN** ONES 绑定成功、失败或用户关闭对话框
- **THEN** 前端 SHALL 清空密码字段且不得把密码写入 URL、本地存储或会话存储

### Requirement: 外部身份生命周期可管理

系统 SHALL 在用户详情中展示钉钉和 ONES 身份，并支持启用、停用和软解绑；所有变更 SHALL 使用版本号保护并保留审计轨迹。

#### Scenario: 停用外部身份

- **WHEN** 管理员使用当前 `expected_revision` 停用一个外部身份
- **THEN** 系统 SHALL 将其标记为停用、递增版本号并保留身份记录

#### Scenario: 软解绑外部身份

- **WHEN** 管理员确认解绑并提交当前 `expected_revision`
- **THEN** 系统 SHALL 将身份标记为已解绑而不是物理删除，并记录操作者和时间

#### Scenario: 并发修改外部身份

- **WHEN** 管理员使用过期的 `expected_revision` 修改身份
- **THEN** 系统 SHALL 返回冲突错误且不得覆盖较新的状态

### Requirement: 身份状态参与运行时身份解析

钉钉消息入口 SHALL 仅把启用用户的启用钉钉身份解析为系统用户；ONES 身份在本阶段 SHALL 仅作为账号关联信息，不得触发 ONES 业务调用。

#### Scenario: 启用用户通过启用钉钉身份发消息

- **WHEN** 钉钉消息来自已绑定且启用的身份，并且系统用户处于启用状态
- **THEN** 系统 SHALL 解析到该系统用户并继续执行现有授权和 Agent 流程

#### Scenario: 停用或解绑的钉钉身份发消息

- **WHEN** 钉钉消息来自停用或已解绑的身份
- **THEN** 系统 SHALL 按未映射身份拒绝处理，并通过现有安全错误投递路径返回可理解结果

#### Scenario: 已停用用户的钉钉身份发消息

- **WHEN** 钉钉身份本身启用但所属系统用户已停用
- **THEN** 系统 SHALL 拒绝创建 Agent 请求，不得绕过用户状态

#### Scenario: 保存 ONES 身份

- **WHEN** ONES 身份绑定完成
- **THEN** 系统 MUST NOT 因该绑定自动调用需求、任务、缺陷或其他 ONES 业务接口

### Requirement: 外部身份写操作受统一安全控制

所有外部身份绑定和状态变更接口 SHALL 复用现有管理端认证、CSRF、`identity:manage` 权限和安全审计机制。

#### Scenario: 无身份管理权限发起绑定

- **WHEN** 已认证用户不具备 `identity:manage` 权限却提交绑定请求
- **THEN** 系统 SHALL 拒绝请求且不得访问 ONES 登录端点或修改身份数据

#### Scenario: 成功或失败的身份管理操作

- **WHEN** 管理员执行钉钉或 ONES 绑定、启用、停用或解绑
- **THEN** 系统 SHALL 写入不含凭据和令牌的审计事件，记录操作者、目标用户、提供方、动作和结果

### Requirement: ONES Mock 支持身份绑定验证

开发测试环境 SHALL 提供独立 Docker Compose ONES Mock，用于验证成功登录、无效凭据和异常响应，不得依赖真实 ONES 凭据。

#### Scenario: 使用 Mock 完成 ONES 绑定

- **WHEN** 测试环境启动 ONES Mock 并使用约定测试账号发起绑定
- **THEN** 系统 SHALL 完成服务端验证并创建符合字段白名单的 ONES 身份

#### Scenario: Mock 返回无效凭据

- **WHEN** 测试使用错误密码调用 ONES Mock
- **THEN** 系统 SHALL 返回验证失败且数据库中不得出现该次失败产生的身份记录

### Requirement: 本阶段不接入 ONES 业务能力

本变更 SHALL NOT 创建 ONES 需求、任务、缺陷查询能力，不得新增 API Capability、工作流节点或 Agent 工具。

#### Scenario: 完成 ONES 身份绑定功能

- **WHEN** 本变更交付
- **THEN** 用户管理页面 SHALL 仅能管理 ONES 身份关联，不得出现需求、任务、缺陷查询或业务调用入口

