## Context

当前 `agent-worker` 从 RabbitMQ 接收 Job，使用 Python 服务完成 dispatch event 校验、Job claim、业务应用授权复核、Agent/Application Publication 解析、MCP Job Binding 冻结、Claude Agent SDK 执行、Job 状态转换、结果保存和 Delivery 入队。真实 SDK 适配器位于 Python 后端，并依赖额外 Node.js/Claude CLI 镜像层；MCP Server 已独立为使用 MCP v2 的 ONES/Data 服务，Worker 通过旧协议兼容客户端连接它们。

`simplify-platform-with-mcp` 已删除旧 API Capability/Internal API Platform 及大部分管理前端，但验收发现 `mcp_tool_publication` 只有 schema 和读取路径，没有受治理写入口，干净环境无法产生真实 Agent/Application 精确 Tool allowlist。此前删除的 Agent/Application 页面又依赖大量已退役 Capability 和资源组合，不能从 `master` 或 Git 历史整体恢复。

官方 TypeScript 包为 `@anthropic-ai/claude-agent-sdk`。实施时必须从官方 npm registry 解析最新非 prerelease 稳定版并把精确版本写入 lockfile；升级不得使用浮动 `latest` 运行生产镜像。官方 SDK 默认会读取用户、项目和本地 settings，因此部署服务必须显式设置 `settingSources: []`，不能继承宿主机或镜像中的 Claude 配置。

## Goals / Non-Goals

**Goals:**

- 将真实 Claude Agent SDK 执行完全迁移到独立 TypeScript 服务，并在最终切换后删除 Python SDK 依赖和执行实现。
- 保持现有 Python Job/RabbitMQ/授权/状态/Delivery 事实源不变，避免用两种语言实现同一套业务事务。
- 保持每个 Job 固定 Agent/Application Publication、精确 MCP Tool allowlist、短期 MCP Token、只读工具和安全失败分类。
- 建立可版本化、可取消、可观测、可幂等判定的 Python Worker 到 TypeScript Runtime 内部协议。
- 补齐 MCP Tool Publication 治理，并恢复多 Agent Publication 与 Business Application 的受控 Web 工作台。
- 支持多个 Application 独立选择 Agent Publication、MCP Tool Publication、Resource Deployment、Channel、Trigger 和 Delivery，并在环境级显式激活。
- 提供可演练的分阶段切换和回滚路径，最终生产不存在静默 Python fallback。

**Non-Goals:**

- 不把 API、RBAC、Job repository、Business Application、Delivery 或资源控制面重写为 TypeScript。
- 不合并 ONES/Data MCP Server 到 Agent Runtime，不自研 MCP Gateway，也不允许自动发现全部 MCP Tool。
- 不恢复 API Capability、Handler、Connection、Internal API Platform、任意 SQL/HTTP/LogQL/Redis/Shell 执行器或资源 Secret Web 编辑器。
- 不把模型 API Key、MCP Token、ONES Token、数据库密码或 Master Key 放进 RabbitMQ、Job 快照、Application Publication 或浏览器。
- 不在本变更引入 Vault、Kubernetes Operator、通用工作流画布或 Agent 编排 DSL。

## Decisions

### 1. 拆分“Python 编排面”和“TypeScript 执行面”

新增 `agent-runtime/` TypeScript workspace 和独立 `agent-runtime` 容器。Python `agent-worker` 继续消费 RabbitMQ、验证 dispatch event、claim Job、构造不可变执行上下文并持久化最终状态；TypeScript Runtime 不直接消费业务 Job 队列，也不写 Agent、Application、Delivery 或授权表。

```text
RabbitMQ
   │
   ▼
Python agent-worker
   ├─ claim / authorization / publication / retry / result / delivery
   ├─ sign execution grant and exact MCP tokens
   │
   └─ internal streaming HTTP
          ▼
      TypeScript agent-runtime
          ├─ resolve exact model credential
          ├─ @anthropic-ai/claude-agent-sdk
          ├─ exact remote MCP servers + allowedTools
          └─ normalized safe events/result
```

该边界使 SDK 高频升级和 Node 依赖留在执行服务，同时保持 PostgreSQL 事务和已有 Job 生命周期只有一个实现。拒绝让 TypeScript Runtime 直接消费 RabbitMQ并重写全部 Worker，因为那会复制 claim、retry、授权、审计和 Delivery 语义，迁移面远大于 SDK 本身。

