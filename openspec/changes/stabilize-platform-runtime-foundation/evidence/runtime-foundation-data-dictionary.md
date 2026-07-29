# Runtime Foundation 数据字典

记录日期：2026-07-28  
适用范围：任务 1.5。本文件定义本 change 预期新增或修改的数据结构、索引、
唯一键、状态、审计和 correlation/idempotency 约定；它不是已执行 migration。

## 1. 全局约定

### 1.1 类型与命名

- 主键使用带实体前缀的不可预测 `TEXT` ID。
- 时间继续使用仓库现有的 UTC ISO-8601 `TEXT`，写入必须含时区；不混用本地时间。
- Boolean 延续现有 `INTEGER NOT NULL CHECK (value IN (0,1))`。
- JSON 使用 `TEXT`，写入前必须 canonicalize，字段名以 `_json` 结尾。
- SHA-256 使用 64 字符小写十六进制 `TEXT`，字段名以 `_hash` 或 `_digest` 结尾。
- 状态机字段使用大写值；现存小写 Outbox 在迁移时显式映射，不允许运行时混用。
- 所有 revision、attempt、sequence、generation 从 1 开始。
- 业务表不存储 Secret 明文、解密值、认证 header、完整敏感 URL、任意 Python、
  任意 SQL 模板或可执行脚本。
- 新外键默认 `ON DELETE RESTRICT`；只有纯草稿从表允许随未发布 Draft 级联删除。
- Published Revision、Application Publication、Execution Scope、Outbox payload fact
  创建后不可修改；只有各自状态、claim、attempt 和安全错误摘要可变化。

### 1.2 Correlation

`correlation_id` 是跨 HTTP、Inbox、Job、Outbox、RabbitMQ、Worker、Tool Call、
Delivery 和审计的非敏感追踪标识：

- 最大 128 字符，不接受换行或控制字符。
- 外部值不可信；缺失或非法时由入口生成。
- correlation 不能参与授权，也不能替代 idempotency。
- 所有新运行事件和审计事件必须非空保存该字段。
- 索引只用于精确查询；不把 correlation 当唯一键。

### 1.3 Idempotency

- `idempotency_key` 表示同一业务效果，只由受信入口按命名空间生成。
- 格式为 `<source>:<stable-business-key>`；外部自由文本先 canonicalize 和 hash。
- `event_key` 表示某个 Outbox 事件，格式为 `<event-type>:<aggregate-id>:<version>`。
- RabbitMQ delivery tag、consumer tag、channel PID 不得作为持久化幂等键。
- replay 复用原 `event_key` 或派生明确的 `replay:<operation-id>:<event-id>`，
  不接受任意新 payload。
- 对外部可能敏感的幂等输入只存 `idempotency_key_hash`；当前 `agent_job` 的既有
  `idempotency_key` 后续单独迁移为受约束内部键，不扩大存储内容。

## 2. Migration 与数据库运行基础

### 2.1 `schema_migration`（新增）

| 字段 | 约束 | 说明 |
|---|---|---|
| `version` | PK, TEXT | 唯一、严格排序的 migration version |
| `name` | NOT NULL | 文件基名 |
| `checksum` | NOT NULL | 规范化文件内容 SHA-256 |
| `applied_at` | NOT NULL | 成功提交时间 |
| `duration_ms` | NOT NULL, >=0 | 完整 migration 事务耗时 |
| `migrator_build` | NOT NULL | 执行程序 build/commit 标识 |

索引/约束：

- `PRIMARY KEY(version)`
- `UNIQUE(name)`
- `CHECK(length(checksum)=64)`
- 账本只记录成功提交；失败 migration 整体回滚，不写“半成功”行。
- checksum 或文件名与已应用记录不一致时，Migrator 和业务服务 readiness 都失败。

### 2.2 数据库约束性不变量

- migration version 在读文件阶段先做唯一性检查，不能依赖数据库 PK 才发现。
- Migrator 用固定 advisory lock key；该锁不是业务表字段。
- 业务服务只读比较代码 expected head 和 `schema_migration` head。
- `platform-admin` 两名人类管理员不变量通过同事务锁定相关角色/成员行和数据库
  constraint trigger 实现；不新增“管理员计数缓存表”。

## 3. Job、Execution Scope 与 Session

### 3.1 `agent_job`（修改）

保留现有字段，新增：

| 字段 | 约束 | 说明 |
|---|---|---|
| `correlation_id` | NOT NULL | Job 根 correlation |
| `execution_scope_id` | UNIQUE, FK | 指向固化 scope |
| `execution_scope_hash` | NOT NULL | canonical scope SHA-256 |
| `debug_requested_by_user_id` | NULL/FK | Debug 来源登录用户；非 Debug 为空 |
| `dispatch_state` | NOT NULL | `PENDING/ENQUEUED/DEAD` 只读摘要，不代替 Outbox |

