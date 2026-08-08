# 11.6 失败关闭与故障注入证据

执行日期：2026-08-06（Asia/Shanghai）

## 故障矩阵

| 故障 | 注入位置 | 失败关闭证据 |
|---|---|---|
| `MISSING` | 固定 Handler Installation | Dispatch 不发布消息，Outbox 进入有界 `RETRY_WAIT`，错误为实现漂移 |
| `DRIFTED` | 固定 Handler Installation | 与 `MISSING` 相同，不浮动到其它实现 |
| `DISABLED` | Built-in Tool Release | Dispatch/Retry/Replay 重新验证原 Snapshot 并拒绝，不选择新 Release |
| Resource Revision `DISABLED` | Application Draft 保存后、Publish 前 | Application Publication 不创建，报 Mapping Missing |
| 资源加载失败且存在 LKG | Secret/Resource Generation Reload | 仅受影响 Resource/Application 标记 `DEGRADED`，继续使用同一 LKG Revision，不泄漏 Secret |
| 资源加载失败且无 LKG | 首次 Generation Load | Resource/Application 标记 `BLOCKED`，Revision 不进入运行时，Job 不创建 |
| 多 placement 未显式选择 | Internal API Job Fact Authorizer | 授权事实写入 `DENIED / placement_required`，没有选择任一资源 |
| global/environment Loki 重叠 | Application Target Matrix | Publish 前以 Mapping Overlap 拒绝 |
| 跨车间 DB/Redis/Loki | SQL/namespace/selector 策略 | 在访问上游前拒绝；GL001/GL002/CZ002 与 Loki 强制条件验收均通过 |
| 伪造 Job/User/Project/Application/Scope/Revision | Internal API HTTP 边界 | 全部返回访问拒绝；断言 DB Executor 在有效请求前调用数为零 |
| Broker confirm/commit/retry 故障 | Dispatch Outbox | 持久化状态与幂等边界保持一致，不重复执行 Job |

## 执行结果

第一组：

```text
.venv/bin/pytest -q backend/tests/test_job_builtin_tool_snapshot.py backend/tests/test_runtime_generation_reload.py backend/tests/test_application_builtin_tool_resource_mapping.py backend/tests/test_real_workshop_partition_examples.py backend/tests/test_loki_configuration_examples.py
```

结果：`33 passed`。

第二组：

```text
.venv/bin/pytest -q backend/tests/test_internal_api_job_fact_authorization.py backend/tests/test_job_dispatch_fault_integration.py
```

结果：`7 passed`。

两组各有一个来自测试依赖的既有 Starlette deprecation warning。故障注入均使用本地持久化与确定性上游，不访问客户系统。
