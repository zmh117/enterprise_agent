# MCP Inspector 一期实施与验收记录

日期：2026-09-18。工作目录：`/Users/mhz/Develop/enterprise_agent`。本记录属于实施证据，不替代 canonical spec，也不代表 Linux CI 或生产环境验收。

## 首次接入的本地环境和路径

本节及下方首次接入结果保留当时的版本与测试数；后续按用户要求调整为 Node 最低版本校验的最新结果见本文末节。

| 项目 | 实测值 |
| --- | --- |
| 主机 | macOS / Darwin arm64 |
| Python | 3.12.2，项目 `.venv` |
| Node | 22.19.0，隔离安装后通过本次命令的 PATH 选择，未修改用户全局 Node |
| Inspector | `@modelcontextprotocol/inspector` 2.7.0 |
| Python MCP | 2.0.0 |
| pytest / uvicorn | 9.1.1 / 0.49.0 |
| Claude Agent SDK | 0.2.144，仅旧 Runtime 合同回归使用 |

默认宿主 Node 为 22.14.0，低于最低要求。首次验收通过临时 Node 22.19.0 完成；临时 Node 的安装不属于生产依赖。当前复跑可按 [开发说明](../../../docs/development/mcp-inspector.md) 选择任意满足 >=22.19.0 的正式版；`.node-version` 仍为 CI 提供精确复现版本。

2026-09-18 跟进：用户直接运行入口时仍使用 Node 22.14.0，版本检查正确阻止了执行。已通过现有 nvm 安装 Node 22.19.0（官方下载校验和匹配），保留 22.14.0、24.13.0 和默认别名 22.14.0。在同一 shell 执行 `nvm use 22.19.0` 后运行专用入口，26 项通过、0 跳过，耗时 17.39 秒。错误提示现同时显示当前与所需版本；文档补充终端切换说明。此结果仍为 macOS 本地验证，Linux CI 状态不变。

已实际执行 `npm ci --prefix tools/mcp-inspector --no-audit --no-fund`，从锁文件安装 226 个包，成功；Inspector 包元数据和锁文件均为 2.7.0。安装阶段提示上游 `server-legacy` 迁移兼容包 deprecated，未导致安装失败。运行阶段只执行本地 Node 和 CLI 文件，不执行 npm/npx、不下载依赖。

实际链路为：

```text
pytest 创建隔离 SQLite / 角色 / Publication / Published Resource / RUNNING Job
  -> Job 冻结工具快照，禁用 DirectJobTestPermissionService
  -> 原 tool-mcp create_app + uvicorn lifespan + 127.0.0.1 随机 socket
  <- 独立 Node / Inspector CLI 进程发送 Streamable HTTP
  -> 真实 Job / 权限 / 资源解析 / 审计代码
  -> FakeSchemaInspector 合成表列（唯一外部 Schema 读取替身）
  -> Inspector JSON 结果 + 数据库 Tool Call / MCP 审计精确核对
```

工具清单和调用均经过真实 TCP/HTTP，没有把 TestClient 响应注入 Inspector。正常请求使用合成 Job 执行 Header；非法 Authorization 场景只使用源码中的固定假值。合成资源指向测试域名，但 Schema 读取由替身完成，不创建真实数据库连接。测试使用项目测试容器和测试配置，不加载真实 `.env`、用户 MCP/OAuth 状态或业务消息。

## 覆盖对照和结果

| 测试集合 | 收集 / 结果 | 耗时 | 证据边界 |
| --- | --- | --- | --- |
| 夹具抽取前 `test_tool_mcp.py` | 19 / 全通过 | 3.66 秒 | 原业务及 TestClient HTTP 基线 |
| 初次抽取后同文件 | 19 / 全通过 | 3.50 秒 | 保留全部原场景 |
| 最终旧 tool-mcp + 分层治理 | 26 / 全通过（19 + 7） | 3.29 秒 | 抽取、格式整理后回归 |
| 完整 Inspector 专用入口 | 26 / 全通过，0 跳过（11 集成 + 15 合同） | 17.75 秒 | 独立 CLI、项目真实 HTTP、合成资源、故障注入 |
| 未启用 Inspector 的两个新文件 | 15 通过、11 明确跳过 | 2.53 秒 | 普通套件不会隐式启动或安装 Inspector |
| 受影响旧回归 + SDK/Runtime 合同 | 55 / 54 通过、1 已有失败，0 跳过 | 8.10 秒 | 下文记录失败，不能报告旧门禁全绿 |