索引：

- `idx_agent_job_correlation(correlation_id, created_at)`
- `idx_agent_job_application_created(business_application_publication_id, created_at)`
- `idx_agent_job_user_application_created(internal_user_id, business_application_id, created_at)`
- 保留 `idempotency_key` 唯一约束。

规则：

- `user_id/internal_user_id` 由服务端登录或绑定事实写入，DTO 不接受覆盖。
- `business_application_publication_id`、`execution_scope_id/hash` 创建后不可修改。
- `dispatch_state` 仅供列表聚合；权威 dispatch 状态在 `job_dispatch_outbox`。

### 3.2 `agent_job_execution_scope`（新增）

| 字段 | 约束 | 说明 |
|---|---|---|
| `id` | PK | Execution Scope ID |
| `job_id` | UNIQUE, FK agent_job | 一 Job 一 scope |
| `business_application_id` | NOT NULL | 稳定应用 ID |
| `application_publication_id` | NOT NULL/FK | 固化发布 |
| `agent_publication_id` | NOT NULL | 固化 Agent 发布 |
| `environment_id` | NOT NULL | 授权环境 |
| `base_id` | NULL | 授权基地 |
| `workshop_id` | NULL | 授权车间 |
| `scope_hash` | UNIQUE, NOT NULL | snapshot canonical hash |
| `schema_version` | NOT NULL | scope contract version |
| `snapshot_json` | NOT NULL | 脱敏、不可变完整事实 |
| `created_at` | NOT NULL | 固化时间 |

索引：

- `UNIQUE(job_id)`
- `idx_job_execution_scope_publication(application_publication_id, created_at)`
- `idx_job_execution_scope_nodes(environment_id, base_id, workshop_id)`

`snapshot_json` 只允许 ID、版本、能力和约束，不保存已解析 Secret、凭据、任意
reply target。

### 3.3 `agent_job_execution_binding`（新增）

| 字段 | 约束 | 说明 |
|---|---|---|
| `id` | PK | binding ID |
| `execution_scope_id` | FK | 所属固化 scope |
| `handler_id` | NOT NULL | 代码 Handler 稳定 ID |
| `handler_version` | NOT NULL | 不可变代码版本 |
| `resource_slot` | NOT NULL | Handler 逻辑资源槽 |
| `resource_revision_id` | FK | 固化资源 revision |
| `constraint_json` | NOT NULL | 行数、字节、timeout、prefix/label 等约束 |
| `binding_hash` | NOT NULL | canonical binding hash |
| `created_at` | NOT NULL | 创建时间 |

约束/索引：

- `UNIQUE(execution_scope_id, handler_id, handler_version, resource_slot)`
- `idx_execution_binding_resource(resource_revision_id, execution_scope_id)`
- Handler、slot、Resource kind 必须与应用发布绑定一致。

### 3.4 `agent_session`（修改）

新增：

| 字段 | 约束 | 说明 |
|---|---|---|
| `application_publication_id` | NULL | 新 session 必填；旧历史可空 |
| `execution_scope_hash` | NULL | 新 session 必填 |
| `isolation_key_version` | NOT NULL DEFAULT 2 | 新 key contract 版本 |
| `history_read_only` | NOT NULL DEFAULT 0 | 旧 application/actor session 标 1 |

索引/约束：

- 新唯一 key 由 application publication、connector、外部 conversation、
  requester（私聊）、scope hash 组成后 hash 到既有 `session_key`。
- `UNIQUE(session_key)` 保留。
- `idx_agent_session_publication_scope(application_publication_id, execution_scope_hash, updated_at)`
- `history_read_only=1` 的 session 禁止附着新 Job。
- Webhook/Grafana 与默认 Debug 每事件创建隔离 session；显式 Debug continue 必须
  publication 与 scope hash 完全相同。

## 4. Job Dispatch Outbox

### 4.1 `job_dispatch_outbox`（新增）

