# Phase 5 旧平台凭据清理确认单

记录时间：2026-07-29T17:33:18+08:00  
状态：PREPARED，等待用户对本确认单中的 operation ID 与 inventory digest
明确确认。  
本确认单生成时没有删除 Secret、运行配置值或模型连接版本。

## 1. 恢复基线

新备份引用：

`file:///Users/mhz/Backups/enterprise_agent/secret-reset-20260729-172433`

目录权限为 `0700`，所有备份文件均为 `0400`。备份包含当前 PostgreSQL
custom dump、globals、RabbitMQ definitions、固定 Master Key、仍能恢复旧
密文的 legacy runtime `.env`、Compose、backend config 和 Git HEAD。

- 所有 8 个备份载荷均通过 SHA-256 校验；
- PostgreSQL dump 已通过 `pg_restore -l` 可读性校验；
- PREPARED manifest 文件自身 SHA-256：
  `d778b2f410e5e9453f7c6b8d5af320a7b15361fdf94008e9e4f88fe054a3b0e4`；
- 当前固定 Master Key ID 为 `3c49324f76f17310`；
- 旧 active 密文的 Master Key ID 为 `710f413ff0ce102f`，两者不一致。

备份中的 Master Key、`.env` 和 PostgreSQL dump 都不得提交到仓库。

## 2. 受控操作

```text
operation_id: platform_secret_reset_0e086a4a-eebe-4069-8c55-55ba8fec85e1
inventory_digest: ae6699fab921d0b671896f5b97c25671ac9ab6d633c157a71cb179abeb9a46d6
status: PREPARED
```

数据库 `audit_event` 已保存不含明文、密文、nonce 或 Master Key 的 PREPARED
审计记录。完整安全清单保存在上述备份目录的
`prepared-manifest.json`。

## 3. 精确删除范围

| 对象 | 精确数量 | 动作 |
|---|---:|---|
| `platform_secret` | 3 | 删除 |
| `platform_secret_version` | 14 | 删除 |
| `platform_secret_change_event` | 0 | 无动作 |
| `platform_runtime_config_value` | 1 | 删除 `ANTHROPIC_API_KEY` 旧绑定 |
| `model_connection_revision` | 4 | 删除旧 DeepSeek 配置/凭据版本 |
| `model_connection` | 1 | 保留 identity，清空 current revision 并设为 `rotation_required` |

三个 Secret code：

- `123456789`
- `deepseek_api_key`
- `dingtalk-dingb9feetjdec11m5wb-a7d92d77fa`

模型连接 identity 为 `default-deepseek-anthropic`。清理后保留稳定连接
identity，但 `current_revision_id` 为空、`revision=0`、
`status=rotation_required`，用户可重新保存配置和录入新 API Key。

## 4. 依赖与保留范围

清单确认这三个 Secret 没有以下其他依赖：

- `integration_connector`
- `platform_secret_reference`
- DB/Redis/Loki resource binding
- Webhook revision/publication

Apply 不删除或修改：

- 固定 Master Key 文件；
- 7 个用户、7 个外部身份、3 个 RBAC Role、7 个 RBAC membership；
- 3 个现有 DingTalk Connector 及 DingTalk Runtime；
- 业务应用、Job、Outbox、Delivery、审计和资源 reset 历史；
- runtime config definition 和 model connection identity。

Apply 后将重新计算上述保留对象的安全 digest，并证明与 PREPARED 基线一致。

## 5. Fail-closed apply 边界

只有用户明确确认本文件中的 operation ID 与 inventory digest 后，才允许短暂停止
相关入口/Worker，并在单个 PostgreSQL 事务内：

1. 锁定 Secret、运行配置和模型连接相关表；
2. 重新生成清单与 SHA-256 digest；
3. 要求 digest 精确等于确认值，且其他依赖计数仍全部为 0；
4. 先清除模型和运行配置依赖，再删除密文版本与 Secret；
5. 写入不含敏感材料的 applied 审计并提交；
6. 启动服务并执行 verify/readiness。

任何库存或依赖变化都会回滚并要求重新 prepare。

本操作不包含
`legacy_auth_cleanup_d6b908008809426c8b0a61ca629251fb`，也不包含旧
RabbitMQ queue 清理；这两个操作仍维持 PREPARED、未执行状态。
