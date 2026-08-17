## MODIFIED Requirements

### Requirement: Real runtime is implemented with the Claude Agent SDK
系统 SHALL 在独立 `python-agent-runtime` 服务中使用官方 Python Claude Agent SDK 执行 `python-v1` Agent loop。公共编排层 SHALL 只依赖语言无关的 `AgentRunResult`/Runtime client 契约，Python SDK 类型不得泄漏到公共 Job 编排逻辑，`agent-worker` 不得进程内加载或执行 Claude Agent SDK。

#### Scenario: Python Runtime驱动Agent loop
- **WHEN** `AgentExecutor` 执行一个固定为 `python-v1` 且配置有效的 Job
- **THEN** Runtime client 调用独立 Python Runtime，由 Runtime 消费 SDK message stream 并返回规范最终结果

#### Scenario: SDK类型不泄漏到应用层
- **WHEN** Python `AgentExecutor` 调用 Runtime client
- **THEN** 公共编排逻辑只处理 Runtime client 契约和 `AgentRunResult`，不直接处理 `claude_agent_sdk` 消息类型

#### Scenario: Worker镜像不包含SDK
- **WHEN** 部署或 CI 检查纯编排 `agent-worker` 镜像
- **THEN** 镜像中不存在 Claude Agent SDK、Claude Code CLI 或 Provider 明文凭据

### Requirement: Read-only tools are exposed only through the deployment-fixed standard MCP server
系统 SHALL 让独立 Python Runtime 通过部署固定的标准 `tool-mcp` 访问 Job 冻结的只读 MCP Tool，并通过部署固定的 `file-service` File MCP 接口访问 Job 冻结的任务文件工具。Runtime MUST NOT 注册旧 Capability Tool、接受任意 Server URL、在 Tool 不可用时 fallback 或把文件工具路由到 `tool-mcp`。`tool-mcp` 继续使用非认证 Job 绑定传输；File MCP MUST 使用平台短时 Principal JWT 并在服务端复核主体、Job、Publication、scope 和任务工作区。

#### Scenario: Python Runtime调用允许的只读Tool
- **WHEN** Python SDK 调用 Job 精确允许的只读 MCP Tool
- **THEN** 调用通过标准 MCP SDK 进入部署固定 `tool-mcp` 并返回安全结果

#### Scenario: Python Runtime调用允许的文件Tool
- **WHEN** Python SDK 调用 Job 精确允许的 File MCP Tool
- **THEN** 调用只进入部署固定 `file-service` 且携带不含下游 Secret 的 Principal JWT

#### Scenario: Tool上下文按Job隔离
- **WHEN** Python Runtime 并发执行两个调用相同只读或文件 Tool 的 Job
- **THEN** 每次调用使用各自 Job、Publication 和 scope 且不共享模型或 MinIO 凭据

#### Scenario: 模型提供任意MCP地址
- **WHEN** 请求内容或模型输出尝试注册未冻结 MCP Server URL 或 Tool
- **THEN** Runtime 与服务端失败关闭

#### Scenario: 旧平台对象被配置
- **WHEN** 启动或执行配置包含旧 Capability、Handler、Resource Mapping、Internal API Token、`RUNTIME_TOOL_MCP_*` 或 HS256 signing key
- **THEN** 部署预检失败且不启动兼容模式

### Requirement: Health endpoints report runtime mode without invoking Claude
系统 SHALL 聚合唯一支持的 Python Runtime 模式、协议/SDK/CLI 版本和必要依赖的脱敏状态。健康与就绪检查 MUST NOT 调用 Claude、模型 Provider 或业务 MCP Tool，也不得继续报告 TypeScript Runtime 为可配置或受支持路径。

#### Scenario: Python单Runtime模式
- **WHEN** `/api/ready` 在默认生产配置下被调用
- **THEN** 响应报告唯一支持 Runtime 为 `python-v1` 及其脱敏 readiness，且不调用模型或 MCP

