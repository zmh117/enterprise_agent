# Phase 3B Gate：受治理凭据、工具资源与 Handler

记录日期：2026-07-28

## 验收范围

- 新 Secret 与资源绑定只允许 `secret://platform/<code>`；`env:` 仅可通过显式
  report/import 转换，`vault:`/`kms:` 是不可创建、不可发布、不可声称可用的预留
  Provider。
- DB、Redis、Loki 使用共享 canonical Provider contract；Draft 经过技术验证后才能
  发布为 immutable Resource Revision，已发布内容不能原地修改或普通物理删除。
- MySQL、SQL Server、Redis、Loki 的只读边界和限额由共享 contract、验证器和运行时
  同时执行；Oracle 固定为 11.2.0.4 contract、19c Thick Client 且禁止 Thin fallback。
- Handler 只能来自代码 Registry，具有稳定 ID、不可变版本、schema、风险、权限和
  逻辑资源槽；数据库不能注入 Python、脚本、SQL 或 URL 实现。
- 应用发布固定具体 Handler version 和 Resource Revision；Job 创建在同一事务中固定
  Execution Scope 及 binding hash，Internal API 从 Job 事实重新授权，不读取浮动版本。
- Handler 执行必须满足
  installed ∩ published ∩ resource-bound ∩ agent ∩ application ∩ role ∩ scope。
  `query_database` 仅供内部诊断 Agent，普通业务应用的能力目录不可见且发布校验拒绝。

## 固定自动化 Gate

命令：

```bash
.venv/bin/python scripts/runtime_foundation_gate.py verify-phase3b
```

结果：

```text
50 passed, 1 warning
PHASE_3B_AUTOMATED_GATE: PASS
```

固定测试覆盖：

- Resource Draft、Verification、Revision、activation/LKG、状态机、并发发布与内容
  不可变性。
- MySQL、SQL Server、Oracle、Redis、Loki Provider 字段转换/拒绝、Secret reference
  限制、只读语句、timeout/rows/bytes 与 prefix/label 边界。
- Handler Registry、资源槽、完整交集解析、内部诊断能力隔离。
- 应用发布 binding、Job Execution Scope、scope hash、Internal API 事实重读和篡改
  拒绝。
- 未实现 Provider 及未通过真实 Oracle 门禁的资源不可发布。

## 全量回归

```text
backend: 632 passed, 20 skipped, 2 warnings, 4 subtests passed
frontend: 10 files passed, 45 tests passed
frontend lint: passed
frontend build: passed
ruff: All checks passed
OpenSpec strict validation: passed
Phase 3B fixed gate: 50 passed
```

已知非阻断告警：

- Starlette `TestClient` 的上游弃用提醒。
- 一个既有 Pytest 测试函数返回 `Settings` 的提醒。
- 前端主 bundle 大于 500 kB 的构建提醒。

## Oracle 边界

Oracle 静态、单元和 aarch64 镜像启动证据见
[`phase-3b-oracle-image.md`](phase-3b-oracle-image.md)。本机没有可连接的 Oracle
11.2.0.4，真实 Oracle 11.2.0.4 连接 deferred；因此 Oracle verification 保持
`BLOCKED`，没有 Oracle Revision 或应用 binding 被误报为已发布。

## 工作区、Migration 与运行状态

- 当前代码基线：`debb504`，工作区有本 change 和用户既有未提交修改；没有执行
  reset、checkout、清理或提交。
- migration 022 文件 checksum（Phase 4 为历史 Job 清理兼容补充无外键说明后）：
  `fc587f4cf3b7317baf97bed5cc3dbc1410dbb176187ef5d0a1fb073021faa2a7`。
- 实际 PostgreSQL migration head 仍为
  `021_platform_secret_hardening.sql`，账本 checksum 为
  `f8f8aad4fb36e82faa93c0206a7ff4068beb46915ad8d83dbbe557c4ab1afff5`。
- PostgreSQL、RabbitMQ、API、Internal API、Worker/Dispatcher 等现有 Compose
  进程仍在运行；本 Gate 未重启或切换业务服务。

migration 022 尚未应用到实际 PostgreSQL，原因是实际库仍有 3 个旧
`AES-256-GCM` Secret，现有业务容器也仍使用旧镜像/配置。未经独立的旧 Secret
迁移或用户重新配置确认，不能重启服务或把数据库切换到新 Master Key。Phase 3B
Gate 证明代码、schema 和自动化门禁已经就绪，不等于现场维护切换已经执行。

## 结论

Phase 3B Gate 通过。新资源的 Secret reference、不可变 Revision、Handler Registry、
应用发布 binding、Job Execution Scope 和 Internal API 事实授权已形成闭环；未实现
Provider 和未实测 Oracle 均 fail closed。实际 migration 022、旧资源清理和服务切换
继续受 Phase 4/维护窗口的 report、prepare、digest 与再次确认约束。