旧回归 55 项组成：tool-mcp 19、分层治理 7、Compose security 10、Python File MCP bridge 16、MCP meta fidelity 3。后两组 19 项全部通过，meta fidelity 使用真实 Claude SDK/CLI 对本地合成模型/MCP 服务；不是向真实模型或真实业务 Provider 发请求。

原 `test_tool_mcp.py` 的 11 个测试函数（参数化后 19 项）抽取前后的 Python AST 完全一致，保留原参数化装饰器、测试体和断言。变化只涉及夹具搬迁、导入和格式整理；共享夹具默认仍保留原测试行为，新 Inspector 夹具显式关闭 direct-job 放宽。新增两个测试文件分别唯一登记到 integration 和 contract，没有删除旧覆盖。

### 11 项集成用例

1. `initialize` 返回 `Enterprise Tool MCP`。
2. `tools/list` 精确返回本 Job 的 `get_schema_directory`，inputSchema hash 与 Manifest、冻结快照一致。
3. 成功调用返回合成 `orders_001.id: bigint`，资源替身读取一次；两个 `_meta` 标识精确关联持久化工具和 AUTHORIZATION/RESOURCE/TOOL 审计。
4. 连续两次同名调用分别关联不同 ID；查询字符串 `"001"` 与 `"order"` 原样到达替身。
5. `limit=51` 在服务端拒绝：CLI 5 / `tool_is_error`，项目码 `mcp_schema_directory_input_invalid`，Tool Call 为 DENIED，资源零读取。
6. 快照外 `query_database` 不在列表，由 Inspector 客户端提前拒绝：CLI 5 / `tool_not_found`，无 Tool Call、资源零读取。**没有将其记为服务端拒绝证据。**
7. 保留 `x-job-id`、移除 `x-invocation-id`：服务端返回 `tool_mcp_context_missing`，无 Tool Call、资源零读取。
8. 固定假 Authorization：服务端 HTTP 400 / `tool_mcp_credentials_forbidden`；CLI 1 / `error`，无 Tool Call、资源零读取。
9. 本地未监听端口：CLI 4 / `unreachable`，成功断言必须失败；单项约 7.97 秒，耗时主要来自固定客户端的连接处理。
10. 本地监听但不响应 HTTP：总期限触发，Node 进程组被终止。
11. 服务内断言失败后端口不再可连接；数据库关闭后 opened/checked_out 均为 0。

另有 15 项合同测试验证 Node 缺失、包缺失、包版本漂移、Node 版本不符、零用例、全跳过、缺场景、错误断言、teardown 失败、pytest 无 session 提前返回、超时与取消的进程回收、状态目录清理、环境变量隔离，以及 CI 原门禁与新门禁接线。故障在隔离环境注入，没有修改生产代码制造缺陷。

已额外实际运行 `PYTEST_ADDOPTS='-k does_not_exist' make test-mcp-inspector`：26 项全部 deselected，入口列出缺失场景并非零退出（内部 1，make 2），没有误报通过。

## 发现的已有行为与失败

### 已有 Compose 断言不一致

`test_python_runtime_and_standard_mcp_are_hardened_and_secret_scoped` 仍期望 `AGENT_RUNTIME_TMPFS_SIZE` 默认 `256m`，而当前 `docker-compose.yml` 默认已是 `1g`。两文件相对 HEAD 均无本次差异，检查命令 `git diff --exit-code -- docker-compose.yml backend/tests/test_agent_runtime_compose_security.py` 为 0。

这是旧 Runtime 门禁的真实失败。本次未修改 Compose 默认值或删除/放宽断言；需要按容量规范单独核对并修复。即使 Inspector 通过，依赖该旧门禁的镜像构建仍不应放行。

### 参数类型校验边界

兼容性探针发现：`get_schema_directory` 声明 `limit` 为 integer，但传 `"10"` 时当前服务会转成整数并成功；传对象时进入通用 `tool_mcp_unavailable`，并非专用参数错误。这是当前 Server 的转换/错误处理行为，Inspector 没有自动阻止。正式负向用例使用已有明确业务边界 `limit=51`，没有宣称所有 Schema 类型错误均已正确分类。

