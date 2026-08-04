# 部署与运维

## 当前部署形态

当前唯一正式建模的 runtime environment 是 `local`，使用 Docker Compose。它适合本地开发、企业内网集成和 MVP 验收，不应直接等同于生产 Kubernetes 或多环境发布架构。

默认 Compose 服务：

```text
postgres
rabbitmq
migrator
api-server
admin-web
dingtalk-runtime
internal-api-platform
agent-worker
job-dispatch-worker
delivery-dispatch-worker
channel-dispatch-worker
webhook-worker
attachment-worker
minio
minio-init
```

开发时还可使用 `mock-internal-api-platform`、`local-internal-api-platform` 和 `ones_mock`，这些是验证替身，不代表正式数据平面。

## 启动依赖

```text
postgres healthy
  -> migrator one-shot success
  -> api-server / internal-api-platform / workers

rabbitmq healthy
  -> api-server / job-dispatch-worker / agent-worker
  -> channel-dispatch-worker / webhook-worker / attachment-worker

api-server healthy
  -> dingtalk-runtime

minio healthy + minio-init success
  -> attachment-worker
```

只有 `migrator` 可以修改 schema。API、Worker 和 Internal API Platform 在启动／readiness 时校验 migration head，不能在业务容器中临时补跑 migration 或绕过失败依赖。

## 配置分层

### 部署安全开关

以下四个开关由部署环境控制，不能由普通数据库配置静默越权开启：

```text
FEATURE_WEB_ADMIN
FEATURE_PUBLISHED_AGENT_RUNTIME
FEATURE_REAL_CLAUDE
FEATURE_REAL_INTERNAL_TOOLS
```

- `FEATURE_WEB_ADMIN` 派生启用统一身份、Web Session、RBAC 和业务应用控制面；
- `FEATURE_PUBLISHED_AGENT_RUNTIME` 决定活动业务应用发布是否接管运行链；
- `FEATURE_REAL_CLAUDE` 决定使用真实 Claude Agent Runtime 还是 stub；
- `FEATURE_REAL_INTERNAL_TOOLS` 决定使用 HTTP Internal API Platform 还是真实网络隔离的 fake client。

数据库中若仍存在对后两个开关的旧 requested value，readiness 会显示 deprecated diagnostic；部署环境仍是唯一 authority。

### Bootstrap-only

典型包括：

- `DATABASE_DSN`
- `APP_CONFIG_MASTER_KEY_FILE`
- `APP_ENV`
- `SEED_LOCAL_CONFIG`
- `RABBITMQ_URL`
- 服务间认证 Token 文件／环境注入
- Model Provider host allowlist
- MinIO／S3 基础设施地址

这些是进程能够安全启动的最小边界，不应被业务应用草稿覆盖。

### DB-backed runtime config

非敏感运行参数通过 PostgreSQL revision 和 snapshot 管理，例如模型非敏感配置、Internal API 路由、执行限制和资源 topology。当前主要在进程启动时加载；并非所有配置都支持热 reload。

### Secret-managed

模型 Key、Connector Secret、外部 Token 和工具资源凭据通过加密 Secret version 管理。部署只提供固定 Master Key 和服务间 Token，不应在 Compose 文件或上传文档中保存真实业务 Secret。

## 服务网络

- Compose 内服务通过服务名访问，例如 `postgres:5432`、`rabbitmq:5672`、`internal-api-platform:9000`、`minio:9000`；
- 容器中的 `127.0.0.1` 只表示该容器自身；
- 独立 Compose 网络中的测试数据库需要通过宿主机发布端口时使用 `host.docker.internal:<port>`；
- Admin Web 由 Nginx 提供静态资源，并同源代理 `/api` 到 `api-server`；
- Internal API Platform 默认不发布宿主机端口，只在应用网络内访问；
- PostgreSQL、RabbitMQ Management、Admin Web、API 和 MinIO 的宿主机端口只用于本地／受控环境。

## 持久化与恢复边界

| 组件 | 持久化内容 | 恢复原则 |
| --- | --- | --- |
| PostgreSQL | 全部配置、身份、发布、Job、Inbox/Outbox、审计 | 变更前 custom-format 备份；恢复后重跑 migration 与 schema 校验 |
| RabbitMQ | 传输中的最小 ID 消息 | 先以 PostgreSQL Outbox 对账，不把 broker 状态当业务真相 |
| MinIO | 私有原始附件 | 以 attachment 元数据和对象 hash 对账；未知对象默认只报告不自动删 |
| Admin Web | 静态构建产物 | 可从源码重建，无业务事实 |
| Workers / Runtime | 无持久业务状态 | 重建后从租约、Outbox、Job 和 DB snapshot 恢复 |

