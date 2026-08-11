## Context

当前系统已经具备 RabbitMQ Job、Python `agent-worker`、独立 TypeScript `agent-runtime`、版本化执行协议、Runtime Grant、模型连接 probe、Delivery Outbox 和 `runtime-tool-mcp`。但运行拓扑并不对称：Python Claude Agent SDK 与 Claude Code CLI 仍安装并运行在 Worker 内，TypeScript SDK 则位于独立服务；新 Job 的 Runtime 由环境/Application allowlist 门禁选择，而不是由用户在 Agent 发布模型中表达。

这使 Worker 镜像同时承担业务状态机和模型执行依赖，Python/TypeScript 的隔离、扩缩容、升级、readiness 和故障恢复标准不同，也使“应用选择 Agent”与“部署门禁选择 Runtime”产生两个可能冲突的事实源。`runtime-tool-mcp` 还重复实现了专用 HS256 Token 和 Runtime 限定逻辑。本设计统一 Worker/Runtime 边界，并在同一阶段删除该专用服务和密钥，改为两个 Runtime 共用的官方 MCP SDK 标准 Tool Server；其他控制面退役留给后续独立变更。

当前有效链路中的事实所有权保持不变：Business Application 固定 Agent Publication，Job/Worker 拥有执行状态，Delivery Outbox/Dispatcher 按 Job 固定的交付渠道返回钉钉或其他受支持目标。

## Goals / Non-Goals

**Goals:**

- 将 `agent-worker` 收敛为不含 Agent SDK/CLI 的纯 Job 编排服务。
- 将 Python 与 TypeScript Claude Agent SDK 都部署为独立、可替换、可独立扩缩容的 Runtime 服务。
- 让两个 Runtime 实现同一版本化内部协议和相同的完成、失败、取消、超时、幂等恢复与观测语义。
- 让 Agent Definition/Publication 成为 Runtime 选择的唯一事实源；Application 通过选择 Agent Publication 间接选择 Runtime。
- 保持 Job、重试、RabbitMQ ack、结果、Tool 事件和 Delivery 的业务事实只由 Worker 提交。
- 删除 `runtime-tool-mcp`、HS256 signing key 和专用 Token/claims，通过官方 MCP SDK 标准 Tool Server 为两个 Runtime 提供同一工具接口。
- 在迁移中保留历史 Job 与现有 TypeScript Runtime 的可恢复性，并提供可回滚部署顺序。

**Non-Goals:**

- 不在本变更退役 API Capability、Handler、Connection、Resource Mapping、Internal API Platform；这些能力进入后续 MCP 专项变更。
- 不新增 MCP Token、签名密钥、服务发现、治理控制面、任意 Server URL 或第二套工具授权模型。
- 不删除 Worker→Runtime 的 Runtime Grant；它继续用于绑定执行/取消请求，不得被复用为 MCP Tool Server 的认证机制。
- 不把 RabbitMQ consumer、Job 状态机、授权、Business Application、Delivery 或管理 API 移入任一 Runtime。
- 不允许 Runtime 故障时自动跨 Python/TypeScript fallback，也不让同一 Agent Definition 在发布时随意切换 Runtime。
- 不改变钉钉入口和配置交付渠道的业务语义。

## Decisions

### 1. 一个纯编排 Worker 连接两个独立 Runtime

目标拓扑如下：

```text
DingTalk / API
      │
      ▼
Business Application Publication
      │ selects exact Agent Publication
      ▼
Job + Dispatch Outbox → RabbitMQ
                           │
                           ▼
                    agent-worker
                    ├─ claim / authorization recheck
                    ├─ frozen snapshot verification
                    ├─ retry / terminal transaction / ack
                    ├─ result / tool event / Delivery Outbox
                    └─ RuntimeClientRegistry
                         ├─ python-v1     → python-agent-runtime
                         └─ typescript-v1 → typescript-agent-runtime
                                                │
                                                ▼
                                  standard MCP SDK Tool Server
```

Runtime 只执行一次模型 attempt 并返回规范事件；它不消费 RabbitMQ、不决定 retry、不写 Job/Delivery 业务表。这样两条语言路径共享一个 Job 状态机，也避免重复投递和不同事务语义。

