# Phase 5 维护切换只读预检

记录时间：2026-07-29T13:20:39+08:00  
范围：任务 10.2、10.4、10.7，以及 10.3、10.5、10.6 的只读准备。  
本次预检没有停止服务、删除旧授权、删除 RabbitMQ 队列、读取 Secret 明文或创建
新的 DB/Redis/Loki 资源。

## 1. 严格 RBAC 与两名人类平台管理员

PostgreSQL 当前存在 2 名同时满足以下条件的人类 `platform-admin`：

- `app_user.status = enabled`
- `app_user.account_type = human`
- `rbac_user_role.status = enabled`
- 存在密码凭据
- 存在未超过 idle/absolute expiry 的 active session
- `audit_event` 存在 `auth.login.succeeded`

| User ID | Username | 未过期 active session | 最近成功登录审计 |
|---|---|---:|---|
| `user_local_admin` | `local-user` | 1 | 2026-07-29T01:23:30.193095+00:00 |
| `user_1354ddf6d1e547faad514fec57a0a3fb` | `zmh` | 1 | 2026-07-29T01:46:40.007248+00:00 |

`zmh2` 的 `platform-admin` membership 为 disabled，不计入不变量。当前无需修复
身份或新 RBAC，也不得恢复 compatibility。

## 2. 旧授权库存

| 表 | Subject | Effect | 状态 | 数量 |
|---|---|---|---|---:|
| `permission_policy` | role | allow | enabled | 39 |
| `permission_policy` | user | allow | enabled | 15 |
| `platform_access_grant` | user | allow | enabled | 5 |

合计 `permission_policy = 54`、`platform_access_grant = 5`。这些记录尚未删除。
任务 10.3 必须先完成可恢复备份，再由受控命令生成新的 operation ID 和 digest，
展示给用户并取得单独确认。

## 3. Job / Outbox / Delivery 切换状态

PostgreSQL：

| 实体 | 状态 | 数量 |
|---|---|---:|
| `agent_job` | `SUCCEEDED` | 19 |
| `job_dispatch_outbox` | `PUBLISHED` | 1 |
| `delivery_outbox` | `SKIPPED` | 1 |
| `job_dispatch_cutover_quarantine` | 全部 | 0 |

不存在 `PENDING`、`RUNNING`、`RETRY_WAIT` 或 `DEAD` 的 Job/Outbox/Delivery
记录，不需要 backfill，也没有无法转换的记录。

执行只读命令：

```bash
docker compose exec -T api-server \
  python -m app.cli.job_dispatch_cutover \
  --max-messages-per-queue 1000
```

结果：

- 当前 `agent.job.queue`：0 messages、1 consumer；
- 旧 `agent.job.retry.delay.v1.queue`：0 messages、0 consumers；
- 旧 `agent.job.retry.queue`：不存在；
- 旧 `agent.job.dead.queue`：0 messages、0 consumers；
- 所有 scan 均为 0，`truncated = false`；
- quarantine 为 0；
- 没有旧 Worker/Dispatcher consumer 需要停止；
- 未删除任何队列。

精确旧拓扑计划：

```text
current: agent.job.queue
old retry: agent.job.retry.delay.v1.queue
old retry: agent.job.retry.queue
old dead: agent.job.dead.queue
topology digest: 43b4b575821afe37b2fdd4274bac868bb56480b8a8dc67bbb499f844d1183301
```

任务 10.5 删除前仍需重新检查消息数和 consumer，并对当时的新鲜 digest 取得
单独用户确认。

## 4. legacy env 引用

显式 import report：

```text
count: 4
digest: 0f463af34a5269c1aa423ca1a9f9d44cbd5a46d2f2c1a3d462d833528ed92091
```

| 引用 | 位置 | 当前环境值 | 初步分类 |
|---|---|---:|---|
| `env:DINGTALK_CLIENT_ID` | enterprise connector metadata | configured | 当前 publication 仍引用，待显式导入 |
| `env:DINGTALK_WEBHOOK_ROBOT_SECRET` | webhook connector | missing | 非 current publication，不能导入 |
| `env:DINGTALK_WEBHOOK_ROBOT_URL` | webhook connector | missing | 非 current publication，不能导入 |
| `env:ORDER_DB_PASSWORD` | disabled sample reference | missing | 已禁用示例，不应导入 |

上述报告只读取引用名和环境值是否存在，没有输出环境变量值。任务 10.6 尚未完成：
需要显式导入仍使用的 Client ID，并对 3 个不应保留的旧引用采用明确的停用/清理
决策。

## 5. 资源重置复核

已完成并保持 `VERIFIED` 的操作：

```text
operation_id: resource_reset_b6a2fbfbc4934740b2b3de880097eb6f
digest: 0cd4d4f41e6f75f6b357690d5d9159eff4c03be1f9533237a3b5f5598a62f966
```

重新执行只读 `resource_reset report`：

- DB/Redis/Loki resources、drafts、verifications、revisions：0；
- legacy/application/handler bindings：0；
- activations/runtime states：0；
- active resource Jobs：0；
- effective snapshot resources：0；
- effective snapshot status：`READY`；
- 当前空库存 fingerprint：
  `9b951cfe856b1bbdeb9f89eae60cd25aff49025c5dfdc7eb1e5430bddb0b51b3`。

因此任务 10.7 的 report/prepare/confirm/apply/verify 已由 Phase 4 的实际操作完成，
本次只读复核没有创建空 reset operation。

## 6. 尚未满足的维护条件

- 10.1：尚未冻结配置写入，也尚未为当前状态创建 PostgreSQL、Master Key、
  RabbitMQ definitions 和 runtime config 的同一维护窗口备份。
- 10.3：旧授权尚未删除，运行时代码/配置清理尚未完成。
- 10.5：旧 RabbitMQ 队列尚未删除。
- 10.6：仍需处理 4 个 legacy env 引用。
- 10.8：资源当前按用户要求保持为空；尚未新建本地验收资源。
- 10.9：只有在上述切换完成后才能声明 core ready。