基础设施升级、授权重置或 destructive maintenance 必须先做只读 report、精确影响清单、仓库外备份和显式确认。普通 migration 不得偷偷清理身份、授权、队列或测试数据。

## 常用开发与验证命令

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
make check
```

前端：

```bash
cd frontend
npm ci
npm run lint
npm run typecheck
npm test -- --run
npm run build
```

DingTalk Runtime：

```bash
cd dingtalk-runtime
npm ci
npm run lint
npm run typecheck
npm test
npm run build
```

Compose 静态检查：

```bash
docker compose config --quiet
docker compose config --services
```

启动或重建会影响当前真实钉钉连接和 Worker，应先确认维护窗口；不要仅因修改了 Compose 就擅自 recreate 正在运行的服务。

## Readiness 与 Health

`api-server` 的 `/api/ready` 至少检查：

- database；
- schema head；
- RabbitMQ；
- Internal API service token；
- Master Key；
- runtime assembly；
- runtime config／feature configuration；
- resource generation 和 effective state。

`internal-api-platform` 的 `/ready` 还检查自身 schema、服务 Token、Master Key、resource generation、各 Resource Revision 和 last-known-good 状态。

Health 只能证明进程或依赖层面可用，不能证明 DingTalk → Job → Tool → Delivery 闭环。

## 排障顺序

### 钉钉无回复

```text
Runtime client state
-> Inbox event
-> Channel Outbox
-> Channel worker / queue
-> Agent Job + Job Dispatch Outbox
-> Agent Worker + Tool Call
-> Artifact
-> Delivery Outbox / attempt / chunk
-> DingTalk adapter response
```

### Tool 不可见

```text
Job fixed publications
-> Agent capability envelope
-> Application capability subset
-> Release / Handler / Resource status
-> current user identity/default Team/credential
-> runtime execution binding
```

不要把“Tool 在代码中注册”直接等同于“当前用户当前 Job 可见”。

### Internal API Platform 不就绪

按顺序检查：

1. database 和 migration head；
2. Master Key 与服务 Token是否可解析；
3. published generation digest 与 effective digest；
4. resource revision 校验、Secret version 和 last-known-good；
5. 应用 binding 是否引用无效 resource；
6. 不要在 DB 配置无效时静默回退 YAML。

### Webhook 接受但无 Job

检查 `webhook_event` 的 auth/filter/status，再检查 `webhook_outbox`、worker、service account、Agent Publication 和 ChannelIngressService。`202` 不代表 Job 已创建。

## 2026-08-04 本机现场快照

以下仅是整理文档时的只读观察，不是本包要修复的事项：

- `api-server` 从容器内查询 `/api/ready` 返回 `status=ready`、migration head `027`；
- 当前本机部署显式开启 Web Admin、Published Agent Runtime、真实 Claude 和真实 Internal Tools；
- PostgreSQL、RabbitMQ、API、DingTalk Runtime、Job／Channel／Webhook／Delivery workers 和 MinIO 处于运行状态；
- `internal-api-platform` 进程在运行但 Compose 显示 `unhealthy`；其 `/ready` 返回 database、Token、Master Key、runtime assembly 和 resource generation 可用，但 `core.schema=false`，因此整体 503；
- 本次只记录该异常，没有重建容器或修改配置，也没有把原因推断为已确认结论。

本机状态是易变事实。后续对运行健康作结论前必须重新检查 `docker compose ps`、readiness、队列、数据库和业务证据链。

## 部署设计仍需补齐

- 生产 HTTPS、Ingress、证书和网络出口策略；
- 多环境 deployment 与审批；
- Kubernetes 或等价编排、弹性和滚动发布；
- PostgreSQL、RabbitMQ、MinIO 的 HA／备份目标和灾备演练；
- Vault／KMS Secret Provider；
- 指标、告警、集中日志和 SLO；
- Worker lease/fencing/cancel 和更强的崩溃恢复；
- 生产级 Webhook replay protection。

## 关键源文件

- `docker-compose.yml`
- `.env.example`
- `backend/Dockerfile`
- `frontend/Dockerfile`
- `dingtalk-runtime/Dockerfile`
- `backend/app/shared/config.py`
- `backend/app/shared/runtime_config_loader.py`
- `backend/app/shared/migrations.py`
- `docs/platform-master-key.md`
- `docs/compose-postgres18-rabbitmq4-upgrade.md`
