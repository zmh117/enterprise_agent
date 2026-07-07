# Web 管理密钥与 DB Runtime Config

本项目现在把配置分成三类：

1. `bootstrap-only`：服务启动前必须存在，不能放进同一个 PostgreSQL 配置库。
2. `db-configurable`：普通运行参数，可由 Web 写入 PostgreSQL。
3. `secret-managed`：密码、API key、token，由 Web 明文提交一次，后端加密保存并只返回 `secret_ref`。

## 最小 bootstrap env

这些配置继续由 Docker Compose、K8s Secret 或部署平台提供：

```bash
DATABASE_DSN=postgresql://...
APP_CONFIG_MASTER_KEY=...
APP_ENV=local
APP_STARTUP_MIGRATE=true
SEED_LOCAL_CONFIG=false
```

`APP_CONFIG_MASTER_KEY` 用于 encrypted DB secret provider。它不能存到同一个数据库里，否则服务无法在连接数据库前解密配置。

## Web 输入密钥流程

管理端提交：

```http
POST /api/platform/secrets
x-admin-user-id: local-user
content-type: application/json

{
  "code": "deepseek_api_key",
  "value": "sk-...",
  "purpose": "claude-runtime"
}
```

后端只在请求处理内短暂接触明文，然后用 AES-GCM 加密到 `platform_secret_version`。响应只返回 `secret_ref`、版本和脱敏摘要，不返回明文。

## 轮换和禁用

```http
POST /api/platform/secrets/deepseek_api_key/rotate
POST /api/platform/secrets/deepseek_api_key/disable
```

禁用后运行时解析 `secret://platform/deepseek_api_key` 会失败，不回退到旧版本或空密码。

## Runtime Config API

```http
GET  /api/platform/runtime-config/definitions
POST /api/platform/runtime-config/values
GET  /api/platform/runtime-config/snapshot?service_name=agent-worker
GET  /api/platform/runtime-config/env-migration
```

保存普通运行参数：

```json
{
  "key": "AGENT_MAX_TURNS",
  "scope_type": "service",
  "scope_code": "agent-worker",
  "service_name": "agent-worker",
  "value": 12
}
```

保存敏感运行参数：

```json
{
  "key": "ANTHROPIC_API_KEY",
  "secret_ref": "secret://platform/deepseek_api_key",
  "service_name": "agent-worker"
}
```

## 生效语义

第一版是启动时读取 DB overlay：

```text
代码默认值 < env fallback < DB global < DB service < DB business scope
```

修改配置后，重启对应服务生效。后续 Web 平台可以在此基础上增加发布、reload 和拖拽编排配置。

## 安全边界

- API 响应、审计、日志、Agent prompt、tool call 摘要不得包含 secret 明文。
- 普通 `config_json` 和 runtime `value_json` 拒绝疑似 password/token/api key 明文。
- `vault:` / `kms:` provider 已保留扩展点，第一版默认 provider 是 `encrypted_db`。
- 本 change 不增加改代码、删 Redis、执行 SQL 更新、重启服务等写操作能力。