### 2. 使用版本化流式执行协议，不以数据库作为跨语言调用接口

内部协议第一版为 `POST /internal/v1/executions` 的 NDJSON 流。请求使用严格 JSON Schema，至少包含：

- `protocol_version`、`invocation_id`、`attempt`、`job_id` 和 correlation ID；
- Agent/Application Publication ID、revision、config hash 与规范化安全上下文；
- 固定模型连接 revision/hash、非敏感模型配置和稳定 Secret ref；
- turns、wall-clock、tool-call、输入/输出字节限制；
- 精确 MCP Server URL、Tool 名、Schema hash、scope、resource binding 和短期 MCP Token；
- 固定不可用提示和安全规则。

响应事件只允许 `accepted`、`assistant_text_delta`、`tool_started`、`tool_finished`、`diagnostic`、`completed`、`failed`，每条具有单调 sequence、schema version 和大小上限。`completed` 返回最终文本、usage 和安全 Tool event；`failed` 只返回稳定错误码、retry class、脱敏诊断和失败前事件。私有 thinking block、完整 Prompt、认证 Header、原始 MCP/Provider payload 不得出站。

取消使用 `DELETE /internal/v1/executions/{invocation_id}`，Runtime 必须把它传播到 SDK AbortController 和正在进行的 MCP 请求。Python 连接断开、Job 被撤销或超时后也必须触发取消。`invocation_id + request_digest` 是幂等键：相同键和摘要可返回已有终态，不同摘要冲突失败；Runtime 只保留有界终态缓存/ledger，不接管 Job 事实源。

拒绝直接让 TypeScript 查询完整 Job 表作为输入协议，因为这会形成隐式共享数据库契约并扩大数据库权限；也拒绝只返回一个同步 JSON，因为那无法可靠保留超时前 Tool 事件和取消状态。

### 3. 执行授权和凭据解析分层

Python Worker 为每次 invocation 签发短期 Runtime Grant，claims 至少包括 `iss`、`aud=agent-runtime`、`azp=agent-worker`、`job_id`、`invocation_id`、Publication/hash、request digest、`iat/exp/jti`。TTL 不得超过 Job 剩余执行窗口加 60 秒且上限 15 分钟；Runtime 校验服务身份、全部 claims、请求摘要和重放状态。

Python Worker 继续签发精确 MCP Token，并只在本次内部请求内把 Token 交给 Runtime；Token 不进入 RabbitMQ、数据库、日志或 SDK Prompt。Runtime 的 logger、error serializer 和 tracing processor 在结构化日志前统一屏蔽 Authorization、API Key、Token、Secret ref 和 URL credential。

模型 API Key 由 Runtime 在 attempt 开始时按 Agent Publication 固定的模型连接和稳定 Secret ref 解析。Runtime 获得只读 Secret/Model revision 数据库权限并只读挂载仓库外 Master Key；Node 实现必须与 Python encrypted DB Secret 格式做双向固定 fixture 兼容测试。API 仍负责 Secret 创建/轮换，Runtime 只允许解析当前 active version。Agent Worker 不重新挂载 Master Key，浏览器和 RabbitMQ 永远不接触 Key。

拒绝由 Worker 解密 Key 后放入队列或持久化执行请求；也拒绝把 Master Key 设为普通环境变量。Compose 私有网络仍需服务令牌保护；生产部署应在反向代理或 service mesh 提供 TLS，协议不能把网络位置当作认证。

### 4. TypeScript SDK 配置必须显式隔离并双重限制 Tool

每次 `query()` 使用独立 options/env 对象，显式设置：

- `settingSources: []`，不读取用户、项目或 local settings；
- Job 固定 model、system prompt、turn limit 和 AbortController；
- 仅当前请求列出的远程 MCP Server；
- `allowedTools` 为精确 `mcp__<alias>__<tool>` 集合；
- `disallowedTools` 至少覆盖 Bash、Write、Edit、NotebookEdit、WebFetch、WebSearch、Shell 及文件修改能力；
- `canUseTool` 对精确集合外任何 Tool 返回 deny，且无 allowlist 时不注册任何 MCP Server。