#### Scenario: Python Runtime缺少配置
- **WHEN** Python Runtime 的 Grant、模型连接、Master Key 文件、数据库或 CLI 依赖未就绪
- **THEN** readiness 失败关闭并返回脱敏原因

#### Scenario: 部署残留TypeScript配置
- **WHEN** readiness 装配仍发现 TypeScript Runtime URL、allowed host、client 注册或健康依赖
- **THEN** 部署预检失败并报告退役配置残留，不把它计入支持 Runtime

### Requirement: Claude runtime DB-backed settings shall be smoke-verifiable
系统 SHALL 提供 smoke 流程，验证 Python Runtime 的 base URL、model、max turns 和 API key Secret ref 能从 Job 固定模型连接进入独立 Runtime，而不是进入 `agent-worker`。

#### Scenario: Fake Runtime验证配置投影
- **WHEN** 默认 smoke 使用 fake provider 且不启用真实外部调用
- **THEN** 流程仍能验证 Job 固定模型连接被正确投影到 Python Runtime 请求，并确认 Worker 不接收明文 Key

#### Scenario: 可选真实Runtime使用Secret ref
- **WHEN** 开发者提供有效 Secret ref 并显式启用 Python 真实 smoke
- **THEN** Python Runtime 在执行前解析 active Secret，ready/job/debug 输出不包含明文 Key

### Requirement: Worker 必须消费真实 RabbitMQ 队列
在 Docker Compose/runtime 装配中，`agent-worker` SHALL 使用 `RabbitMQConsumer` 持续消费 `agent.job.queue`，claim 固定 Job，并通过平台固定的 Runtime client 调用 Job Publication 决定的独立 Python Runtime。Worker MUST 不得进程内加载或执行 Claude Agent SDK。

#### Scenario: Worker消费Python Job
- **WHEN** `agent.job.queue` 中存在固定为 `python-v1` 的未消费 Job 消息
- **THEN** `agent-worker` 从 RabbitMQ 接收消息、claim Job，并调用 `python-agent-runtime`

#### Scenario: 退役后收到TypeScript消息
- **WHEN** 删除 TypeScript Runtime 后队列出现引用 `typescript-v1` 的消息
- **THEN** Worker 先按持久化 Job 状态幂等处理已终态消息；若 Job 仍可执行则以稳定退役完整性错误失败关闭并触发运维告警
- **AND** Worker 不调用 Python 模型、不改写 runtime kind 且不跨 Runtime fallback

#### Scenario: Worker成功执行后确认消息
- **WHEN** Runtime 终态已验证且 Worker 成功将 Job、结果与 Delivery Outbox 提交到本地数据库
- **THEN** `agent-worker` ack 当前 RabbitMQ 消息，且不会再次执行同一模型 invocation

### Requirement: Docker Compose 必须可验证完整闭环
系统 SHALL 提供 Docker Compose 级验证方式，证明 `api-server`、PostgreSQL 18、RabbitMQ 4 Management、纯编排 `agent-worker`、`python-agent-runtime` 和 Delivery Dispatcher 能协同完成 Python Runtime 成功 Job、真实延迟重试、dead-letter、终态失败和结果投递闭环。默认部署 MUST 不包含 `typescript-agent-runtime` 服务或依赖。

#### Scenario: Python Runtime成功闭环
- **WHEN** 使用 Docker Compose 启动服务并通过受支持入口提交选择 Python Agent 的问题
- **THEN** Worker 经 RabbitMQ 消费后调用 Python Runtime，将 Job 更新为 `SUCCEEDED`，查询能看到结果且配置渠道收到一次投递

#### Scenario: 验证RabbitMQ 4延迟重试回流
- **WHEN** Python Runtime 集成 smoke 首次触发可重试错误并配置短延迟
- **THEN** 测试观察 retry queue 入队、到期、dead-letter 回主队列、同一 Job 被再次 claim，并使用原冻结 `python-v1` Runtime 最终成功或进入终态