| 字段 | 约束 | 说明 |
|---|---|---|
| `id` | PK | event ID，同时进入 Rabbit payload |
| `event_key` | UNIQUE, NOT NULL | 业务幂等事件键 |
| `job_id` | UNIQUE, FK | 一个 Job 一个初始 dispatch event |
| `correlation_id` | NOT NULL | 根追踪标识 |
| `status` | NOT NULL | Outbox 状态 |
| `attempt_count` | NOT NULL DEFAULT 0 | 已开始发布次数 |
| `max_attempts` | NOT NULL, >0 | 有限重试上限 |
| `next_attempt_at` | NOT NULL | 下次可领取时间 |
| `claimed_by` | NOT NULL DEFAULT '' | Dispatcher instance |
| `claim_token` | NOT NULL DEFAULT '' | 本次领取随机 token |
| `claimed_at` | NULL | 领取时间 |
| `claim_expires_at` | NULL | Dispatcher 领取恢复边界 |
| `last_error_code` | NOT NULL DEFAULT '' | 稳定错误 code |
| `last_error_summary` | NOT NULL DEFAULT '' | 脱敏摘要 |
| `published_at` | NULL | confirm 成功时间 |
| `dead_at` | NULL | 最终 DEAD 时间 |
| `created_at` | NOT NULL | 创建时间 |
| `updated_at` | NOT NULL | 更新时间 |

状态：

`PENDING → PUBLISHING → PUBLISHED`

`PUBLISHING → RETRY_WAIT → PUBLISHING`，耗尽后 `→ DEAD`。精确 replay 创建受审计
的状态转换 `DEAD → RETRY_WAIT`，不修改 payload fact。

索引/约束：

- `UNIQUE(event_key)`、`UNIQUE(job_id)`
- `idx_job_dispatch_outbox_claim(status, next_attempt_at, created_at)`
- `idx_job_dispatch_outbox_claim_expiry(status, claim_expires_at)`
- `idx_job_dispatch_outbox_correlation(correlation_id, created_at)`
- `CHECK(attempt_count BETWEEN 0 AND max_attempts)`

Dispatcher 使用 `FOR UPDATE SKIP LOCKED`；claim lease 仅保护 Outbox 发布，不是
Agent Worker 执行租约。

### 4.2 `runtime_message_consumption`（新增）

| 字段 | 约束 | 说明 |
|---|---|---|
| `consumer_name` | PK part | 稳定 consumer 逻辑名 |
| `event_id` | PK part | Outbox event ID |
| `aggregate_id` | NOT NULL | Job 或 Delivery ID |
| `correlation_id` | NOT NULL | 追踪 |
| `status` | NOT NULL | `PROCESSING/SUCCEEDED/FAILED` |
| `first_received_at` | NOT NULL | 首次接收 |
| `completed_at` | NULL | 业务结果已提交 |
| `last_error_code` | NOT NULL DEFAULT '' | 安全错误 code |

约束/索引：

- `PRIMARY KEY(consumer_name, event_id)`
- `idx_message_consumption_aggregate(consumer_name, aggregate_id)`
- consumer dedup claim 与业务状态转换在同一 UoW。
- `FAILED` 仅表示本次消费事务明确失败；事务整体回滚时不留伪完成记录。

## 5. Delivery Outbox 与投递明细

### 5.1 `delivery_outbox`（新增）

| 字段 | 约束 | 说明 |
|---|---|---|
| `id` | PK | Delivery event ID |
| `event_key` | UNIQUE | 结果版本级幂等键 |
| `job_id` | FK | Agent Job |
| `result_artifact_id` | FK | 固化结果 artifact |
| `application_publication_id` | NOT NULL | 固化应用发布 |
| `delivery_binding_json` | NOT NULL | 固化 route/connector 配置，不含 Secret |
| `target_summary` | NOT NULL | 脱敏目标摘要 |
| `correlation_id` | NOT NULL | 根追踪 |
| `status` | NOT NULL | Delivery 状态 |
| `attempt_count` | NOT NULL DEFAULT 0 | Dispatcher attempt |
| `max_attempts` | NOT NULL, >0 | 有限上限 |
| `next_attempt_at` | NOT NULL | 下次可领取 |
| `claimed_by/claim_token` | NOT NULL DEFAULT '' | 多副本 claim |
| `claimed_at/claim_expires_at` | NULL | claim 时间 |
| `last_error_code/last_error_summary` | NOT NULL DEFAULT '' | 脱敏错误 |
| `started_at/finished_at/dead_at` | NULL | 时间线 |
| `created_at/updated_at` | NOT NULL | 审计时间 |

状态：

`PENDING/RUNNING/RETRY_WAIT/SUCCEEDED/FAILED/DEAD/SKIPPED`

- `none` route 原子转 `SKIPPED`。
- 可重试 adapter 错误：`RUNNING → RETRY_WAIT`。
- 单次不可重试错误可记 `FAILED` 后终结；重试耗尽为 `DEAD`。
- Delivery 终态不回写 Job 成败，不触发 Agent 重跑。

索引/约束：

