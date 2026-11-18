## ADDED Requirements

### Requirement: Webhook 通过角色选择维护机器授权
Webhook 配置 SHALL 直接选择可委派且启用的业务角色，发布时原子应用到自动维护的专用服务身份。用户 MUST NOT 被要求在人员管理中创建或选择执行人。角色的应用访问、工具与资源范围继续实时求值，MUST NOT 隐式授予目标应用或借用接收人的角色、钉钉或 ONES 凭据。

#### Scenario: 无角色委派权限
- **WHEN** 操作者尝试关联其无权分配的角色
- **THEN** 发布失败，机器身份角色和现有发布均不变

#### Scenario: 选择具有管理权限的角色
- **WHEN** Webhook 试图使用含后台管理权限的角色
- **THEN** 系统拒绝，不授予机器身份管理能力