#### Scenario: 验证RabbitMQ 4最终失败路径
- **WHEN** Python Runtime 持续触发可重试错误直到次数耗尽或直接触发不可重试错误
- **THEN** Job 状态、retry count、dead-letter 消息、审计和一次安全失败 delivery attempt 保持一致

#### Scenario: Compose不再装配TypeScript Runtime
- **WHEN** CI 解析默认 Compose、镜像目标、服务依赖、网络和健康检查
- **THEN** 不存在 `typescript-agent-runtime`、其 URL/allowed host、Node SDK 镜像或对其 readiness 的依赖

### Requirement: RabbitMQ确认必须等待本地终态提交
Worker MUST 在 Python Runtime 终态被验证且本地 Job/结果/Delivery 事务提交后才 ack 当前 RabbitMQ 消息。Runtime 已完成但本地提交失败时，Worker SHALL 通过相同 invocation/digest 恢复终态，不得直接启动新的模型执行。

#### Scenario: Runtime完成后数据库提交失败
- **WHEN** Runtime 已返回 completed 但 Worker 本地事务回滚
- **THEN** RabbitMQ 消息不被错误确认，重试使用相同 invocation/digest 获取既有安全终态

#### Scenario: 重复RabbitMQ消息
- **WHEN** 相同 dispatch event 被重复投递
- **THEN** Job claim、Runtime invocation 幂等和本地终态共同阻止重复模型执行与重复 Delivery

### Requirement: Runtime选择必须来自Job固定的Agent Publication
Worker MUST 使用 Job 创建事务中从 Agent Publication 固定的 `python-v1` runtime kind 和协议版本调用平台固定 Python Runtime。环境变量、Application allowlist、Runtime 健康状态或错误不得覆盖该事实；未知、不一致或退役的 runtime kind MUST 失败关闭。

#### Scenario: 固定Python Runtime发生瞬时故障
- **WHEN** `python-v1` Job 调用 Python Runtime 发生可重试连接错误
- **THEN** Worker 仍以相同 `python-v1` 和 invocation 语义调度后续 retry，不使用进程内 SDK 或其它 Runtime

#### Scenario: Job与Publication Runtime不一致
- **WHEN** 新 schema Job 的 runtime kind 与其 Agent Publication snapshot 不一致或不为 `python-v1`
- **THEN** Worker 在调用模型前以不可重试完整性错误停止并创建安全失败结果

#### Scenario: 旧迁移门禁仍有配置
- **WHEN** 环境中残留 TypeScript environment/Application allowlist 配置
- **THEN** 新 Job 创建与 Worker 执行不读取该配置，运维预检报告残留项并阻止退役完成

### Requirement: Runtime镜像必须隔离SDK依赖
`agent-worker` 镜像 MUST 不包含 Python Agent SDK 或 Claude Code CLI。Python SDK 与其所需 CLI SHALL 只安装在 `python-agent-runtime` 镜像；已退役 TypeScript Agent SDK、Node Runtime 镜像和 lockfile MUST 不再参与 Agent Runtime 构建或部署。

#### Scenario: 检查Worker镜像内容
- **WHEN** CI 对最终 `agent-worker` 镜像执行依赖和可执行文件检查
- **THEN** Python Claude Agent SDK 和 Claude Code CLI 均不存在

#### Scenario: 检查Runtime镜像内容
- **WHEN** CI 检查 `python-agent-runtime` 镜像和默认 Compose 镜像集合
- **THEN** Python Runtime 镜像只包含执行所需 SDK/CLI 和协议产物，且集合中不存在 TypeScript Agent Runtime 镜像

### Requirement: Runtime Grant不得扩展为MCP认证
Worker→Runtime 的 Runtime Grant SHALL 继续只绑定执行、取消和终态恢复请求。Runtime Grant 的私钥、公钥或 Bearer Token MUST NOT 传递给标准 MCP Tool Server，也不得作为替代的 MCP signing key。

#### Scenario: Runtime调用MCP工具
- **WHEN** Python Runtime 调用标准 MCP Tool Server
- **THEN** 请求不携带 Runtime Grant，MCP Tool Server 也不读取 Runtime Grant key pair

