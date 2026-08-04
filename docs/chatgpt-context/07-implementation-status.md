# 实施状态、缺口与路线图

## 阅读规则

本文件基于 2026-08-04、提交 `1eebd0d`。任务计数来自 `openspec list --json`，它表示 change checklist 进度，不等于全部生产验收已经完成。

当前文档整理没有修改应用代码、运行 migration、重建容器或补做外部 E2E。历史验证记录可以证明相应日期的结果，但不能替代未来 checkout 和现场状态的重新验证。

## 已实现的架构主干

以下能力已在当前代码和迁移中存在：

- PostgreSQL 18 + RabbitMQ 4 + 多 Worker 的异步 Agent Job 闭环；
- Channel、Webhook、Job Dispatch 和 Delivery 的 Inbox/Outbox；
- React 管理控制台与 FastAPI 控制面；
- 内部用户、Session、RBAC、角色授权中心和外部身份；
- Agent／Business Application／Workflow 的 revision、publication 和 activation；
- 模型连接 revision、受管 Secret 和 Job provenance；
- 多 DingTalk Stream Client 的固定 TypeScript Runtime；
- Webhook Trigger 发布、服务账号、Bearer 认证和声明式映射；
- 连续会话、MinIO 附件和受限 Office／Markdown 提取；
- 内置只读工具、Internal API Platform 和多方言数据库网关；
- 受治理工具资源 Draft → Verify → Publish → Generation；
- 受治理 API Connection／Capability／Handler／Mapping／Release；
- ONES 两阶段个人绑定、默认 Team 和当前发送人 Token 执行；
- 运行记录、Tool Call、HTTP attempt、Delivery 和 Audit 证据。

## OpenSpec 进度矩阵

| Change | 进度 | 判断 | 主要剩余项 |
| --- | ---: | --- | --- |
| `model-dingtalk-enterprises-and-identity-observations` | 107/109 | 部分完成 | 真实钉钉私聊／群聊和本人／管理员浏览器验收 |
| `add-governed-api-capability-handlers` | 122/124 | 部分完成 | 外部身份页面浏览器验收；仓库级静态质量门 |
| `stabilize-platform-runtime-foundation` | 88/110 | 部分完成 | 旧授权／队列清理、CI／Compose gate、真实工具到钉钉、最终文档与 strict gate |
| `redesign-deepseek-model-connection-setup` | 40/44 | 部分完成 | 使用新 Key 完成真实 discover/test/configure、DB 脱敏核对、Agent 选择与回滚证据 |
| `reset-identity-and-authorization-bootstrap` | 2/79 | 规划早期 | 绝大部分实现、备份、维护门禁、首次改密、恢复演练均未完成 |
| `add-role-and-authorization-control-center` | 115/115 | 已实现 | change checklist 完成；真实新钉钉事件仍是外部验收补充 |
| `add-unbound-dingtalk-identity-discovery` | 37/43 | 部分完成 | 以该 change 的具体剩余任务为准，需和 027 新企业模型重新核对 |
| `add-web-managed-multi-dingtalk-stream-runtime` | 79/82 | 部分完成 | 双真实机器人、无需重启新增机器人、停用后发布拒绝浏览器验收 |
| `add-agent-profile-model-connection-management` | 56/61 | 部分完成 | Key 轮换、显式应用升级和真实钉钉 Job provenance |
| `enforce-business-application-execution-policy` | 48/48 | 已实现 | checklist 完成 |
| `simplify-feature-flag-configuration` | 35/35 | 已实现 | checklist 完成 |
| `complete-business-application-runtime-routing` | 65/65 | 已实现 | checklist 完成，运行环境仍为 local |
| `complete-user-external-identity-management` | 56/56 | 已实现 | checklist 完成 |
| `add-business-application-control-plane-foundation` | 64/64 | 已实现 | checklist 完成 |
| `connect-admin-auth-and-external-identity-management` | 0/74 | 规划／待整理 | 与后来已落地变更存在重叠，不能直接按原 proposal 实施，需先判定是否废弃或重写 |
| `prototype-agent-application-control-plane-ui` | 43/43 | 已实现原型基础 | 后续页面已演进，静态 prototype 数据不能当实时事实 |
| `fix-agent-runtime-retry-and-failure-delivery` | 39/41 | 部分完成 | 真实模型对照 smoke、真实钉钉用户成功／有界失败闭环 |
| `add-web-managed-webhook-agent-triggers` | 90/93 | 部分完成 | Compose 故障恢复、真实只读工具到钉钉、真实 Grafana E2E |
| `add-unified-user-identity-and-rbac` | 58/59 | 部分完成 | 真实脱敏钉钉用户绑定前后权限／投递验收 |
| `add-continuous-dingtalk-multimodal-conversations` | 22/25 | 部分完成 | 以 change 中剩余真实附件／会话验收为准 |
| `upgrade-compose-postgres18-rabbitmq4` | 21/21 | 已实现 | checklist 完成 |
| `add-agent-test-data-environment` | 29/35 | 部分完成 | 独立测试数据环境和部分真实驱动验收仍需核对 |
| `add-schema-inspector-oracle-sqlserver-preview` | 26/26 | 已实现 | checklist 完成；真实数据库权限仍由部署负责 |
| `add-redis-cluster-oracle-instant-client` | 17/17 | 已实现 | checklist 完成 |
| `smoke-db-backed-config-with-compose` | 25/25 | 已实现 | checklist 完成 |
| `add-local-internal-api-platform-loki` | 34/34 | 已实现 | 本地验证能力，不等于生产拓扑 |

