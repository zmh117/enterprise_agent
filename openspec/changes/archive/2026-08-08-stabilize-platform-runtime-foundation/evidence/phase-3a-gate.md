# Phase 3A Gate：固定 Master Key 与凭据中心后端

## 验收范围

- Master Key 只从仓库外只读文件加载，文件格式固定且无代码/Compose 明文回退。
- 平台 Secret 使用版本化 AES-256-GCM、上下文 AAD 和单 active 约束。
- 新配置只允许 `secret://platform/<code>`；`env:` 只能显式 report/import，
  `vault:`/`kms:` 明确为未实现。
- Secret API 只返回 metadata，创建、轮换、禁用和用途查询均不回显内容。
- Secret 变化触发资源快照重载；失败保留 Last Known Good 并安全降级。
- 数据库普通表、API、日志、审计、Job、tool-call 和前端状态/产物不出现
  Secret 明文、密文、nonce、key ID 或 Master Key。

## 固定自动化 Gate

命令：

```bash
.venv/bin/python scripts/runtime_foundation_gate.py verify-phase3a
```

结果：

```text
25 passed, 1 warning
PHASE_3A_AUTOMATED_GATE: PASS
```

动态 canary 测试覆盖：

- 明文不进入任何数据库行；密文、nonce 和 key ID 只存在于
  `platform_secret_version`。
- Secret metadata API、受保护 Job/tool-call API、日志和两类审计记录均无
  明文或密码学材料。
- tool-call 与通用审计在写入时递归脱敏，读取时再次防护；合法
  `secret://platform/...` 引用保留。
- 禁用被资源使用的 Secret 后重载失败，资源继续使用上一版 LKG，
  状态为 degraded，事件只保存固定安全错误。
- 前端 TypeScript 状态契约和生产构建产物均不存在 Master Key、ciphertext
  或 secret value 字段。

## 全量回归

```text
backend: 575 passed, 20 skipped, 2 warnings, 4 subtests passed
frontend: 10 files passed, 45 tests passed
ruff: All checks passed
frontend build: passed
Phase 3A fixed gate: 25 passed
```

已知非阻断告警：

- Starlette `TestClient` 的上游弃用提醒。
- 一个既有 Pytest 测试函数返回 `Settings` 的提醒。
- 前端主 bundle 大于 500 kB 的构建提醒。

## 本地 Compose 与 PostgreSQL 证据

- 仓库外固定 Master Key 文件已存在，权限为 `0400`，内容未输出。
- Migrator 实际应用结果：

```text
MIGRATION_SUCCEEDED: head=021 baselined=0 applied=021
```

- PostgreSQL 已存在：

```text
schema head: 021_platform_secret_hardening.sql
platform_secret_change_event: present
uq_platform_secret_version_active: present
```

- Compose 日志敏感 marker 扫描：`0`。
- 前端 `dist` 的 Master Key/ciphertext/secret value marker 扫描：`0`。
- 迁移后当前运行容器保持健康，没有在 schema 迁移过程中重启业务服务。

## 受控暂停：旧凭据的 Master Key 切换

实际数据库中有 3 个旧 `AES-256-GCM` Secret 和 5 个旧 `env:` 标量引用。
它们的内容、密文和引用值均未输出。当前业务容器继续使用迁移前镜像和旧
运行时配置；未把 3 个 Secret 静默改写为新 Master Key，也未删除。

切换业务容器到新的固定 Master Key 前，必须在停机窗口中单独选择：

1. 按紧急离线 runbook 将旧 Secret 与数据库备份作为一对迁移；或
2. 禁用/删除不再需要的旧 Secret，并由用户在凭据中心重新配置。

这个暂停不放宽新代码的 fail-closed 规则，也不阻塞 Phase 3A 自动化 Gate；
它防止未经确认的凭据重加密或运行中断。

## 结论

Phase 3A Gate 通过。固定 Master Key、平台 Secret、显式旧引用导入、变化通知、
LKG 和跨持久化/接口/前端脱敏边界均已实现并通过回归；旧生产凭据的实际
Master Key 切换保留在明确确认边界。
