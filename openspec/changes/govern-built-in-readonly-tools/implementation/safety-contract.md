# 安全错误、脱敏与 Correlation 契约（任务 1.4）

## 1. 错误 Envelope

所有新管理 API、迁移命令、发布校验、Job 创建和 Tool Call 拒绝统一返回：

```json
{
  "error": {
    "code": "stable_machine_code",
    "message": "安全、可操作且不含敏感数据的说明",
    "correlation_id": "server-tracked-id",
    "retryable": false,
    "details": {}
  }
}
```

`code` 是稳定机器契约；`message` 可改进措辞但不能携带原始异常。`details` 只能由白名单构造，禁止把异常对象、请求 body、上游响应或数据库 row 直接序列化。

## 2. 稳定错误码

### 2.1 依赖与 legacy 迁移

- `builtin_tool_migration_dependency_not_ready`
- `builtin_tool_legacy_write_forbidden`
- `builtin_tool_legacy_resolution_missing`
- `builtin_tool_legacy_resolution_ambiguous`
- `builtin_tool_legacy_job_quarantined`
- `builtin_tool_legacy_removal_gate_failed`
- `builtin_tool_legacy_reactivation_forbidden`

### 2.2 Manifest、安装与验证

- `builtin_tool_manifest_invalid`
- `builtin_tool_identifier_conflict`
- `builtin_tool_reserved_namespace`
- `builtin_tool_security_boundary_expanded`
- `builtin_tool_installation_missing`
- `builtin_tool_installation_drifted`
- `builtin_tool_verification_missing`
- `builtin_tool_verification_stale`
- `builtin_tool_verification_failed`
- `builtin_tool_manual_verification_forbidden`

### 2.3 Release 与发布组成

- `builtin_tool_release_not_active`
- `builtin_tool_release_lifecycle_invalid`
- `builtin_tool_release_dependency_in_use`
- `builtin_tool_publish_idempotency_conflict`
- `builtin_tool_agent_envelope_conflict`
- `builtin_tool_application_subset_violation`
- `builtin_tool_resource_mapping_missing`
- `builtin_tool_resource_mapping_ambiguous`
- `builtin_tool_resource_mapping_overlap`
- `builtin_tool_policy_not_published`
- `builtin_tool_policy_hash_mismatch`
- `builtin_tool_partition_policy_inconsistent`
- `workshop_partition_policy_invalid`
- `workshop_partition_policy_conflict`
- `workshop_partition_policy_revision_conflict`
- `workshop_partition_policy_draft_missing`
- `workshop_partition_policy_verification_stale`
- `builtin_tool_topology_placeholder_forbidden`
- `builtin_tool_placement_invalid`
- `builtin_tool_placement_required`

### 2.4 Job 与运行时

- `builtin_tool_snapshot_missing`
- `builtin_tool_snapshot_immutable`
- `builtin_tool_snapshot_hash_mismatch`
- `builtin_tool_exact_implementation_missing`
- `builtin_tool_implementation_digest_mismatch`
- `builtin_tool_lifecycle_blocked`
- `builtin_tool_use_denied`
- `builtin_tool_target_scope_denied`
- `builtin_tool_resource_override_forbidden`
- `builtin_tool_partition_policy_violation`
- `builtin_tool_database_table_out_of_scope`
- `builtin_tool_redis_key_out_of_scope`
- `builtin_tool_redis_scan_pattern_out_of_scope`
- `builtin_tool_loki_selector_conflict`
- `builtin_tool_loki_query_out_of_bounds`

## 3. `details` 和审计白名单

允许字段：

- `correlation_id`、`error_code`、`category`、`retryable`
- `operation`、`entity_type`、`entity_id`
- `tool_identifier`、`tool_release_id`、`handler_version`
- 截断后的 `implementation_digest_prefix`、`content_hash_prefix`
- `application_publication_id`、`agent_publication_id`、`job_id`、`tool_call_id`
- `resource_kind`、`resource_revision_id`、`resource_slot`
- `policy_type`、`policy_revision_id`
- `environment_id`、`base_id`、`workshop_id`、`placement`
- `status`、`candidate_count`、`match_count`、`truncated`
- `actor_id`、`occurred_at`、`verifier_version`

永不进入 error/details、日志或普通审计字段：

- password、token、API key、Cookie、Authorization header、Secret 明文或密文
- `secret_ref` 的解析值、Master Key、数据库 DSN
- host、port、base URL、完整 endpoint、username
- 原始 SQL、完整 Redis key/value、完整 Loki selector/label value、LogQL
- 原始请求/响应 body、原始异常字符串、stack trace、业务消息和无界工具结果

对查询和范围只记录规范化 hash、允许的对象 ID、计数与截断标志。错误 payload 必须从允许字段显式构造，不能先序列化后黑名单脱敏。

## 4. Correlation ID 契约

- 外部入口可提交 `X-Correlation-Id`；只接受 8–128 字符的 `[A-Za-z0-9._:-]+`，否则由服务端生成。
- 客户端提供的 ID 只用于追踪，绝不作为身份、授权、幂等或对象所有权证据。
- 同一个根 correlation ID 必须贯穿 API/ingress、Unit of Work、Job、Dispatch Outbox、RabbitMQ envelope、Worker、Internal API、Tool Call、Delivery Outbox 和最终 Delivery attempt。
- 每个持久化事件保存 correlation ID；子操作可以增加独立 operation/event ID，但不能替换根 ID。
- 跨服务请求必须把 correlation ID 放在固定 header/envelope 字段中；接收方校验格式，缺失时生成并在响应中返回。
- 所有拒绝和 verifier 结果都返回 correlation ID；上游异常只映射为稳定错误码和安全类别。

## 5. HTTP 与重试语义

- 400：输入/schema/selector/prefix/placement 无效。
- 401：服务信任根或登录身份无效。
- 403：管理权限、tool-use 或业务目标范围拒绝。
- 404：调用者有权知道但对象不存在；对不可披露对象可统一返回 404。
- 409：revision、idempotency、lifecycle、依赖或唯一解析冲突。
- 422：Draft 可保存但未满足 verify/publish 业务门禁。
- 503：精确实现/资源当前不可装载且属于可恢复平台健康问题。

权限、策略越界、legacy 歧义、Release lifecycle 阻断均为 `retryable=false`；暂时连接失败、限流和上游 5xx 可为 `retryable=true`，但重试必须继续使用原 Job Snapshot。
