# 前置 MCP 与 TypeScript Runtime 基线验收记录（2026-08-10）

## 结论

本轮已经完成可丢弃 Compose 环境的不可恢复清理、空库重建、MCP 协议级真实数据链路、主要失败关闭场景、服务重启恢复和 TypeScript Runtime 到达性验证，并修复验收期间发现的七类基线缺陷。

当前不能把两个前置 change 判定为“完整真实链路验收通过”：环境中没有真实模型 API Key，也没有钉钉 Connector/Delivery 凭据。TypeScript Job 已到达 Runtime 并产生 `execution_started`，但没有真实模型成功终态；DingTalk → Delivery 全链路没有可执行条件。任务 1.2 仍要求用户分别明确接受这两个前置 change 后才能同步/归档。

## 可复现命令与自动化证据

### 后端 MCP/Runtime 合并回归

```bash
.venv/bin/pytest -q \
  backend/tests/test_*mcp*.py \
  backend/tests/test_data_mcp_runtime.py \
  backend/tests/test_ones_mcp_runtime.py \
  backend/tests/test_agent_profile_model_connections.py \
  backend/tests/test_service_database_grants.py \
  backend/tests/test_authorization_center_retired_scope.py \
  backend/tests/test_worker_secret_and_provider_boundaries.py \
  backend/tests/test_typescript_runtime_client.py
```

结果：

```text
116 passed, 3 skipped, 1 warning
```

三个 skip 为测试自身标记的可选外部集成。warning 是 Starlette `TestClient` 对 `httpx` 的弃用提示，不是本变更回归。

### TypeScript Agent Runtime

```bash
cd agent-runtime
npm run lint
npm run typecheck
npm test
npm run build
```

结果：

```text
lint passed
typecheck passed
28 passed, 0 failed
build passed
```

`npm test` 在普通受限沙箱中只有 HTTP listener 用例因 `listen EPERM: operation not permitted 127.0.0.1` 失败；在获准的非受限环境复跑为 28/28，通过，确认是监听权限限制而非代码失败。

### OpenSpec 与格式

```bash
openspec validate simplify-platform-with-mcp --strict
openspec validate migrate-agent-runtime-to-typescript --strict
openspec validate restore-mcp-governance-console --strict
git diff --check
```

结果：三个 change 均严格校验通过，`git diff --check` 通过。

## 可丢弃环境清理与空状态重建

用户明确授权丢弃数据后执行：

```bash
docker compose down -v --remove-orphans
docker compose up -d
```

结果：

- Core PostgreSQL、RabbitMQ、MinIO volume 已删除，没有备份、导出或迁移，无法恢复；
- `enterprise_agent-internal-api-platform-1` orphan 已移除；
- 新数据库从空状态迁移到 schema head `040`；
- 新建本地管理员并用真实 Session 完成登录验证；
- 重新创建加密数据库 Secret、Database/Redis/Loki Resource、不可变 Revision/Deployment/Generation；
- 重新完成测试 ONES 本人两阶段验证，密码只在请求内使用，Provider Token 加密保存；
- 重新发布并激活 `baseline-diagnostic-agent` 与 `baseline-mcp-app`，活动 Application Publication 固定 7 个 MCP Tool。

用于验收的合成 Provider 是 ONES Mock、MySQL、Redis 和临时 Loki；没有使用生产数据。

## MCP 协议级真实链路

真实协议 Job `job_dcb0776833ce41fbbb0d01e3b0b6d247` 固定 7 个 eligible binding，并通过短期 MCP Token 调用受信 Server：

| Provider | Tool | 结果 |
| --- | --- | --- |
| ONES Mock | `ones_work_item_search` | 成功 |
| MySQL | `data_sample_rows` | 成功，2 行合成数据 |
| Redis | `redis_get` | 成功 |
| Loki | `loki_search` | 成功，1 条合成日志 |

`mcp_tool_call_provenance` 为 4/4 `SUCCEEDED`。该证据证明 Worker 生成的冻结 subject/tool/resource binding、短期 Token、MCP Server、Resource Generation、Provider 调用和 provenance 链路可用；它不等同于真实模型自动选择工具。

## 失败关闭与 LKG 证据