MCP Server 继续独立验证短期 Token、Job 状态和 scope，所以 Runtime allowlist 不是唯一安全边界。所有 MCP 输出继续作为不可信业务数据；Tool description、system prompt 和安全规则只能来自代码与不可变 Publication，不能被 MCP 输出或前端自由字段覆盖。

SDK 版本策略采用“实施时解析最新稳定版、精确 pin、契约验证后升级”。lockfile、镜像 label、readiness 和 Job provenance 都记录确切 SDK/CLI 版本。不得在容器启动时执行 `npm install`，也不得依赖全局 `@anthropic-ai/claude-code`。

### 5. Runtime 只返回规范事件，Python 继续决定状态与重试

TypeScript 将 SDK/CLI 异常映射为稳定协议错误族：认证/模型/配置、权限拒绝、最大轮次、最大 Tool Call、timeout/cancel、rate limit/overload、transport/CLI decode、矛盾 result、协议错误。Python 使用协议中的 `retry_class` 和本地 Job policy 决定 retry/dead-letter，TypeScript 不发布 RabbitMQ retry 消息。

Python Worker 按 sequence 持久化安全 Tool event/provenance，最终在一个本地事务完成 result、Job SUCCEEDED 和 Delivery outbox。Runtime 完成但 Python 未提交时，使用相同 invocation 查询终态后重放，避免不确定网络错误立即重复产生模型费用。任何摘要、Publication 或序列不一致都按不可重试完整性错误失败。

### 6. MCP Tool Publication 是独立治理对象并被应用发布冻结

现有表把 Tool Publication 直接同时关联 Agent/Application，缺少稳定生命周期和写入口。本变更将其调整为稳定 Identity/可变 Draft/不可变 Revision 或等价的不可变 Publication 模型，并至少冻结：`server_code`、`tool_name`、`required_scope`、`tool_schema_hash`、可选 `resource_code/resource_deployment_id`、状态、revision 和审计主体。

Tool 目录只能来自代码发布的 ONES/Data MCP registry。管理员可以选择目录项并绑定资源，但不能填写自由 Tool 名、Server URL、Schema、scope、SQL 或认证信息。发布时服务端实时校验 Server/Tool 仍存在、Schema hash 匹配、Resource Deployment active、Agent/应用范围一致；Application Publication 保存精确 Tool Publication ID/revision/hash。取消发布立即阻止新 Job，已固定 Job 仍在每次调用时复核撤权并失败关闭。

Agent Publication 定义“这个 Agent 允许使用的最大 Tool 集合”；Application Publication 从其中选择子集并绑定具体资源。最终可调用集合是 Agent Publication、Application Publication、当前主体/凭据、Resource Deployment 和服务端 scope 的交集。该规则原子解决多个 Application 使用同一 Agent 但暴露不同 Tool 的场景。

### 7. 恢复前端时重建当前控制面，不整体恢复旧代码

前端恢复两个权限感知工作区：

1. Agent：多 Agent 列表、详情、草稿、校验、模型连接、MCP Tool 最大集合、Publication 历史与回退；
2. Application：列表、详情、Agent Publication、MCP Tool 子集/Resource、Channel/Trigger/Delivery、校验、发布、环境激活/停用和 effective preview。

页面复用现有 Session/RBAC/CSRF、TanStack Query、表单和错误契约。旧删除文件只作为交互参考，不能直接恢复其 Capability、Handler、Connection、Resource Composition、静态 fixture 或旧 API Client。后端先建立统一治理 API 和契约测试，CLI 可复用同一 Application Service 做应急运维；前端随后调用同一 API，不在浏览器复制发布规则。

管理导航按权限显示；无权访问具体对象返回防枚举结果。所有写请求携带 expected revision 和幂等键。旧 `/applications` 退役页仅在新 API/UI 未启用时保留，正式切换后替换为真实页面；已删除的 `/platform/resources` 等路径继续退役。

### 8. 迁移从当前 MCP 分支继续，不从 master 回搬旧平台

实施基线必须是当前 `mcp_dev` 的 MCP 代码与 schema。首先把 MCP 基线提交为可回退点，再实施本变更；不能从 `master` 开新分支后合并，因为 master 仍含本次明确退役的 API/Internal Platform 与过重前端。OpenSpec 语义先以 `simplify-platform-with-mcp` 为基线，归档时先归档前置变更，再重放/校验本变更 delta。

