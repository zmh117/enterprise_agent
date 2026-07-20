## ADDED Requirements

### Requirement: 平台配置 API 提供类型化工具资源管理视图
系统 SHALL 提供适合 Web 管理的数据库、Redis 和 Loki 资源分页列表、详情、创建、更新、启停和绑定 API，并返回统一的资源状态、作用域、revision 和脱敏 Secret 引用。

#### Scenario: 按资源类型筛选
- **WHEN** 管理端按 database、redis 或 loki 类型查询资源
- **THEN** 系统返回匹配且有权访问的资源以及稳定分页信息

#### Scenario: 更新发生并发冲突
- **WHEN** 管理员基于过期 revision 更新资源
- **THEN** 系统拒绝覆盖并返回冲突错误和当前 revision

### Requirement: 平台配置 API 提供受审计的只读连接测试
系统 SHALL 为 database、redis 和 loki 资源提供显式连接测试 API，该 API MUST 使用已保存的 Secret 引用、短超时、只读探测和服务端 allowlist，并返回脱敏结果。

#### Scenario: 测试 Redis 资源
- **WHEN** 授权管理员显式测试 Redis 资源
- **THEN** 系统执行无写入副作用的连通性探测并记录审计

#### Scenario: 测试请求包含明文凭据
- **WHEN** 调用方在连接测试请求中提交未受支持的明文密码或 token
- **THEN** 系统拒绝请求并要求使用受控 Secret 写入/引用流程

### Requirement: 工具资源 API 拒绝动态可执行定义
系统 SHALL 只接受后端注册表声明的资源类型和只读工具绑定，MUST NOT 通过该 API 接受任意 HTTP endpoint、脚本、Shell 命令或写操作模板。

#### Scenario: 提交未知资源类型
- **WHEN** 管理端提交未被后端注册的资源类型或动态执行定义
- **THEN** 系统拒绝保存并返回可审计的领域校验错误