拒绝“一个镜像内同时安装 Python/Node 两套 Runtime，并由 Worker 启动子进程”的方案，因为它仍然绑定升级、资源限制和故障域，不能形成真正的独立 Runtime。

### 2. 复用并扩展现有版本化 Runtime 协议

继续使用 `POST /internal/v1/executions` 的版本化请求与 NDJSON 事件流，以及取消、终态恢复、`/health`、`/ready`、`/version` 和 `/internal/v1/model-probes`。协议 schema 的 `runtime_kind` 扩展为 `python-v1 | typescript-v1`，两个实现必须通过同一组 provider/consumer contract 与 golden fixtures。

Worker 使用固定的 `RuntimeClientRegistry` 把受支持的 runtime kind 映射到平台配置的内部 URL。请求、Agent 配置或模型输出不得提供 Runtime URL，也不得触发动态插件发现。

每次请求固定 `invocation_id`、`attempt`、`request_digest`、Job/Agent/Application Publication 标识与 hash、模型连接 revision/hash、执行限制、Tool allowlist 和 correlation ID。事件 sequence 必须单调且只能有一个终态；未知版本、字段越界、摘要冲突或第二个终态均失败关闭。

拒绝为 Python 另建协议，因为两套协议会把差异重新推回 Worker，并使重试、观测和 E2E 无法等价验证。

### 3. Agent Publication 是 Runtime 选择的唯一事实源

在 Agent Definition 增加平台管理、创建后不可变的 `runtime_kind`；每个 Agent Publication snapshot 复制并校验该值。`model_policy.runtime` 继续表达 SDK/模型策略类别，不承担部署 Runtime 选择，避免复用含义不清的旧字段。

内置 Agent：

- `default-diagnostic-agent`：固定 `python-v1`。
- `typescript-diagnostic-agent`：固定 `typescript-v1`。

两个 Agent 都可独立编辑草稿、校验、发布和回滚。要切换 Runtime，管理员选择另一 Agent 的 Publication，而不是修改既有 Agent 的 runtime kind。

Business Application 草稿继续只保存精确 `agent_publication_id`。发布/激活时校验 Publication 完整性、Runtime 支持状态和对应服务 readiness，但不保存第二个 runtime override。创建 Job 的同一事务从 Agent Publication 复制 `agent_runtime_kind`、协议版本及 config hash；所有 retry 继续使用这些冻结值。

环境变量/Application allowlist 的 `RuntimeMigrationGate` 在数据迁移和应用切换完成后删除。拒绝保留双事实源，因为门禁与 Agent Publication 不一致时无法确定哪个配置代表用户意图。

### 4. SDK 与 CLI 只存在于各自 Runtime 镜像

Python `claude-agent-sdk` 从项目公共依赖/Worker target 移入 Python Runtime 专属依赖组或锁定清单；Node 与 Claude Code CLI 只安装在 `python-agent-runtime` 镜像。TypeScript `@anthropic-ai/claude-agent-sdk` 只存在于 `typescript-agent-runtime` workspace/image。纯 Worker 从不继承 Claude Runtime 镜像层。

CI 增加镜像内容断言：Worker 中不能 import 两种 SDK、不能找到 Claude CLI；Python Runtime 不包含 TypeScript SDK workspace；TypeScript Runtime 不安装 Python SDK。运行时版本由 `/version` 返回并写入安全 provenance。

拒绝继续使用当前全局 Python dependencies，因为它会让 API、Migrator 等无关镜像也安装 Agent SDK，扩大构建和安全边界。

### 5. Worker 保有业务事实，Runtime 保有短期执行状态

Worker 负责 claim、当前授权复核、快照/hash 验证、attempt 编号、超时/retry 决策、Tool 事件与结果持久化、Job 终态、Delivery Outbox 和 RabbitMQ ack。Runtime ledger 只保存以 `invocation_id + request_digest` 为键的有界脱敏事件/终态，用于断线或 Worker 本地提交失败后的恢复，不替代 Job 历史。

Runtime 返回 completed/failed 并不代表业务事务已完成。Worker 只有在本地 Job/结果/Delivery 事务提交后才 ack；提交失败或消息重复时，使用相同 invocation/digest 读取既有终态，禁止重新产生模型费用。取消、Worker 超时和 shutdown 通过协议传递，Runtime 最终仍需产生一个规范终态。

