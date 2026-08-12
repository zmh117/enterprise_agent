# 统一身份 ONES MCP

第一阶段只提供固定只读 Tool `ones-mcp:ones_work_item_search`。它接受
`keyword`、`issue_type=demand|task|defect` 和 `limit=1..50`，输出仅包含有界的
工作项编号、名称、类型、总数、截断标记及 `untrusted_data=true`。

## MCP 传输边界

`ones-mcp` 固定使用 `mcp==2.0.0` 的无状态 Streamable HTTP。平台 Runtime 和本地
测试只通过部署配置中的固定 HTTP URL 调用；服务不保存跨请求 MCP Session，也不提供
Cursor/stdio 启动方式或独立 ONES 凭据旁路。服务支持 v2 `server/discover`、`tools/list`
和 `tools/call`，同时保留 SDK 的旧协议初始化回退供现有 Runtime HTTP 客户端使用。

`ones-mcp` 依赖只安装在独立镜像中。`tool-mcp` 与 Python Agent Runtime 继续使用各自
兼容的 MCP SDK v1 依赖，避免 `claude-agent-sdk` 的 `<2` 约束与 ONES MCP v2 冲突。

## 身份与凭据边界

1. Agent Worker 从运行中的 Job、当前用户、发布快照与当前 RBAC 签发最长五分钟的
   Ed25519 Principal JWT。
2. Runtime 只在该次 invocation 的内存 Secret Context 中持有 JWT，并只把它作为
   `ones-mcp` 的 Bearer Header；请求 JSON、digest、Grant、事件和 ledger 均不含 JWT。
3. `ones-mcp` 验证 JWKS 后实时复核 Job、用户、发布快照、授权、唯一启用的 ONES
   身份、默认 Team 与 ACTIVE credential。JWT 不包含 ONES User ID、Team、邮箱或 Token。
4. 邮箱、密码和 ONES Token 使用平台 Master Key 与 purpose AAD 进行 AES-256-GCM
   加密；公开 API 只返回 configured/status/revision 和安全时间。

首次查询返回 401 时，服务在 credential 级进程锁内重读 revision。若没有其它实例
完成轮换，则用加密登录材料调用固定登录端点，复核 subject 与默认 Team，以 CAS
升级 Token，并只重试原查询一次。第二次 401 或身份变化会进入
`REAUTH_REQUIRED`。

## 审计

`mcp_operation_audit` 原样保存已通过大小与 schema 校验的 Tool Input、固定 GraphQL
query/variables、Provider 业务响应和 Tool Output。业务字段（包括邮箱、ONES User ID、
keyword 和工作项内容）不脱敏。密码、Token、Principal JWT、Authorization/Cookie、
密文、nonce 和私钥在结构上禁止进入审计。

完整详情接口为 `/api/admin/mcp-operation-audits`，要求 `audit:*:read`，读取行为本身也
写入平台审计。`MCP_OPERATION_AUDIT_RETENTION_DAYS` 必须为 1..3650；服务启动后按小时
执行到期清理。

## Key 初始化与轮换

```bash
scripts/bootstrap_agent_runtime_secrets.sh /absolute/secret/directory
```

脚本同时生成 Runtime Grant、Model Probe 和 Principal JWT 文件。Worker 只挂载
`principal-jwt-private.pem`；`ones-mcp` 只挂载 `principal-jwks.json`。轮换时先把新旧
公钥同时发布到 JWKS，再切换 Worker 私钥；等待旧 Token 最长五分钟过期后才能移除旧
公钥。

脚本支持原地升级：完整的既有 Runtime Grant、Model Probe 或 Principal JWT 材料会被
保留，只补齐完全缺失的一组；若任一密钥组处于半套状态，脚本会失败关闭且不覆盖文件。

## Mock 验收边界

本地可把 Provider 固定到仓库 `ones_mock`，并显式开启 HTTP。Mock 支持查询、401
刷新、403、429、5xx、重定向、非法 JSON、超大响应、subject 变化和 Team 消失等固定
测试控制。只允许使用仓库的假凭据。

Mock 通过只证明本仓库契约闭环，不证明真实 ONES GraphQL 兼容性，也不等于真实
钉钉到交付的生产 E2E 已完成。
