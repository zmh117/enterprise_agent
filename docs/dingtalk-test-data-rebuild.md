# 钉钉测试数据受保护重建 Runbook

本命令只用于明确标记为 `local`、`test`、`development`、`staging` 或 `qa` 的
环境。默认模式只读；生产或未知环境永久拒绝。常规 migration、服务启动和管理页面
都不会自动清理钉钉数据。

## 保留与清理边界

必须保留：

- `app_user`、角色、成员关系、Web Session；
- ONES 身份、加密个人凭据、默认 Team 和使用事实；
- API Capability、Handler、Agent、业务应用主体及不可变发布；
- 全部 Agent Job、Tool 调用、Delivery Outbox 和投递尝试；
- 历史 Application Revision 中指向旧 Connector 的 Trigger／Delivery 引用。

允许清理或失效：

- 钉钉候选消息与候选；
- DingTalk Channel Ingress Outbox 和 Ingress Event；
- DingTalk Runtime 状态与租约；
- 钉钉身份应用观察、昵称审计和钉钉身份；
- 当前活动业务应用路由；相关 Deployment 改为未激活；
- 旧钉钉 Stream Connector 的专属 Platform Secret；
- 钉钉企业。

旧 Connector 不物理删除。它会被设置为 `enabled=0`、`deleted=1`，清除 Secret 和
企业引用，并在 metadata 标记为 `UNAVAILABLE` 历史来源。因此历史 Job、投递和不可
变 Application Revision 仍能保留原 Connector ID，但它不能再次参与活动路由。

## 外键盘点与事务顺序

执行器使用以下固定顺序；任一步骤失败会回滚整个数据库事务：

1. 删除仅与目标 Connector／企业关联、且没有 Tool Call 引用的治理审计。
2. 删除 `dingtalk_identity_nickname_audit`。
3. 删除 `dingtalk_identity_application_observation`；该表同时引用身份、Connector 和
   Ingress Event，必须先于三者。
4. 删除 `dingtalk_identity_candidate_message`；它同时引用候选、Connector 和
   Ingress Event。
5. 删除 `dingtalk_identity_candidate`。
6. 删除 `channel_ingress_outbox`，再删除 `channel_ingress_event`。
7. 删除 `channel_connector_runtime` 和已停止／过期的 `channel_runtime_lease`。
8. 删除 `provider='dingtalk'` 的 `user_external_identity`。若
   `external_api_credential`、`api_capability_verification` 或
   `agent_job_external_subject` 反向引用目标身份，计划标记为 blocker 并拒绝执行。
9. 删除 `business_application_active_route`，并停用对应
   `business_application_deployment`；不修改 Revision 和 Publication。
10. 将仅由目标 Connector 使用、且 `purpose='dingtalk_stream_client_secret'`、
    `managed_by='managed_channel'` 的 Platform Secret 及活动版本设为 `disabled`。
11. 软删除旧 `integration_connector`，清除 `dingtalk_enterprise_id` 和
    `secret_ref`，保留 Connector ID、名称和历史标记。
12. 删除 `dingtalk_enterprise`。
13. 复核全部目标数量为零、受保护分类数量不变，再写入一条不含认证材料的成功审计。

`business_application_revision_trigger`、
`business_application_revision_delivery` 和 `agent_channel_binding` 对旧 Connector 的
引用不删除；`agent_job.source_connector_id`、`delivery_attempt.connector_id` 等历史
来源值也不改写。

## 1. 备份与停止写入

先创建可恢复的 PostgreSQL 逻辑备份，并记录绝对目录和校验值：

```bash
scripts/compose_infra_upgrade.sh backup-postgres /absolute/path/to/dingtalk-rebuild-backup
shasum -a 256 /absolute/path/to/dingtalk-rebuild-backup/enterprise_agent.dump
```

随后停止所有可能产生钉钉配置或消息写入的服务：

```bash
docker compose stop api-server dingtalk-runtime channel-dispatch-worker
```

保留 `postgres` 和 `rabbitmq` 运行。确认没有未过期
`dingtalk-stream-runtime-singleton` 租约、处于 `publishing` 的 Channel Outbox 或处于
`DISPATCHING` 的 Ingress Event。执行器还会在事务内复查；PostgreSQL 执行时会锁定
相关写表，SQLite 使用 `BEGIN IMMEDIATE`。

## 2. 应用 schema migration

```bash
docker compose run --rm migrator
```

迁移只调整 schema，不含测试数据删除。迁移后应先确认 schema head 和现有 ONES
身份／凭据仍完整。

## 3. 只读预检

```bash
docker compose run --rm --no-deps api-server \
  python -m app.cli.dingtalk_test_data_rebuild
```

保存完整 JSON。输出包含：

- `environment`、`database_engine`、`database_fingerprint`；
- 每类目标的安全 ID、数量、受影响业务应用和历史引用；
- 将停用的专属 Secret 元数据，不含密文或 Secret 值；
- `protected_counts`、`protected_blockers`、`write_stop_evidence`；
- 确定性 `plan_hash` 和固定确认文字。

相同数据连续预检的 `plan_hash` 必须一致。计划出现 blocker、写入未停止或数量无法
解释时，不得执行。

## 4. 固定确认后执行

只有用户在当前操作上下文中原样回复：

```text
确认清空钉钉测试数据
```

才可使用同一份预检的 Hash 执行。任何“同意”“可以”“确认”都不等价。

```bash
docker compose run --rm --no-deps api-server \
  python -m app.cli.dingtalk_test_data_rebuild \
  --execute \
  --writes-stopped \
  --plan-hash '<PREVIEW_PLAN_HASH>' \
  --confirm '确认清空钉钉测试数据' \
  --backup-reference 'sha256:<BACKUP_DUMP_SHA256>' \
  --actor-id '<CURRENT_ADMIN_USER_ID>'
```

执行前会在同一事务中重新生成计划。数据库指纹、目标、数量、历史引用、受保护数量或
写入状态任何一项变化，都会以 `dingtalk_rebuild_plan_changed` 或
`dingtalk_rebuild_writers_active` 拒绝，必须重新预检和重新确认。

成功结果为 `APPLIED`，并返回计划数量、全部为零的 `remaining_counts`、受保护数量和
保留的历史引用。再次预检应得到 `empty=true`；使用该空计划执行只返回 `NOOP`。

## 5. 失败恢复与重新接入

事务内失败不会留下部分清理。若执行成功后需要恢复旧身份或 Secret，代码回滚无效，
必须先停止平台服务，再从操作前快照恢复：

```bash
scripts/compose_infra_upgrade.sh restore-postgres18 /absolute/path/to/dingtalk-rebuild-backup
scripts/compose_infra_upgrade.sh verify /absolute/path/to/dingtalk-rebuild-backup
```

不恢复时，重新构建并启动服务：

```bash
docker compose up -d --build api-server agent-worker job-dispatch-worker \
  delivery-dispatch-worker channel-dispatch-worker admin-web dingtalk-runtime
```

然后按顺序创建企业草稿、应用连接、发送验证消息、从受信候选绑定人员、为业务应用
选择新连接并重新发布。最后分别使用管理员和本人会话验收身份字段，并确认历史 Job、
Tool 调用和投递仍可读取、旧 Connector 显示为不可用历史来源。
