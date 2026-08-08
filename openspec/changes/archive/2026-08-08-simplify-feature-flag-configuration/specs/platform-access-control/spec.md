## ADDED Requirements

### Requirement: 管理后台必须由统一身份与 RBAC 原子保护
系统 SHALL 将管理 Web、管理 API、统一身份、Web Session、RBAC 和业务应用控制面视为同一个管理面启停单元。管理面开启时 MUST 要求可解析的统一用户身份和授权；系统不得支持无身份或无 RBAC 的管理后台组合。

#### Scenario: 管理面开启
- **WHEN** `FEATURE_WEB_ADMIN=true`
- **THEN** 管理 Web 和管理 API 启用统一身份、Web Session 与 RBAC 校验
- **AND** 未认证调用方不能访问受保护管理资源

#### Scenario: 管理面关闭
- **WHEN** `FEATURE_WEB_ADMIN=false`
- **THEN** 系统不暴露管理 Web 和管理 API
- **AND** Channel ingress 与已发布 Agent Runtime 不因管理面关闭而自动停止

#### Scenario: 旧身份开关与管理面冲突
- **WHEN** `FEATURE_WEB_ADMIN=true` 但兼容期旧身份或业务应用控制面开关显式为 `false`
- **THEN** 系统拒绝启动并报告冲突配置
- **AND** 系统不得降级为无认证或不完整管理后台

### Requirement: 测试身份不得绕过生产访问控制
系统 MUST 在生产环境拒绝测试身份请求头适配器，无论该请求头由反向代理、客户端还是内部服务提供。

#### Scenario: 生产请求携带测试身份头
- **WHEN** 生产环境收到仅能由测试身份适配器识别的身份请求头
- **THEN** 系统不将其解析为已认证用户
- **AND** 系统按未认证请求拒绝并记录审计事件
