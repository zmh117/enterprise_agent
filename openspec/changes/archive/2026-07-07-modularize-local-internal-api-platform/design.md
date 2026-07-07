## Context

`add-local-internal-api-platform-loki` 已经把本地 Internal API Platform 跑通：`docker-compose.yml` 使用 `app.local_internal_api_platform:create_app` 启动 `local-internal-api-platform`，Agent 通过 `INTERNAL_API_BASE_URL=http://local-internal-api-platform:9000` 调用只读工具，Loki 查询仍由本地平台代理。

当前实现集中在 `backend/app/local_internal_api_platform.py`。这个入口位置本身合理，但文件内混合了 FastAPI 路由、Loki 校验和查询、summary 转换、错误分类、脱敏 helper、DTO 和 placeholder endpoint。继续扩展真实 DB、Redis、ER 或业务图网关时，单文件会让边界不清，也容易误把本地平台实现和 Agent runtime 工具服务混在一起。

本变更是结构重构：稳定顶层入口，拆分内部实现，不改变 endpoint、响应 envelope、错误分类、Compose profile 或 Agent runtime 依赖。

## Goals / Non-Goals

**Goals:**

- 保留 `backend/app/local_internal_api_platform.py` 作为顶层入口，继续支持 `app.local_internal_api_platform:create_app`。
- 将实现拆入 `backend/app/modules/local_internal_api_platform/`，按 app factory、routes、Loki gateway、schemas、envelope/error helper 分离职责。
- 保持 `/health`、`/tools/context/er`、`/tools/context/business-flow`、`/tools/loki/query`、`/tools/database/query`、`/tools/redis/get`、`/tools/redis/scan` 的行为不变。
- 保持 `mock-tools`、`local-tools`、`real-platform` 模式边界清晰，Agent runtime 仍只通过 HTTP Internal API Platform 调工具。
- 迁移测试 import，使 endpoint 回归测试仍通过顶层入口，Loki gateway 单元测试直接覆盖模块实现。

**Non-Goals:**

- 不新增真实数据库、Redis、ER 图或业务图接入。
- 不修改 `HttpInternalApiClient` 的 endpoint 契约。
- 不修改 `docker-compose.yml` 的 local platform command，除非实现过程中证明 re-export 不可行。
- 不把 Loki 连接逻辑放入 Agent runtime、`ReadOnlyToolService` 或 Claude client。
- 不改变现有 local-loki 查询策略，不允许 Agent 传任意完整 LogQL。

## Decisions

### 1. 顶层文件只保留兼容入口

保留：

```text
backend/app/local_internal_api_platform.py
```

该文件只从模块实现导入并暴露 `create_app`：

```python
from app.modules.local_internal_api_platform.app import create_app
```

这样 `docker-compose.yml` 中现有命令：

```text
app.local_internal_api_platform:create_app
```

可以继续工作。替代方案是把 Compose command 改成 `app.modules.local_internal_api_platform.app:create_app`。暂不采用，因为本变更目标是降低结构风险，不制造运行入口迁移成本。

### 2. 本地平台实现进入独立 module

目标结构：

```text
backend/app/modules/local_internal_api_platform/
  __init__.py
  app.py
  routes.py
  schemas.py
  loki_gateway.py
  envelope.py
```

职责划分：

- `app.py`：`create_app(settings=None, urlopen_func=urlopen)`，加载配置、创建 gateway、注册 routes。
- `routes.py`：FastAPI route 定义和 HTTP request/response 编排，不放 Loki upstream 查询细节。
- `schemas.py`：`LokiQuery`、`LocalToolResult` 等内部数据结构。
- `loki_gateway.py`：Loki 输入校验、LogQL 构造、`query_range` 请求、Loki 错误分类、Loki summary 转换。
- `envelope.py`：标准 envelope、`tool_not_configured`、脱敏和 safe error text 等共享 helper。

替代方案是拆成 `local_internal_api_platform/` 顶层包，和 `modules/` 平级。暂不采用，因为当前项目主要按 `app/modules/<bounded-context>/` 组织业务模块，本地平台作为内部工具平台的本地实现，更适合跟随 modules 结构。

### 3. 测试区分入口兼容和模块内部

endpoint 测试继续通过顶层入口：

```python
from app.local_internal_api_platform import create_app
```

Loki gateway、LogQL 构造、summary 转换等单元测试改为导入模块实现：

```python
from app.modules.local_internal_api_platform.loki_gateway import LokiGateway, build_logql
```

这样能同时验证 Compose 使用的入口仍可用，以及内部模块边界确实可被单独测试。

### 4. 行为回归优先于文件移动本身

拆分后必须保持现有行为：

- `/health` 返回 mode 和 Loki 配置摘要。
- context endpoint 返回明确 local placeholder。
- DB/Redis endpoint 返回 `tool_not_configured`，不访问真实数据源。
- Loki 查询仍限制 service、keyword、minutes、limit 和 response chars。
- Loki transient error、rejected query、invalid JSON、敏感字段脱敏保持现有分类和摘要行为。

迁移过程中如果发现需要改变行为，应停止实现并补充新的 OpenSpec 需求，而不是把行为变更混入本重构。

## Risks / Trade-offs

- [Risk] 移动代码后 Compose 入口失效。  
  Mitigation: 顶层文件 re-export `create_app`，并通过 endpoint 测试或 uvicorn import 检查验证。

- [Risk] helper 拆分后测试只验证模块，不验证真实启动路径。  
  Mitigation: endpoint 测试必须从 `app.local_internal_api_platform:create_app` 进入。

- [Risk] 重构时无意改变 Loki 错误分类或脱敏结果。  
  Mitigation: 保留现有测试断言，补充 import-path 回归，不减少现有用例。

- [Risk] 新模块命名让人误解为生产 Internal API Platform。  
  Mitigation: 文档和 module docstring 明确这是 local development platform，不是生产平台实现。

## Migration Plan

1. 新增 `backend/app/modules/local_internal_api_platform/` 包。
2. 将 dataclass、Loki gateway、envelope/helper、routes、app factory 从顶层文件迁移到模块文件。
3. 将 `backend/app/local_internal_api_platform.py` 改成兼容入口，只 re-export `create_app`。
4. 更新 `backend/tests/test_local_internal_api_platform.py` 的 import 路径，保留 endpoint 测试从顶层入口进入。
5. 运行 targeted tests 和 `make check`。
6. 运行 `openspec validate modularize-local-internal-api-platform`。

回滚方式：恢复单文件 `backend/app/local_internal_api_platform.py`，删除新增模块包；由于不改变 Compose command 和外部 endpoint，回滚不需要数据迁移。

## Open Questions

- 顶层入口是否需要临时 re-export `LokiGateway`、`build_logql`、`summarize_loki_response` 以兼容潜在外部调试脚本？当前仓库内只有测试使用这些 helper，建议不保留，改由测试直接导入模块实现。