可用隔离 `target` 夹具和 `call_tool(..., arguments={**TOOL_ARGUMENTS, "limit": "10"})` 或对象参数重现。源码定位为 `backend/app/modules/mcp_tool_runtime/service.py` 的整数转换，以及 `backend/app/services/tool_mcp.py` 的通用错误处理。生产端严格 Schema 校验是否调整应另定范围；本次不修改 MCP 代码或放宽发布权限。

## 静态检查和 CI 状态

新旧相关 5 个 Python 文件 Ruff lint、format check 通过；本 change strict OpenSpec 校验、仓库 Markdown 链接检查（`MARKDOWN_LINK_CHECK_SUCCEEDED`）和 `git diff --check` 均通过。入口合同测试收尾复跑 15 项通过，2.52 秒。

Git 现有 `node_modules/` 规则已排除 Inspector 安装目录；`.dockerignore` 的白名单没有包含 `tools/` 和 `backend/tests/`。无需修改生产 Dockerfile 或 Compose；本次没有生产代码、数据库 migration、部署、提交或推送操作。

CI 工作流已新增独立 `mcp-inspector` job，锁定 Node 22.19.0、Python 3.12、MCP 2.0.0、Inspector 2.7.0 及 npm 依赖锁。沿用项目其余 Python 依赖安装方式，不额外宣称整个 Python 依赖树已被本次锁定。该 job 无条件覆盖原工作流 PR/push 范围，必须成功才能进入 `runtime-images`，旧成功条件全部保留。本地合同测试只证明 YAML 接线，**不是 GitHub Actions 实际调度证据**。

**Linux CI 尚无实际运行结果，任务 6.1 保持未完成。** 未触发远端工作流、未核验或修改远端 required-check / 分支保护；旧 Compose security 失败也需在真实 CI 验收中处理，不能补勾完成。

## 未覆盖范围

| 范围 | 状态 |
| --- | --- |
| 发布镜像构建、容器内运行和部署 | 未验证 |
| 生产网络、代理、证书、跨主机通信 | 未验证 |
| 真实 MySQL/Oracle/SQL Server/Redis/Loki | 未验证；本次使用合成 Schema |
| ONES MCP、钉钉 MCP、File MCP | 未加入本期 Inspector 套件 |
| 模型工具选择、完整 Agent Job 与交付链路 | 未验证；SDK 合同只覆盖本地合成输入 |
| 运行记录/OTel/claude-code-monitoring-guide 改造 | 不在本次实施范围 |
| 远端 required-check 设置 | 未核验 |

收益是新增独立客户端对实际服务、精确工具合同和审计结果的可重复反馈，以及有失败校验的本地/CI 入口。没有测量模型准确率、线上故障率或开发效率百分比；不能给出“准确率提高多少”的数值结论，也不能以此替代旧测试。

## 2026-09-18 跟进：Node 最低版本校验

用户明确要求将本地 Node 检查改为至少 22.19.0。入口现读取开发包 `package.json` 的 `engines.node`（`>=22.19.0`），按 major/minor/patch 的数值顺序比较正式版；不再要求与 `.node-version` 相等。CI 仍通过 `.node-version` 固定 22.19.0，Inspector 仍精确锁定 2.7.0。预发布和无法解析的版本不被当成满足正式版要求。

新增 8 项版本边界合同用例，覆盖低于最低版本、恰好最低版本、更高 patch/minor/major、多位 minor（22.100.0）、预发布及不可解析输出。测试同时把隔离夹具中的 CI pin 改为 24.13.0，确认它不会改变本地最低要求。

实测结果：

- Node 24.13.0 下完整 `make test-mcp-inspector`：**34 项通过、0 跳过，17.66 秒**（11 项集成 + 23 项合同）。
- 入口合同测试单独运行：23 项通过，2.72 秒。
- 实际 Node 22.19.0 依赖预检通过。
- 实际 Node 22.14.0 运行入口仍非零退出，提示“当前 22.14.0，需要 >=22.19.0（正式版）”。
- 修改文件 Ruff lint / format、strict OpenSpec、Markdown 链接与 whitespace 检查通过。

未改变用户默认 Node 22.14.0；可在执行测试的终端使用已安装的 `nvm use 24.13.0`。上述为 macOS 本地结果，Linux CI 任务 6.1 和首次记录的旧 Compose 断言失败状态不变。
