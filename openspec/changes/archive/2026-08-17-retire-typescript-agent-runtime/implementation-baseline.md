# TypeScript Agent Runtime 退役实现基线

## 证据边界

- 采集时间：2026-08-17（Asia/Shanghai）。
- checkout：`mcp_new`，基准提交 `dfae7bf0771600483b83630e6e74d144dd1b0717`；本变更实现尚未提交，因此该提交仅用于标识实现起点。
- 目标环境：当前本地 Compose 环境 `local`。本页不代表测试、预发布或生产环境；这些环境仍属于未验证环境，不能由本地零计数替代。
- 采集只使用聚合查询、标识字段、被动队列状态和源码/Compose 配置键扫描。未读取或记录 Secret、Token、密码、Prompt、业务消息、文件正文或 Runtime 配置值。

## Confirmed-current：源码与装配

- schema head：`111`。
- Agent Runtime protocol：`1.3`。
- 新 Definition/Job 的代码默认 Runtime：`python-v1`。
- 当前 Compose 仍同时装配 `python-agent-runtime` 与 `typescript-agent-runtime`；API、Agent Worker、Webhook Worker 和 Channel Dispatch Worker 仍对 TypeScript Runtime 存在健康依赖。
- Compose 仍声明 `TYPESCRIPT_AGENT_RUNTIME_URL` 与 `TYPESCRIPT_AGENT_RUNTIME_ALLOWED_HOSTS` 两个配置键；数据库 Runtime 配置表中匹配 TypeScript Runtime 的行数为 `0`。

## Confirmed-current：本地数据库引用

| 对象 | `python-v1` | `typescript-v1` |
|---|---:|---:|
| Agent Definition | 2 enabled | 1 enabled |
| Agent Publication | 1 active、5 inactive | 1 active |
| Definition 当前 Publication 指针 | 1 | 1 |
| Business Application Publication | 11 | 0 |
| Active Business Application Deployment | 1 | 0 |

本地历史 TypeScript 标识事实：

- Definition：`agent_typescript_diagnostic`，当前指向 `agent_publication_abb2d87c7c2f48b582a7dd9c739eb2f8`。
- Publication：`agent_publication_abb2d87c7c2f48b582a7dd9c739eb2f8`，revision `2`，状态 `active`。
- 该 TypeScript Publication 当前没有 Business Application Publication 或 active Deployment 引用，但仍是 Definition 的 current Publication，因此退役门禁尚未通过。

## Confirmed-current：本地 Job、Outbox 与队列

| Runtime | Job 状态 | 数量 |
|---|---|---:|
| `python-v1` | `SUCCEEDED` | 55 |
| `python-v1` | `FAILED` | 9 |
| `typescript-v1` | 任意状态 | 0 |

| Runtime | Dispatch Outbox 状态 | 数量 |
|---|---|---:|
| `python-v1` | `PUBLISHED` | 61 |
| `python-v1` | `DEAD` | 3 |
| `typescript-v1` | 任意状态 | 0 |

当前已存在的 Job/Webhook/Attachment/Channel 主队列与 dead queue 消息数均为 `0`；`agent.job.queue` 有 1 个 consumer。`agent.job.retry.delay.v1.queue` 与 `agent.job.retry.queue` 的被动声明结果为明确不存在，因此可证明这两个配置队列没有可执行消息；只有 RabbitMQ 不可达、预期队列标签缺失或返回结构无法验证时，preflight 才按拓扑未知失败关闭。

## 初始门禁结论

本地环境在 Job、Outbox 和已存在队列的可执行消息方面未发现 TypeScript 工作，但仍有以下阻塞项：

1. TypeScript Definition 仍把 TypeScript Publication 作为 current Publication。
2. Compose 与后端配置仍包含 TypeScript Runtime URL/allowed-host 配置键，且 TypeScript Runtime 服务仍在运行。
3. 测试、预发布和生产环境未验证。

因此，此基线只批准继续实施“合同迁移、Python 能力收口和冻结新写入”，不批准删除 TypeScript 运行面。