模型调用前，Runtime 以 `invocation_id + request_digest + runtime kind` 写入不含 Prompt、Secret 的持久化 claim；终态安全保存后释放 claim。部署边界保持每种 Runtime 单活。若 Runtime 重启后发现旧进程遗留 claim 且无终态，系统采用失败关闭语义：保存 `runtime_orphaned_invocation / NEVER` 终态，不自动重放不可恢复的 SDK 流。操作者如需重试，必须创建新的 Job/invocation。该取舍优先保证不重复模型费用与副作用，而不是伪造流式续跑能力。

### 6. 删除runtime-tool-mcp并改用标准MCP SDK Tool Server

两个 Runtime 都使用 Job 固定的模型连接 revision/config hash、模型映射、effort 和 Credential binding，并在各自基础设施边界只读解析 active Secret。Worker 不接收或转发 provider 明文凭据；health/readiness 不调用外部模型，真实 probe 只在显式管理操作中执行。

`runtime-tool-mcp`、`RuntimeToolTokenIssuer`/验证代码、HS256 signing key、Compose secret、`RUNTIME_TOOL_MCP_*` 配置和专用 claims 全部删除。不得保留旧服务别名、兼容端点、双发 Token 或长期并行路径。

新增单一轻量 MCP Tool Server，直接使用官方 MCP SDK 注册当前阶段仍需使用的工具。该服务地址只由部署配置固定，只连接私有内部网络，不发布宿主机端口；Runtime 只能注册 Worker 从 Job/Publication 冻结的 Tool 名称，Agent、Application、用户 payload 和模型不得提供 Server URL。

MCP Tool Server 不要求或签发 Bearer Token/JWT，不拥有 signing key，也不新建 MCP 专用 RBAC、授权表或治理 API。调用携带非敏感的 Job/invocation 上下文标识，服务端从现有持久化 Job/Publication 读取上下文并调用当前工具实现；现有业务权限与只读约束继续由 Job 创建、Worker 执行前复核和底层工具实现承担，而不是复制到 MCP transport。

Runtime Grant 继续只保护 Worker→Python/TypeScript Runtime 的执行与取消请求。它的 Ed25519 key pair 不传给 MCP Tool Server，也不能用作 MCP 认证。后续 MCP 专项变更负责退役 API Capability 等控制面，但不得恢复 `runtime-tool-mcp` 或其 signing key。

### 7. Readiness、路由和观测按 Runtime 分层

平台 readiness 分别报告 Worker、`python-v1` 和 `typescript-v1` 的协议兼容、SDK/CLI 存在性、配置状态和服务可达性，且不调用模型或 Tool。应用发布/激活只要求其所选 Agent Runtime 可部署；一个未被任何活动应用使用的 Runtime 不应使整个 API 停止提供管理能力，但必须阻止依赖它的新激活和新 Job。

每个 Job/attempt 持久化 runtime kind、协议版本、Runtime/SDK/CLI 版本、invocation、request digest、耗时和稳定错误码；日志、事件和 ledger 不得包含 Key、Token、完整 Prompt、完整 provider/MCP payload 或私有推理。

### 8. 现有 TypeScript 迁移变更以本设计为后续拓扑

`migrate-claude-agent-sdk-to-typescript` 已交付的协议、TypeScript Runtime、Runtime Grant、模型 probe 和合约测试继续复用；其未完成真实 E2E 可以并入本变更的双 Runtime 验收。但其中“Python SDK 长期保留在 Worker”和“环境/Application 门禁决定 Runtime”的决策不再继续实施。

实现开始前必须在 OpenSpec/任务状态中显式标注该取代关系，不能让旧任务 7.5 与新 Worker 镜像要求同时被视为有效验收门槛。

## Risks / Trade-offs