#### Scenario: Worker调用Runtime
- **WHEN** Worker 创建或取消一次 Runtime invocation
- **THEN** Python Runtime 仍校验绑定该 Job、Publication、invocation 和 request digest 的短期 Runtime Grant

### Requirement: Runtime 请求必须只冻结 MCP Tool 而不包含旧平台对象
Worker 发送给 Python Runtime 的执行请求 SHALL 只包含固定 `tool-mcp` Server code、精确 Tool identifier/schema hash 和 Job 标识；MUST NOT 包含 Capability Release、Handler Revision、API Connection、Resource Mapping、Resource Revision、Internal API Token、Runtime URL 或任意 MCP URL。

#### Scenario: Worker 构造 Runtime 请求
- **WHEN** Job 冻结了两个 MCP Tool
- **THEN** Runtime 请求只携带这两个 Tool 的稳定标识和 schema hash，并由 Python Runtime 使用部署固定 URL

#### Scenario: 请求包含旧平台字段
- **WHEN** 请求包含 capability、handler、connection、resource_mapping、internal_api_token 或 runtime_url
- **THEN** Runtime 合约校验失败且不启动模型调用

### Requirement: Runtime 管理单 Job 文件沙盒
Python Runtime MUST 为每次调用创建隔离 Job Sandbox，以受控映射保存本地相对路径、File ID 和基础 Version ID，并在成功、失败、取消或超时终态清理。启动恢复或周期扫描 MUST 清理没有 RUNNING Job 归属的残留沙盒；目录不得跨 Job 复用或持久化。

#### Scenario: Runtime进程异常退出
- **WHEN** Job Sandbox 未执行正常 finally 清理且对应 Job 已经不再 RUNNING
- **THEN** 恢复扫描删除该目录
- **AND** 后续 Job 不能看到其内容

### Requirement: Runtime 通过受控文件桥完成物化和提交
Runtime MUST 通过 File Service 受控流式接口下载 Job File Manifest 中的精确版本和上传显式选中的沙盒文件。File MCP 只创建物化或提交意图并返回不透明标识，完整文件字节 MUST NOT 进入模型上下文、MCP JSON、Tool 事件或审计。Runtime 不得获得 MinIO 凭据、Bucket、对象键或可供模型使用的上传 URL。

Python Runtime MUST 使用代码注册的进程内 File MCP bridge 代理 Job 冻结的部署固定 File Service 工具，并在远端 ToolResult 交回模型前处理隐藏传输控制信息。bridge MUST 使用当前 Job File Principal JWT 和固定内部流式路径，不得接受模型提供的 URL、Header、Token、绝对路径或对象位置；SDK 消息返回后再处理的旁路不满足本要求。

Agent Worker MUST 将有界且无正文的 Job File Manifest 投影交给 Runtime。Runtime MUST 在模型请求前主动物化所有 `auto_materialize=true` 精确版本并向模型提供已校验的安全沙盒元数据；任何自动物化失败 MUST 使 Job 失败关闭。其余候选只能由 Agent 使用 Manifest 中的精确 File/Version ID 按需物化。

#### Scenario: 当前消息附件在模型执行前已进入沙盒
- **WHEN** Job File Manifest 包含一个合法 `auto_materialize=true` 的当前消息文件版本
- **THEN** Runtime 在首次模型请求前通过受控 File bridge 完成下载、大小和 SHA-256 校验及 sandbox entry 登记
- **AND** 模型可直接从安全相对路径读取该文件而无需先发现 File ID

#### Scenario: Agent显式提交沙盒文件
- **WHEN** Agent 调用已冻结的文件提交工具并选择一个受控沙盒文件
- **THEN** Runtime 使用当前 Job 绑定流式上传内容到 File Service
- **AND** Tool 事件只保留文件身份、版本、大小、哈希摘要和结果

