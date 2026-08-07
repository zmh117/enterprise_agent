# 11.5 Runtime 到 Delivery 完整链验收证据

执行日期：2026-08-06（Asia/Shanghai）

## 验收链

新增 `backend/tests/test_runtime_builtin_tool_delivery_e2e.py`，在一条验收链中执行：

```text
Debug Runtime
→ 精确 Application Publication
→ Job + Dispatch Outbox + Built-in Tool Snapshot
→ Message Bus
→ AgentJobWorker
→ 模拟模型 Tool Loop
→ ReadOnlyToolService
→ HttpInternalApiClient 契约
→ Internal API Platform 路由/Job Fact Authorizer
→ DB / Redis / Loki 网关
→ Result Artifact + Delivery Outbox
→ Delivery Dispatcher
→ Delivery Attempt + Audit
```

## 冻结与执行证据

- Application Publication 显式包含 `query_database`、`query_redis_get`、`query_loki` 三个精确 Tool Release 与对应 Resource Mapping；
- Job 创建时冻结同一个 Publication ID、三个 Resource Revision、Loki Scope Policy 和 Snapshot Hash；
- Worker 从已持久化 Dispatch Event 消费 Job，不直接调用 Executor 绕过消息链；
- 模拟模型依次调用三个 MCP Tool，均由正式 Tool Registry 与 ReadOnlyToolService 执行；
- HTTP 客户端携带 Job、User、Project、Tool Call、Correlation 和服务 Token 请求 Internal API Platform；
- Internal API Platform 从 Job Snapshot 重新授权每次 Tool Call，并写入三条 `agent_tool_call_builtin_tool_fact`；
- DB 只读查询执行一次，Redis GET 执行一次，Loki 最终 selector 强制包含 `customer=local` 且保留调用方 `service=orders`；
- 三条 Tool Call 均为 `SUCCEEDED`，具有独立 Audit ID，授权事实均为 `exact_job_snapshot_allowed`；
- Worker 保存结果 Artifact，生成独立 Delivery Outbox；Delivery Dispatcher 通过记录适配器完成一次投递，Attempt 为 `SUCCEEDED` 且关联 Outbox；
- Job 审计包含 `worker.claimed`、`result.delivery.requested` 和 `delivery.completed`。

## 隔离说明

验收使用 SQLite 内存数据库、进程内消息总线、FastAPI TestClient HTTP 桥和确定性 DB/Redis/Loki 网关，不访问客户数据源或外部投递地址。它验证完整生产代码控制流、HTTP 契约、不可变事实和持久化证据；不声称替代真实 RabbitMQ、真实客户上游或真实钉钉的部署验收。

## 执行结果

```text
.venv/bin/pytest -q backend/tests/test_runtime_builtin_tool_delivery_e2e.py
```

结果：`1 passed`；另有一个来自测试依赖的既有 Starlette deprecation warning。
