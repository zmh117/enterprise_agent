## Why

`web-managed-secrets-and-env-config` 已经通过单元测试验证，但还缺一个真实 Docker Compose 闭环：真实 PostgreSQL migration、真实 api-server、真实 agent-worker、真实 DB-backed runtime config overlay、真实 encrypted DB secret 解析，以及从 `POST /api/platform/secrets` 到 `POST /api/agent/jobs` 的完整 curl 过程。

这一步要把“代码上支持”推进到“本地可重复验证”，否则后续做 Web 管理页面时，很容易把后端配置链路、容器 env、服务重启语义和 Agent job 执行问题混在一起排查。

## What Changes

- 增加一个 Docker Compose smoke 验证流程，覆盖 Web-managed secret 到 DB-backed runtime config，再到 Agent job 的完整路径。
- 增加 curl 文档，记录创建 secret、写 runtime config、重启服务、检查 `/api/ready`、提交 Agent job、轮询 job/steps/tool-calls 的命令和预期结果。
- 增加可选脚本或 Make target，用于降低手工 curl 出错率，但保持每一步命令可读、可复制。
- 增加测试/检查点，确认 smoke 流程不会泄漏 DeepSeek API key 或 secret 明文。
- 明确 smoke 默认使用 synthetic 问题和 fake/mock/internal tool 模式；如果启用真实 DeepSeek，必须显式提醒外部模型数据出境风险。

## Capabilities

### New Capabilities

- `db-backed-config-compose-smoke`: Docker Compose 下验证 DB-backed runtime config、Web-managed secret、api-server、agent-worker 和 Agent job 的完整 smoke 流程。

### Modified Capabilities

- `platform-secret-management`: 补充通过 compose/curl 验证 secret create/rotate/disable 和明文不泄漏的要求。
- `platform-runtime-config`: 补充通过 compose/curl 验证 DB overlay 生效、ready/source/degraded 状态和服务重启语义的要求。
- `claude-agent-runtime-integration`: 补充 DeepSeek/Anthropic key 通过 `secret://platform/<code>` 注入 runtime 的 smoke 验证要求。
- `agent-job-debug-api`: 补充 smoke 过程必须通过 job/steps/tool-calls 查询证明 Agent job 已执行完成。

## Impact

- 文档：新增 `docs/db-backed-config-compose-smoke.md`，记录中文 curl 验证流程和排错点。
- 脚本/Make：可新增 `scripts/smoke_db_backed_config.sh` 或 Make target，封装但不隐藏核心 curl 命令。
- Docker Compose：如需要，补充 compose profile/env 示例，确保 api-server 与 agent-worker 能读取同一个 PostgreSQL runtime config。
- API：不新增业务 API；只使用现有 `/api/platform/secrets`、`/api/platform/runtime-config/*`、`/api/ready`、`/api/agent/jobs*`。
- 安全：文档和脚本不得打印真实 API key；日志/响应检查必须验证明文没有出现在返回体和审计摘要里。
