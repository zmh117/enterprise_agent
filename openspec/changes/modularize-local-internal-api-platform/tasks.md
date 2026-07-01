## 1. 模块结构

- [ ] 1.1 新增 `backend/app/modules/local_internal_api_platform/` 包和 `__init__.py`。
- [ ] 1.2 新增 `schemas.py`，迁移 `LokiQuery`、`LocalToolResult` 等内部数据结构。
- [ ] 1.3 新增 `envelope.py`，迁移标准 envelope、`tool_not_configured`、脱敏和 safe error text helper。

## 2. 实现迁移

- [ ] 2.1 新增 `loki_gateway.py`，迁移 Loki 输入校验、LogQL 构造、`query_range` 请求、upstream 错误分类和 summary 转换。
- [ ] 2.2 新增 `routes.py`，迁移 `/health`、context placeholder、`/tools/loki/query`、database/Redis disabled endpoint。
- [ ] 2.3 新增 `app.py`，实现模块内 `create_app(settings=None, urlopen_func=urlopen)` 并注册 routes。
- [ ] 2.4 将 `backend/app/local_internal_api_platform.py` 收窄为顶层兼容入口，继续暴露 `create_app`。
- [ ] 2.5 确认 `docker-compose.yml` 的 `app.local_internal_api_platform:create_app` command 无需修改。

## 3. 测试迁移

- [ ] 3.1 更新 `backend/tests/test_local_internal_api_platform.py`，endpoint 测试继续从顶层入口导入 `create_app`。
- [ ] 3.2 更新 Loki gateway、LogQL、summary、错误分类和脱敏单元测试，使其直接导入 `app.modules.local_internal_api_platform` 下的模块。
- [ ] 3.3 保留或补充断言，确认 `/health`、context placeholder、Loki 成功响应、Loki 校验失败、Loki upstream 错误、DB/Redis `tool_not_configured` 行为不变。

## 4. 验证

- [ ] 4.1 运行 `backend/tests/test_local_internal_api_platform.py`。
- [ ] 4.2 运行 `backend/tests/test_runtime_wiring_and_debug_api.py`，确认 Internal API Platform client 兼容路径未被破坏。
- [ ] 4.3 运行 `make check`。
- [ ] 4.4 运行 `openspec validate modularize-local-internal-api-platform`。
