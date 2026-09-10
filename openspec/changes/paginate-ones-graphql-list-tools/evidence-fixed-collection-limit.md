# 固定累计1000条：本地验证（2026-09-10）

## 范围与结论

- 工作目录为主 checkout `/Users/mhz/Develop/enterprise_agent`，分支 `one_runtime`，验证基线为 `c139f97` 加本次未提交修改。
- 九个 GraphQL 列表移除公开 MCP 入参 `limit`。模型只提交业务筛选，累计上限由服务端固定为1000；任意旧 `limit`（包括50和1000）与 `cursor` 在输入校验阶段拒绝。
- bucket 请求仍使用内部 `variables.pagination.limit`，每次最多200；根据 `hasNextPage` 和原样传递的 `endCursor/after` 继续，不以短页或近似 `totalCount` 停止。
- 工作项类型与用例模块使用上游完整直接列表，一次读取后本地限量，不伪造游标。对应工具描述已明确这一例外。
- 保留重复条目/游标、空异常页、50页、90秒、8MiB等既有保护；失败不发布部分成功集合。REST、详情和写入契约未改变。
- Provider 请求摘要用 `collection_limit=1000` 区分累计上限与各页 `pagination.limit`；摘要不保留可复用的 `after`。
- Job 只读结果文件、终态清理和安全错误时间线沿用既有实现，本轮相关回归通过。

## 自动化验证

以下命令结果为 **421 passed in 43.24s**：

```sh
.venv/bin/pytest -q --tb=short \
  backend/tests/test_ones_auto_collection.py \
  backend/tests/test_ones_mcp_runtime.py \
  backend/tests/test_ones_basic_query_interfaces.py \
  backend/tests/test_identity_aware_ones_mcp_architecture.py \
  backend/tests/test_python_agent_runtime.py \
  backend/tests/test_ones_graphql_operations.py \
  backend/tests/test_ones_response_compatibility.py \
  backend/tests/test_ones_rest_operations.py \
  backend/tests/test_mcp_audit_coordinator.py \
  backend/tests/test_agent_job_debug_queries.py \
  backend/tests/test_agent_runtime_and_worker.py \
  backend/tests/test_python_file_mcp_runtime_bridge.py \
  backend/tests/test_tool_mcp.py \
  backend/tests/test_principal_jwt.py \
  backend/tests/test_python_runtime_internal_architecture.py \
  backend/tests/test_ones_task_update.py \
  backend/tests/test_ones_bug_create.py
```

补充纠正两项直接列表的说明后，重跑 `test_ones_auto_collection.py` 和 `test_ones_task_update.py`：**113 passed in 8.64s**。

覆盖九个公开输入/服务校验器、256/1000/1001条、每页50条短页、内部残留limit不能降低累计上限、旧冻结契约拒绝、权限/身份/审计、沙盒成功/失败/取消/超时清理。契约哈希快照仅更新九个 GraphQL 列表，八个其他既有只读工具的哈希保持一致。

- 修改文件 Ruff：通过。
- 五个修改生产 Python 文件定向 mypy：通过；不宣称全仓 mypy 通过。
- `docker compose config --quiet`、`git diff --check`、`openspec validate paginate-ones-graphql-list-tools --strict`：通过。

## 本地部署与容器内检查

部署前仅聚合检查本地 `agent_job` 状态，PENDING/RUNNING/RETRY_WAIT结果为空；未读取业务正文或凭据。

```sh
docker compose build ones-mcp api-server agent-worker python-agent-runtime
docker compose up -d --no-deps --no-build ones-mcp api-server agent-worker python-agent-runtime
```

| 服务 | 新容器ID | 状态 |
| --- | --- | --- |
| ones-mcp | 3097c2c05987 | running / healthy |
| api-server | 723382584b41 | running / healthy |
| agent-worker | 4ccc22d9dddb | running；原配置无healthcheck |
| python-agent-runtime | a1e3975aaa61 | running / healthy |

四个容器均确认九个公开输入没有 `limit/cursor`，且 `additionalProperties=false`；九工具输入哈希集合摘要一致：`3b1d3f62baa24201da31a3d8bb8b0048e6a682af26172f533069545590ab65d0`。`ones_query_work_items` 新输入哈希为 `13fed3cbc1b6f6476486865000a63cf8d48e6dfb18285c7a8906610a7f55b3d0`。

在新 ones-mcp 容器中使用进程内合成 HTTP 替身，经真实 `OnesGraphqlClient`、`OnesWorkItemQueryService.call_provider`、响应规范化与收集器验证；每次最多返回50条，且包含空迭代关联。没有网络请求到 ONES，也未启动 Mock 服务。

| 合成总量 | 实际返回 | 请求次数 | truncated | pagination_limit_reached |
| --- | --- | --- | --- | --- |
| 256 | 256 | 6 | false | false |
| 1000 | 1000 | 20 | false | false |
| 1001 | 1000 | 20 | true | true |

同时验证过滤/排序跨页不变、游标逐页一致、内部页大小不超过200、输出通过共享 schema、摘要不含after。传入旧 `limit=50` 返回 `ones_tool_input_invalid`。

## 仍待真实验收

- 依照用户要求，未连接真实 ONES、未重跑历史 Job、未改环境示例/连接配置、未恢复 Mock。ones-mcp保持启用。
- 共享输入 schema 已改变。旧 Agent/Application publication及Job冻结快照不会静默升级；必须选择目标Agent重新发布，更新并发布Application、启用相应部署，再创建新Job进行真实验收。
- 本次未修改发布/授权/Job快照，未执行上述真实验收。任务5.3与6.6继续待办，容器健康和合成成功不能替代它们。
- 本次没有Git提交或推送，也没有规范同步/归档。
