# 最大工具调用次数上限提高至500：代码验证记录

日期：2026-09-12

## 变更范围

- 用户要求提高代码允许配置的最大工具调用次数，不是直接更改应用的当前值。
- 管理 API、业务应用领域校验、Job Execution Policy 快照和 Web 数字输入上限由 200 改为 500。
- 当前受支持的 Runtime 1.4/1.5 请求合同此前仍限制为 128；本次仅将 `ExecutionLimits.max_tool_calls.maximum` 对齐至 500，并同步生成合同文件中的 schema SHA-256。
- 协议版本、请求/事件结构、digest 算法和既有 golden 请求不变；未修改退役的 1.3 合同。
- 默认值仍为 30，已有应用及 Job 策略不修改。轮次、墙钟超时、128 个工具定义的数量上限、查询分页、沙盒容量、权限和确认要求均不扩大。

## 验证证据

### 测试先行

新增边界回归在生产代码修改前：后端 11 failed / 23 passed，前端 1 failed / 8 passed。失败分别证明原 API/Job/Web 200 次限制与 Runtime 128 次限制会阻止新上限。

### 修改后

- 以下后端套件合计 **225 passed**：
  - `test_business_application_control_plane.py`
  - `test_job_execution_policy.py`
  - `test_agent_runtime_protocol_contract.py`
  - `test_business_application_runtime_routing.py`
  - `test_python_agent_runtime.py`
  - `test_runtime_http_client.py`
- `applications.test.tsx`：**9 passed**，包含默认值 30、输入 max=500、501 为无效输入、500 为有效输入及保存请求携带 500。
- `npm run build`：TypeScript 与 Vite 生产构建通过；有 Vite 配置加载器迁移提示及 chunk 大小警告，无构建失败。
- 修改 Python 文件的 Ruff 检查通过。
- `MYPYPATH=backend` 下针对三个生产校验模块的 `mypy --follow-imports=silent` 通过。
- `docker compose config --quiet`、`git diff --check` 和 `openspec validate enforce-runtime-execution-budgets --strict` 通过。

覆盖 API、领域、Job 快照和 Runtime 对 201/500 的接受及 -1/501 的拒绝；30/50/200 等旧值仍有效。路由组件测试通过保存、发布、激活、入站和持久化 Job，验证 requested/effective 均保留 500，轮次及超时仍受 Agent 较严格值约束。实际预算守卫测试在 500 次授权后，对第 501 次返回硬中断拒绝。

以上为本地自动化/组件测试，数据库及外部依赖采用测试环境或替身，没有执行 500 次真实业务 API 调用，也没有调用真实模型。

## 部署边界

检查时本机 Compose 服务在运行。本次没有重启或重新部署它们，没有修改 Web 业务应用配置、发布版本或任何真实 Job，因此线上页面和运行容器尚不代表已使用新代码。

部署扩大上限时先更新 Python Runtime，再更新控制面、执行/入站 Worker 和 Web；相关组件全部更新后，在应用的“会话与执行策略 → 最大工具调用”按需设为 500，并保存、发布和激活。只有此后创建的新 Job 使用新值，原 50 次 Job 不变。无需数据库迁移；真实 Web 配置与新 Job 验收待部署后完成。
