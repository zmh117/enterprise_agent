## 1. 管理面与可信 actor

- [x] 1.1 先补管理面关闭时平台、Workflow、调试 Job 和认证入口均返回 404 的契约测试
- [x] 1.2 将全部管理 Router 和调试入口统一移入 `FEATURE_WEB_ADMIN` 装配分支
- [x] 1.3 先补管理面开启后的 401、伪造 Header 401、无权限 403 和授权 200 契约
- [x] 1.4 删除生产 `optional_legacy_actor` 兼容路径并让平台配置写 actor 只来自可信 principal
- [x] 1.5 为平台 topology/Secret/runtime/resource 读写补齐 `platform`/`secret` action 矩阵
- [x] 1.6 为 Workflow Router 与 Service 落实 `agent/read|edit|publish` 权限矩阵并更新既有测试
- [x] 1.7 为 Compose `admin-web` 恢复 admin profile、传入 feature flag 并增加镜像启动守卫与配置测试

## 2. RabbitMQ poison-message 边界

- [x] 2.1 先补 malformed JSON、缺失标识、首次 handler 异常和 redelivery 持续异常的 consumer 契约测试
- [x] 2.2 实现 Agent Job envelope 的有界解析与安全错误分类
- [x] 2.3 实现 durable dead queue quarantine、发布确认后 ack，以及首次异常一次 requeue
- [x] 2.4 补充正常 Worker 业务 retry 返回后 consumer 只 ack、不改变数据库 retry/Outbox 的回归测试

## 3. Job 查询下推

- [x] 3.1 先补超过旧 500 条预取窗口仍能命中过滤记录和稳定 cursor 翻页的 API 契约
- [x] 3.2 将 AdminScope、全部 Job 过滤条件、keyset cursor 与 `limit + 1` 下推 `AdminReadRepository`
- [x] 3.3 删除 controller 的截断后 Python 过滤并保持现有响应投影与脱敏契约
- [x] 3.4 运行 SQLite 聚焦测试并补 PostgreSQL repository integration 覆盖或记录环境阻塞

## 4. 前端错误边界

- [x] 4.1 先补 CapabilityGate 对无权限和网络/5xx/解析失败区别呈现的组件测试
- [x] 4.2 实现 capability 查询失败状态、重试入口和 401/403 分流
- [x] 4.3 先补根组件渲染异常的安全恢复测试并实现全局 React Error Boundary
- [x] 4.4 运行前端测试、typecheck 和生产构建

## 5. 非本地对象存储失败关闭

- [x] 5.1 先补 production 缺失/默认对象存储凭据失败及 local/test 允许的设置契约
- [x] 5.2 实现设置加载的非本地对象存储凭据校验且错误不包含凭据
- [x] 5.3 收紧 Compose MinIO 本地默认边界并更新 Compose/Secret 分离测试和运维说明

## 6. 综合验证

- [x] 6.1 运行受影响后端测试、静态检查和 `git diff --check`
- [x] 6.2 运行 `docker compose config`、OpenSpec strict validation 并确认无 Secret/旧 actor 路径残留
- [x] 6.3 汇总 Confirmed-current 测试证据与未执行的 Compose/RabbitMQ/PostgreSQL 实网验收

## Evidence

- 后端全量：`996 passed, 30 skipped, 2 subtests passed`。
- 前端全量：`15` 个测试文件、`112` 个测试通过；`typecheck`、`lint` 与 production build 通过。
- 静态检查：受影响 Python 文件 `ruff` 与 `mypy` 通过；`git diff --check` 通过。
- 部署配置：默认与 admin profile 的 `docker compose config --quiet` 通过；admin-web 关闭守卫退出码为 `1`，启用时为 `0`。
- OpenSpec：`openspec validate harden-management-and-runtime-boundaries --strict` 通过。
- 当前环境未提供 `MIGRATION_POSTGRES_DSN`，新增 PostgreSQL Job 查询 integration 已收录但本次按 opt-in 跳过；RabbitMQ 4 实网 poison/retry 验收同样未启用，单元边界与现有数据库 retry/Outbox 回归已通过。