## 最近记录的验证证据

`add-governed-api-capability-handlers/verification.md` 记录的最近综合结果包括：

- 2026-08-02 后端 `769 passed, 22 skipped, 4 subtests passed`；
- 前端 `13` 个测试文件、`71` 个测试通过，lint、typecheck 和 production build 通过；
- OpenSpec strict validation 与 `git diff --check` 通过；
- Compose API／Admin Web 重建和 schema head `026` readiness 通过；
- 2026-08-03 外部身份入口模式调整的前端专项和全量检查通过。

之后仓库已增加 migration `027` 和钉钉企业／观察模型，并在提交 `1eebd0d` 修复 Agent 配置页对不可用 Connector 的展示与校验发布门禁。本次整理未重新运行完整测试套件，因此不能把上述数字表述为当前 HEAD 的新鲜全量验证结果。

## 已知质量基线

历史验证明确记录：

- 对应日期的 `.venv/bin/pytest -q` 和前端质量门通过；
- repository-wide `make check` 仍受既有 strict mypy 错误和大量 Ruff format 差异影响；
- 这些无关文件没有被批量格式化或静默 baseline；
- `add-governed-api-capability-handlers` 的质量任务 14.6 因此保持未完成。

讨论“CI 已全绿”或“仓库质量门已完成”前必须在当前 HEAD 重新运行并记录精确结果。

## 当前运行现场风险

2026-08-04 只读现场快照：

- `api-server` ready，schema head `027`；
- 真实模型和真实 Internal Tools 部署开关已开启；
- `internal-api-platform` 容器运行但 unhealthy，`/ready` 因 `core.schema=false` 返回 503；
- 其 database、Token、Master Key、runtime assembly、resource generation 和资源状态当时均显示可用；
- 未在本任务中继续诊断或重建，根因不能视为已确认。

因此，“真实 Internal Tools 已开启”不等于“当前每个工具调用链健康”。进行实时技术讨论时应先刷新该状态。

## 设计与验收缺口

### 必须优先处理

1. 解决并验证 Internal API Platform schema readiness 异常；
2. 收敛 `stabilize-platform-runtime-foundation`，明确旧授权 compatibility 和旧 RabbitMQ topology 的清理窗口；
3. 建立当前 HEAD 可重复的仓库级 CI／Compose gate；
4. 补齐真实钉钉、Webhook、ONES、模型、只读 Tool 和 Delivery correlation 证据；
5. 清理或重写与现状重叠的 0/74 旧 change，避免 ChatGPT 按过期设计重复建设。

### 生产化前必须设计

- HTTPS、网络出口、Network Zone／CIDR／DNS 安全；
- Webhook HMAC、timestamp、nonce 和 replay protection；
- Worker lease、fencing、cancel、RUNNING 崩溃恢复；
- PostgreSQL／RabbitMQ／MinIO HA、备份目标、恢复演练；
- Vault／KMS；
- 多环境发布、审批和灰度；
- Metrics、SLO、告警和集中日志；
- 数据保留、定时清理、导出和记忆生命周期。

### 需要保持为延期而非误报完成

- 写操作 Capability；
- 任意脚本／模板／通用 executor；
- 多 ONES 实例和跨 Team 查询；
- 长期记忆和向量检索；
- PDF／OCR／视觉和附件恶意软件扫描；
- 完整 SSRF 防护；
- Kubernetes 和跨区域容灾。

## 推荐演进顺序

```text
Phase A 事实收敛
  现场 readiness + 当前 HEAD 全量质量门 + 过期 change 整理

Phase B Runtime Foundation 完成
  strict authorization + 旧队列/兼容清理 + CI/Compose 故障 gate

Phase C 真实业务闭环
  DingTalk / Webhook / ONES / Model / Tool / Delivery 可关联证据

Phase D 生产安全
  HTTPS + Egress + Webhook replay protection + Secret provider + HA/DR

Phase E 平台扩展
  新只读 Capability、更多 Provider、Worker lease/cancel、多环境发布

Phase F 新能力
  记忆、检索、更多附件类型或写操作；每项单独 OpenSpec 和风险模型
```

## 讨论新方案前的检查清单

- 目标是控制面配置、入口、Agent Tool、内部数据工具还是外部业务 API？
- 当前代码是否已经有对应领域对象和发布链？
- 是否会改变身份、Credential Subject Policy 或应用访问语义？
- 是否需要新 migration、不可变 snapshot 字段或 runtime provenance？
- 是否破坏“发布不自动激活”和“Job 不读最新草稿”？
- 是否需要 Outbox、幂等、重试、dead 和 replay？
- 是否把外部原始数据或 Secret 带入模型／日志／审计？
- 是否有回退版本、运行阻断开关和真实 E2E 证据？

## 关键状态来源

- `openspec list --json`
- `openspec/changes/*/tasks.md`
- `openspec/changes/*/verification.md`
- `openspec/changes/*/implementation-evidence.md`
- `backend/migrations/`
- `git status --short --branch`
- `docker compose ps` 和服务 readiness
