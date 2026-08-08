# Phase 5 旧授权与 RabbitMQ 精确清理确认单

记录时间：2026-07-29T16:12:00+08:00  
状态：PREPARED，等待用户对本确认单中的 operation ID 与 digest 明确确认。  
本确认单生成时没有删除数据库记录或 RabbitMQ 对象。

## 1. 恢复基线

已校验备份引用：

`file:///Users/mhz/Backups/enterprise_agent/runtime-foundation-20260729-155943`

备份包含 PostgreSQL、固定 Master Key、RabbitMQ definitions 与运行配置；
校验细节见 `phase-4-maintenance-backup.md`。数据库当前 schema head 为 `024`，
核心服务已恢复 healthy。

## 2. 旧授权清理

受控操作：

```text
operation_id: legacy_auth_cleanup_d6b908008809426c8b0a61ca629251fb
digest: bd2e94bce4eaabe8e0fd7b15b0b299092d6db20d6be56ff4a6e71cdc9a1b2a5a
status: PREPARED
```

精确库存：

| 表 | Subject | Effect | 状态 | 数量 |
|---|---|---|---|---:|
| `permission_policy` | role | allow | enabled | 39 |
| `permission_policy` | user | allow | enabled | 15 |
| `platform_access_grant` | user | allow | enabled | 5 |

本操作只事务删除 `permission_policy` 的 54 行和
`platform_access_grant` 的 5 行，不删除用户、密码、Session、RBAC Role、
RBAC Membership 或其他身份数据。

删除前不变量已满足：

- `local-user` / `user_local_admin`：active session 1，成功登录审计 9；
- `zmh` / `user_1354ddf6d1e547faad514fec57a0a3fb`：
  active session 1，成功登录审计 10；
- 两者均为 enabled human，并由 strict `rbac_*` 表授予 enabled
  `platform-admin`。

Apply 会在事务内重新生成库存；只要当前 digest 与确认 digest 不一致，
操作即 fail closed，不执行删除。Apply 后还必须运行 verify，证明两个旧表为空
且两名人类管理员仍成立。

## 3. 旧 RabbitMQ Job 拓扑

```text
topology_digest: 43b4b575821afe37b2fdd4274bac868bb56480b8a8dc67bbb499f844d1183301
current queue: agent.job.queue
old retry queue: agent.job.retry.delay.v1.queue
old retry queue: agent.job.retry.queue
old dead queue: agent.job.dead.queue
```

当前精确状态：

| Queue | 存在 | Messages | Consumers | 动作 |
|---|---:|---:|---:|---|
| `agent.job.queue` | 是 | 0 | 1 | 保留 |
| `agent.job.retry.delay.v1.queue` | 是 | 0 | 0 | 删除 |
| `agent.job.retry.queue` | 否 | 0 | 0 | 跳过 |
| `agent.job.dead.queue` | 是 | 0 | 0 | 删除 |

- `job_dispatch_cutover_quarantine=0`；
- 所有 scan 均为 0，`truncated=false`；
- 当前 vhost 不存在自定义 named exchange；只有 default exchange 与
  `amq.*` 内置 exchange，因此没有旧 named exchange 需要删除；
- 两个现存旧 queue 只有 default exchange 的隐式 binding，精确 queue delete
  时由 RabbitMQ 同步删除；
- apply 前会短暂停止 `agent-worker`，再次要求所有 exact Job queue 无
  consumer、无消息；只按上表精确名称执行 `if_empty=true`、
  `if_unused=true` 删除，不支持 wildcard；
- 当前 `agent.job.queue` 及其他 Webhook/Channel/Attachment queue 均不删除。

## 4. 待确认命令边界

只有用户明确同意本文件中的两个 digest 后，才允许：

1. 对上述旧授权 operation 执行 apply，再执行 verify；
2. 对上述 RabbitMQ topology digest 执行 apply，并精确删除两个已排空旧
   Job queue；
3. 恢复 `agent-worker`，重新验证 schema、RBAC、Outbox、queue topology 与
   核心服务健康。

任何库存、consumer、消息数或 digest 变化都会中止操作并重新生成确认单。
