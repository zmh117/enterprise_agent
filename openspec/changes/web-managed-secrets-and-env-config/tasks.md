## 1. 数据模型与迁移

- [x] 1.1 新增 migration：`platform_secret`、`platform_secret_version`、`platform_runtime_config_definition`、`platform_runtime_config_value`、必要索引和注释。
- [x] 1.2 定义 domain model：Secret、SecretVersion、RuntimeConfigDefinition、RuntimeConfigValue、RuntimeConfigScope、ConfigValueType。
- [x] 1.3 扩展 repository：secret metadata、secret version、runtime config definition/value 的 CRUD、启停、版本和 revision/hash。
- [x] 1.4 扩展配置审计：secret create/update/rotate/disable、runtime config create/update/disable/publish 均写审计且不含明文。

## 2. Encrypted DB Secret Provider

- [x] 2.1 实现 `SecretProvider` port，支持 `resolve(ref)`、`create_secret`、`rotate_secret`、`disable_secret`。
- [x] 2.2 实现 encrypted DB provider：使用 `APP_CONFIG_MASTER_KEY` 加密/解密 secret value，保存 algorithm/key_id/nonce/ciphertext。
- [x] 2.3 扩展 `SecretResolver`：保留 `env:`，新增 `secret://platform/<code>` 解析，预留 `vault:`/`kms:` provider。
- [x] 2.4 增加脱敏工具：API、异常、审计、日志、snapshot 只能显示 masked summary/configured/version。
- [x] 2.5 单元测试：创建 secret 不落明文、轮换版本、禁用后解析失败、缺 master key 失败安全、日志/审计不含明文。

## 3. Runtime Config Registry

- [x] 3.1 建立 runtime config definition registry，覆盖当前 `.env.example` 中可迁移 key 的类型、默认值、敏感性、适用服务和 bootstrap-only 标记。
- [x] 3.2 实现 runtime config 校验：bool/int/string/url/json/secret_ref 类型校验，拒绝 secret 明文进入普通 value。
- [x] 3.3 实现 scope 合并规则：default/env fallback/global/service/project/environment/base/workshop/connector 的确定性优先级。
- [x] 3.4 实现 runtime config snapshot：返回 source、revision/hash、effective values、masked secret refs、errors。
- [x] 3.5 单元测试：类型错误拒绝、service override 覆盖 global、禁用 override 后回退、bootstrap-only key 拒绝 DB 配置。

## 4. Platform API

- [x] 4.1 新增 `/api/platform/secrets` API：create/list/detail/rotate/disable，写入权限沿用 platform_config admin 权限。
- [x] 4.2 新增 `/api/platform/runtime-config/definitions` 和 `/api/platform/runtime-config/values` API。
- [x] 4.3 新增 `/api/platform/runtime-config/snapshot` API，用于 Web 页面和调试查看 effective config。
- [x] 4.4 扩展 resource binding / connector 保存逻辑：支持引用 Web-managed `secret://platform/<code>`。
- [x] 4.5 API 测试：未授权拒绝、secret write-only、响应不含明文、runtime config CRUD、env migration list。

## 5. Runtime Settings Overlay

- [x] 5.1 设计并实现 `RuntimeConfigLoader`：读取 bootstrap env，连接 DB，加载 DB runtime config overlay，生成现有 `Settings`。
- [x] 5.2 明确 bootstrap-only env：`DATABASE_DSN`、`APP_CONFIG_MASTER_KEY`、`APP_ENV`、`APP_STARTUP_MIGRATE`、`SEED_LOCAL_CONFIG`。
- [x] 5.3 接入 api-server、agent-worker、dingtalk-stream-ingress、internal-api-platform 的配置加载路径。
- [x] 5.4 支持 DB 不可用时 env/default fallback，并在 `/api/ready` 或 `/health` 中报告 degraded/source。
- [x] 5.5 单元测试：DB overlay 生效、env fallback 生效、DB 配置错误 fail safe、ready/health 不泄漏 secret。

## 6. Claude/DeepSeek 与工具平台配置迁移

- [x] 6.1 将 `ANTHROPIC_BASE_URL`、`ANTHROPIC_MODEL`、默认模型、effort level、max turns、timeout 纳入 runtime config definition。
- [x] 6.2 支持 `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` 通过 Web-managed secret ref 配置。
- [x] 6.3 将 `INTERNAL_API_BASE_URL`、timeout、max response chars、`FEATURE_REAL_INTERNAL_TOOLS` 纳入 runtime config。
- [x] 6.4 将 Internal API Platform 的 max rows、Loki limits、Redis scan limit 纳入 runtime config。
- [x] 6.5 回归测试：RealClaudeCodeAgentClient 读取 DB-backed model/API key 配置；Internal API Platform 读取 DB-backed limits。

## 7. 钉钉、队列与默认路由配置迁移

- [x] 7.1 将 DingTalk client id/secret、stream enabled、connector id、默认投递配置、默认环境/基地/车间/服务纳入 runtime config / secret management。
- [x] 7.2 将 RabbitMQ consumer heartbeat/reconnect、Agent retry/delay 等非启动循环配置纳入 runtime config；`RABBITMQ_URL` 第一版保留 env fallback。
- [x] 7.3 更新 seeds：本地默认配置可从 DB 提供，但不写真实 secret。
- [x] 7.4 测试：DingTalk stream/delivery 使用 DB-backed 配置，缺失 secret 时失败安全。

## 8. 文档与迁移指南

- [x] 8.1 更新 `.env.example`：标记 bootstrap-only、db-configurable、secret-managed 三类配置。
- [x] 8.2 新增 `docs/web-managed-secrets-and-env-config.md`：Web 输入密钥流程、加密存储、secret ref、轮换、禁用、审计。
- [x] 8.3 新增 env 到 DB runtime config 迁移表，列出每个 key 的目标 definition、类型、作用域和是否敏感。
- [x] 8.4 更新 README/backend README：说明最小 env、DB-backed runtime config、服务重启/未来 reload 语义。

## 9. 最终校验

- [x] 9.1 运行 `.venv/bin/pytest backend/tests`。
- [x] 9.2 运行 `.venv/bin/mypy backend/app` 和 `.venv/bin/ruff check .`。
- [x] 9.3 运行 `openspec validate web-managed-secrets-and-env-config --strict`。
- [x] 9.4 运行 `openspec validate --specs`。
- [x] 9.5 核对 proposal、design、specs、tasks 与实现一致，记录未迁移的 bootstrap-only env 和后续 Vault/KMS 扩展点。
