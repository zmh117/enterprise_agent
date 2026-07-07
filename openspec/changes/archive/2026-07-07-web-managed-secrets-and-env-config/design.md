## Context

当前配置分三类：

```text
1. bootstrap env
   DATABASE_DSN、RABBITMQ_URL、APP_ENV、APP_CONFIG_MASTER_KEY 等启动必需配置

2. runtime env
   FEATURE_REAL_CLAUDE、ANTHROPIC_BASE_URL、ANTHROPIC_MODEL、LOKI_MAX_LINES、
   AGENT_MAX_TURNS、DINGTALK_DEFAULT_*、INTERNAL_API_* 等运行参数

3. sensitive env / secret refs
   ANTHROPIC_API_KEY、DINGTALK_CLIENT_SECRET、DB_PASSWORD、REDIS_PASSWORD、LOKI_TOKEN
```

现有 `secret://...` 是“引用”，不是密钥存储。它能防止 topology、snapshot、审计和 prompt 泄露明文，但 Web 页面直接输入密码后，系统还需要一个 Secret Provider 把明文变成可解析的 `secret_ref`。

目标结构：

```text
Web 管理端
  │ 输入 secret value / runtime setting
  ▼
api-server / platform_config
  │ 校验、加密、审计
  ▼
PostgreSQL
  ├─ platform_secret_value / platform_secret_version   (密文)
  ├─ platform_secret_reference                         (引用元数据)
  └─ platform_runtime_config                           (非敏感运行配置 + secret refs)
  ▼
Runtime Config Loader
  │ 构造 Settings overlay
  ▼
api-server / agent-worker / internal-api-platform / ingress worker
```

## Goals / Non-Goals

**Goals:**

- 支持 Web 页面直接输入密码、API Key、token，并安全保存为可解析 `secret_ref`。
- 支持将当前 `.env` 中的大部分业务运行配置迁移到 PostgreSQL 并由 Web 配置。
- 保留最小 bootstrap env，避免服务在无法连接数据库或无法解密时完全不可启动。
- 支持配置作用域：global、service、environment/base/workshop、connector、project。
- 支持配置变更审计、版本、启停、脱敏展示和运行时快照。
- 继续保持 Agent MVP 只读诊断边界。

**Non-Goals:**

- 不在第一版实现完整 Vault/KMS 集成；但接口和 provider 字段必须预留。
- 不要求所有配置热更新；第一版允许服务启动时读取 DB-backed config，部分服务可后续增加 reload。
- 不把 PostgreSQL 数据库连接串和主加密密钥本身迁入同一个数据库。
- 不做 Web 前端页面，只做后端 API、领域模型和文档契约。

## Decisions

### 1. `secret_ref` 继续作为唯一对外引用，Web 输入值不直接进入配置表

Web 提交：

```json
{
  "code": "deepseek_api_key",
  "value": "sk-...",
  "purpose": "claude-runtime"
}
```

后端返回：

```json
{
  "secret_ref": "secret://platform/deepseek_api_key"
}
```

配置表只引用：

```json
{
  "anthropic_api_key_ref": "secret://platform/deepseek_api_key"
}
```

这样 resource binding、connector、runtime settings、审计和 snapshot 都只接触 ref，不接触明文。

### 2. 第一版用 PostgreSQL 加密密钥表作为 Secret Provider

第一版 provider：

```text
provider = encrypted_db
ref      = secret://platform/<code>
```

密文表保存：

```text
secret_code
version
ciphertext
nonce
key_id
algorithm
status
created_by
created_at
```

主密钥来自 bootstrap env：

```text
APP_CONFIG_MASTER_KEY
```

替代方案是直接把明文存 PostgreSQL。拒绝，因为任何 DB dump、SQL 查询、审计误写都会泄露凭据。另一个替代是第一版直接接 Vault/KMS。这个更安全，但会拖慢本地闭环；所以接口预留，默认实现先做 encrypted DB。

### 3. 最小 bootstrap env 保留，其它配置逐步 DB-backed

不能把所有 env 都放进 DB。至少这些必须留在环境或部署平台：

