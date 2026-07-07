## Why

后续 Web 配置平台需要让管理员直接输入数据库密码、DeepSeek/Anthropic Key、钉钉凭据、Loki/Redis token 等敏感值，并且希望当前散落在 `.env` / YAML 中的运行配置逐步落到 PostgreSQL。现有 `secret://...` 只解决“引用不泄漏”，还没有解决“Web 输入密钥后安全保存、轮换、审计、运行时解析”的完整闭环。

## What Changes

- 新增平台密钥管理能力：Web API 可以接收明文 secret value，但后端只短暂使用，必须加密后保存或转存到 Secret Provider，并返回稳定 `secret_ref`。
- 新增 DB-backed runtime config 能力：把当前 env 中的功能开关、模型配置、队列参数、钉钉默认配置、Internal API Platform 参数、Loki 限制、Agent 执行限制等落到 PostgreSQL，供后续 Web 配置。
- 明确配置优先级：启动必需 bootstrap env 保留最小集合；其余运行配置优先从 DB 读取，DB 缺失时可回退 env 默认值。
- 扩展 SecretResolver：支持 `env:`、`secret://`、未来 `vault:`/`kms:`，第一版可用本地加密 DB provider 实现 Web 输入密钥。
- 增加配置审计和敏感字段脱敏：创建、更新、轮换、禁用、读取摘要都必须审计，但不得记录明文密钥。
- 保持只读诊断边界：本 change 只管理配置和密钥，不增加 Agent 写库、删 Redis、重启服务、改代码能力。

## Capabilities

### New Capabilities

- `platform-secret-management`: Web 输入密钥、加密存储、secret ref 生成、解析、轮换、禁用、审计和脱敏。
- `platform-runtime-config`: PostgreSQL-backed runtime settings，用于替代当前大部分 env 配置，并提供配置快照、优先级和服务级加载规则。

### Modified Capabilities

- `platform-config-api`: 增加 secret value 写入接口、runtime config 管理接口、敏感响应脱敏和配置验证。
- `platform-config-registry`: 扩展配置 registry，使 resource binding、connector、runtime settings 能引用 Web 管理的 secret refs。
- `readonly-tool-platform`: Internal API Platform 使用统一 SecretResolver 和 DB-backed runtime config 解析资源连接参数。
- `claude-agent-runtime-integration`: Claude/DeepSeek runtime 的 base URL、model、API key、effort、turn limit 等支持从 DB-backed runtime config 和 secret refs 读取。

## Impact

- 数据库：新增或扩展平台密钥、密钥版本、runtime config、配置发布/审计相关表；不拆库。
- API：新增 `/api/platform/secrets/*` 和 `/api/platform/runtime-config/*` 管理接口。
- Runtime：`load_settings()` 或 runtime bootstrap 需要支持 DB-backed overlay；服务启动时读取配置快照。
- 安全：需要应用级加密 key 或外部 KMS/Vault 接入点；明文 secret 不得写入日志、审计、prompt、tool call、API 响应。
- 文档：更新 Web 配置平台、密钥策略、env 迁移路径和本地开发 bootstrap 说明。
