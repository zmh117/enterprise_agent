# Loki 资源范围内动态标签修复验证

日期：2026-09-15。记录当前工作区验证结果；未提交、未部署、未调用真实 Loki，未修改任何现有资源配置或业务数据库。

## 已实现

- 共享 `app.shared.loki_contract`：标签名 1–128 位合法标识符、精确值 1–256 位、最多 8 个追加条件；管理端既有最多 8 个固定条件保持不变。固定范围和追加条件合并后 HTTP 层允许最多 16 个条件。
- MCP Schema、入口、领域执行、管理端标签格式和发现结果共用校验；不再硬编码 app/logtype 等名称集合。
- 四类 Loki 工具服务端注入固定条件；任何固定 key 重复提交均返回 `loki_fixed_label_conflict`。固定范围缺失时失败关闭，标签枚举不再回退全局 labels/values 端点。
- 空追加 selector 只使用资源固定范围；合法但不存在的标签返回空候选，不伪装无权限。
- 参数错误使用 `loki_label_invalid`、`loki_selector_invalid`、`loki_selector_value_invalid` 等稳定码及中文说明；错误经过真实 JobToolService 审计链路保留。
- 更新 query_loki、diagnose_loki_probe、diagnose_loki_label_values 三个工具的 seed Schema 哈希。标签发现仅描述变化，Schema 哈希未变化。未改 Runtime 协议或迁移编号。

## 本地验证

以下命令结果为 **246 passed, 1 skipped**：

```sh
env -u GOVERNED_RESOURCE_POSTGRES_DSN .venv/bin/pytest \
  backend/tests/test_loki_resource_scoped_labels.py \
  backend/tests/test_resource_scope_bindings.py \
  backend/tests/test_tool_mcp.py \
  backend/tests/test_mcp_tool_runtime.py \
  backend/tests/test_governed_tool_resource_lifecycle.py \
  backend/tests/test_governed_tool_resource_schema.py \
  backend/tests/test_governed_tool_resource_api.py \
  backend/tests/test_tool_pagination.py \
  backend/tests/test_user_visible_message_localization.py \
  backend/tests/test_test_suite_governance.py \
  backend/tests/test_mcp_audit_coordinator.py \
  backend/tests/test_runtime_http_client.py \
  backend/tests/test_agent_profile_creation.py \
  backend/tests/test_retired_legacy_platform_contract.py -q --tb=short -rs
```

跳过项：需要 `GOVERNED_RESOURCE_POSTGRES_DSN` 的 PostgreSQL 资源列表集成测试。其余测试使用隔离测试库、合成数据及模拟 HTTP，没有连接真实 Provider。

完整链路覆盖 Job 冻结工具及授权 → 测试库已发布 Resource Revision → 实际 DirectResourceResolver/Executor → HttpLokiClient 模拟 HTTP → 统一审计。请求断言包含固定 customer/workshop，非法标签、固定范围冲突、空范围和超限均在 HTTP 前失败。回归同时覆盖标签名/取值注入、精确字符串转义、未知自定义标签、固定标签枚举和 bounded/truncated。

通过的其他检查：相关源文件与测试 Ruff；`git diff --check`；`openspec validate allow-resource-scoped-loki-labels --strict`；`docker compose config --quiet`；`app.services.tool_mcp` 与 `app.bootstrap` 导入检查。检查 Dockerfile 确认相关镜像复制完整 shared 包；未执行镜像构建。

## 部署与现场验收边界

1. 本机当前无运行中的服务容器，不能将上述结果视为部署或真实 Loki 验收。
2. 部署包含本次代码的相关服务，避免控制面、Worker、Runtime、tool-mcp 使用不同工具契约；无需数据库迁移。
3. 重新发布 Agent，并让应用选择该 Agent 新版本后重新发布；使用新 Job，不能原地改写旧 Job/Publication 的冻结 Schema。
4. 在已有固定 customer/workshop 的资源内，只读验收标签发现、app/logtype 与自定义标签取值枚举、追加查询和探测。核对实际请求范围与审计；固定 key 覆盖必须被拒绝，资源配置必须保持不变。
5. 日志 line_count、limit、highlights 等既有统计语义本次没有变更。

## 追加：单次行数配置调整（2026-09-15）

本节记录用户随后确认的行数调整，与上述动态标签修复分开验证。

- 平台 `ExecutionSettings.max_loki_lines`、`LokiSettings.max_lines`、两项 env fallback 及运行配置目录默认值统一为 10000。
- 新建资源默认及管理 API/Web 输入上限为 1000；资源字段显示单次上限、默认 limit=100、非 Job 累计以及超限拒绝的说明。
- 保持 `min(平台限制, 已发布资源限制)`；不新增累计行数预算，不增加自动分页，不改变响应字符/字节容量。
- 不改写任何 DB/env 显式配置、已发布资源或 Job。历史已发布资源大于 1000 的值仍保留，重新编辑/验证时须调整为不超过 1000。

### 本地验证

后端 **198 passed**：

```sh
env -u GOVERNED_RESOURCE_POSTGRES_DSN .venv/bin/pytest \
  backend/tests/test_loki_line_limits.py \
  backend/tests/test_loki_resource_scoped_labels.py \
  backend/tests/test_provider_contract_registry.py \
  backend/tests/test_runtime_config_reconciliation.py \
  backend/tests/test_platform_config.py \
  backend/tests/test_mcp_tool_runtime.py \
  backend/tests/test_tool_mcp.py \
  backend/tests/test_resource_scope_bindings.py \
  backend/tests/test_test_suite_governance.py \
  backend/tests/test_database_resource_verifier.py -q --tb=short -rs
```

补强旧定义从 500 对账到 10000、显式数据库值仍保留的场景后，新增测试文件再次 **31 passed**。覆盖四类工具 1000/1001 边界、较小平台/资源限制、省略 limit 仍为 100，以及同一 Job 上下文连续 11 次各返回 1000 条合成日志（累计 11000，未触发行数累计拒绝）。Provider HTTP 使用模拟响应，非真实 Loki 验收。

前端 `platform-governance.test.tsx` **38 passed**；新建默认 1000，编辑保留已有 200，1–1000 输入约束及中文解释通过。`pnpm run build`（TypeScript + Vite）通过；Vite 提示既有 native config 兼容及大 bundle 警告，未阻止构建。

相关 Ruff、前端 ESLint、`git diff --check`、`docker compose config --quiet`、严格 OpenSpec 校验，以及 `app.services.tool_mcp` / `app.bootstrap` 导入检查通过。

### 升级边界

- 未部署、未重启服务、未修改真实数据库或资源，也未执行真实 Loki 请求。
- 更新前后端及使用相关配置的服务后，新默认值才可被使用。已有显式 `MAX_LOKI_LINES=500` 不会被覆盖；管理员如需提高，应修改运行配置并按现有配置生效流程加载。
- 仅此次行数补充不改变 MCP 工具 Schema、Agent/Job 快照或 Runtime 协议，不要求为此单独重新发布 Agent/Application；动态标签修复的发布要求仍见上一节。
- 新建/修改资源需按原有 Draft → 验证 → 发布流程生效。