- `UNIQUE(event_key)`
- `UNIQUE(job_id, result_artifact_id)`
- `idx_delivery_outbox_claim(status, next_attempt_at, created_at)`
- `idx_delivery_outbox_job(job_id, created_at)`
- `idx_delivery_outbox_correlation(correlation_id, created_at)`

### 5.2 `delivery_attempt`（修改）

新增：

| 字段 | 约束 | 说明 |
|---|---|---|
| `delivery_outbox_id` | FK | 所属 Outbox |
| `attempt_no` | NOT NULL | 从 1 开始 |
| `correlation_id` | NOT NULL | 追踪 |
| `idempotency_key` | NOT NULL | 固定 attempt key |
| `error_code` | NOT NULL DEFAULT '' | 稳定错误 code |

约束/索引：

- `UNIQUE(delivery_outbox_id, attempt_no)`
- `UNIQUE(idempotency_key)`
- `idx_delivery_attempt_outbox(delivery_outbox_id, attempt_no)`
- 旧 `job_id` 保留用于兼容读取，但新写入必须与 Outbox job 一致。

### 5.3 `delivery_chunk`（修改）

新增：

| 字段 | 约束 | 说明 |
|---|---|---|
| `delivery_outbox_id` | FK | 逻辑 Delivery |
| `attempt_no` | NOT NULL | 本次发送 attempt |
| `idempotency_key` | NOT NULL | 跨 attempt 稳定逻辑 chunk key |
| `payload_hash` | NOT NULL | 分片正文 hash，不保存到审计 |
| `sent_at` | NULL | 成功时间 |

索引/约束：

- `UNIQUE(delivery_outbox_id, attempt_no, chunk_index)`
- `idx_delivery_chunk_logical(delivery_outbox_id, chunk_index, status)`
- PostgreSQL partial unique：
  `UNIQUE(delivery_outbox_id, chunk_index) WHERE status='SUCCEEDED'`
- adapter 调用前查询逻辑 chunk 是否已成功，重复 event 不重复发送。

## 6. Secret 与导入

### 6.1 `platform_secret` / `platform_secret_version`（修改约束）

- `platform_secret.ref` 必须唯一且匹配 `secret://platform/<code>`。
- 新建 API 的内部 provider 固定为 `encrypted_db`。
- `UNIQUE(platform_secret.ref)`；现有普通索引升级为唯一约束。
- `UNIQUE(platform_secret_version.secret_id, platform_secret_version.version)`。
- 每个 enabled Secret 恰有一个 active version；用 partial unique
  `UNIQUE(secret_id) WHERE status='active'`。
- version 状态：`active/superseded/disabled`（保留当前小写以避免无收益迁移）。
- `ciphertext/nonce/key_id/algorithm` 永不出现在 list/detail/audit payload。

### 6.2 `secret_import_operation`（新增）

| 字段 | 约束 | 说明 |
|---|---|---|
| `id` | PK | 导入 operation |
| `source_provider` | NOT NULL | 本次只允许 `env` |
| `source_ref_hash` | NOT NULL | 原引用 hash，不保存读取值 |
| `target_secret_id` | NULL/FK | 创建/复用的平台 Secret |
| `target_ref` | NOT NULL DEFAULT '' | `secret://platform/...` |
| `status` | NOT NULL | `DRY_RUN/IMPORTED/FAILED/SKIPPED` |
| `inventory_digest` | NOT NULL | 输入清单 digest |
| `actor_id/correlation_id` | NOT NULL | 审计主体与追踪 |
| `error_code/error_summary` | NOT NULL DEFAULT '' | 脱敏错误 |
| `created_at/completed_at` | NOT NULL/NULL | 时间线 |

约束：

- `UNIQUE(source_provider, source_ref_hash, inventory_digest)`
- import 只读取 env 一次；幂等重跑不得产生重复 Secret version。
- `vault`/`kms` 不创建 operation 成功记录，直接返回明确的未实现错误。

## 7. Tool Resource 版本模型

旧 `platform_resource_binding` 在切换前只读兼容；新发布和运行时只使用以下表。

### 7.1 `tool_resource`（新增，稳定 Identity）

| 字段 | 约束 | 说明 |
|---|---|---|
| `id` | PK | 稳定资源 ID |
| `code` | UNIQUE | 稳定 code |
| `display_name` | NOT NULL | 展示名 |
| `resource_kind` | NOT NULL | `database/redis/loki` |
| `scope_type` | NOT NULL | `environment/base/workshop` |
| `environment_id/base_id/workshop_id` | FK/NULL | topology scope |
| `status` | NOT NULL | `ACTIVE/DISABLED/ARCHIVED` |
| `revision` | NOT NULL | Identity optimistic revision |
| `created_by/updated_by` | NOT NULL | 管理主体 |
| `created_at/updated_at` | NOT NULL | 时间 |

