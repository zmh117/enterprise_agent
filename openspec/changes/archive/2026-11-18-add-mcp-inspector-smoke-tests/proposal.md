## Why

当前项目已有 pytest 业务测试、TestClient MCP HTTP 合同测试，以及真实 Claude SDK/CLI 对本地模拟服务的调用测试，但尚无固定版本 MCP Inspector 对实际启动的项目 MCP 服务进行独立客户端验证的入口。引入一组可重复、可进入 CI 的 Inspector 冒烟测试，补充客户端兼容性和真实 HTTP 接线证据，并为编码 Agent 提供统一反馈入口。

## What Changes

- 一期只覆盖 `tool-mcp`：以 `get_schema_directory` 为代表工具，用现有服务工厂启动真实回环 HTTP 服务，底层资源使用合成数据和测试替身。
- 使用官方 Inspector CLI 执行连接、`tools/list` 和 `tools/call`；pytest 继续负责测试上下文、业务断言、数据库核验与清理。
- 复用并按需抽取现有测试 Job、Publication、角色、资源及工具快照夹具，不为每个工具增加适配器。
- 增加声明一致性、成功调用、参数拒绝、冻结快照外工具拒绝、非法 Authorization Header 拒绝和精确审计关联的代表性场景。
- 固定 Inspector 精确版本及依赖锁文件，增加显式本地命令和独立 CI 门禁；缺依赖、调用超时和断言失败不得被当成通过。
- 记录新测试实际版本、场景结果、耗时和与旧测试的覆盖差异，区分真实 HTTP 加 Mock 资源与真实 Provider/部署验收。
- 保留现有测试覆盖；本次不删除旧测试，不修改生产 MCP 工具合同、权限规则或业务实现，不引入运行监控改造。

## Capabilities

### New Capabilities

无新增 canonical 领域。

### Modified Capabilities

- `platform-operations`：在现有测试分层、完整回归和证据边界要求上，新增固定版本 Inspector、隔离真实 HTTP 测试、代表性覆盖、CI 失败传播和证据记录要求。

`builtin-tool-resource` 的固定 Server、Job 鉴权、冻结工具合同和审计关联要求保持生效，本次通过测试验证这些要求，不修改其业务规范。

## Impact

- **已核对的当前事实（Confirmed-current）**：`backend/tests/test_tool_mcp.py` 已准备并 claim 调试 Job，使用 TestClient 验证 MCP 调用与审计；`backend/tests/test_mcp_meta_fidelity.py` 已使用真实 SDK/CLI 和本地模拟 HTTP 服务；`.github/workflows/ci.yml` 已有快速、完整和 Runtime 合同测试入口。这些是代码与配置事实，不是本次运行通过的证据。
- **计划新增（Documented-intent）**：`tools/mcp-inspector/` 下的开发依赖及锁文件、`backend/tests/support/` 下的轻量夹具与调用辅助函数、`backend/tests/test_mcp_inspector_smoke.py`、测试层级登记、Makefile 入口、独立 CI job 和开发说明。
- **现有测试调整**：允许将 `test_tool_mcp.py` 中被两组测试实际复用的夹具抽到 support；原用例及其断言保留。
- **依赖**：Node.js、npm 和官方 `@modelcontextprotocol/inspector`，仅用于开发与 CI；沿用现有 Python MCP、pytest、uvicorn 和测试数据库能力。
- **运行影响**：无数据库 migration，无生产服务、Compose、业务 API、模型提示词或工具发布变化。接入中发现的生产缺陷另行记录，不为 Inspector 绕过现有合同。
- **边界**：不覆盖 ONES/钉钉/File MCP、Runtime 内部派生工具、真实业务写入、发布镜像或生产网络；不声称提高某个百分比的正确率，也不以该冒烟套件替代真实业务验收。
