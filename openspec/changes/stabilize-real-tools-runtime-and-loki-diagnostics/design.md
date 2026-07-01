## Context

当前系统已经跑通了基础 Agent 执行链路：`api-server` 创建任务，RabbitMQ 投递，`agent-worker` 消费执行，工具调用经 `InternalApiClient` 进入内部工具平台。代码里同时存在三类工具平台入口：

```text
mock-internal-api-platform   -> mock-tools，返回假业务证据
local-internal-api-platform  -> local-tools，开发机真实 Loki 快速联调
internal-api-platform        -> real-tools，拓扑化正式工具平台主线
```

`local-tools` 已经验证可以从容器访问宿主机 Loki，但测试结果为 `line_count=0`。这说明网络链路通了，但还缺少 label、tenant、selector、时间窗口和样例日志的诊断能力。`internal-api-platform` 已经具备拓扑、权限、多库、Redis/Loki 隔离雏形，但 Compose profile、文档和 smoke test 还没有把它明确成正式主线。

真实 Claude/DeepSeek 联调还存在安全边界问题：如果直接提交真实业务问题，工具摘要和日志证据可能被发送到外部模型。因此本 change 必须同时定义“真实工具链如何验证”和“真实模型如何安全验证”。

## Goals / Non-Goals

**Goals:**

- 明确 fake、mock-tools、local-tools、real-tools 四种运行模式的用途、启动命令和验收方式。
- 将 `internal-api-platform` 固化为正式 real-tools 主线，避免继续把生产形态建立在 `local-internal-api-platform` 上。
- 为 Loki 增加受限诊断能力，能回答“为什么查不到日志”：tenant 是否有效、有哪些 labels、某 label 有哪些 values、selector 是否能在指定时间窗命中。
- 让 real-tools smoke test 能从工具平台层验证到 Agent debug API 层：health、topology resolve、labels、query、job、steps、tool-calls。
- 建立真实 Claude/DeepSeek 联调的安全默认值：只用合成日志或脱敏摘要；未经确认不发送真实业务日志到外部模型。

**Non-Goals:**

- 不增加写操作，不实现 Redis 删除、数据库更新、服务重启、发版或代码修改。
- 不做 Web 配置台 UI。
- 不把 Agent runtime 改成直连 Loki/DB/Redis。
- 不在本 change 中完成 ER 图、业务图、真实 schema 搜索平台的全部接入。
- 不强制接入真实 SQL Server / Oracle 实例；保留可选真实实例验证路径。

## Decisions

### 1. `internal-api-platform` 是 real-tools 主线

选择：将 `internal-api-platform` 作为正式工具平台服务，使用 `real-tools` profile 启动；`local-internal-api-platform` 只保留为本机 Loki 快速验证入口。

理由：

- `internal-api-platform` 已经有拓扑、权限、多方言 SQL、基地级 Redis/Loki 设计，更接近后续生产形态。
- `local-internal-api-platform` 只有扁平 service/query 形态，适合快速排查容器到宿主 Loki 的网络问题，但不能承载多环境、多基地、多车间权限。

备选：继续增强 `local-internal-api-platform`。放弃原因是会形成两套平台主线，后续 Web 配置、权限、审计和拓扑都会重复。

### 2. Loki 诊断 API 仍在 Internal API Platform 内部，不暴露给 Agent 直连

选择：新增或扩展平台 endpoint，例如：

```text
GET/POST /tools/loki/labels
GET/POST /tools/loki/label-values
POST     /tools/loki/probe
```

这些 endpoint 仍通过 platform 权限、拓扑、tenant、label allowlist、时间窗和响应大小限制。

理由：

- 诊断能力本身也可能泄露内部系统结构，必须走平台访问控制。
- Agent runtime 只知道工具平台契约，不应该知道 Loki 地址、tenant header 或认证方式。

备选：在 README 里用 `curl localhost:3100` 手工排查。放弃原因是无法进入可审计工具链，也无法被 agent-worker/debug API 复用。