#### Scenario: Runtime在模型看到结果前物化文件
- **WHEN** File Service 为 `file_prepare_materialization` 返回合法隐藏传输控制信息
- **THEN** Runtime bridge 在该 ToolResult 返回模型前完成流式下载、大小与 SHA-256 校验和 sandbox entry 登记
- **AND** 模型只收到安全相对路径、不透明 handle、大小和摘要

## ADDED Requirements

### Requirement: 真实Runtime固定为Python
系统 SHALL 为所有新 Agent Publication、Application Publication 和 Agent Job 固定 `python-v1`。生产环境 MUST 不再提供 Runtime 选择、TypeScript feature flag 或跨实现 fallback；测试容器仅在显式注入时使用 stub。

#### Scenario: 新Job固定Python Runtime
- **WHEN** 系统从有效 Python Agent Publication 创建新 Job
- **THEN** Job 在同一事务中固定 `python-v1` 和受支持协议版本，所有 retry 使用相同事实

#### Scenario: 新配置请求TypeScript Runtime
- **WHEN** Agent、Application、环境变量或外部请求尝试为新执行选择 `typescript-v1`
- **THEN** 系统在创建 Job 前以稳定不支持错误拒绝，不改写为 Python

#### Scenario: 本地测试保持Stub
- **WHEN** 单元测试构建测试 Container 且显式注入 stub Runtime client
- **THEN** `AgentExecutor` 使用 stub，不需要模型凭据、Runtime 服务或外部网络

### Requirement: Worker必须拥有Runtime执行的业务状态
`agent-worker` SHALL 独占 claim、授权复核、Publication/hash 校验、retry/终态决策、Tool 事件与结果持久化、Delivery Outbox 创建和 RabbitMQ ack。Python Runtime MUST NOT 直接改变这些业务事实。

#### Scenario: Runtime执行成功
- **WHEN** Python Runtime 返回合法 completed 终态
- **THEN** Worker 在本地事务中保存结果、将 Job 转为 SUCCEEDED 并创建唯一 Delivery Outbox 后再确认 RabbitMQ 消息

#### Scenario: Runtime执行失败
- **WHEN** Python Runtime 返回 failed 终态或协议客户端抛出分类错误
- **THEN** Worker 使用现有 Job policy 决定 RETRY_WAIT 或 FAILED/TIMEOUT，并仅在终态创建一次安全失败投递

#### Scenario: Runtime越权写业务状态
- **WHEN** 部署检查 Python Runtime 的队列订阅、数据库角色和容器配置
- **THEN** Runtime 不具备 RabbitMQ consumer 或 Agent Job、授权、Outbox、Delivery 写权限

### Requirement: Python Runtime必须是独立服务
系统 SHALL 提供唯一 `python-v1` Agent Runtime 独立服务；该服务只执行一次 Agent attempt，不得消费 RabbitMQ、claim Job、决定 retry、写 Job/Delivery 业务状态或直接投递结果。

#### Scenario: Worker调用Python Runtime
- **WHEN** Job 固定的 runtime kind 为 `python-v1`
- **THEN** Worker 通过内部 Runtime client 调用 `python-agent-runtime`
- **AND** Python Runtime 使用 Python Claude Agent SDK 完成本次 attempt

#### Scenario: Runtime尝试拥有业务状态
- **WHEN** 检查 Python Runtime 的队列订阅、数据库角色和容器配置
- **THEN** Runtime 不具备 RabbitMQ consumer 或 Job/Delivery 写权限

### Requirement: Python Runtime必须实现版本化执行协议
Python Runtime MUST 实现平台版本化执行、事件、取消、终态恢复和错误 schema。协议 SHALL 固定 runtime kind、invocation、attempt、request digest、Publication/hash、模型连接、执行限制、Tool allowlist 和 correlation ID；Runtime URL 不得来自 Agent、Application、外部请求或模型输出。

#### Scenario: 合同用例运行于Python Runtime
- **WHEN** contract suite 对 Python Runtime 执行 accepted、tool、completed、failed 和 cancel fixture
- **THEN** Runtime 返回 schema 合法、sequence 单调且唯一终态的结果

