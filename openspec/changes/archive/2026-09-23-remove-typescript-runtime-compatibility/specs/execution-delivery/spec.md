## MODIFIED Requirements

### Requirement: Runtime 与 Worker 必须隔离执行职责
唯一生产 Runtime SHALL 通过 `FixedMcpClaudeSdkClient`/`ClaudeSdkClient` 使用 Python Claude Agent SDK；公共编排只依赖 `AgentRuntimeClient`。Worker MUST 独占 Job claim、授权与快照校验、重试/终态、结果和安全事件持久化、Delivery Outbox 与 RabbitMQ ack。Runtime 只执行单次 attempt，不消费 RabbitMQ、不写 Job/Delivery 业务状态。SDK/CLI 和模型明文凭据只存在所需 Runtime 边界，Worker 镜像不得包含 SDK/CLI；测试 stub 必须显式注入。

#### Scenario: Runtime 成功但本地提交失败
- **WHEN** Runtime 已 completed，而 Worker 的 Job/结果/Delivery 事务回滚
- **THEN** Worker 不错误 ack，并以相同 invocation/digest 恢复既有终态，不启动第二次模型执行

#### Scenario: Runtime 内部模块组装
- **WHEN** 系统装配请求边界、SDK、事件规范化、工具策略、文件桥与 Sandbox
- **THEN** 使用静态代码端口，不注册任意 Runtime/MCP URL、动态插件或 Worker 进程内 SDK

#### Scenario: 默认部署
- **WHEN** 当前 Compose 装配 Agent 执行链
- **THEN** Worker 通过同一 PostgreSQL 的 Job 和真实 RabbitMQ 调用固定 Python Runtime，不提供其它 Runtime 实现或跨实现 fallback
