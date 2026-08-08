# Phase 4 维护冻结与恢复基线

记录时间：2026-07-29T15:59:43+08:00  
结果：PASS

## 冻结与排空

- 停止配置写入、HTTP/DingTalk 入口以及 Agent、Job、Delivery、Webhook、
  Channel、Attachment Worker。
- 停止前后 RabbitMQ 所有队列均为 `messages_ready=0`、
  `messages_unacknowledged=0`；停止后所有目标队列 `consumers=0`。
- PostgreSQL 中 19 个 Agent Job 均为 `SUCCEEDED`；
  Job Dispatch Outbox 为 `PUBLISHED`，Channel Ingress Outbox 为
  `published`，Delivery Outbox 为 `SKIPPED`，没有 pending、running、
  retry 或 dead 记录。
- 备份时数据库 schema head 为 `023`；备份校验通过后才应用 migration
  `024_legacy_authorization_cleanup.sql`。

## 可恢复备份

备份引用：

`file:///Users/mhz/Backups/enterprise_agent/runtime-foundation-20260729-155943`

目录权限为 `0700`，其中敏感文件均为 `0400`。备份包含：

- PostgreSQL custom-format 逻辑备份和不含角色密码的 globals；
- 固定 Master Key 副本；
- RabbitMQ definitions JSON；
- `.env`、`docker-compose.yml`、`backend/config` 归档和 Git HEAD；
- 独立 `checksums.sha256`。

校验结果：

- PostgreSQL custom dump 已通过 `pg_restore --list`；
- RabbitMQ definitions 已通过 JSON 解析；
- 8 个载荷均通过 `shasum -a 256 -c`；
- PostgreSQL dump 为 680352 bytes，RabbitMQ definitions 为 2458 bytes，
  Master Key 为 61 bytes；没有空备份载荷；
- 容器内临时 dump/definitions 文件已在复制和校验后删除。

## 恢复后状态

- migration `024` 已由 one-shot Migrator 成功应用；
- API、Internal API Platform、DingTalk Runtime 及全部核心 Worker 已从当前
  源码镜像重建并通过 Compose health；
- Internal API server/client Token 改为从仓库外 `0400` JSON 文件挂载，
  不再依赖命令进程临时注入或 `.env` 明文；
- Internal API `/ready` 报告 `schema_head=024`、数据库、Master Key、
  Internal API Token 和 runtime assembly 均为 `true`；
- 资源运行态仍为数据库 Generation 1、`resource_count=0`、`degraded=false`。

本证据只完成维护恢复基线，不授权或执行旧授权行、旧 RabbitMQ
queue/exchange/binding 的删除。
