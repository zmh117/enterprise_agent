# MCP Inspector 开发测试

`make test-mcp-inspector` 使用官方 Inspector CLI，经过真实回环 HTTP 调用项目 `tool-mcp`。它补充独立客户端兼容性证据，pytest 继续负责业务断言、数据库审计核对和资源清理。

一期覆盖 `get_schema_directory`，底层数据库结构由合成 Schema 替身提供。角色、Publication、资源发布、Job 创建与 claim、冻结快照、权限检查和审计均使用项目实现。测试显式禁用 direct-job 权限放宽夹具。

## 安装和执行

在仓库根目录操作。Python 使用 3.12；Inspector 固定为 2.7.0，本地 Node 要求正式版 **>=22.19.0**，允许更高的 patch、minor 和 major，例如 24.13.0。最低版本读取 `tools/mcp-inspector/package.json` 的 `engines.node`；`.node-version` 仅为 CI 和本地复现指定精确版本，目前是 22.19.0。Inspector 升级需同步依赖锁文件、Node 兼容要求和验证证据。

```bash
# 已使用 >=22.19.0 的正式版可跳过；以下用 nvm 选择 CI 的复现版本：
nvm install "$(cat tools/mcp-inspector/.node-version)"
nvm use "$(cat tools/mcp-inspector/.node-version)"

# 已有项目 .venv 可直接复用；首次准备时创建。
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev,tool-mcp]'
npm ci --prefix tools/mcp-inspector --no-audit --no-fund

make test-mcp-inspector
```

`nvm use` 只对当前终端生效。若当前版本过低，请在执行测试命令的同一个终端切换到兼容版本，例如 `nvm use 24.13.0`。新开终端后用 `node --version` 确认版本；错误提示也会显示当前值和最低要求。

安装是单独步骤。测试不执行 `npx`、不联网安装、不启动浏览器，也不需要运行 Compose 或配置真实服务。每次 CLI 调用使用新的临时 HOME、配置及 OAuth 存储目录；不继承宿主模型 Key、代理、Node 注入参数或用户 MCP 配置。

普通 `make test-fast` 仍选择 unit/contract，其中包含入口防误报测试；不启动 Inspector。普通完整套件未设置 `RUN_MCP_INSPECTOR_SMOKE=1` 时，11 个 Inspector 集成用例会明确跳过。专用入口运行这 11 项以及 23 项版本、入口与清理合同测试，任一失败、零用例、全部跳过、缺少必需场景，或 pytest 提前退出但没执行用例，都返回非零。

单项排障可以使用下面的 pytest 命令；它只验证所选用例，不能替代专用入口的完整场景门禁：

```bash
RUN_MCP_INSPECTOR_SMOKE=1 .venv/bin/pytest -q -s \
  backend/tests/test_mcp_inspector_smoke.py::test_success_and_audit
```

## 覆盖与拒绝层次

| 场景 | 固定版本下的断言 |
| --- | --- |
| `initialize` | 项目 Server 身份，真实 HTTP 服务已完成 lifespan |
| `tools/list` | 本 Job 的精确工具集合；inputSchema hash 同时匹配 Manifest 与冻结快照 |
| 成功调用 | 已知表列、资源读取事实、两个 `_meta` ID 与工具及 MCP 审计一致 |
| 连续同名调用 | 两次调用 ID 不同且分别关联审计；`"001"` 这样的字符串参数保持原值 |
| 参数越界 `limit=51` | **服务端拒绝**：CLI 5 / `tool_is_error`，项目码 `mcp_schema_directory_input_invalid`，资源读取零次 |
| 快照外 `query_database` | **客户端拒绝**：CLI 5 / `tool_not_found`；不出现在列表，未产生 Tool Call 或资源读取 |
| 缺 `x-invocation-id` | **服务端拒绝**：CLI 5 / `tool_is_error`，项目码 `tool_mcp_context_missing` |
| 固定假 Authorization | **服务端 HTTP 拒绝**：CLI 1 / `error`，HTTP 400、`tool_mcp_credentials_forbidden` |
| 服务不可达 | CLI 4 / `unreachable`；不能当成授权拒绝 |
| 调用超时 | 外层期限终止进程组；不能重试后隐藏失败 |
| 断言失败清理 | HTTP 端口关闭、数据库连接归零 |

