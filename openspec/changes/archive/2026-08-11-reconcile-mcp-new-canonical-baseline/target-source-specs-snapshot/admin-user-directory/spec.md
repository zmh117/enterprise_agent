# admin-user-directory Specification

## Purpose
TBD - created by archiving change complete-user-external-identity-management. Update Purpose after archive.
## Requirements
### Requirement: 管理员使用真实用户目录

系统 SHALL 为具备 `user:manage` 权限的已认证管理员提供真实用户目录，并 SHALL 从后端用户数据读取列表与详情，不得使用前端静态数据或演示数据代替。

#### Scenario: 有权限的管理员查看用户列表

- **WHEN** 已认证且具备 `user:manage` 权限的管理员打开用户管理页面
- **THEN** 系统 SHALL 返回真实用户列表，并展示用户名、显示名称、账号类型、状态和更新时间

#### Scenario: 未认证访问用户目录

- **WHEN** 未认证请求访问用户目录接口或页面
- **THEN** 系统 SHALL 拒绝访问并要求认证

#### Scenario: 无权限访问用户目录

- **WHEN** 已认证但不具备 `user:manage` 权限的用户访问用户目录
- **THEN** 系统 SHALL 返回权限不足，且不得泄露用户目录数据

### Requirement: 查询和查看用户详情

系统 SHALL 支持按用户名、显示名称或已绑定外部身份的展示名称查询用户，并 SHALL 在用户详情中返回基本资料、账号状态和外部身份摘要。

#### Scenario: 查询匹配的用户

- **WHEN** 管理员输入用户名或显示名称关键字
- **THEN** 系统 SHALL 返回匹配用户，并保持稳定分页和排序

#### Scenario: 查看用户详情

- **WHEN** 管理员打开一个存在的用户详情
- **THEN** 系统 SHALL 展示该用户的基本资料、账号状态、账号类型、版本号以及钉钉和 ONES 身份摘要

#### Scenario: 用户不存在

- **WHEN** 管理员请求不存在的用户
- **THEN** 系统 SHALL 返回明确的未找到结果，不得创建占位用户

#### Scenario: 敏感字段不出现在响应中

- **WHEN** 系统返回用户列表或详情
- **THEN** 响应 MUST NOT 包含密码、密码哈希、会话令牌、CSRF 令牌或外部系统令牌

### Requirement: 创建系统用户

系统 SHALL 允许具备 `user:manage` 权限的管理员创建人类用户，并 SHALL 校验用户名唯一性和必填资料。

#### Scenario: 创建有效用户

- **WHEN** 管理员提交唯一用户名、显示名称和有效的初始状态
- **THEN** 系统 SHALL 创建人类用户并返回其非敏感资料

#### Scenario: 用户名重复

- **WHEN** 管理员提交已存在的用户名
- **THEN** 系统 SHALL 拒绝创建并返回可识别的冲突错误

#### Scenario: 创建请求包含密码

- **WHEN** 管理员为用户设置初始密码
- **THEN** 系统 SHALL 仅保存安全密码哈希，并 MUST NOT 在响应、审计详情或应用日志中记录明文密码

### Requirement: 编辑用户基本资料

系统 SHALL 允许管理员编辑用户显示名称等受支持的基本资料，并 SHALL 使用版本号防止覆盖并发修改。

#### Scenario: 使用当前版本更新用户

- **WHEN** 管理员提交有效资料和当前 `expected_revision`
- **THEN** 系统 SHALL 保存更新、递增版本号并返回最新资料

#### Scenario: 使用过期版本更新用户

- **WHEN** 管理员提交的 `expected_revision` 已过期
- **THEN** 系统 SHALL 返回冲突错误，且不得覆盖较新的修改

### Requirement: 启用和停用用户

系统 SHALL 支持启用和停用用户，且状态变更 SHALL 立即影响管理端会话和外部身份解析。

#### Scenario: 停用用户

- **WHEN** 管理员停用一个已启用的人类用户
- **THEN** 系统 SHALL 将用户标记为停用、使其现有管理端会话失效，并拒绝通过其外部身份创建新的 Agent 请求

#### Scenario: 重新启用用户

- **WHEN** 管理员重新启用一个已停用用户
- **THEN** 系统 SHALL 允许该用户重新认证，并仅允许解析仍处于启用状态的外部身份

#### Scenario: 重新启用用户不改变身份状态

- **WHEN** 用户被重新启用但其某个外部身份仍为停用状态
- **THEN** 系统 MUST NOT 自动启用该外部身份

### Requirement: 服务账号与人类用户分离

系统 SHALL 在用户目录中明确区分服务账号和人类用户，并 SHALL 禁止为服务账号绑定个人钉钉或 ONES 身份。

#### Scenario: 查看服务账号

- **WHEN** 管理员在用户目录中查看服务账号
- **THEN** 系统 SHALL 明确显示其账号类型为服务账号

#### Scenario: 尝试为服务账号绑定个人身份

- **WHEN** 管理员尝试为服务账号绑定钉钉或 ONES 用户身份
- **THEN** 系统 SHALL 拒绝请求，且不得创建身份记录

### Requirement: 用户管理写操作受统一安全控制

所有用户创建、编辑和状态变更接口 SHALL 复用现有管理端认证、CSRF、RBAC 和审计机制，不得增加绕过这些机制的专用入口。

#### Scenario: 缺少 CSRF 保护的写请求

- **WHEN** 浏览器会话发起用户管理写请求但缺少有效 CSRF 凭据
- **THEN** 系统 SHALL 拒绝请求且不得修改数据

#### Scenario: 成功修改用户

- **WHEN** 管理员成功创建、编辑、启用或停用用户
- **THEN** 系统 SHALL 写入包含操作者、目标用户、动作和结果的审计事件

### Requirement: MVP 用户界面范围受限

第一版管理界面 SHALL 仅开放用户列表、创建用户和用户详情编辑入口；角色管理、权限策略编辑、会话管理和其他系统管理功能不得因本变更而启用。

#### Scenario: 管理员进入用户管理

- **WHEN** 管理员从导航进入用户管理
- **THEN** 系统 SHALL 提供用户列表以及进入创建和详情页面的入口

#### Scenario: 查看本变更之外的系统管理入口

- **WHEN** 管理员查看角色、授权、会话或其他未实现模块
- **THEN** 这些入口 SHALL 保持禁用、隐藏或明确标记为未开放，不得展示伪功能
