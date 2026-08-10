## Context

当前 `mcp_new` 的 `agent-worker` 在 Python 进程内完成 Job claim、授权、上下文构造、`claude_agent_sdk` 调用、进程内 MCP Tool 调用、结果持久化和 Delivery 入队。Python SDK 还依赖 Node/Claude CLI，使 SDK 升级、Secret 注入和工具执行故障与核心业务事务处于同一进程。

`mcp_dev` 已实现独立 TypeScript Runtime、跨语言协议、模型连接 probe 和远程 MCP 执行，但该分支同时包含大规模平台裁剪。本变更只把经过验证的执行面设计移植到 `mcp_new`，不得恢复或删除与本迁移无关的控制面。

## Goals / Non-Goals

**Goals:**

- 在现有 Python SDK Runtime 之外提供隔离的 TypeScript Claude Agent SDK Runtime。
- 保持 Python 对 Job、授权、Publication、重试、审计、结果和 Delivery 的唯一事实所有权。
- 保持当前只读 Tool、业务应用授权、资源范围和失败提示语义。
- 使用严格版本化协议、短期执行授权、精确 Tool allowlist 和隔离的每次调用环境。
- 支持无 Tool 模型 probe、测试 Application 灰度、明确回滚和双 Runtime 长期兼容。

**Non-Goals:**

- 不把 RabbitMQ consumer、Job repository、RBAC、Business Application、Delivery 或管理 API 重写为 TypeScript。
- 不合并 `mcp_dev` 的前端、API Capability 退役、资源控制面或数据库清理。
- 不增加任意 URL、任意 MCP Server、SQL、Shell、脚本或通用执行器。
- 不切换 Python 默认 Runtime，也不删除 Python SDK、进程内真实执行路径或其 CLI 镜像层。

## Decisions

### 1. Python 编排面与 TypeScript 执行面分离

Python Worker 继续消费 RabbitMQ、claim Job、复核业务授权并构造冻结执行请求；TypeScript Runtime 只执行一次 SDK attempt 并返回规范事件。Runtime 不直接写业务表，也不发布重试或 Delivery。

```text
RabbitMQ
   │
   ▼
Python agent-worker
   ├─ claim / authorization / immutable snapshot
   ├─ retry / audit / result / Delivery Outbox
   └─ POST /internal/v1/executions (NDJSON)
                │
                ▼
        TypeScript agent-runtime
          ├─ model binding + Secret resolve
          ├─ @anthropic-ai/claude-agent-sdk
          ├─ exact remote MCP allowlist
          └─ normalized events / terminal result
```

拒绝让 Runtime 直接消费 RabbitMQ，因为那会在两种语言中复制 Job 状态机、重试和事务语义。

### 2. 使用严格的版本化 NDJSON 协议

执行端点为 `POST /internal/v1/executions`，请求至少固定 protocol、invocation、attempt、Job/Publication/model revision 与 hash、执行限制、精确 MCP Server/Tool、resource scope 和 correlation ID。响应只允许 accepted、tool、diagnostic、completed、failed 等规范事件，并要求 sequence 单调、唯一终态和有界字节数。

取消通过独立端点传播到 SDK AbortController。`invocation_id + request_digest` 作为幂等键；相同摘要可读取既有终态，不同摘要必须拒绝。Runtime ledger 只保存脱敏、有界的协议终态，不替代 Job 历史。

### 3. Runtime Grant 与凭据隔离

Worker 为每次 attempt 签发短期 Runtime Grant，绑定 audience、service identity、Job、invocation、Publication/hash、request digest、过期时间和 JTI。Runtime 必须在启动 SDK 前验证全部 claims。

模型 Key 由 Runtime 按请求固定的模型连接 revision/config hash 和稳定 Credential binding 读取 active Secret；Master Key 只读文件挂载，Runtime 数据库角色只读最小字段。MCP Token 只存在于本次内部调用和 SDK MCP transport 配置，不进入 Prompt、RabbitMQ、数据库、日志或终态 ledger。

### 4. 当前 Python Tool 通过受治理远程 MCP 边界提供

当前进程内 MCP 不能跨语言复用。迁移将只读工具按现有 Tool Catalog 分类暴露为受治理的远程 MCP 服务或窄范围适配器；服务端继续验证短期 Token、Job 状态、主体、Application、Tool 名、scope 和资源绑定。Runtime 只注册 Job 请求中精确列出的 Server 和 Tool，不做平台全量发现。

