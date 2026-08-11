# Runtime Foundation 六阶段 Gate

记录日期：2026-07-28  
适用范围：任务 1.6。Gate 是不可跨越的验收边界，不是进度标签；任务勾选和一份
证据文件同时存在仍只是必要条件，证据内容必须包含该阶段的自动化、数据核验和
真实运行结果。

检查器：
[`scripts/runtime_foundation_gate.py`](../../../../../scripts/runtime_foundation_gate.py)

## 使用

```bash
.venv/bin/python scripts/runtime_foundation_gate.py status
.venv/bin/python scripts/runtime_foundation_gate.py status --json
.venv/bin/python scripts/runtime_foundation_gate.py verify-phase1
MIGRATION_POSTGRES_DSN='<本机测试 PostgreSQL 管理连接>' \
  .venv/bin/python scripts/runtime_foundation_gate.py verify-phase2a
MIGRATION_POSTGRES_DSN='<本机测试 PostgreSQL 管理连接>' \
RABBITMQ_TEST_URL='<本机 RabbitMQ 连接，未记录>' \
  .venv/bin/python scripts/runtime_foundation_gate.py verify-phase2b
.venv/bin/python scripts/runtime_foundation_gate.py check --gate 1
```

`status` 总是只读返回当前状态；`check` 只有在 Phase 0 基线任务、该 Gate 全部任务
和规定 evidence 文件均完成时才返回 0。
`verify-phase1` 会执行固定的拒绝、隔离与脱敏测试清单；不得用单纯的 tasks/evidence
存在性检查替代该命令。
`verify-phase2a` 会执行固定的 Migrator、真实 PostgreSQL、连接池/UoW、外部 I/O
边界和 Compose 契约测试；缺少 `MIGRATION_POSTGRES_DSN` 时必须失败，不能把 skip
当成通过。
`verify-phase2b` 会执行固定的 Job/Outbox 原子提交、真实 PostgreSQL 多 Dispatcher、
真实 RabbitMQ 4 publisher confirm、重复消息幂等、有限 retry/DEAD 和有界 replay
测试；缺少任一真实依赖连接时必须失败，不能把 skip 当成通过。真实链路只使用临时
PostgreSQL 数据库和随机隔离队列，结束后清理，不向证据文件写入连接信息。

## Gate 映射

| Gate | 任务 | 规定 evidence | 必须证明 |
|---:|---|---|---|
| 1 | 2.1–2.12 | `gate-1-strict-runtime.md` | Debug 不可冒充；Internal Token + Job fact；strict RBAC；双管理员；Webhook Bearer；Session 隔离 |
| 2 | 3.*, 4.*, 5.* | `gate-2-transactional-runtime.md` | 唯一 Migrator；UoW 隔离；Job/Delivery 双 Outbox；DB/Rabbit/Delivery 故障注入 |
| 3 | 6.*、7.*（除 7.5/7.6） | `gate-3-governed-resources.md` | 固定 Master Key；平台 Secret；资源不可变 revision；Handler 交集；应用/Job 固定 binding |
| 4 | 7.5、7.6、8.* | `gate-4-runtime-reset.md` | Oracle 静态/镜像且真实连接 deferred；热加载/LKG；精确资源 reset/verify |
| 5 | 9.*、10.* | `gate-5-management-ui.md` | 脱敏管理 API；凭据/资源/调试 UI；并发冲突和 MISCONFIGURED/blocked/degraded 展示 |
| 6 | 11.* | `gate-6-acceptance.md` | CI、Compose、多副本、故障注入、真实本地 Grafana→Agent→工具→DingTalk 新鲜链路 |

Gate 证据必须写明：

- 代码 commit/worktree 状态和 migration head/checksum
- 精确测试命令与结果
- 数据库/RabbitMQ/运行状态的只读查询
- 实现项、明确延期项和失败项
- 无 Secret、Token、Master Key、DSN、完整敏感 URL 或密文

Gate 4 的 Oracle 证据必须明确写“真实 Oracle 11.2.0.4 连接 deferred”；不得因为
单元测试或 19c Client 镜像启动而声称真实 Oracle 已验证。

## 破坏性操作边界

以下操作必须使用相同流程：

- 删除旧 `permission_policy` / `platform_access_grant`
- 删除 RabbitMQ 旧 queue/exchange/binding
- resource reset 的 DB/Redis/Loki resource、revision、binding 和有效 runtime state
- 任何后续被批准的历史数据物理清理

### 1. 新鲜 report

在准备执行的同一维护窗口重新读取数据库和 RabbitMQ，不能复用 Phase 0 快照。
report 只列 ID、code、revision、status、计数和受影响应用，不读取 Secret value、
ciphertext、密码、Token 或 config JSON。

### 2. 备份和 prepare

- 创建可恢复的数据库备份引用。
- 阻止新的依赖 Job，等待现有任务排空；超时中止，不强杀。
- 生成 JSON manifest，至少包含：
  `operation_id/generated_at/database_fingerprint/backup_reference/targets/impact`。
- target 必须逐项包含 `type/id/revision/action`，禁止通配符。

### 3. 生成并展示 digest

```bash
.venv/bin/python scripts/runtime_foundation_gate.py manifest-digest \
  --manifest /absolute/path/to/operation-manifest.json
```

检查器会：

- 拒绝空 targets、重复 target、未知 action
- 拒绝 `password/token/ciphertext/nonce/config_json/snapshot_json` 等敏感字段
- 对规范化 JSON 计算 SHA-256
- 展示 operation ID、database fingerprint、backup reference、精确 target 和 impact

### 4. apply 前重新核验

```bash
.venv/bin/python scripts/runtime_foundation_gate.py destructive-preflight \
  --manifest /absolute/path/to/operation-manifest.json \
  --expected-digest <刚刚展示的64位sha256>
```

结果定义：

- exit 2：manifest 非法或 digest/数据库状态漂移，必须重新 report/prepare。
- exit 3 + `USER_CONFIRMATION_REQUIRED`：技术预检通过，但仍未授权 apply。
- 该脚本故意没有 `--yes`、`--force` 或环境变量绕过。

### 5. 获得本次用户确认

必须在 apply 前向用户重新展示：

- operation ID 与完整 digest
- 备份引用
- 每类对象数量
- 精确 target ID/code/revision/action
- 受影响应用与预期 blocked/degraded 行为
- 明确保留的身份、新 RBAC、平台 Secret、业务应用、Job、Delivery、Audit 和历史
  snapshot

只有用户针对这份同 digest 清单作出明确同意，才可调用后续具体 apply 命令。较早
对需求方向的“同意”、Phase 0 的“从空配置开始”或脚本 exit 3 都不能替代本次确认。

### 6. apply 后 verify

- 同一事务内校验 target revision/digest；任一漂移则全部拒绝。
- 保存 affected-row count 和审计事件。
- 重跑 inventory，检查目标为空、保留对象完整、无悬空 binding。
- RabbitMQ 只有在 `ready=0/unacked=0/consumer=0` 后才按精确名称删除。
- 将 verify 结果写入对应 Gate evidence；失败时停止后续阶段。

## 当前状态

Phase 0 的 1.1–1.5 已有证据；1.6 完成后六阶段检查器生效。当前 Gate 1–6 都应为
BLOCKED，这是尚未实施后续任务的正确结果，不是脚本故障。
