## MODIFIED Requirements

### Requirement: Loki diagnostics shall expose bounded label discovery
系统 SHALL 由 `tool-mcp` 提供受限的 Loki label 诊断能力，用于列出当前授权目标在指定时间窗口内、已发布资源固定 selector 覆盖范围内可见的合法 label 名称；MUST NOT 使用静态标签名称白名单过滤合法标签，也不得回退为无固定范围的全局枚举。

#### Scenario: 查询可见 labels
- **WHEN** 授权用户请求指定 environment/base/workshop 的 Loki labels
- **THEN** `tool-mcp` 返回该资源固定范围内的 bounded 合法 label 名称列表、tenant 信息是否已配置、时间窗口和 truncated 标记，包括自定义标签

#### Scenario: label 查询超出限制
- **WHEN** 请求的时间窗口或响应大小超过平台限制
- **THEN** `tool-mcp` SHALL 拒绝或截断响应并返回可审计错误分类

### Requirement: Loki diagnostics shall expose bounded label values
系统 SHALL 由 `tool-mcp` 提供受限的 Loki label values 诊断能力，用于列出语法合法 label 在已发布资源固定 selector 内的候选值。标签 Schema、入口与执行器 MUST 共用语法契约而非名称白名单。

#### Scenario: 查询合法 label 的 values
- **WHEN** 授权用户请求 app、logtype 或其他合法自定义 label 的 values
- **THEN** `tool-mcp` 返回固定范围内的 bounded values、label 名称、时间窗口、truncated 标记和资源摘要

#### Scenario: 查询非法 label
- **WHEN** 请求的 label 格式非法或超长
- **THEN** `tool-mcp` 在访问 Provider 前拒绝，返回稳定错误码和明确中文参数错误，不使用通用安全错误掩盖原因

#### Scenario: 固定标签取值枚举
- **WHEN** 资源固定 customer=A 且用户枚举 customer 的 values
- **THEN** 查询仍带固定范围，不能枚举其他客户的值

### Requirement: Loki diagnostics shall preserve tenant and topology isolation
Loki 诊断 Tool SHALL 使用与真实 `query_loki` 相同的当前授权目标、唯一 Published Resource Revision、tenant、强制 selector 和访问控制。查询、探测、标签发现与取值枚举 MUST 在任何 Provider I/O 前要求非空固定条件；Agent 可追加任意合法非固定标签的精确匹配，不得删除、覆盖或改写固定条件。固定标签名由资源配置决定，不对 customer/workshop 等名字做特殊授权推断。

#### Scenario: Workshop 目标诊断
- **WHEN** 用户请求 GL001 的 Loki 诊断
- **THEN** 平台 SHALL 使用该目标解析到的 Environment 或 Environment/Base selector binding
- **AND** 不从 Workshop code 自动推断、注入或放宽 Loki label

#### Scenario: tenant 错误
- **WHEN** Loki upstream 返回 tenant/auth 相关错误
- **THEN** 平台 SHALL 返回安全错误摘要和 retryable 分类
- **AND** 响应 MUST NOT 暴露认证 token 或 secret

#### Scenario: 固定范围内自由追加标签
- **WHEN** 资源固定 customer=A、workshop=GL001，Agent 仅提交 app=mes-run、logtype=error
- **THEN** 最终 selector MUST 包含四个精确条件的 AND，不要求 Agent 重复固定条件

#### Scenario: Agent 提交固定标签
- **WHEN** Agent 的追加 selector 含资源固定 key，无论值是否相同
- **THEN** 平台在访问 Provider 前明确拒绝固定范围冲突，不静默覆盖

#### Scenario: 资源固定范围缺失
- **WHEN** 已解析 Loki 资源无有效固定条件
- **THEN** 四类工具均失败关闭，不能回退全局标签目录或无范围日志查询
