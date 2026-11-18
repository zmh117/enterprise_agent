# 本地验证记录（2026-09-20）

## 范围与结果

- 仅将 `ones_query_work_items` 的累计收集和输出校验上限从1000改为10000，最多200次分页请求；单页仍最多200。
- `ones_work_item_search`、自定义选项查询、项目搜索、类型列表仍为1000；四类测试资产仍为10000。
- 保留90秒、8MiB、HTTP/Job/Sandbox预算、精确内部游标、异常失败关闭、只读文件及终态清理。
- 本轮未连接真实ONES或用户其他环境，未读取业务数据或凭据，未修改env、Compose、数据库、发布快照或历史Job，未重启服务、提交或推送代码。

## 分页与Runtime回归

修改实现前，新测试对4715条合成数据的普通/迭代查询、50/200条页四种组合均失败：实际只收集1000条。

修改后：

```text
.venv/bin/pytest -q --tb=short backend/tests/test_ones_auto_collection.py backend/tests/test_ones_testcase_collection.py
124 passed in 35.04s
```

- 普通及迭代查询覆盖256、1000、1001、4715、9999、10000、10001条，两种Provider页大小50/200。
- 4715条全部返回，分别需要95/24页；10000条全部返回，分别需要200/50页。
- 10001条只返回10000条，`truncated` 与 `pagination_limit_reached` 均为true；10000条终页时二者均为false。
- 每页大小最多200，筛选排序保持一致，下一请求原样使用上一页游标，模型不接收续页游标。
- 每页仅1条时达到200次请求后有界失败；默认收集器仍为50次。
- 10000条工作项结果经共享schema校验后写入只读Sandbox文件，模型仅获得元信息与路径。
- Job成功、失败、取消、超时均清理临时文件；调整测试标记写法后再次运行Runtime相关20项，全部通过。

## 周边回归与既有失败

扩展运行以下17个测试文件，结果为 **479 passed, 11 failed in 48.82s**：

```text
test_ones_mcp_runtime.py test_ones_basic_query_interfaces.py
test_identity_aware_ones_mcp_architecture.py test_python_agent_runtime.py
test_ones_graphql_operations.py test_ones_response_compatibility.py
test_ones_rest_operations.py test_mcp_audit_coordinator.py
test_agent_job_debug_queries.py test_agent_runtime_and_worker.py
test_python_file_mcp_runtime_bridge.py test_tool_mcp.py test_principal_jwt.py
test_python_runtime_internal_architecture.py test_ones_task_update.py
test_ones_bug_create.py test_tool_query_results.py
```

11项失败全部来自未修改的 `test_agent_job_debug_queries.py`，在创建测试Job冻结发布快照时抛出 `mcp_tool_schema_drift` / `Publication MCP Tool server or schema does not match the code manifest`。

基线复核：通过内存import loader将本轮修改的三个生产模块加载为HEAD（`df7f7ff`）版本，再运行该文件；其余相关生产及该测试文件未修改。结果同样为 **11 failed, 1 passed in 3.72s**，失败位置和信息相同。本轮不修复该既有问题，不将扩展回归记为全绿。

## 合同与静态检查

- 对比全部19个工具，所有input schema hash不变；只有 `ones_query_work_items` 的output schema发生变化。
- 该工具input hash：`13fed3cbc1b6f6476486865000a63cf8d48e6dfb18285c7a8906610a7f55b3d0`。
- 新output hash：`163d0586a334fd75ae9dca2e3baafba96e1b51943ddf09ac01d55c40049c471a`。
- 三个生产文件mypy通过；三个生产及两个测试文件Ruff通过。
- `docker compose config --quiet`、`openspec validate raise-ones-work-item-query-limit --strict`、`git diff --check`通过。

## 运行与交付边界

只读检查本地 `ones-mcp`、`api-server`、`agent-worker`、`python-agent-runtime`：均在运行；有健康检查的三个服务均healthy。四者容器内收集/输出上限仍是1000，输入hash与上述一致。

**代码已改，运行实例尚未部署。** 本次保留现有服务运行状态。后续需将ONES、API、Worker、Runtime相关消费者更新为同版本，防止服务返回10000却被旧Runtime的1000条schema拒绝；其他环境也需单独更新并用新Job验证。本次仅调整输出上限，不因本次变更额外要求修改发布输入快照；仍带旧公开limit/cursor的更早发布版本继续遵循此前迁移要求。

合成测试、静态检查和容器健康均不是实际ONES数据完整性或其他环境部署成功的证据。
