## ADDED Requirements

### Requirement: Webhook 使用不可交互登录的服务账号
系统 SHALL 支持 `account_type=service` 的内部账号，并 MUST 禁止该账号创建密码凭证、Web session或绑定钉钉等人类外部身份。

#### Scenario: 创建 Webhook Trigger
- **WHEN** 管理员创建 Trigger 且未选择现有专用服务账号
- **THEN** 系统事务创建一个默认禁用权限的专用服务账号并绑定该 Trigger

#### Scenario: 服务账号尝试 Web 登录
- **WHEN** 调用方使用服务账号标识提交登录请求
- **THEN** 系统拒绝认证且不创建 session

#### Scenario: 服务账号绑定人类外部身份
- **WHEN** 管理员试图把钉钉或其他人类身份绑定到服务账号
- **THEN** 系统返回校验错误且不创建绑定

### Requirement: 服务账号复用统一 RBAC 和平台范围
系统 SHALL 使用 Trigger 绑定的服务账号作为 Webhook job 的内部权限主体，并 MUST 校验项目、Agent、工具和 environment/base/workshop 平台数据范围。

#### Scenario: 服务账号拥有最小诊断权限
- **WHEN** 服务账号被允许使用默认诊断 Agent、目标项目、query_loki 和指定生产范围
- **THEN** Webhook job 可以创建且 Agent 只能在该交集范围内调用 query_loki

#### Scenario: Trigger routing 超出服务账号范围
- **WHEN** 映射得到的 environment/base/workshop 不在服务账号 grant 中
- **THEN** 系统拒绝创建 job并记录范围拒绝决策

#### Scenario: Agent publication 包含未授权工具
- **WHEN** Agent publication 分配了某工具但服务账号没有该工具的 use 权限
- **THEN** 该工具不进入运行时允许集合

### Requirement: 服务账号和 Trigger 启停均为运行时闸门
系统 SHALL 在接收新事件和创建 job 时检查 Trigger、Connector、服务账号和相关 publication 状态，任一被禁用时 MUST fail closed。

#### Scenario: 禁用服务账号
- **WHEN** 管理员禁用 Trigger 绑定的服务账号
- **THEN** 后续 Webhook 请求不能创建新 job，且拒绝结果可审计

#### Scenario: 禁用 Trigger
- **WHEN** 管理员停用 Trigger 但服务账号仍启用
- **THEN** public endpoint 拒绝新事件且不影响该服务账号的其他明确授权用途

### Requirement: 服务账号操作具有独立审计主体
系统 SHALL 在 Webhook event、Agent job、tool call、permission decision 和 Delivery 证据中记录服务账号 ID、Trigger ID 和 correlation ID，MUST NOT 把行为错误归属到发布管理员或固定字符串 `grafana`。

#### Scenario: Webhook Agent 调用工具
- **WHEN** Agent 为 Webhook job 调用允许的只读工具
- **THEN** tool call 和权限审计记录 Trigger 服务账号为主体，并保留 Trigger publication 引用
