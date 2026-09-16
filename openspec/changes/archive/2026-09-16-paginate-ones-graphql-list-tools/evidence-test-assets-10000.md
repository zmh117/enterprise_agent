# 测试资产累计10000条：本地验证（2026-09-10）

## 本轮范围

用户确认四个列表提高单次调用累计上限：`ones_list_testcase_libraries`、`ones_list_testcase_modules`、`ones_list_test_plans`、`ones_query_test_cases`。工作目录为主checkout `/Users/mhz/Develop/enterprise_agent`；保留上一轮尚未提交的1000条修复，本轮叠加实施，不撤销已有修改。

- 共享 `ONES_COLLECTION_LIMITS` 驱动四个服务的收集上限与输出schema；数组、returned、cumulative_returned均允许10000。
- 其余五个GraphQL列表仍为1000，REST/详情/写入工具不变。公开输入仍不接受limit/cursor。
- bucket每页最多200，四个测试资产列表最多200次请求，支持50条短页；其余列表仍最多50次。模块直接列表仍一次获取后本地限量。
- 保留90秒、8MiB、HTTP响应大小/超时、Job总超时、沙盒文件数/容量以及不稳定分页检查。10000是条数上限，不保证忽略其他预算后必定取满；预算失败不发布部分成功文件。
- Provider摘要继续使用collection_limit区分总量与每页大小，不保留可复用after。

## 测试与静态验证

新增 `backend/tests/test_ones_testcase_collection.py` 并纳入现有test tier清单；增强现有Runtime终态清理测试覆盖10000条用例。

首轮用例收集与自动收集测试：**86 passed in 15.82s**。以下扩展回归：**463 passed in 53.73s**。

```sh
.venv/bin/pytest -q --tb=short \
  backend/tests/test_ones_auto_collection.py \
  backend/tests/test_ones_testcase_collection.py \
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

覆盖四工具及模块/计划两种用例来源、9999/10000/10001边界、50/200条页、原样游标和固定筛选/排序、直接模块列表、用例200次/其他50次请求预算、90秒/8MiB保护、旧limit拒绝，以及10000条结果只读物化、成功/失败/取消/超时清理。

本轮修改Python文件Ruff通过；三个修改生产文件定向mypy通过。Compose配置、git diff空白检查、严格OpenSpec校验通过。不宣称全仓测试或全仓mypy通过。

## 契约范围检查

相对于本轮开始时已部署的1000条版本，对所有ONES工具输入/输出schema分别计算哈希：**所有输入哈希不变；只有上述四个工具输出哈希变化**。本轮不改输入契约、不人为改变input schema hash、不修改发布/授权/Job冻结快照。

四个容器的九工具输入/输出schema和累计上限集合摘要一致：`fc5b65cb61091d697847307742a0d57c6b7d2f9f858f069d6fc0bbfb5943e320`。均确认用例查询10000、工作项查询1000。

## 本地部署与容器验证

部署前只聚合查询本地Job状态：PENDING/RUNNING/RETRY_WAIT为空，没有读取业务正文或凭据。

```sh
docker compose build ones-mcp api-server agent-worker python-agent-runtime
docker compose up -d --no-deps --no-build ones-mcp api-server agent-worker python-agent-runtime
```

| 服务 | 容器ID | 状态 |
| --- | --- | --- |
| ones-mcp | ebc0b186ba83 | running / healthy |
| api-server | 62649977ee8a | running / healthy |
| agent-worker | 7e19619d5741 | running；原配置无healthcheck |
| python-agent-runtime | 1d6dd6421c9a | running / healthy |

新ones-mcp容器使用进程内合成HTTP替身，经真实GraphQL文档/变量、解析器与服务收集执行。未启动Mock服务、未访问真实ONES。

| 验证路径 | 上游每页 | 10000条的请求数 | 总量10001时 |
| --- | --- | --- | --- |
| 用例库 | 50 | 200 | 返回10000，明确截断 |
| 用例模块 | 完整直接列表 | 1 | 返回10000，明确截断 |
| 测试计划 | 50 | 200 | 返回10000，明确截断 |
| 模块来源用例 | 50 | 200 | 返回10000，明确截断 |
| 计划来源用例 | 50 | 200 | 返回10000，明确截断 |

总量恰好10000时均不截断。另验证公开limit=10000仍拒绝，摘要collection_limit为10000且不含after。

新Runtime容器分别物化四类10000条合成结果：计划889161字节、用例库1119165字节、模块1118053字节、用例389166字节。均可Read、拒绝Write，返回摘要不包含集合正文；沙盒清理后四个结果文件均不存在。

## 边界与后续

- 本轮未连接真实ONES、未改配置、未恢复Mock、未重跑历史Job，也未提交或推送Git。ones-mcp保持启用。
- ONES与Runtime必须同步部署输出schema；旧Runtime仍可能拒绝大于1000条的结果。当前本地四个受影响服务已同步。
- 若发布仍使用更早带limit/cursor的输入契约，仍需完成上一轮正常重新发布流程；本轮只扩大输出上限，不额外引入输入哈希迁移。
- 真实ONES及选定Agent/Application的新Job端到端验收仍未完成，任务5.3与6.6保持待办。合成验证和容器健康不能替代真实验收。
