# Gate 2：Migrator、Unit of Work 与双 Outbox

状态：**PASS**

记录日期：2026-07-29

本文件汇总已分别通过的 Phase 2A、2B、2C 证据：

- [独立 Migrator 与操作级 Unit of Work](phase-2a-gate.md)
- [Job Dispatch Outbox](phase-2b-gate.md)
- [Delivery Outbox 与独立状态机](phase-2c-gate.md)

## 已通过

- one-shot Migrator 是唯一 schema writer；PostgreSQL advisory lock、稳定 checksum、
  逐版本事务、失败回滚、幂等重跑和业务服务只读 head 校验均已验证。
- 同步连接池和显式 Unit of Work 已覆盖请求、消息与 CLI 边界；并发事务、异常
  回滚、连接归还和外部 I/O 不跨平台数据库事务均有测试。
- Job、消息、授权快照和唯一 Job Dispatch Outbox event 原子提交；Dispatcher
  使用 `FOR UPDATE SKIP LOCKED`、publisher confirm、有限 retry/DEAD 和有界 replay。
- Worker 从 PostgreSQL 重读完整执行事实；重复 event/RabbitMQ message 不重复
  执行业务结果。
- Agent 结果、Job 终态与 Delivery intent 原子保存；Delivery event/attempt/chunk
  独立幂等，故障不会重跑 Agent。
- Delivery Dispatcher 的有限 retry/DEAD、none route `SKIPPED`、分片恢复和精确
  `delivery_id` replay 已通过真实 PostgreSQL/RabbitMQ 组合测试。
- Job 与 Delivery 终态分别展示和审计，不把 Job `SUCCEEDED` 误报为“已送达”。

固定阶段 Gate 原始结果：

```text
Phase 2A: 41 passed, PHASE_2A_AUTOMATED_GATE: PASS
Phase 2B: 34 passed, PHASE_2B_AUTOMATED_GATE: PASS
Phase 2C: 25 passed, PHASE_2C_AUTOMATED_GATE: PASS
```

当前工作树最终回归：

```text
.venv/bin/pytest -q
652 passed, 20 skipped, 2 warnings, 4 subtests passed
```

当前数据库 migration head 已随后续阶段前进到 `023`，checksum 为
`cc5f3692797611c62a9d47e1af09c5f76516da8eae88eb42d6989008f8da9cb0`；
API 启动只读校验和 `/api/ready` 均通过。

## 明确边界

- Outbox 保证已提交意图可恢复，不是已进入 `RUNNING` 的 Worker 执行租约；
  Worker 崩溃后的 fencing/取消仍延期到独立 change。
- 旧 RabbitMQ retry/dead 拓扑没有在本 Gate 物理删除；精确清理仍属于任务 10.5，
  必须重新盘点、生成 digest 并获得用户确认。
- 真实模型、Grafana、工具和 DingTalk 的新鲜外部链路属于 Phase 6，不以
  PostgreSQL/RabbitMQ 组合测试替代。