切换阶段：

1. 固化 Python 运行时契约 fixture、真实 opt-in smoke 和 MCP 协议测试；
2. 上线不承载生产 Job 的 TypeScript Runtime，完成健康、Secret、MCP 和失败分类测试；
3. 为测试环境/指定 Application Publication 显式选择 `typescript-v1`，禁止单次 attempt 自动 fallback；
4. 验证完整 `Ingress → Job → Python Worker → TypeScript Runtime → MCP → Result → Delivery` 链路、取消、重试和重启；
5. 把新 Job 默认路由切换到 TypeScript，允许已开始的 Python Job 完成；
6. 观察窗口通过后删除 Python SDK、适配器、依赖和全局 CLI 镜像层。

删除前可通过显式 deployment/feature gate 把尚未开始的新 Job 切回 Python；运行中的 attempt 不跨 Runtime 重放。删除后的回滚是部署上一版本镜像并切回 runtime gate，数据库迁移必须保持向后兼容一个发布窗口。生产切换需要用户明确确认，不随代码部署自动发生。

## Risks / Trade-offs

- [跨服务调用增加延迟和故障点] → 私有网络长连接、严格超时、幂等 invocation、终态查询和分层 readiness；不在协议中做聊天式多次往返。
- [Python 与 TypeScript 契约漂移] → 单一 JSON Schema、生成两端类型、golden fixture、consumer/provider contract test 和 protocol version 拒绝策略。
- [Node Secret 解密实现错误] → 固定密文 fixture、Python/Node 交叉兼容测试、最小数据库 grant、Master Key 只读文件和日志敏感扫描。
- [SDK 最新版产生 breaking change] → 实施时精确 pin，先跑无凭据契约与可选真实 smoke，再更新镜像；生产不使用 semver 浮动安装。
- [Runtime 完成但 Worker 断线导致重复费用] → invocation ledger/终态重取；只允许相同 request digest 重放，摘要冲突失败。
- [双 Runtime 迁移期行为不同] → 测试环境/Application 级显式选择、相同 golden cases、无自动 fallback、短观察窗口后删除旧路径。
- [恢复前端重新引入旧平台复杂度] → UI 仅管理 Agent/Application/MCP Publication，代码与静态扫描禁止 Capability、Handler、Connection 和自由执行器复活。
- [两个活动 OpenSpec 变更修改相同能力] → 实施以 MCP change 当前代码为事实，归档前先完成并归档 `simplify-platform-with-mcp`，再重新严格校验本变更 delta。

## Migration Plan

1. 提交并标记当前 MCP 基线，记录自动回归和仍需真实凭据完成的验收项。
2. 增加协议 schema、Python fake client、TypeScript fake SDK 和跨语言 golden contract，先证明失败路径与敏感字段规则。
3. 创建 TypeScript Runtime、镜像、非 root 用户、只读 Secret 解析、服务授权、health/readiness 和 Compose 接线。
4. 迁移 Claude query、MCP server config、permission hooks、事件/错误归一化、取消与 invocation ledger。
5. 让 Python Worker 通过新客户端执行测试 Job，保留 Python SDK 为受控迁移 gate；完成 MCP v2 compatibility 和真实模型 opt-in smoke。
6. 建立 MCP Tool Publication 管理 schema/service/API/CLI，再恢复 Agent 和 Application 管理 API/UI。
7. 在可丢弃环境创建多个 Agent/Application，验证不同 Tool 子集、资源、环境激活、撤权、并发编辑和完整渠道 Delivery。
8. 经用户确认切换新 Job 默认 Runtime；观察通过后删除 Python SDK 路径、依赖、镜像层和旧 feature gate。

回滚只能切换尚未开始的新 Job；RUNNING attempt 必须在原 Runtime 结束、取消或超时。任何回滚不得放宽 Tool allowlist、Publication integrity 或凭据隔离。

## Open Questions

无阻断性产品问题。SDK 精确版本、Node LTS patch 版本和生产 TLS 终止点属于实施时可验证的部署输入，必须在 lockfile、镜像和验收记录中固化，不允许作为运行时浮动配置。
