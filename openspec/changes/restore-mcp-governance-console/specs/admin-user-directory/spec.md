## MODIFIED Requirements

### Requirement: MVP 用户界面范围受限
管理界面 SHALL 在统一人员与账号目录中提供用户列表、创建、详情编辑、启用/停用、Session 摘要、角色成员关系和外部身份摘要入口。角色、Session 和身份的写操作 MUST 跳转或调用各自受治理能力，不得在用户页面复制第二套事实。

#### Scenario: 管理员进入用户管理
- **WHEN** 管理员从导航进入人员与账号
- **THEN** 系统提供用户列表、创建和详情入口，并按权限展示 Session、角色和身份摘要

#### Scenario: 无会话管理权限查看用户
- **WHEN** 操作者具有用户读取权限但没有 Session 管理权限
- **THEN** 页面不显示会话撤销动作，后端也拒绝对应请求

#### Scenario: 从用户详情维护角色
- **WHEN** 有角色分配权限的管理员从用户详情添加或移除角色
- **THEN** 系统复用统一角色成员事实、并发控制和审计，不在用户表保存重复授权

## ADDED Requirements

### Requirement: 用户详情聚合账号安全与身份摘要
系统 SHALL 在用户详情中聚合账号类型、状态、最后登录、活动 Session 摘要、角色、有效 Application 访问和外部身份状态，并 MUST 对敏感字段和无权查看的范围进行脱敏或省略。

#### Scenario: 查看自然人用户详情
- **WHEN** 有权限管理员查看自然人用户
- **THEN** 页面显示允许的账号、角色和外部身份摘要，不显示密码 hash、Session token、ONES 密码或外部 Token

### Requirement: 用户管理支持受控 Session 撤销
系统 SHALL 允许具有 Session 管理权限的管理员撤销目标用户的单个或全部活动 Session，并 MUST 保护最后平台管理员和当前操作安全。

#### Scenario: 撤销停用用户的 Session
- **WHEN** 管理员停用自然人用户并确认撤销其活动 Session
- **THEN** 系统使后续管理请求失效、记录审计并保留历史登录摘要

### Requirement: 身份治理复用统一 app_user 和本人验证事实
系统 SHALL 在人员详情和身份治理页面展示钉钉与 ONES External Identity 的状态、Provider 实例、验证时间、默认 Team 和 Credential 状态摘要，且 MUST 让这些身份引用同一个 `app_user`。管理员只能查看安全摘要、停用、恢复或解绑受信身份，不得代用户提交 ONES 邮箱密码、查看 Token 或手工创建钉钉 subject。

#### Scenario: 管理员查看 ONES 身份
- **WHEN** 管理员查看其他用户的 ONES 身份与 Credential 状态
- **THEN** 页面显示已绑定主体、Team 和需重新验证等安全状态，不显示邮箱密码、Token 或内部加密引用

#### Scenario: 用户本人重新验证 ONES
- **WHEN** 当前登录用户在“我的外部身份”通过受信 ONES 实例提交邮箱密码并确认服务端 Challenge
- **THEN** 系统把外部 Identity、默认 Team 和加密个人 Token 关联到同一个 `app_user`，并在请求结束前丢弃密码

#### Scenario: 管理员代用户提交 ONES 凭据
- **WHEN** 管理员在治理接口中提交其他用户的 ONES 邮箱、密码、Token 或 user UUID
- **THEN** 系统拒绝请求且不创建或覆盖身份和 Credential
