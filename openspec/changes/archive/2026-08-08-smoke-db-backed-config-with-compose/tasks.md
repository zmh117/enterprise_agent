## 1. Smoke 流程文档

- [x] 1.1 新增 `docs/db-backed-config-compose-smoke.md`，记录从 Docker Compose 启动到 Agent job 完成的中文 curl 流程。
- [x] 1.2 文档覆盖基础服务启动：`postgres`、`rabbitmq`、`api-server`、`agent-worker`，并说明必要 profile/env。
- [x] 1.3 文档覆盖 `/api/platform/secrets` 创建 `deepseek_api_key`，并标注响应不得包含明文 key。
- [x] 1.4 文档覆盖 `/api/platform/runtime-config/values` 写入 `ANTHROPIC_BASE_URL`、`ANTHROPIC_MODEL`、`ANTHROPIC_API_KEY`、`AGENT_MAX_TURNS`。
- [x] 1.5 文档覆盖重启 `api-server` / `agent-worker` 后查询 `/api/ready`，验证 `runtime_config.source`、revision、hash 和 degraded 状态。
- [x] 1.6 文档覆盖 `POST /api/agent/jobs`、轮询 job、查询 steps、查询 tool-calls 的命令和预期结果。

## 2. 可选自动化脚本

- [x] 2.1 新增 `scripts/smoke_db_backed_config.sh` 或等价 Make target，按文档顺序执行核心 curl。
- [x] 2.2 脚本支持默认 stub Claude smoke，不要求真实 DeepSeek API key。
- [x] 2.3 脚本支持可选真实 DeepSeek smoke，通过 `DEEPSEEK_API_KEY` 环境变量读取，不打印明文。
- [x] 2.4 脚本对关键字段做断言：`secret_ref`、`runtime_config.source`、`job_id`、job 终态、steps/tool-calls 可查询。
- [x] 2.5 脚本在失败时输出下一步排查命令，包括 `docker compose ps`、api-server logs、agent-worker logs、job detail。

## 3. Compose 与运行时检查

- [x] 3.1 核对 Docker Compose 中 api-server/agent-worker 是否具备 DB-backed secret 所需的 `APP_CONFIG_MASTER_KEY` bootstrap env。
- [x] 3.2 如缺失，补充 compose env 示例或 `.env.example` 说明，确保 smoke 能真实解密 `secret://platform/<code>`。
- [x] 3.3 验证写入 runtime config 后必须重启服务，文档明确第一版不做热更新。
- [x] 3.4 验证默认 smoke 不依赖真实 internal-api-platform 上游，不引入 Loki/DB/Redis 外部不稳定因素。

## 4. 安全与失败排查

- [x] 4.1 在文档和脚本中加入明文泄漏检查，确认响应、snapshot、steps、tool-calls 不包含 `DEEPSEEK_API_KEY`。
- [x] 4.2 文档化 secret 缺失、secret 禁用、runtime config 类型错误、DB 不可用、RabbitMQ 未消费、worker 未启动时的排查顺序。
- [x] 4.3 文档化真实 DeepSeek 可选 smoke 的数据出境风险，只允许 synthetic 或已脱敏问题。
- [x] 4.4 文档化 `FEATURE_REAL_CLAUDE=true` 且 secret 无法解析时应失败为安全配置错误。

## 5. 验证

- [x] 5.1 运行 `docker compose config --quiet`。
- [x] 5.2 按 `docs/db-backed-config-compose-smoke.md` 执行默认 smoke，并记录一次成功输出摘要。
- [x] 5.3 运行 `.venv/bin/pytest backend/tests -q`。
- [x] 5.4 运行 `.venv/bin/ruff check .` 和 `.venv/bin/mypy backend/app`。
- [x] 5.5 运行 `openspec validate smoke-db-backed-config-with-compose --strict`。
- [x] 5.6 运行 `openspec validate --specs`。
