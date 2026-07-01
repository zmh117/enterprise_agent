## ADDED Requirements

### Requirement: Loki diagnostics shall expose bounded label discovery
系统 SHALL 提供受限的 Loki label 诊断能力，用于列出当前授权目标在指定时间窗口内可见的 label 名称。

#### Scenario: 查询可见 labels
- **WHEN** 授权用户请求指定 environment/base/workshop 的 Loki labels
- **THEN** Internal API Platform 返回 bounded label 名称列表、tenant 信息是否已配置、时间窗口和 truncated 标记

#### Scenario: label 查询超出限制
- **WHEN** 请求的时间窗口或响应大小超过平台限制
- **THEN** Internal API Platform SHALL 拒绝或截断响应并返回可审计错误分类

### Requirement: Loki diagnostics shall expose bounded label values
系统 SHALL 提供受限的 Loki label values 诊断能力，用于列出允许 label 的候选值，帮助确认服务名、job 名或 container 名是否存在。

#### Scenario: 查询允许 label 的 values
- **WHEN** 授权用户请求允许 label 的 values
- **THEN** Internal API Platform 返回 bounded values、label 名称、时间窗口、truncated 标记和数据源摘要

#### Scenario: 查询不允许 label
- **WHEN** 用户请求未在 allowlist 中的 label values
- **THEN** Internal API Platform MUST 拒绝请求并说明 label 不允许

### Requirement: Loki probe shall explain empty query results
系统 SHALL 提供 Loki selector probe 或等价诊断结果，用于解释指定 selector、keyword 和时间窗口为何没有命中日志。

#### Scenario: selector 无命中
- **WHEN** Loki 查询返回 `line_count=0`
- **THEN** 响应 summary SHALL 包含 selector、query、minutes、stream_count、line_count 和 empty result hints

#### Scenario: selector 有命中
- **WHEN** Loki probe 在指定时间窗口内命中日志流
- **THEN** 响应 summary SHALL 返回 stream_count、line_count 或可用样本摘要，并保持结果大小受限

### Requirement: Loki diagnostics shall preserve tenant and topology isolation
Loki 诊断 endpoint SHALL 使用与真实 `query_loki` 相同的 environment/base/workshop 解析、tenant 设置、workshop label 注入和访问控制。

#### Scenario: 车间隔离诊断
- **WHEN** 用户请求 GL001 的 Loki 诊断
- **THEN** 平台 SHALL 注入或强制 GL001 对应的 workshop label
- **AND** 响应 MUST NOT 返回 GL002 专属日志样本

#### Scenario: tenant 错误
- **WHEN** Loki upstream 返回 tenant/auth 相关错误
- **THEN** 平台 SHALL 返回安全错误摘要和 retryable 分类
- **AND** 响应 MUST NOT 暴露认证 token 或 secret
