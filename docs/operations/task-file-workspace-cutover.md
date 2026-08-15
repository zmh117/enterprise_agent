# Task File Workspace 切换与运行手册

本手册不授权真实环境写入。执行前必须确认目标、备份、镜像 digest、migration head、短时服务 Principal 签发/轮换和回滚窗口。不得把 JWT、MinIO 或钉钉凭据写入命令、工单或证据。

## 目标拓扑

- 新增 `file-service`，内部同时提供 File MCP 与受控流式 API；
- `file-worker` 替换 `attachment-worker`，继续消费原 `agent.attachment.queue`；
- Delivery Worker 保持独立并通过 File Service 读取精确版本；
- 不部署独立 `file-mcp` 或 `docling-server`；
- 只有 File Service 解析 MinIO Secret Reference。

## 1. 部署前只读检查

1. 验证 migration 精确到当前 catalog head，File Service 的用户 JWKS、服务 JWKS、互不相同的新文件私有 Bucket 与旧附件私有 Bucket，以及固定 Tool Manifest readiness 均通过。旧附件 Bucket 只用于 File Service 执行 360 天到期清理，不把对象入口重新开放给 Worker。
2. 确认 File Worker 与 Delivery Worker 的短时 JWT 文件由平台身份服务轮换，角色分别是 `file-worker` 与 `delivery-worker`，每个 Token 有效期不超过 300 秒。
3. 记录旧附件队列 `ready`、`unacked`、consumer 数、retry/dead 队列计数。切换前只能有一个附件消费者。
4. dry-run 回填，按返回的 `next_cursor` 循环；任何 `status=blocked` 都停止：

```bash
python -m app.cli.backfill_task_file_attachments --batch-size 100
python -m app.cli.backfill_task_file_attachments --reconcile --batch-size 100
```

命令只处理 PostgreSQL 关联和到期/清理事实，不下载、复制或删除对象。`unassociated_legacy` 表示旧内容没有跨过 File Service 边界，不能伪造为可处理版本；到期后用户必须重新上传。

## 2. 单消费者切换

1. 暂停旧 `attachment-worker`，不要清空或重建队列。
2. 等待旧消费者数变为 0、`unacked=0`；记录此时 `ready`。若无法归零，恢复旧 Worker 并停止切换。
3. 启动 File Service，等待 `/ready` 为 ready。
4. 启动 `file-worker`，确认原附件队列 consumer 数精确为 1、File Worker 状态同时显示 `rabbitmq=ready` 和 `file_service=ready`。
5. 用无真实业务内容的合成 TXT 发布一条消息；验证 attachment ID 幂等、File/Version/Workspace/来源关联、Job 释放和安全审计。
6. 重新投递同一附件队列消息，确认没有第二个版本或对象；再观察 retry/dead 与 lifecycle backlog。
7. 在维护窗口授权后执行有界写回填，每批用上一批 `next_cursor` 继续，直到 `has_more=false`：

```bash
python -m app.cli.backfill_task_file_attachments --apply --batch-size 100
```

8. 再运行 `--reconcile`；只有 `status=ready` 且关联差异为零才能关闭切换窗口。`unassociated_legacy` 可非零，但必须记录为只可重新上传的历史内容。

## 3. 验证与观察

- 平台运维页显示 File Service/File Worker 接线、单消费者、ready/unacked、附件/暂存/工作区/保留/冲突积压、最早到期和最近清理结果；
- 页面和 API 不得出现文件名、正文、Bucket、对象键、Secret 或 JWT；
- Runtime readiness 显示非敏感容量上限，并验证 tmpfs 可用空间至少 64 MiB；默认容器 tmpfs 256 MiB，单 Job 逻辑上限 224 MiB；
- Publication 四项文件开关先保持全关，再按应用逐级启用；未命中 Job 保持原行为；
- 至少观察附件重试、File Service 短暂不可用恢复、交付响应丢失重试和到期清理。

## 4. 回滚

1. 先关闭 Business Application 的四项文件开关并发布/激活新 Revision，阻止新文件 Job 进入新能力。
2. 停止 `file-worker`，等待 consumer 数为 0 且 `unacked=0`。
3. 若仍在允许回滚的兼容窗口，恢复已验证的旧 `attachment-worker` 镜像，并确认 consumer 数精确为 1；不得让两个 Worker 并行。
4. File Service 已创建的不可变版本、Retained File、Delivery 和清理事实不得删除或回退；继续按生命周期治理。
5. 不回退 migration，不删除 ledger，不手工改对象键。若 contract 已移除旧入口，则只能发布 forward fix，不能恢复直连 MinIO 的旧 Worker。

## Stop conditions

任一条件立即停止：多个附件消费者；unacked 无法归零；File Service/JWKS/Bucket 未 ready；回填 `blocked`；消息幂等产生重复版本；Worker/Runtime/Delivery 获得 MinIO 凭据；审计或 UI 泄漏正文、对象位置或 Secret；没有经验证的回滚镜像和备份。