索引/约束：

- `UNIQUE(code)`
- `idx_tool_resource_scope(scope_type, environment_id, base_id, workshop_id)`
- `idx_tool_resource_kind_status(resource_kind, status)`
- scope_type 与三层 ID 组合使用 CHECK 保证合法。

### 7.2 `tool_resource_draft`（新增，可编辑）

| 字段 | 约束 | 说明 |
|---|---|---|
| `id` | PK | Draft ID |
| `resource_id` | FK | Identity |
| `draft_revision` | NOT NULL | 乐观并发版本 |
| `provider` | NOT NULL | `mysql/sqlserver/oracle/redis/loki` |
| `contract_version` | NOT NULL | canonical Provider schema |
| `config_json` | NOT NULL | 结构化非敏感配置 |
| `config_hash` | NOT NULL | canonical hash |
| `status` | NOT NULL | `DRAFT/VERIFIED` |
| `created_by/updated_by` | NOT NULL | 管理主体 |
| `created_at/updated_at/verified_at` | NOT NULL/NULL | 时间 |

索引/约束：

- `UNIQUE(resource_id, draft_revision)`
- partial unique：每个 resource 最多一个 `DRAFT/VERIFIED` 可编辑 current draft。
- config 不含 username/password 明文；username 也通过 Secret ref 管理时不写入 config。
- Oracle `service_name`/`sid` 使用 CHECK 或 canonical validator 保证二选一。

### 7.3 `tool_resource_draft_secret`（新增）

| 字段 | 约束 | 说明 |
|---|---|---|
| `draft_id` | PK part/FK | Draft |
| `field_path` | PK part | canonical 字段路径 |
| `secret_id` | FK | 平台 Secret identity |
| `created_at` | NOT NULL | 绑定时间 |

约束：

- `PRIMARY KEY(draft_id, field_path)`
- 只接受 enabled `platform_secret` 且 ref 为 `secret://platform/`。
- Draft 删除时级联删除；Secret 被依赖时禁止物理删除。

### 7.4 `tool_resource_verification`（新增）

| 字段 | 约束 | 说明 |
|---|---|---|
| `id` | PK | verification ID |
| `draft_id` | FK | 被验证 Draft |
| `config_hash` | NOT NULL | 防止验证后篡改 |
| `verifier_version` | NOT NULL | 验证器 build |
| `status` | NOT NULL | 验证状态 |
| `schema_check/secret_check/connectivity_check/readonly_check` | NOT NULL | 各门禁状态 |
| `result_summary_json` | NOT NULL | 脱敏、有界结果 |
| `error_code/error_summary` | NOT NULL DEFAULT '' | 安全错误 |
| `verified_by/verified_at` | NOT NULL | 主体与时间 |

状态：

`RUNNING/PASSED/FAILED/BLOCKED_DEFERRED`

Oracle 无真实连接时只能 `BLOCKED_DEFERRED`，不能映射成 PASSED。

索引：

- `idx_resource_verification_draft(draft_id, verified_at)`
- `idx_resource_verification_status(status, verified_at)`

### 7.5 `tool_resource_revision`（新增，不可变）

| 字段 | 约束 | 说明 |
|---|---|---|
| `id` | PK | Revision ID |
| `resource_id` | FK | Identity |
| `revision_no` | NOT NULL | 单资源递增版本 |
| `source_draft_id` | FK | 发布来源 |
| `verification_id` | FK | 必须 PASSED |
| `provider/contract_version` | NOT NULL | 固化契约 |
| `config_snapshot_json` | NOT NULL | 非敏感不可变 snapshot |
| `config_hash` | NOT NULL | canonical hash |
| `status` | NOT NULL | `PUBLISHED/DISABLED/ARCHIVED` |
| `published_by/published_at` | NOT NULL | 发布事实 |
| `disabled_by/disabled_at` | NULL | 停用事实 |
| `archived_by/archived_at` | NULL | 归档事实 |

索引/约束：

- `UNIQUE(resource_id, revision_no)`
- `UNIQUE(resource_id, config_hash)`
- `idx_tool_resource_revision_status(resource_id, status, revision_no)`
- 发布后禁止 UPDATE 配置字段的数据库 trigger；只允许合法状态转换。

### 7.6 `tool_resource_revision_secret`（新增）

| 字段 | 约束 | 说明 |
|---|---|---|
| `resource_revision_id` | PK part/FK | Published revision |
| `field_path` | PK part | canonical 字段路径 |
| `secret_id` | FK | 稳定 Secret identity |
| `secret_ref` | NOT NULL | 发布时确认的 platform ref |

