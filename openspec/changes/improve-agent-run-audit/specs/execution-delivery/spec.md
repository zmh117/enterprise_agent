## ADDED Requirements

### Requirement: Agent Job 生命周期事实与执行审计投影必须分离
系统 MUST 保持 `agent_job` 为 Job 身份、冻结来源、路由和生命周期状态的事实源，并 MUST 将可重算的模型轮次、Token、耗时、估算成本和执行失败诊断保存到独立执行审计投影。系统 MUST 为每个 Job 最多维护一条执行汇总，并 MUST NOT 因本变更向 `agent_job` 增加运行统计字段。

#### Scenario: Worker 首次执行 Job
- **WHEN** Worker 开始执行一个尚无执行汇总的 Job
- **THEN** 系统在独立执行汇总事实中创建或更新该 Job 的记录，而不改变 `agent_job` 的事实边界

#### Scenario: 查询没有执行统计的历史 Job
- **WHEN** 授权用户查询一个在本能力上线前已结束且没有执行投影的 Job
- **THEN** 系统将统计可用性返回为 `UNAVAILABLE`，不得把未知 Token、耗时或成本展示为零

### Requirement: Runtime 必须投影 SDK 可安全观察的运行事件
TypeScript Runtime 和长期保留的 Python Runtime MUST 将 SDK 消息流中可安全观察的 Runtime 初始化、模型轮次、API retry 和 ResultMessage 终态归一化为同一套版本化事件合同。Worker MUST 在切换新版 Runtime 前同时接受当前已发布版本和新增 minor version，并 MUST 拒绝未知 major version 或不满足 schema 的事件。

#### Scenario: SDK 返回成功 ResultMessage
- **WHEN** Runtime 收到包含耗时、Token、模型 usage 和估算成本的成功 ResultMessage
- **THEN** Runtime 发出一个受 schema 约束的唯一终态事件，Worker 幂等保存其安全汇总

#### Scenario: SDK 返回 API retry 消息
- **WHEN** SDK 报告一次 API retry 及其 attempt、delay 和安全错误分类
- **THEN** Runtime 发出不含请求正文和认证材料的 retry 事件，并将其关联到当前 invocation

#### Scenario: SDK 报告 MCP Server 初始化失败
- **WHEN** SDK 初始化消息把某个部署固定的 MCP Server 标记为连接失败
- **THEN** Runtime 保存有界的 Server 标识和稳定状态，并将执行失败定位为 MCP 连接阶段

#### Scenario: Worker 收到旧版 Runtime 事件
- **WHEN** 受控切换期间 Worker 收到当前已支持的旧 minor version 事件
- **THEN** Worker 继续完成 Job，并把新增统计标记为 `PARTIAL` 或 `UNAVAILABLE`，不得制造缺失值

### Requirement: 模型轮次必须按 SDK 观测语义记录
系统 MUST 为 SDK 消息流中可唯一识别的每个模型响应轮次保存一条 `agent_model_call` 事实，并 MUST 以 Job、invocation 和 Runtime 单调 sequence 或等价稳定身份保证幂等。模型轮次仅能记录模型标识、安全 request/message 标识、状态、时间、SDK 可见 Token、停止原因和有界错误；逐轮耗时 MUST 明确标记为 `SDK_OBSERVED` 或 `UNAVAILABLE`，不得表述为 Provider HTTP 精确耗时。

#### Scenario: 模型轮次具有可关联的起止边界
- **WHEN** Runtime 能将一次模型响应与 invocation 内的模型请求起点安全关联
- **THEN** 系统保存该轮次的 SDK 观测耗时并在 API 和页面中显示“SDK 观测”语义

#### Scenario: 模型轮次缺少可靠起点
- **WHEN** SDK 只提供模型响应完成消息而没有可关联的请求起点
- **THEN** 系统仍保存该模型轮次，但将其耗时和耗时来源记录为不可用，不得用 Job 总耗时或工具耗时推算

#### Scenario: 同一模型轮次被重放
- **WHEN** Runtime 恢复或 MQ 重复消费再次提交相同 invocation 和 sequence 的模型轮次
- **THEN** 系统只保留一条模型轮次事实且不重复累计任何 Token

#### Scenario: 逐轮成本不可得
- **WHEN** SDK 只在 ResultMessage 中提供整个 query 的估算成本
- **THEN** 系统只在 Job 执行汇总显示该估算成本，不得按 Token 比例伪造逐轮成本

### Requirement: ResultMessage 使用量必须形成幂等的 Job 级汇总
系统 MUST 以 SDK ResultMessage 为单次 invocation 的汇总证据，并 MUST 从 Job 下具有唯一终态身份的 invocation 重算 Job 级总耗时、API 总耗时、输入 Token、输出 Token、cache creation Token、cache read Token、按模型 usage 和估算成本。系统 MUST 优先使用覆盖完整 query 的 `modelUsage`；只有主循环 `usage` 可用时 MUST 将统计标记为 `PARTIAL`。汇总 MUST 区分 `COMPLETE`、`PARTIAL` 和 `UNAVAILABLE`，并 MUST 将 SDK 报告的成本标记为估算值。

