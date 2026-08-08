# Gate 1：严格授权与运行时信任边界

记录时间：2026-07-29T02:20:45+08:00  
结果：PASS

## 代码与 migration

- 分支：`master`
- 基线 commit：`debb504`
- worktree：dirty（本 OpenSpec change 与用户原有未提交改动并存，未执行 reset/checkout）
- 源码 migration head：`018_runtime_session_isolation.sql`
- migration SHA-256：
  `1f46be4f0aa62d15af03e2ee44c49c5391d684302f8d0e6f7ddebc7c9ce67d62`
- PostgreSQL 实际存在
  `application_publication_id/execution_scope_hash/isolation_key_version/history_read_only`
  四列。
- 旧 `application/actor` Session 查询结果为 `0`，其中只读标记数为 `0`；
  当前没有需要回填的旧记录。
- 稳定 migration 账本/checksum 尚未实现，属于 Phase 2A 任务 3.1；Gate 1
  只记录源码 head、文件 checksum 和实际 schema，不声称已具备独立 Migrator。

## 自动化证据

```bash
.venv/bin/python scripts/runtime_foundation_gate.py verify-phase1
```

结果：`24 passed`，`PHASE_1_AUTOMATED_GATE: PASS`。固定清单覆盖：

- 错误 Webhook Bearer Token 被拒绝且不创建 Job；
- 缺失登录或 `agent.debug.execute` RBAC 时不创建 Debug Job；
- Debug DTO 拒绝身份、Agent、资源、Connector、路由和 conversation 注入；
- Internal API current/next Token 与数据库权威 Job facts；
- Session 不跨请求人、应用发布和 Execution Scope 复用；
- 旧 `actor/application` Session 只读；
- Internal Token、Webhook、DingTalk route audit 和 Connector 管理读取不泄漏 Secret。

```bash
.venv/bin/pytest -q
```

结果：`460 passed, 12 skipped, 3 xfailed, 2 warnings, 4 subtests passed`。
两个 warning 分别是既有 Starlette TestClient 弃用提示和既有 pytest
return-not-none 提示，无失败。

```bash
cd frontend
npm test -- --run
npm run build
```

结果：前端 `44 passed`；TypeScript 与 Vite 生产构建通过。仅保留既有
单 chunk 大于 500 kB 的构建提示。

## 本地 Compose 与数据只读核验

受影响 API、Internal API、Admin Web、Agent/Webhook/Channel/Attachment Worker
和 DingTalk Runtime 已从当前 worktree 重建。启动时未配置 Internal API Docker
Secret 会安全失败；使用未落盘、未回显的同一 JSON current Token 重新创建
server/client Secret 后，相关服务全部启动。

只读核验结果：

- `api-server`：healthy，`/api/health` 返回 `status=ok`；
- `admin-web`、`internal-api-platform`、四类 Worker：running；
- `dingtalk-runtime`：healthy；
- PostgreSQL 18：healthy；
- RabbitMQ 4：fully booted and running；
- RabbitMQ 当前业务队列 `messages_ready=0`、`messages_unacknowledged=0`；
  Job、Webhook、Channel、Attachment 活跃队列各有 1 个 consumer；
- 已登录验证的人类 `platform-admin` 数量：`2`。

本机 `.env` 仍未持久化 Internal API Token。以后重新创建容器前必须从本机
Secret 来源设置 `INTERNAL_API_SERVER_AUTH_TOKENS` 和
`INTERNAL_API_CLIENT_AUTH_TOKEN` 的 JSON 文件内容；不得提交仓库或使用空值。

## 明确未在 Gate 1 声称完成

- 独立 Migrator、UoW、Job/Delivery Outbox：后续 Phase 2；
- 固定 Master Key、凭据中心、资源 revision、Handler：后续 Phase 3；
- 真实 Oracle 11.2.0.4：deferred；
- HTTPS/HMAC、公网生产安全：未实现；
- 真实 Grafana→Agent→工具→DingTalk 新鲜链路：最终 Gate 6。