若某个当前 Tool 尚未具备远程 MCP 等价实现，该 Application 不得切到 TypeScript Runtime；不得以任意 HTTP 回调、自动 Python fallback 或放宽 allowlist 代替。

### 5. SDK 采用双重 Tool 限制

每次调用显式设置 `settingSources: []`，不读取用户、项目或镜像内 Claude settings。`allowedTools` 只包含冻结的 `mcp__<server>__<tool>`；`canUseTool` 对集合外调用失败关闭；Bash、Write、Edit、NotebookEdit、WebFetch、WebSearch、Shell 和文件修改能力进入固定 denylist。

### 6. Runtime 只分类错误，Python 决定 retry 和终态

Runtime 将认证、配置、权限、最大轮次、最大 Tool Call、timeout/cancel、429/5xx、transport、协议和矛盾 result 映射为稳定错误码及 retry class。Python 根据本地 Job policy 决定 retry/dead，不允许 Runtime 直接改变 Job 状态。

Tool 事件只保留顺序、Tool 标识、安全输入摘要、结果大小、状态、错误码和 provenance；不返回 thinking、完整 Prompt、原始 Provider/MCP payload 或认证材料。

### 7. 双Runtime长期共存且单次attempt不自动fallback

Runtime 选择必须在 Job/Application Publication 中冻结。系统长期支持 `python-v1` 与 `typescript-v1`；没有显式 TypeScript 选择时必须使用 `python-v1`。同一次 attempt 或 retry 不得在连接故障时自动跨 Runtime，避免重复费用和不同 Tool 语义。真实钉钉 E2E、敏感扫描和观察窗口只决定某个 Application 是否可启用 TypeScript，不改变全局 Python 默认值，也不触发 Python SDK 删除。

### 8. 模型连接 probe 与正式执行共用 Runtime 安全边界

模型连接测试调用 `/internal/v1/model-probes`，固定 revision/config hash，禁止 MCP/Tool，单轮、短超时，只返回 Runtime/SDK 版本、脱敏 host、model、耗时和稳定错误码。Python API 继续先执行 RBAC、SSRF、重定向和 host allowlist 校验。

## Risks / Trade-offs

- [跨服务调用增加延迟和故障点] → 使用私有网络、严格超时、幂等 invocation、终态读取和分层 readiness。
- [Python/TypeScript 协议漂移] → 使用单一 JSON Schema、生成类型、golden fixture 和 consumer/provider contract test。
- [现有进程内 Tool 无远程等价物] → 按 Tool Catalog 建立明确迁移清单，未完成的 Application 禁止切换，不允许隐式 fallback。
- [Node Secret 解密或配置解析错误] → 使用 Python/Node 固定密文交叉 fixture、最小只读数据库授权和敏感输出扫描。
- [Runtime 完成但 Worker 未提交] → 相同 invocation/digest 查询既有终态，Python 再完成本地事务，避免重复模型费用。
- [双 Runtime 期间行为不一致] → Application 级显式 gate、相同 golden case、短观察窗口和可追溯 runtime provenance。

## Migration Plan

1. 固化当前 Python Runtime 的成功、Tool、timeout、权限和错误分类 golden 行为。
2. 移植 TypeScript workspace、协议、Runtime Grant、ledger、模型绑定、probe 和无凭据测试。
3. 接入 Python Runtime client 与显式 migration gate，默认仍为 `python-v1`。
4. 为当前只读 Tool 建立远程 MCP 等价映射及服务端 Job/scope 复核。
5. 在 Compose 启动非 root、只读文件系统的 Runtime 和必要 MCP 服务，完成健康与契约验证。
6. 在可丢弃 Application 上切换 `typescript-v1`，验证模型、Tool、取消、重试、重启和失败投递。
7. 验证真实 `DingTalk → Inbox/Outbox → RabbitMQ → Python Worker → TypeScript Runtime → MCP → Result → Delivery`。
8. 固化 Python 默认值和双 Runtime 兼容门禁；TypeScript 仅对显式批准的 Application 启用，回滚只影响尚未开始的新 Job。

回滚只影响尚未开始的新 Job；RUNNING attempt 必须在原 Runtime 完成、取消或超时。数据库、协议和两条 Runtime 路径需要持续向后兼容。

## Open Questions

- 当前 `mcp_new` 每个只读 Tool 的远程 MCP 等价实现和灰度优先级需要在实施清单中逐项核对；这不改变“无等价实现则禁止切换”的失败关闭规则。
- 生产 TLS 终止点由部署环境决定，但内部协议不能仅依赖网络位置进行认证。
