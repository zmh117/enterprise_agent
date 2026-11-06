## MODIFIED Requirements

### Requirement: 内部用户是跨入口唯一权限主体
系统 SHALL 使用持久化内部用户 ID 作为管理 Web、钉钉、Webhook Job、Tool 和审计的权限主体。外部 provider、企业或 tenant、subject 只能在受信解析后关联内部用户，MUST NOT 以群 ID、昵称、邮箱、手机号、发布管理员或客户端 actor 字段代替内部用户。

#### Scenario: 同一用户从不同入口访问
- **WHEN** 已启用自然人从有效 Web Session 或已绑定钉钉身份进入
- **THEN** 系统解析同一内部用户，并按本次入口、角色和应用独立授权

#### Scenario: 绑定用户触发 Webhook
- **WHEN** 已发布 Trigger 接收合法事件
- **THEN** Job 和下游审计使用 Trigger 发布固定的已启用 human 用户，保留 Trigger、Publication 和 correlation 关联

### Requirement: 服务账号与人类账号分离
系统 SHALL 区分 `human` 与 `service`。服务账号可持有明确的业务角色，MUST NOT 创建个人密码凭据、交互式 Web Session、个人钉钉或 ONES 身份，亦不得加入包含管理后台能力的角色。Webhook MUST 绑定已启用 human 用户，不再创建或使用专用服务账号。

#### Scenario: 服务账号登录管理端
- **WHEN** 使用服务账号提交用户名密码
- **THEN** 认证失败且不创建 Session

#### Scenario: 给服务账号分配管理角色
- **WHEN** 目标角色包含管理能力
- **THEN** 系统拒绝成员写入，业务角色分配仍按目标角色委派权限处理

## ADDED Requirements

### Requirement: Webhook 执行用户继承现有身份与权限
Webhook SHALL 在配置页必选一个启用人员；执行使用此人的既有角色、应用/工具/资源/知识库权限与已绑定外部身份，不独立设置角色，不复制个人 Credential，不改变角色成员关系。各工具既有的来源渠道与个人身份要求仍须满足，不自动借用投递 Connector 作为工具来源。投递收件人 MUST 与执行用户独立。任意需要本人确认的写入 MUST 保留原确认规则。

#### Scenario: 配置执行用户
- **WHEN** 管理员发布选择人员的 Webhook
- **THEN** 系统固定该人员 ID，并在 Job 与审计中使用同一身份

#### Scenario: 外部身份不可用
- **WHEN** 所绑定人员没有有效的当前个人外部身份或凭据
- **THEN** 对应个人工具按原合同拒绝，不借用管理员或其他收件人的身份
