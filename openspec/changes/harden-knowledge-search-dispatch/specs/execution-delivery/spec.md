## ADDED Requirements

### Requirement: Runtime必须在派发前串行协调同Job知识工具
Runtime SHALL 对当前 Job 冻结的知识工具执行串行派发，队列等待发生在 Knowledge MCP 请求发出之前，计入原 Job 墙钟预算。排队取消或墙钟到期 MUST 阻止尚未发出的调用；失败 MUST 释放派发槽且不得自动重试。派发 MUST 保持冻结工具名称/schema、身份、现行授权及单次最多 360 秒边界。请求内续期的知识 Principal 只允许经内部传输头接续到 Runtime 内存，MUST NOT 进入模型结果、日志或持久化审计，不得延长票据寿命或替过期凭证放行。

#### Scenario: 模型并行请求三个库
- **WHEN** 同一个 Job 同时发起三次知识检索
- **THEN** Runtime 按到达顺序逐次发出，同一时刻最多一条该 Job 知识请求进入 MCP；每条派发后按单次上限及剩余 Job 预算计算截止

#### Scenario: 等待项取消或到期
- **WHEN** 后续知识请求正在等待且 Job 取消或达到原截止
- **THEN** 等待项结束且不发出 HTTP，请求不会在清理后迟到执行

#### Scenario: 长调用后的凭证接续
- **WHEN** 前一知识调用在有效授权下完成短期 Principal 续期并存在下一条排队请求
- **THEN** Runtime 仅使用接续后的有效凭证派发，Knowledge MCP 重新检查当前授权，任何工具结果或审计均不包含该凭证

## MODIFIED Requirements

### Requirement: 知识 MCP 客户端必须显式衔接有界执行预算
Python Runtime SHALL 为固定知识 MCP 配置显式超时：本地 SDK bridge 等待覆盖当前 Job 时限，派发后的远端 HTTP 仍复用知识服务代码级预算上限并与剩余 Job 时间取较小值；不得依赖 SDK 隐式首响应默认值提前中断有效排队或长调用。该配置 MUST 只作用于知识 MCP，不能由模型参数覆盖。Runtime 的 invocation 总截止与取消，以及服务端当前 Job 剩余预算、授权与身份续期校验 MUST 继续生效；排队及单次调用均不得重置或延长 Job 截止时间。

#### Scenario: 超过客户端默认首响应时间
- **WHEN** 知识调用在有效 Job 与服务预算内超过 SDK 默认首响应时间才返回
- **THEN** 客户端接收结果，不因默认 60 秒限制提前中断

#### Scenario: Job 总时限较短或已取消
- **WHEN** Job 时限小于知识服务上限，或 invocation 被取消
- **THEN** 更短的 Job 截止或取消优先生效，不继续等待完整知识服务上限

#### Scenario: 同一任务包含其他 MCP
- **WHEN** 当前任务同时配置知识 MCP 与 ONES 等其他 MCP
- **THEN** 仅知识 MCP 获得对应逐服务超时，其他服务的超时与身份 Header 不改变