```text
DATABASE_DSN
APP_CONFIG_MASTER_KEY
APP_ENV
APP_STARTUP_MIGRATE
SEED_LOCAL_CONFIG
```

原因很简单：服务必须先连接数据库并解密配置，才能读取 DB 配置。

其它配置可以进 DB：

```text
FEATURE_REAL_CLAUDE
FEATURE_REAL_INTERNAL_TOOLS
INTERNAL_API_BASE_URL
INTERNAL_API_TIMEOUT_SECONDS
ANTHROPIC_BASE_URL
ANTHROPIC_MODEL
AGENT_MAX_TURNS
DINGTALK_DEFAULT_*
LOKI_MAX_*
RABBITMQ_CONSUMER_*
```

### 4. Runtime config 使用 typed key + scope，而不是把整份 `.env` 文本塞数据库

推荐表意：

```text
platform_runtime_config
  key
  value_type
  value_json
  secret_ref
  scope_type
  scope_id
  service_name
  status
  revision
```

这样 Web 可以校验类型、展示说明、按服务/环境筛选，也方便后续灰度和发布。

### 5. 配置优先级明确化

读取顺序：

```text
代码默认值
  < bootstrap env
  < DB runtime config global
  < DB runtime config service
  < DB runtime config environment/base/workshop/project/connector scope
```

敏感配置只读取 `secret_ref`，由 SecretResolver 解析。

### 6. 修改配置默认需要重启服务，热更新后续再做

第一版保持简单：

```text
Web 修改配置
  ↓
写 DB + audit
  ↓
服务重启或未来 reload
  ↓
runtime 读取新 snapshot
```

后续可以加：

```text
GET /api/platform/runtime-config/snapshot
POST /api/platform/runtime-config/reload
配置发布事件 -> worker reload
```

## Risks / Trade-offs

- [Risk] 主加密密钥丢失会导致 encrypted DB secret 无法解密。  
  Mitigation: 文档要求备份 `APP_CONFIG_MASTER_KEY`，并记录 `key_id` 支持未来轮换。

- [Risk] Web/API/日志不小心打印明文。  
  Mitigation: 明文只允许出现在 request DTO 到 encryptor 的短路径；日志、异常、审计统一脱敏。

- [Risk] 配置迁入 DB 后服务启动依赖数据库。  
  Mitigation: 保留 bootstrap env 和 env fallback；DB 不可用时服务可用默认/旧 env 启动，并报告 degraded。

- [Risk] 运行时配置类型散乱。  
  Mitigation: 引入 runtime config definition registry，声明 key、类型、默认值、是否敏感、适用服务、是否可热更新。

- [Risk] 把 RabbitMQ URL 等基础设施配置放 DB 会出现循环依赖。  
  Mitigation: 第一版不迁移 `DATABASE_DSN`，`RABBITMQ_URL` 是否迁移取决于服务启动顺序；消费者启动必需时仍保留 env fallback。

## Migration Plan

1. 新增 encrypted DB Secret Provider 表和 resolver。
2. 新增 runtime config definition 和 runtime config value 表。
3. 在 API 层增加 secret create/update/rotate/disable 和 runtime config CRUD。
4. 扩展 settings loader：先读 bootstrap env，再叠加 DB runtime config。
5. 把 `.env.example` 中可迁移项分组标记：bootstrap-only、db-configurable、secret-managed。
6. 文档化 Web 配置流程、密钥轮换流程、服务重启生效语义。
7. 回滚方式：禁用 DB runtime config overlay，继续使用 env；secret ref 可保留但不参与 runtime。

## Open Questions

- 第一版 encrypted DB 使用 `cryptography.fernet` 还是 AES-GCM？建议 AES-GCM，并把 key id/algorithm 写入版本表。
- `RABBITMQ_URL` 是否第一阶段进入 DB？如果 worker 必须在 DB overlay 前启动，建议暂时 bootstrap env 保留。
- Web 页面是否需要“查看 secret 是否已配置”的状态，不提供明文回显？建议只显示 configured/version/updated_at。