约束：

- `PRIMARY KEY(resource_revision_id, field_path)`
- 不固定 Secret version；运行快照解析当时 active version，轮换触发 reload。
- `secret_ref` 必须与 `secret_id` 当前稳定 ref 一致且以 `secret://platform/` 开头。

## 8. Handler 与应用发布绑定

### 8.1 `handler_installation`（新增，代码发现事实）

| 字段 | 约束 | 说明 |
|---|---|---|
| `handler_id` | PK part | 稳定代码 ID |
| `handler_version` | PK part | 不可变版本 |
| `implementation_digest` | NOT NULL | 代码/manifest digest |
| `input_schema_json/output_schema_json` | NOT NULL | JSON Schema |
| `risk_level` | NOT NULL | `LOW/MEDIUM/HIGH` |
| `required_permission_json` | NOT NULL | 权限 codes |
| `resource_slots_json` | NOT NULL | 逻辑资源槽声明 |
| `installation_status` | NOT NULL | `INSTALLED/MISSING/DRIFTED` |
| `first_seen_at/last_seen_at` | NOT NULL | 发现时间 |

约束：

- `PRIMARY KEY(handler_id, handler_version)`
- DB 不包含实现源码、脚本、SQL 模板或 URL。
- 同 version digest 漂移时标 `DRIFTED` 并阻止 readiness/发布。

### 8.2 `handler_publication`（新增，治理状态）

| 字段 | 约束 | 说明 |
|---|---|---|
| `id` | PK | publication ID |
| `handler_id/handler_version` | FK installation | 精确代码版本 |
| `status` | NOT NULL | `PUBLISHED/DISABLED/ARCHIVED` |
| `published_by/published_at` | NOT NULL | 发布事实 |
| `disabled_by/disabled_at` | NULL | 停用事实 |
| `revision` | NOT NULL | 乐观并发 |

约束/索引：

- `UNIQUE(handler_id, handler_version)`
- `idx_handler_publication_status(status, handler_id)`
- 未 installed、digest drift 或依赖 schema 非法时不得 PUBLISHED。

### 8.3 `business_application_publication_handler`（新增）

| 字段 | 约束 | 说明 |
|---|---|---|
| `id` | PK | binding ID |
| `application_publication_id` | FK | 不可变应用发布 |
| `handler_publication_id` | FK | 精确 Handler 发布 |
| `capability_code` | NOT NULL | 应用可见能力 |
| `constraint_json` | NOT NULL | 应用级门禁 |
| `created_at` | NOT NULL | 发布时间 |

约束：

- `UNIQUE(application_publication_id, capability_code)`
- `UNIQUE(application_publication_id, handler_publication_id)`

### 8.4 `business_application_publication_resource`（新增）

| 字段 | 约束 | 说明 |
|---|---|---|
| `id` | PK | binding ID |
| `application_handler_id` | FK | 应用 Handler binding |
| `resource_slot` | NOT NULL | 逻辑 slot |
| `resource_revision_id` | FK | 精确 Published resource revision |
| `constraint_json` | NOT NULL | scope/prefix/label/limit |
| `binding_hash` | NOT NULL | canonical hash |
| `created_at` | NOT NULL | 发布时间 |

约束/索引：

- `UNIQUE(application_handler_id, resource_slot)`
- `idx_application_publication_resource_revision(resource_revision_id)`
- 资源 kind 必须满足 Handler slot；普通应用不得绑定内部 `query_database` Handler。

## 9. Runtime generation、LKG 与应用状态

### 9.1 `runtime_snapshot_generation`（新增）

| 字段 | 约束 | 说明 |
|---|---|---|
| `id` | PK | generation ID |
| `generation_no` | UNIQUE | 单调递增 |
| `snapshot_digest` | NOT NULL | 完整 canonical snapshot digest |
| `status` | NOT NULL | `BUILDING/ACTIVE/FAILED/SUPERSEDED` |
| `resource_count/application_count` | NOT NULL | 安全计数 |
| `error_code/error_summary` | NOT NULL DEFAULT '' | 脱敏失败 |
| `built_at/activated_at` | NOT NULL/NULL | 时间 |

约束：

- 全局最多一个 ACTIVE generation（partial unique）。
- FAILED generation 不得成为请求 snapshot。

### 9.2 `tool_resource_runtime_state`（新增）