stdout 必须是 JSON 结果，stderr 单独解析错误；工具参数使用 `--tool-args-json`，不拼接 shell 命令。连接期限 10 秒，总调用期限 30 秒，服务就绪期限 10 秒，正常退出等待 5 秒；超时和取消都会清理子进程及临时状态。服务仅监听随机回环端口，显式允许该测试 Host，保留原 DNS rebinding 防护。

Inspector 不是完整 Schema 校验器。本期实际证明了上表指定的参数边界；参数类型能否被严格拒绝仍取决于 Server。不要把 `tools/list` 的 Schema hash 一致等同于所有非法输入都能被拒绝，也不要把客户端拒绝记成服务端负向验收。

## 编写或修改 MCP 工具

1. 先运行受影响的业务、权限和 HTTP 合同测试，保留事务、恢复、写操作确认等原有断言。
2. 在共享夹具中准备真实授权和合成资源，确保新工具确实进入本测试 Job 的冻结快照。不要把全局 Manifest 中所有工具都加进期望列表。
3. 在 [Inspector 用例](../../backend/tests/test_mcp_inspector_smoke.py) 中调用同一个 `Inspector.call`，提供方法、工具名称、JSON 参数和结果断言；每个工具不需要专用适配器。不同外部资源需要自己的测试数据或 Provider 替身。
4. 新增必需集成场景时更新 [入口](../../backend/tests/support/mcp_inspector.py) 的 `REQUIRED_SCENARIOS`，再运行专用命令。新增测试文件必须登记到 [测试分层清单](../../backend/tests/test_suite_tiers.toml)。
5. 按失败层次定位并修复：声明/协议、业务结果、授权、资源或审计。仅退出码为零不足以证明工具正确。

这条反馈路径可以帮助编码 Agent 更早发现工具接线和返回结构错误；没有模型准确率提升百分比的测量。现有 pytest、TestClient、Claude SDK/CLI 和业务验收继续保留，Inspector 不取代它们。

## CI 和排障

[CI 工作流](../../.github/workflows/ci.yml) 的 `mcp-inspector` job 使用固定 Node、Python 3.12 和 npm 锁文件，在工作流原有 PR/push 范围运行同一命令。`runtime-images` 同时依赖该 job 成功与原有门禁成功；没有 `continue-on-error`。远端分支保护的 required-check 配置属于另一个验收项，不能从 YAML 推断已启用。

- “缺少依赖 / 版本不符”：先按上文安装与切换版本；执行入口不会代为安装或静默跳过。
- `unreachable` 或超时：先查测试服务就绪与本机回环连接，不可调整负向预期让测试通过。
- 业务错误码不符：查看 `structuredContent.error_code` 和对应数据库记录；不要放宽生产 Host、权限或 Schema 来适配测试。
- 新用例未执行：检查分层登记和必需场景名称，不要删掉门禁检查或加 skip 掩盖。
- 全套旧回归出现不相关失败：单独记录文件、预期与实际值；不要以 Inspector 通过替代旧门禁。

本期不验证发布镜像、生产网络、真实数据库、ONES、钉钉、File MCP、真实模型工具选择或完整 Agent 链路。具体本地结果和 Linux CI 未完成项见 [本次验收记录](../../openspec/changes/add-mcp-inspector-smoke-tests/evidence.md)。

官方来源：[Inspector 项目](https://github.com/modelcontextprotocol/inspector)、[固定 2.7.0 版本](https://github.com/modelcontextprotocol/inspector/tree/2.7.0)。