#### Scenario: Runtime协议版本不受支持
- **WHEN** Worker 或 Runtime 收到不受支持的协议版本、非 `python-v1` runtime kind 或超限事件
- **THEN** 调用以稳定协议错误失败关闭且不执行模型

#### Scenario: 请求尝试指定任意Runtime地址
- **WHEN** Agent/Application 配置或外部 payload 包含自定义 Runtime URL
- **THEN** 系统拒绝该字段，只使用平台固定 Python Runtime client

### Requirement: Runtime协议事实源必须独立于可退役实现
版本化 Runtime schema、limits、errors 和 golden fixtures SHALL 位于不属于任何可独立退役 Runtime 实现的仓库级合同目录，并由 Worker、Python Runtime、测试和镜像构建共同引用。删除 Runtime 实现 MUST NOT 删除或重写仍受支持的历史协议事实。

#### Scenario: 删除TypeScript实现前迁移合同
- **WHEN** 实施准备删除 TypeScript Runtime 源码目录
- **THEN** 协议 schema、limits、errors 和 golden fixtures 已等内容迁移到仓库级合同目录
- **AND** Python validators、Docker 构建和合同测试全部从新路径通过

#### Scenario: 读取历史协议事件
- **WHEN** 管理端读取退役前按受支持旧协议保存的 Runtime 事件
- **THEN** 系统仍能校验和安全展示这些事件，不要求 TypeScript Runtime 代码存在

## REMOVED Requirements

### Requirement: Real runtime is selectable via feature flag
**Reason**: 平台决定只保留 Python Runtime；继续保留环境/Application TypeScript 选择会产生无法执行的新 Job 和配置漂移。

**Migration**: 新执行固定为 `python-v1`；先冻结 TypeScript 新写入并排空原 Runtime Job，再删除选择配置。

### Requirement: Worker必须拥有跨Runtime执行的业务状态
**Reason**: “跨 Runtime”语义随 TypeScript Runtime 退役而消失，Worker 业务状态所有权仍必须保留。

**Migration**: 使用新增的“Worker必须拥有Runtime执行的业务状态”要求，保持 claim、retry、终态、Outbox 和 ack 责任不变。

### Requirement: Python Worker必须拥有跨语言执行的业务状态
**Reason**: 平台不再跨语言调用 TypeScript Runtime，该要求与新的单 Runtime Worker 所有权要求重复。

**Migration**: Worker 继续以 Python 实现拥有业务状态，Runtime 继续仅执行 attempt。

### Requirement: Python与TypeScript Runtime必须是独立服务
**Reason**: TypeScript Runtime 被退役，双服务拓扑不再成立。

**Migration**: 使用新增的“Python Runtime必须是独立服务”要求；保持 Worker/Runtime 进程与权限隔离。

### Requirement: 双Runtime必须实现同一版本化执行协议
**Reason**: 不再需要跨语言 parity，但 Worker 与 Python Runtime 仍需要同一版本化合同。

**Migration**: 使用新增的“Python Runtime必须实现版本化执行协议”和独立合同事实源要求。

### Requirement: Runtime健康与模型探测必须语言对等
**Reason**: 只有 Python Runtime 后不再存在语言对等目标。

**Migration**: readiness 和模型 probe 统一由 Python Runtime 提供，并继续满足无副作用、固定连接和脱敏要求。

### Requirement: 双Runtime必须共享无专用密钥的标准MCP工具服务
**Reason**: 双 Runtime 等价性不再适用，但无专用密钥的固定标准 MCP 服务边界继续适用。

**Migration**: 使用修改后的标准 MCP 要求，由 Python Runtime 单独调用 `tool-mcp` 与 `file-service`。

### Requirement: 系统必须提供独立TypeScript Agent Runtime
**Reason**: TypeScript Agent Runtime 的维护成本和语义漂移风险高于其未被实际采用的灰度价值，平台正式选择 Python 单 Runtime。

**Migration**: 冻结新 TypeScript 配置，显式迁移 Application Publication，排空非终态 TypeScript Job 后删除服务和依赖；历史事实保持只读。