| 字段 | 约束 | 说明 |
|---|---|---|
| `resource_revision_id` | PK part/FK | revision |
| `generation_id` | PK part/FK | 生成代 |
| `status` | NOT NULL | `READY/DEGRADED/BLOCKED/DISABLED` |
| `resolved_secret_versions_json` | NOT NULL | 仅 Secret ID/version，不含值 |
| `last_known_good_generation_id` | NULL/FK | LKG |
| `error_code/error_summary` | NOT NULL DEFAULT '' | 脱敏错误 |
| `checked_at` | NOT NULL | 装载时间 |

索引：

- `PRIMARY KEY(resource_revision_id, generation_id)`
- `idx_resource_runtime_state_status(generation_id, status)`

### 9.3 `business_application_runtime_state`（新增）

| 字段 | 约束 | 说明 |
|---|---|---|
| `application_publication_id` | PK part/FK | 应用发布 |
| `generation_id` | PK part/FK | generation |
| `status` | NOT NULL | `READY/DEGRADED/BLOCKED` |
| `last_known_good_generation_id` | NULL/FK | LKG |
| `reason_codes_json` | NOT NULL | 脱敏原因 codes |
| `updated_at` | NOT NULL | 状态时间 |

规则：无 LKG 的必需资源失败才 BLOCKED；有 LKG 时 DEGRADED；不得因一个资源使
无关应用 BLOCKED。

## 10. 受控资源重置

### 10.1 `resource_reset_operation`（新增）

| 字段 | 约束 | 说明 |
|---|---|---|
| `id` | PK | operation ID |
| `status` | NOT NULL | reset 状态 |
| `target_kinds_json` | NOT NULL | 精确 `database/redis/loki` |
| `inventory_digest` | NOT NULL | prepare 清单 SHA-256 |
| `database_fingerprint` | NOT NULL | 防 TOCTOU 数据状态摘要 |
| `backup_reference` | NOT NULL | 仓库外备份引用，不含凭据 |
| `impact_summary_json` | NOT NULL | 数量与受影响应用 |
| `prepared_by/prepared_at` | NULL | prepare 事实 |
| `confirmed_by/confirmed_at` | NULL | 本次 apply 确认事实 |
| `applied_by/applied_at` | NULL | apply 事实 |
| `verified_by/verified_at` | NULL | verify 事实 |
| `correlation_id` | NOT NULL | 追踪 |
| `error_code/error_summary` | NOT NULL DEFAULT '' | 脱敏错误 |
| `created_at/updated_at` | NOT NULL | 时间 |

状态：

`REPORTED → PREPARED → CONFIRMED → APPLYING → APPLIED → VERIFIED`

任何阶段可因漂移或错误进入 `ABORTED/FAILED`；失败不能复用旧确认。

索引/约束：

- `UNIQUE(inventory_digest, database_fingerprint, status)` 不作为重复 apply 许可，
  仅用于检测重复操作。
- `idx_resource_reset_status(status, created_at)`
- `CONFIRMED` 必须由 prepare 后的新用户确认产生；不能由旧对话中的“同意”自动填充。

### 10.2 `resource_reset_target`（新增）

| 字段 | 约束 | 说明 |
|---|---|---|
| `operation_id` | PK part/FK | reset operation |
| `target_type` | PK part | resource/revision/binding/runtime-state |
| `target_id` | PK part | 精确 ID |
| `target_revision` | NOT NULL DEFAULT 0 | prepare 时 revision |
| `action` | NOT NULL | `DELETE/INVALIDATE/BLOCK` |
| `item_digest` | NOT NULL | 单项 digest |
| `apply_status` | NOT NULL | `PENDING/APPLIED/SKIPPED/FAILED` |
| `error_code/error_summary` | NOT NULL DEFAULT '' | 脱敏结果 |

约束：

- `PRIMARY KEY(operation_id, target_type, target_id)`
- apply 前逐项验证 revision/item digest，任一漂移则整个事务拒绝。
- 身份、新 RBAC、业务应用、平台 Secret、Job、Delivery、Audit 不得成为 DELETE target。

## 11. Audit

### 11.1 `audit_event`（修改）

新增：

| 字段 | 约束 | 说明 |
|---|---|---|
| `correlation_id` | NOT NULL | 跨链路追踪 |
| `entity_type/entity_id` | NOT NULL DEFAULT '' | 精确对象 |
| `event_key` | NOT NULL DEFAULT '' | 幂等审计事件键 |
| `operation_id` | NOT NULL DEFAULT '' | replay/reset/import 等 operation |

索引：

- `idx_audit_event_correlation(correlation_id, created_at)`
- `idx_audit_event_entity(entity_type, entity_id, created_at)`
- partial unique `UNIQUE(event_key) WHERE event_key <> ''`

