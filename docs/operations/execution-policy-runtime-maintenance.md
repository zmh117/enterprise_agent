# Job Execution Policy 一次性维护窗口

本 Runbook 只用于把测试环境从“旧 Job 没有固定执行策略”升级到
`execution_policy_json v1`。它会删除 Agent 运行数据和关联对象，但保留用户、外部身份、
RBAC、Agent、业务应用、Publication、Deployment、Connector、Webhook Trigger 和密钥配置。

该清理不是 `retention_days` 实现，不会安装定时任务或后台清理 Worker。

## 删除范围

数据库按外键安全顺序删除：

1. `attachment_content`、`message_attachment`
2. `delivery_chunk`、`delivery_attempt`
3. `agent_tool_call`、`agent_artifact`、`agent_step`、`job_id IS NOT NULL` 的 Job 审计；
   无 Job 归因的控制面审计保留
4. `webhook_outbox`、`webhook_event`、`webhook_replay_nonce`
5. `agent_message`、`agent_job`、`agent_session`

数据库删除前，命令会先删除 `message_attachment.object_key` 和采用
`s3://bucket/key` 或 `minio://bucket/key` 表示的 Agent 产物对象。对象删除失败时数据库
不会开始删除。

## 维护步骤

1. 备份 PostgreSQL 和 MinIO bucket，并记录当前 Git commit。
2. 停止所有可能创建、消费或投递 Job 的进程：

   ```bash
   docker compose stop api-server admin-web dingtalk-stream-ingress agent-worker webhook-worker file-worker
   ```

3. 用同一 commit 重建应用镜像，避免新旧版本并行：

   ```bash
   docker compose build api-server agent-worker dingtalk-stream-ingress webhook-worker file-worker admin-web
   ```

4. 先输出删除前计数和对象摘要，不执行删除：

   ```bash
   docker compose run --rm --no-deps api-server \
     python -m app.cli.purge_legacy_agent_runtime
   ```

5. 核对报告后执行一次性删除和 PostgreSQL `NOT NULL` 收口：

   ```bash
   docker compose run --rm --no-deps api-server \
     python -m app.cli.purge_legacy_agent_runtime \
     --apply --confirm delete-legacy-agent-runtime
   ```

6. 检查输出满足：

   - 所有 `after.runtime_rows` 为 `0`；
   - `before` 与 `after` 的 `preserved_control_plane_rows` 完全一致；
   - `deleted_object_count` 与删除前 `object_count` 一致。

7. 在 PostgreSQL 检查列约束和默认值：

   ```sql
   SELECT is_nullable, column_default
   FROM information_schema.columns
   WHERE table_name = 'agent_job'
     AND column_name = 'execution_policy_json';
   ```

   预期为 `is_nullable = 'NO'`、`column_default IS NULL`。

8. 启动同一 commit 的服务并创建一个全新 local Job：

   ```bash
   docker compose up -d api-server admin-web dingtalk-stream-ingress agent-worker webhook-worker file-worker
   ```

   在运行记录确认 Job 同时显示 `schema_version=1`、`requested`、`effective`、
   `sources` 和实际工具调用数。

## 回滚边界

执行删除前可以直接取消维护并恢复服务。执行删除后不能依靠应用回滚恢复运行数据；
如需恢复，只能使用步骤 1 的 PostgreSQL 和 MinIO 同时间点备份。
