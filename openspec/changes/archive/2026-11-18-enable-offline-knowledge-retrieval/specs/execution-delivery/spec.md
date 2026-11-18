## ADDED Requirements

### Requirement: 知识 MCP 客户端必须显式衔接有界执行预算
Python Runtime SHALL 为固定知识 MCP 配置显式的逐服务调用超时，复用知识服务代码级预算上限并与当前 Job 总时限取较小值，不得依赖 SDK 隐式首响应默认值提前中断有效长调用。该配置 MUST 只作用于知识 MCP，不能由模型参数覆盖。Runtime 的 invocation 总截止与取消，以及服务端当前 Job 剩余预算、授权与身份续期校验 MUST 继续生效；单次调用配置不得重置或延长 Job 截止时间。

#### Scenario: 超过客户端默认首响应时间
- **WHEN** 知识调用在有效 Job 与服务预算内超过 SDK 默认首响应时间才返回
- **THEN** 客户端接收结果，不因默认 60 秒限制提前中断

#### Scenario: Job 总时限较短或已取消
- **WHEN** Job 时限小于知识服务上限，或 invocation 被取消
- **THEN** 更短的 Job 截止或取消优先生效，不继续等待完整知识服务上限

#### Scenario: 同一任务包含其他 MCP
- **WHEN** 当前任务同时配置知识 MCP 与 ONES 等其他 MCP
- **THEN** 仅知识 MCP 获得对应逐服务超时，其他服务的超时与身份 Header 不改变