- [增加一个 Python Runtime 服务和一次内部网络跳转] → 使用私有网络、短连接/流式超时、分层 readiness、受限并发和相同 invocation 终态恢复。
- [Python/TypeScript SDK 对事件和错误的表达不同] → 单一 schema、golden fixtures、稳定错误码映射和两端 contract tests；差异只保留在 Runtime adapter 内。
- [历史 Publication 没有 runtime kind] → 默认 Agent/历史 Publication 确定性回填 `python-v1`；已有 Job 保留其已存 runtime kind，并用 legacy schema version 区分。
- [已通过旧门禁运行 TypeScript 的应用发生语义变化] → 不自动改写应用；先创建/发布 TypeScript Agent，再由管理员显式选择并重新发布/激活应用。
- [Runtime 完成但 Worker 本地提交失败] → Runtime ledger 按 invocation/digest 返回同一终态，Worker 重放本地事务，不重跑模型。
- [Runtime 在模型流中崩溃] → 持久化 claim 由新进程识别并转成不可自动重试的 orphan 终态；不重放模型，由操作者显式创建新 Job。
- [无MCP专用Token降低内部服务隔离] → MCP Tool Server 仅在私有网络可达、不映射宿主机端口、使用固定地址和最小数据库权限；接受该边界以避免重新建设自定义签名治理。
- [后续控制面退役造成返工] → 标准 MCP Tool Server 只依赖官方 SDK、通用 Tool schema 和持久化 Job/Publication 上下文，不复制 API Capability 等控制面模型。
- [双 Runtime 资源用量增加] → Runtime 可独立配置并发和扩缩容；Worker 保持轻量且两种 SDK 不重复进入其镜像。

## Migration Plan

1. 对齐并冻结现有协议、TypeScript Runtime 与 Python 进程内执行的成功、Tool、timeout、取消、重试和错误 golden 基线；显式记录对旧 OpenSpec 变更的取代关系。
2. 扩展 schema：Agent Definition/Publication 增加不可变 runtime kind，协议接受双 Runtime；历史默认 Agent/Publication 回填 `python-v1`，历史 Job 保留已有 runtime kind。
3. 新增官方 MCP SDK 标准 Tool Server，使其在无 MCP Token/signing key 的情况下通过私有网络为现有工具提供标准接口；完成两个 Runtime 的工具合约验证。
4. 新增 `python-agent-runtime` 服务、专属依赖和镜像，实现与 TypeScript 相同的执行/取消/终态/probe/health 契约；先部署但不切流。
5. 引入 Worker `RuntimeClientRegistry`，让它能够按 Job 冻结值调用两个 Runtime；保留旧执行路径作为短期部署回滚开关，但不再接收新配置。
6. Seed 并发布 `typescript-diagnostic-agent`；前端开放两个 Agent 的独立管理，Application 页面展示 Runtime 标签并选择精确 Publication。
7. 将旧 TypeScript 灰度应用显式迁移到 TypeScript Agent Publication，完成发布、激活和新 Job 验证；未迁移应用保持 Python Agent。
8. 将两个 Runtime 一次性切到标准 MCP Tool Server，确认无旧调用后删除 `runtime-tool-mcp` 容器/代码、HS256 issuer/verifier、secret、配置和测试；不得长期双运行。
9. 切换到纯 Worker 镜像，删除 RuntimeMigrationGate 和 Worker 内 SDK/CLI 依赖；验证两个 Runtime 的 Compose、重启、重复消息和终态恢复。
10. 分别完成 Python、TypeScript 两条真实 `DingTalk -> Application -> Agent -> Job -> Worker -> Runtime -> MCP Tool Server -> Result -> Delivery` E2E，并执行敏感信息扫描和观察窗口。
11. 观察稳定后删除仅用于回滚的 Worker 进程内执行代码和旧门禁配置；API Capability 等控制面保持现状并另建后续 OpenSpec change 退役。

回滚按阶段执行：纯 Worker 切换前可回退镜像且保留新增字段；切换后若单一 Runtime 故障，只停止依赖该 Runtime 的新 Job/应用激活，不把在途 Job切到另一 Runtime。回退旧 Worker 时必须继续尊重 Job 已冻结的 runtime kind 和 invocation，不能回写 Agent/Application Publication。

## Open Questions

无阻塞问题。服务端口、资源配额和 Python Runtime 源码目录属于实现配置，不改变上述服务边界与协议；实施时按仓库现有命名和端口约束落地。
