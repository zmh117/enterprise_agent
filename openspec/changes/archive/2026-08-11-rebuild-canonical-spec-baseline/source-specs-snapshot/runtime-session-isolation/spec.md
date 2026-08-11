# runtime-session-isolation Specification

## Purpose
TBD - created by archiving change stabilize-platform-runtime-foundation. Update Purpose after archive.
## Requirements
### Requirement: 新连续会话必须绑定发布版本和 Execution Scope
系统 MUST 以业务应用发布 ID、Connector、外部 conversation ID 和 Execution Scope hash 构造连续会话身份；发布或范围变化时必须创建新 Session。

#### Scenario: 同一群聊继续对话
- **WHEN** 同一 Connector、外部 conversation、业务应用发布和 Execution Scope 收到后续消息
- **THEN** 系统可以复用同一受控 Session

#### Scenario: 应用重新发布
- **WHEN** 同一外部 conversation 使用新的业务应用发布版本
- **THEN** 系统必须创建新 Session，不得附着旧上下文

### Requirement: 私聊会话必须额外绑定请求人
私聊 Session key MUST 包含已解析的内部 requester ID，不能仅依赖外部 conversation 或 Connector。

#### Scenario: 两个用户共享异常外部 conversation ID
- **WHEN** 两个内部用户被映射到相同外部 conversation 标识
- **THEN** 系统仍必须为其创建不同 Session

### Requirement: Webhook 和 Debug 默认使用隔离 Session
Webhook/Grafana 每个外部事件 MUST 默认创建独立 Session；Debug 每次运行 MUST 默认创建新 Session。

#### Scenario: Grafana 重复投递同一事件
- **WHEN** 同一幂等事件被重复接收
- **THEN** 系统返回原 Job/Session，不创建新的连续上下文

#### Scenario: Debug 显式继续 Session
- **WHEN** 当前用户请求继续自己可访问的 Debug Session
- **THEN** 只有业务应用发布和 Execution Scope 未变化时系统才可继续

### Requirement: application 和 actor 连续会话模式必须停用
新 Job MUST NOT 使用 `application` 或 `actor` 模式共享上下文；旧模式 Session 只可作为历史读取，不得再附着新 Job。

#### Scenario: 旧应用配置仍声明 application 模式
- **WHEN** 旧发布版本尝试创建新 Job
- **THEN** 系统必须阻止并要求重新发布为受支持的隔离策略