### 3. 空结果要成为可解释结果，而不是“HTTP 200 即成功”

选择：Loki query/probe 返回 summary 时必须包含：

```text
selector
query
minutes
line_count
stream_count
labels_seen 或 candidate_label_values
empty_reason_hints
```

理由：

- `line_count=0` 是真实排障中高频问题，通常来自 label 名不对、tenant 不对、时间窗不对、服务名不对或日志内容不存在。
- Agent 最终报告需要能说明“不具备证据”的原因，而不是继续扩大查询直到 max turns。

备选：让模型自己继续换 selector 猜。放弃原因是这会消耗 token，并可能扩大日志查询范围。

### 4. 真实模型测试默认使用合成/脱敏数据

选择：真实 Claude/DeepSeek + real-tools 端到端 smoke test 必须满足以下之一：

- Loki 中注入或使用明确合成的测试日志。
- 工具平台返回给模型的日志摘要已经脱敏，并且不包含密钥、token、个人信息、内部敏感内容。
- 用户明确确认当前测试数据可发送到外部模型。

理由：

- DeepSeek Anthropic-compatible API 是外部模型 API，默认不应接收未脱敏内部日志。
- 该项目 MVP 是只读诊断 Agent，安全边界比“跑通一次”更重要。

备选：直接用真实业务问题测试。放弃原因是安全风险不可控。

### 5. Smoke test 分两层

选择：验收分为工具平台层和 Agent 层：

```text
工具平台层：
  health -> resolve/context -> labels -> label-values -> probe/query

Agent 层：
  POST /api/agent/jobs -> worker -> tool-calls -> steps -> final status
```

理由：

- 当 Agent job 失败时，可以快速判断是模型、队列、worker、工具客户端、平台、Loki tenant/selector 哪一层的问题。
- 这也符合后续 Web 配置平台的调试体验。

## Risks / Trade-offs

- [Risk] Loki label values 可能很多，诊断 endpoint 可能变成昂贵查询。→ 只允许 bounded label 查询，限制时间窗、limit、响应字节数，并允许返回 truncated。
- [Risk] label/series 诊断可能泄露服务拓扑。→ 所有诊断 endpoint 必须走 `X-Agent-User-Id`、拓扑解析和访问控制；返回值做上限与脱敏。
- [Risk] `local-tools` 和 `real-tools` 并存导致用户混淆。→ README 和 compose 注释必须明确用途，real-tools 是正式主线，local-tools 是本地 Loki 快速排查入口。
- [Risk] 真实模型联调被误认为已经允许发送真实日志。→ 文档和任务必须把“合成/脱敏/显式确认”作为验收前置条件。
- [Risk] Compose 默认启动 internal-api-platform 后需要 secret env，否则服务可启动但实际查询失败。→ health 和 smoke test 必须暴露配置缺失的安全诊断，不把缺 secret 误报为工具 bug。

## Migration Plan

1. 保留现有 fake、mock-tools、local-tools 行为，先新增/整理 real-tools，不破坏已有开发路径。
2. 将 `internal-api-platform` Compose profile、环境变量和文档补齐，使 `INTERNAL_API_BASE_URL=http://internal-api-platform:9000` 成为 real-tools 推荐配置。
3. 增加 Loki 诊断 endpoint 和测试，先使用 fake/client stub 覆盖 tenant、labels、label-values、probe、empty result。
4. 增加真实 Loki smoke test 文档，记录命令、job_id、tool-call 摘要和空结果排查路径。
5. 如果新 real-tools 配置失败，可回退到 mock-tools 或 local-tools；Agent 侧仍通过同一 `InternalApiClient` 契约调用。

## Open Questions

- 真实 Loki 中服务标识的主 label 是否统一为 `service`，还是按环境使用 `app`、`job`、`container`、`service_name`？
- 真实 DeepSeek 联调是否允许发送脱敏后的日志摘要，还是必须只使用合成日志？
- 后续 Web 配置平台中，Loki label mapping 应先落 PostgreSQL，还是继续由 topology YAML 管理一版？