#### Scenario: Job 首次成功完成
- **WHEN** Worker 保存一个通过合同校验的成功 ResultMessage 终态
- **THEN** 系统从唯一终态证据计算 Job 执行汇总，并返回四类 Token、总耗时、API 总耗时和估算成本

#### Scenario: Job 经历多次 Runtime invocation
- **WHEN** Job 因可重试错误产生多个具有不同 invocation 身份的终态证据
- **THEN** Job 汇总包含所有唯一 invocation 已实际消耗的可用 Token、耗时和估算成本，并保留是否重试耗尽的独立标记

#### Scenario: 终态或消息被重复投递
- **WHEN** 相同 `invocation_id + request_digest` 的终态事件被恢复或重复消费
- **THEN** 系统通过重算或幂等 upsert 得到相同汇总，不得对已有合计执行盲目累加

#### Scenario: ResultMessage 缺少完整核算字段
- **WHEN** ResultMessage 未提供 `modelUsage`、成本或某一类 Token
- **THEN** 系统将对应字段保留为未知并降低统计可用性，不得把缺失值记为零

### Requirement: 执行失败位置必须稳定、可关联且不覆盖根因
系统 MUST 使用稳定枚举和安全错误码定位 Runtime 启动、Runtime 协议、MCP 连接、模型 API、工具权限、工具执行和未知执行阶段的失败。Job retry 是否耗尽 MUST 作为独立结果保存，不得覆盖首次可行动的根因阶段。错误摘要 MUST 有界、脱敏，并能关联 Job、invocation 以及已有工具或 MCP 审计事实。

#### Scenario: 模型 API 错误后重试耗尽
- **WHEN** 模型 API 错误触发 Job retry 且最终耗尽允许次数
- **THEN** 系统返回失败阶段 `MODEL_API` 和 `retry_exhausted=true`，不得只返回笼统的 Job 失败

#### Scenario: 工具被权限策略拒绝
- **WHEN** SDK 或现有工具治理链拒绝一次工具调用
- **THEN** 系统返回失败阶段 `TOOL_PERMISSION`，并关联现有 `agent_tool_call` 或 ResultMessage permission denial 安全证据

#### Scenario: 工具或 MCP 执行失败
- **WHEN** 已允许的工具在执行阶段失败
- **THEN** 系统返回 `TOOL_EXECUTION` 根因并复用 `agent_tool_call` 与 `mcp_operation_audit`，不得复制原始请求或响应载荷

#### Scenario: 无法确定执行失败阶段
- **WHEN** 安全错误码不能确定性映射到受支持阶段
- **THEN** 系统返回 `UNKNOWN` 和可关联诊断码，不得根据错误文本猜测阶段

### Requirement: Agent 执行状态与结果投递状态必须独立展示
系统 MUST 保持 Agent 执行汇总和 Delivery 事实相互独立。运行记录查询层 MUST 从 `delivery_attempt` 等既有事实计算投递阶段及其失败位置，不得用投递失败修改 Agent 执行状态或执行汇总；页面 MUST 同时展示执行状态和投递状态。

#### Scenario: Agent 成功但投递失败
- **WHEN** Agent 执行成功且后续渠道投递失败
- **THEN** 页面显示 Agent 执行成功、Delivery 失败和失败位置 `DELIVERY`，执行汇总仍保持成功

#### Scenario: Agent 失败且未投递
- **WHEN** Agent 在模型或工具阶段失败而没有进入结果投递
- **THEN** 页面显示对应执行失败阶段，并将 Delivery 显示为未开始而不是失败

### Requirement: 运行记录查询和页面必须受授权且默认安全
受授权的运行记录列表和 Job 详情 MUST 展示用户安全标识、Agent、执行与投递状态、统计可用性、总耗时、API 总耗时、模型轮次、四类 Token、估算成本、工具安全摘要和失败位置。查询 MUST 复用当前登录、业务应用运维权限和平台管理员授权，并 MUST 对租户与应用范围执行服务端过滤。系统 MUST NOT 在新增表、事件、API、日志或页面中保存或返回完整 Prompt、完整模型回复、原始 SDK 消息、Provider/MCP 原始载荷、private thinking、Secret、Token、密码、Cookie 或数据库凭据。

#### Scenario: 应用运维人员查看授权 Job
- **WHEN** 当前用户对 Job 所属业务应用具有运行中心查看权限
- **THEN** API 返回该 Job 的安全汇总、模型轮次和既有工具及投递证据

#### Scenario: 用户查询未授权应用
- **WHEN** 当前用户请求不在其租户或应用授权范围内的 Job 或模型轮次
- **THEN** 服务端拒绝请求且不泄漏记录是否存在或任何统计数据

#### Scenario: 错误和模型消息包含敏感内容
- **WHEN** SDK 错误、模型响应或工具载荷包含认证材料、原始业务正文或 private thinking
- **THEN** 归一化与持久化边界仅保留稳定分类和有界脱敏摘要，敏感内容不进入数据库或页面

#### Scenario: Job 执行事实被清理
- **WHEN** Job 按既有保留和清理策略被合法删除
- **THEN** 关联执行汇总和模型轮次随 Job 一并清理，不得形成无主审计投影