`payload_summary` 必须经过字段 allowlist；禁止 Secret value/ciphertext/nonce、认证
header、完整 DSN、数据库密码、RabbitMQ URL、Master Key 路径内容。

### 11.2 `platform_config_audit`（修改）

新增 `event_code`、`status`、`operation_id`，保留已有 `correlation_id`。
`before_json/after_json` 改为公共 metadata snapshot，必须先移除 Secret、config
中的敏感字段和完整错误堆栈。

索引：

- `idx_platform_config_audit_correlation(correlation_id, created_at)`
- `idx_platform_config_audit_operation(operation_id, created_at)`

### 11.3 必须产生的审计事件 code

| 范围 | Event code |
|---|---|
| Debug/授权 | `debug_job_allowed`, `debug_job_denied`, `internal_tool_allowed`, `internal_tool_denied` |
| strict RBAC | `authorization_mode_switched`, `legacy_authorization_removed`, `platform_admin_invariant_denied` |
| Migrator | `migration_applied`, `migration_checksum_rejected`, `schema_head_rejected` |
| Job Outbox | `job_dispatch_created`, `job_dispatch_published`, `job_dispatch_retry_wait`, `job_dispatch_dead`, `job_dispatch_replayed` |
| Delivery | `delivery_created`, `delivery_attempted`, `delivery_chunk_succeeded`, `delivery_dead`, `delivery_replayed`, `delivery_skipped` |
| Secret | `secret_created`, `secret_rotated`, `secret_disabled`, `secret_env_imported`, `secret_resolution_failed` |
| Resource | `resource_draft_saved`, `resource_verified`, `resource_verification_failed`, `resource_published`, `resource_disabled`, `resource_archived` |
| Handler/App | `handler_published`, `handler_disabled`, `application_resource_bound`, `execution_scope_created` |
| Runtime | `runtime_generation_activated`, `runtime_generation_failed`, `resource_lkg_retained`, `application_blocked` |
| Reset | `resource_reset_reported`, `resource_reset_prepared`, `resource_reset_aborted`, `resource_reset_applied`, `resource_reset_verified` |

Denied/failed 事件只保存规则 code 与安全摘要，不回显请求中的伪造身份 Header 或
Secret。

## 12. 关键唯一性与删除规则汇总

| 不变量 | 数据库保障 |
|---|---|
| migration version/name 唯一 | `schema_migration` PK + UNIQUE |
| 一个 Job 一个初始 dispatch | `UNIQUE(job_dispatch_outbox.job_id)` |
| event 不能重复产生业务效果 | Outbox `event_key` UNIQUE + consumer composite PK |
| 一个 Job/result 一个 Delivery | `UNIQUE(job_id, result_artifact_id)` |
| 成功分片不重复发送 | Delivery partial unique + stable chunk idempotency key |
| 一个 Job 一个 Execution Scope | `UNIQUE(agent_job_execution_scope.job_id)` |
| 应用每能力一个 Handler | application publication capability UNIQUE |
| Handler 每 slot 一个 revision | application handler + slot UNIQUE |
| Resource Revision 不可变 | revision unique + immutable trigger |
| enabled Secret 一个 active version | partial unique active version |
| 新资源仅 platform Secret | FK + ref CHECK + publish validator |
| 一个 generation ACTIVE | partial unique ACTIVE |
| reset 只作用精确清单 | operation/target PK + digest/revision 比对 |
| 至少两名人类平台管理员 | 同事务锁 + constraint trigger |

普通业务 API 不提供 Published Revision、Outbox、Audit、历史 Session 的物理删除。
特殊 reset 也不得删除身份、新 RBAC、业务应用、平台 Secret、Job、Delivery、Audit
或历史 snapshot；维护清理由独立、离线、有备份的流程处理。

## 13. 实施顺序

1. 修复 migration version 并建立 `schema_migration`。
2. 增加 Job/Session/Audit correlation 和 Execution Scope。
3. 新增 Job Dispatch Outbox 与 consumer dedup，再切换 Job publish。
4. 新增 Delivery Outbox，扩展 attempt/chunk，再切换 Delivery。
5. 加固 Secret 唯一性与 env import operation。
6. 新增 Resource/Handler/Application binding/Runtime generation 模型。
7. 迁移仍需保留的数据；之后在独立确认下执行受控 resource reset。
8. 每一阶段 migration 完成后运行 FK、唯一性、悬空引用、Secret 泄漏和状态机检查，
   Gate 通过后才进入下一阶段。

任何实现若需要改变本字典的实体边界、唯一键或删除范围，必须先更新 OpenSpec
设计和本文件，不能在 migration 中静默偏离。