- ONES 403：返回脱敏拒绝错误，Credential 保持 `ACTIVE`；
- ONES 401：返回脱敏凭据错误，Credential 转为 `INVALID`；
- 过期 MCP Token：在 Provider 调用前拒绝；
- Redis Secret 正确轮换：新 Secret version 与 Generation 激活；
- Redis Secret 错误轮换：候选 Generation `FAILED`、Resource `DEGRADED`，当前/LKG 指针不变；
- 指定旧 LKG Generation：即使其 Secret version 已为 `superseded`，仍能按冻结版本成功读取；
- 恢复正确 Secret：新 Generation 激活。

失败注入期间没有输出密码、Token、密文、nonce、Master Key 或连接凭据。

## 重启恢复证据

重启 RabbitMQ、ONES MCP、Data MCP、Agent Runtime 和长驻 Worker 后：

- MCP Server、Runtime、API 均恢复 healthy；
- Agent Worker 在 broker shutdown 后重新连接并恢复 consumer；
- Attachment Worker 在 RabbitMQ 启动窗口内失败后由 `restart: unless-stopped` 自主恢复；
- Job、Attachment、Webhook、Channel 队列均恢复 consumer，验收时积压为 0。

## TypeScript Runtime 真实队列证据

活动 Application 已固定为 `typescript-v1`。真实 RabbitMQ Job 逐步暴露并修复了以下问题：

1. Application 角色授权 repository 仍查询已删除的 `rbac_role_application_scope`；
2. Worker 缺少模型 Secret “是否可用”的列级数据库读取能力；
3. Worker 镜像没有包含 `agent-runtime/contracts/v1`；
4. SDK 的 bare `allowedTools` 会自动放行 MCP Tool，遮蔽 `canUseTool` 的逐次授权与预算检查。

修复后，Job `job_739906f8b32c41eb944eaaf3ac270b9a` 进入 TypeScript Runtime，并持久化：

```text
sequence=1 event_type=execution_started
```

发现第 4 项安全问题后主动取消该 Job，没有把它计为成功终态。修复后的 Runtime 将 SDK `allowedTools` 保持为空，所有 MCP Tool 必须经过 `canUseTool`；28/28 Runtime 测试通过，新的容器日志不再出现 `CLAUDE_SDK_CAN_USE_TOOL_SHADOWED`。

随后一次 Job 因验收过程中在旧流仍运行时人工重启 Worker，使用相同 invocation 但新的短期 Token/digest 重入，Runtime 正确返回 `runtime_invocation_conflict`。该人为冲突不计入成功证据。

## 本轮修复清单

1. Worker 数据库角色补 `provider_credential` 与 `mcp_resource_generation` 读取授权；
2. Data MCP 兼容 MySQL `information_schema` 大写字典键；
3. ONES MCP Compose 继承本地明文 HTTP 显式策略；
4. MCP Secret decryptor 兼容 `EA_MASTER_KEY_V1:` Master Key 文件前缀；
5. Data MCP 按冻结 Generation 接受 `superseded` Secret version，保留 LKG 语义；
6. Application 授权路径移除已退役 Scope/Capability 查询，只接受精确 Application access；
7. Worker 使用列级 Secret 状态视图且不能读取密文，镜像补齐 Runtime V1 contract；
8. 长驻 API/Worker 增加 `restart: unless-stopped`；
9. TypeScript Runtime 取消 SDK bare MCP auto-allow，恢复逐调用 fail-closed 检查。

## 仍未通过的门禁

### `simplify-platform-with-mcp`

- 未验证真实 DingTalk `Runtime → Inbox → Outbox → RabbitMQ → Job → Worker → MCP → Delivery`；
- 未验证真实 Delivery 失败重试；
- 尚未执行 Tool Publication 取消发布后的真实运行拒绝；
- 生产不可恢复清理门禁仍禁止，除非用户另行安排维护窗口。

### `migrate-agent-runtime-to-typescript`

- `.env` 中没有 `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`，数据库只有随机占位 Credential，不能证明真实 Claude/DeepSeek 成功终态；
- 未验证真实模型自动选择 ONES/DB/Redis/Loki Tool；
- 没有 DingTalk Stream/Robot Connector 凭据，无法执行 TypeScript Runtime 到 Delivery 的完整链路；
- 尚未完成跨数据库、RabbitMQ、日志、前端产物和 Runtime ledger 的全介质敏感材料扫描；
- Python adapter/依赖仍保留，生产切换门禁未关闭。

## 前置 change 状态

两个前置 change 的 strict validation 均通过，但以上真实环境门禁仍未满足。本记录不代替用户对两个前置 change 的分别明确验收，也不授权归档、生产切换或删除 Python fallback。
