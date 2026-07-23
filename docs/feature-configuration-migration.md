# 功能开关收敛与迁移

## 当前部署入口

普通部署只需要决定四个顶层开关：

| 开关 | 默认值 | 边界 |
|---|---:|---|
| `FEATURE_WEB_ADMIN` | `false` | 管理 Web、统一身份、Session、RBAC、业务应用控制面 |
| `FEATURE_PUBLISHED_AGENT_RUNTIME` | `false` | 是否允许已发布 Agent Runtime 执行任务 |
| `FEATURE_REAL_CLAUDE` | `false` | 是否允许调用真实模型服务 |
| `FEATURE_REAL_INTERNAL_TOOLS` | `false` | 是否允许调用真实内部 API 工具 |

开启 `FEATURE_WEB_ADMIN` 不会联动后三项。三个数据面开关只能由部署环境开启，数据库运行配置不能越过关闭的部署闸门。

`DATABASE_DSN`、`RABBITMQ_URL`、`APP_CONFIG_MASTER_KEY`、`APP_ENV` 和启动迁移参数仍是 bootstrap 配置，不属于功能开关。

## 代码读取边界

| 原读取点 | 新事实源 |
|---|---|
| `shared/config.py` 中各自读取环境变量 | `EffectiveFeatureConfiguration` 统一解析 |
| Bootstrap 选择真实模型/工具 | deployment safety gate |
| 统一身份、管理 Web、业务应用控制面 | `FEATURE_WEB_ADMIN` 派生值 |
| `permission_shadow_mode` | `PERMISSION_SHADOW_MODE` runtime policy |
| Webhook 全局启停 | Connector 状态与已发布 Trigger |
| 连续会话、附件全局启停 | 已发布 Business Application `session_policy` |
| API、Worker 各自解释默认值 | 同一个有效配置解析器和诊断快照 |

业务代码不得直接读取旧 `FEATURE_*` 环境变量。兼容读取只存在于 `app.shared.feature_configuration`。

## 旧配置映射

兼容逻辑计划在 `0.3.0` 删除。

| 旧键 | 迁移目标 |
|---|---|
| `FEATURE_UNIFIED_IDENTITY` | `FEATURE_WEB_ADMIN` |
| `FEATURE_BUSINESS_APPLICATION_CONTROL_PLANE` | `FEATURE_WEB_ADMIN` |
| `FEATURE_WEBHOOK_TRIGGERS` | 启用 Connector 并发布 Trigger Binding |
| `FEATURE_CONTINUOUS_CONVERSATION` | Business Application `session_policy.continuous_conversation_enabled` |
| `FEATURE_MESSAGE_ATTACHMENTS` | Business Application `session_policy.attachments_enabled` |
| `FEATURE_TEST_IDENTITY_HEADERS` | 仅测试进程的内部配置；生产禁止 |
| `FEATURE_PERMISSION_SHADOW_MODE` | `PERMISSION_SHADOW_MODE` runtime config |

只配置旧键时，兼容适配器会输出去敏弃用告警。新旧值语义冲突时服务拒绝启动，不会静默选择某一方。

## 上线前检查

只读检查不会写数据库、发布应用或改变路由：

```bash
PYTHONPATH=backend .venv/bin/python -m app.cli.audit_feature_configuration
```

输出中的：

- `legacy`：当前仍在使用的旧键和迁移目标；
- `policy_draft`：建议写入领域草稿的值；
- `write_performed=false`；
- `publication_performed=false`。

先清理冲突，再通过管理端保存并发布相应 Business Application、Connector 或 Trigger。迁移命令本身不发布任何对象。

## 迁移顺序

1. 保持三个数据面开关当前值不变。
2. 运行只读检查，消除新旧管理开关冲突。
3. 用 `FEATURE_WEB_ADMIN` 替换统一身份和业务应用控制面旧键。
4. 将权限 shadow mode 写入受审计 runtime config。
5. 将会话和附件设置保存到 Business Application 草稿，验证后显式发布。
6. 确认 Webhook Connector 已启用、方向正确且 Trigger 已发布。
7. 删除旧环境变量并重新执行检查。
8. 分别验证管理面、已发布 Runtime、真实模型和真实工具。

## 回滚

回滚应用版本时可恢复旧环境变量。新领域策略使用独立 revision，不删除历史发布版本；未发布草稿不会影响运行链路。回滚过程中不得把三个数据面闸门从 `false` 改成 `true`。

如果运行配置存储不可用，服务使用最后一个已验证快照或安全默认值，并标记 degraded；它不会因此开启真实模型、真实工具或已发布 Runtime。
