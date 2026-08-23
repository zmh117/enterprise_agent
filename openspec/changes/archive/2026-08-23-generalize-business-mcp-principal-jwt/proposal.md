## Why

当前平台的用户/Job Principal JWT 签发与 Runtime 凭据传递仍分别绑定 `ones-mcp` 和 `file-service`，继续为每个业务 MCP 增加专用签发方法会复制 Job、用户、工具快照、授权和审计校验，并使一个 Job 难以同时安全携带多个互不混用的业务 MCP 身份令牌。现在需要把“业务 MCP Principal”收敛为按冻结 Server 和 Tool scope 签发的通用能力，同时保留 File Principal 的工作区专用边界。

## What Changes

- 新增统一的 `issue_business_mcp_for_job(job_id, server_code)` 签发语义：读取并校验 RUNNING Job、当前用户、Publication、Job MCP 工具快照和业务授权，仅为指定业务 MCP Server 的冻结工具生成精确 scope，并签发 `aud=server_code` 的短时 Principal JWT。
- 将 `ones-mcp` 迁移到统一业务 MCP 签发路径；后续 `dingtalk-mcp` 等代码固定业务 MCP 可复用相同能力，不再新增 `issue_<server>_for_job()` 方法。
- 为 MCP Server 增加部署固定、代码拥有的鉴权模式分类；通用签发器只接受分类为业务 Principal JWT 的 Server，显式拒绝 `tool-mcp`、`file-service`、未知 Server、空工具集合、重复工具绑定和漂移快照。
- 将业务 Principal JWT 验证收敛为由各 MCP Server 固定 expected audience 和 required scope 的通用验证路径，防止请求方选择 audience 或跨 Server 复用令牌。
- **BREAKING（内部 Runtime 凭据接口）**：将单一 `principal_token` 演进为按 `server_code` 索引的 `mcp_principal_tokens`，Control Plane 与 Python Runtime 必须逐 Server 传递、校验和使用令牌；凭据仍不得进入 Runtime 请求 JSON、请求摘要、持久化账本、事件、日志或审计 payload。
- 保留独立 `file_principal_token` 和 File Principal 专用签发/验证语义，不改变 tenant、任务工作区、文件权限、File MCP bridge、文件审计或沙盒行为。
- 本变更不新增 `dingtalk-mcp` 服务、钉钉 Tool Manifest、下游钉钉凭据或业务操作，也不引入任意 MCP URL、动态 Server 注册、插件扫描或通用凭据代理。

## Capabilities

### New Capabilities

- 无。

### Modified Capabilities

- `identity-access`：身份服务从 ONES 专用 Job Principal 签发/验证收敛为按代码固定业务 MCP audience 和冻结 Tool scope 签发/验证的通用能力，同时保持 File Principal 特殊边界。
- `builtin-tool-resource`：业务 MCP Server 使用相互隔离的短时 Principal JWT，并按自身固定 audience、Job 快照和精确 Tool scope 复核调用；固定 Server 鉴权模式成为 fail-closed 治理事实。
- `execution-delivery`：Control Plane 与 Python Runtime 使用 `mcp_principal_tokens[server_code]` 传递和选择业务 MCP 令牌，使单个 Job 可同时调用多个业务 MCP 而不跨 Server 复用身份。

## Impact

- 身份签发与验证：`backend/app/modules/identity/application/principal_jwt.py` 及对应 JWKS、审计和安全测试。
- Job 工具快照与固定 MCP 策略：`backend/app/modules/mcp_tool_runtime/`，继续复用现有 Manifest、schema hash、authorization hash 和业务授权事实。
- Control Plane → Runtime 密钥传递：`backend/app/modules/agent/infrastructure/runtime_http_client.py` 及 Runtime HTTP 客户端测试；不修改公开业务请求体。
- Python Runtime：Invocation Secret Context、服务端 Header 校验、Executor 和固定 MCP SDK 配置按 `server_code` 精确取业务令牌，File Principal 继续独立。
- 兼容性：旧的 ONES 单令牌内部接口和通用 `X-MCP-Principal-Token` 传输将被受控替换；对外管理 API、Agent Runtime 业务协议正文、Job/Event/Audit schema、MCP Tool 输入协议和 File Service 合约保持不变。
