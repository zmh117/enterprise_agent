## Context

平台当前已经拥有一套 Ed25519/JWKS Principal 信任根、Job MCP 工具快照、Business Application Tool 授权和短时 JWT 审计，但用户/Job Principal 的业务路径仍把 `aud`、Tool 和 scope 固定为 `ones-mcp`；File Principal 则通过另一专用方法绑定租户和任务工作区。Control Plane 只传递一个 `principal_token` 和一个 `file_principal_token`，Python Runtime 也只认识 ONES 与 File 两个固定凭据槽位。

这会产生两个问题：每增加一个业务 MCP 都容易复制一套签发/验证方法；一个 Job 同时冻结多个业务 MCP 时，单一 `principal_token` 无法表达 audience 隔离，容易出现令牌缺失、错误复用或为了兼容而放宽 audience。与此同时，File Principal 还承担 tenant、任务工作区、文件权限和进程内 File bridge 约束，不能被普通业务 MCP 通用化吞并。

本设计跨越身份服务、MCP Manifest/Job 快照、Control Plane → Runtime Secret 传输和 Python Runtime MCP 装配。它不改变 Runtime 请求 JSON、请求摘要、Job/Event/Audit 数据模型或 MCP Tool 输入协议，也不引入新的数据库表或外部依赖。

## Goals / Non-Goals

**Goals:**

- 以一个 `issue_business_mcp_for_job(job_id, server_code)` 统一所有部署固定业务 MCP 的用户/Job Principal JWT 签发。
- 让签发、验证和 Runtime 使用均以 `server_code` 为隔离键，使同一 Job 能同时携带多个 audience 不同的业务 MCP 令牌。
- 继续复用当前 Job、内部用户、Session、Agent/Application Publication、冻结 Tool/schema、Business Application 授权、authorization hash、Ed25519/JWKS、短 TTL 和审计事实。
- 让固定 MCP Server 的鉴权模式成为代码拥有、fail-closed 的治理事实，而不是从请求、数据库或模型动态推断。
- 保持 File Principal、File MCP bridge、文件工作区、文件操作权限、审计和沙盒行为不变。
- 保证 Principal JWT 和下游 ONES/钉钉等 Provider Credential 完全分离，令牌不进入 Prompt、Tool 参数、请求正文、事件、日志或持久化账本。

**Non-Goals:**

- 不新增 `dingtalk-mcp` 服务、Tool Manifest、Provider Credential 生命周期或任何钉钉业务操作。
- 不开放任意 Server URL、动态 MCP 注册、插件发现、请求提供 Header/Token、通用 HTTP 代理或凭据代理。
- 不把 `tool-mcp` 改成 JWT 认证，也不把 File Principal 合并到业务 Principal。
- 不改变外部身份绑定本身的授权含义；完成 ONES 或钉钉身份绑定仍不自动授予 Tool、角色、数据范围或 Job 执行权限。
- 不改变 Runtime 业务协议版本和请求 JSON schema；本变更只替换独立 Secret 传输接口。

## Decisions

### 1. 使用代码固定的 MCP Server 鉴权策略

平台增加不可由数据库、请求或模型修改的 MCP Server 鉴权策略，至少区分：

- `job-context`：现有 `tool-mcp`，继续使用非敏感 Job 上下文并拒绝 Authorization。
- `business-principal-jwt`：`ones-mcp` 以及未来经独立变更加入的部署固定业务 MCP。
- `file-principal-jwt`：`file-service`，继续使用专用 File Principal。

每个代码 Manifest Tool 的 `server_code` 必须能解析到恰好一个固定策略，Job 快照验证继续校验 Tool identifier、server code 和 schema hash。`issue_business_mcp_for_job` 只接受 `business-principal-jwt`，因此即使调用方传入 `file-service`、`tool-mcp` 或未知字符串也会在签名前失败关闭。

选择显式鉴权模式而不是“除 `tool-mcp`/`file-service` 外都视为业务 JWT”，是为了让未来新增 Server 时必须主动选择安全模型，避免默认分支静默扩大 JWT 接受面。该策略是静态代码事实，不是动态 Server registry。

### 2. 通用签发器从冻结 Job 快照派生完整 scope

`issue_business_mcp_for_job(*, job_id: str, server_code: str) -> str` 按以下顺序执行：

1. 读取 Job 并确认内部用户有效、Job 为 RUNNING、Session 与 Agent/Application Publication 事实完整。
2. 验证 Job MCP 工具快照的完整性、provenance、schema hash 和 authorization hash。
3. 确认 `server_code` 的固定鉴权模式为 `business-principal-jwt`。
4. 从快照中筛选该 Server 的 Tool；要求集合非空、Tool identifier 唯一，且每个 Tool 的当前代码 Manifest 仍属于同一 Server 和鉴权模式。
5. 对每个 Tool 以当前内部用户和 Business Application 重新执行授权检查。
6. 按 Tool identifier 排序生成唯一 scope：`mcp:<server_code>:<tool_identifier>:invoke`。
7. 使用现有 Principal Ed25519 私钥签发 TTL 不超过 300 秒的 JWT。

Claims 保持封闭白名单，至少包含 `iss`、`sub`、`aud=server_code`、`azp`、`job_id`、`session_id`、Agent/Application Publication、完整 `scope`、`authorization_hash`、`jti`、`iat`、`nbf` 和 `exp`。JWT 不包含 Provider Token、密码、Cookie、MCP URL、Header、Tool 参数、Prompt、租户凭据或下游 Secret。

审计继续使用统一的签发成功/拒绝事件，记录安全的 `job_id`、actor、audience、scope、kid、jti、时间和稳定错误码，不记录 JWT 原文。ONES 调用迁移后直接调用该方法，不保留 `issue_for_job()` 兼容包装，也不增加任何 `issue_dingtalk_for_job()`。

### 3. 验证器由服务端固定 expected audience

通用业务 Principal 验证器在 MCP Server 组装时注入固定 `expected_audience`，调用请求不能提供或覆盖该值。验证器继续校验 EdDSA 算法、JWKS kid、issuer、audience、authorized party、claims 白名单、时间、TTL、JTI、scope 格式和大小上限。

当具体 Tool 被调用时，MCP Server 使用自身固定 `server_code` 和 Tool identifier 构造 required scope，并重新读取 RUNNING Job、用户、Publication 与已验证工具快照；token 的 `authorization_hash` 必须等于当前 Job 快照，token scopes 必须恰好等于该 Server 在快照中的已授权 scope 集合。这样即使某个已签名 token 被送到另一个业务 MCP，也会因 audience 不匹配在上游或业务数据访问前失败。

不采用“先无验证解码 aud，再选择验证器”的方案，因为那会让不受信 claim 参与信任策略选择，形成 confused-deputy 风险。

### 4. Runtime Secret Context 使用按 Server 索引的不可持久化映射

Control Plane 内部凭据结构演进为：

```python
RuntimePrincipalTokens(
    business: Mapping[str, str],
    files: str,
)
```

Python Runtime Invocation Secret Context 演进为：

```python
InvocationSecretContext(
    mcp_principal_tokens: Mapping[str, str],
    file_principal_token: str,
)
```

Control Plane 根据已经验证并冻结到 Runtime 请求中的 MCP bindings，针对每个 `business-principal-jwt` Server 恰好签发一个 token；File Server 继续独立签发一个 File Principal。映射在构造时复制并只读暴露，`repr`、异常和诊断始终隐藏值。

不把映射加入 Runtime 请求 JSON，因为请求正文会参与 digest、重放账本和诊断投影。业务 token 使用逐 Server Secret Header 传输：

```text
X-MCP-Principal-Token-Ones-Mcp: <JWT>
X-MCP-Principal-Token-Dingtalk-Mcp: <JWT>
X-File-Principal-Token: <File JWT>
```

业务 Server code 必须满足固定的小写 header-safe 格式，Control Plane 只为冻结 bindings 生成 Header。Runtime 从原始 Header 集合中按固定策略解析，拒绝重复、未知、格式非法、超长、含 CR/LF、缺失或超出请求 Server 集合的业务 Token；File Header 继续执行独立的恰好一次校验。Header 名和值加入全局 Secret redaction/禁止持久化测试。

不使用单个 JSON/Header bundle，因为聚合值更容易触碰代理单 Header 大小限制，也会引入第二套 JSON 解析与 canonicalization；不使用重复同名 Header，因为中间层可能合并或丢失重复字段。

### 5. Python Runtime 按当前 MCP binding 精确选择 token

Python Runtime 只在处理已经由 Runtime 协议验证的固定 MCP bindings 后访问 Secret Context。对于每个 `business-principal-jwt` binding，SDK MCP 配置从 `mcp_principal_tokens[binding.server_code]` 取唯一 Bearer Token；缺失、额外或空 token 都在连接 MCP 前作为不可重试配置/身份错误失败，不回退到其它 Server token，也不共享 Header dict。

Python Runtime 的固定 MCP 装配从 ONES 单 URL 槽位收敛为只读 `business_mcp_server_urls[server_code]`，但该映射只能由启动装配根据代码固定策略和显式部署配置构造；请求、Job、Agent、Application和模型均不能添加或覆盖条目。当前生产装配只包含 `ones-mcp`，未来加入 `dingtalk-mcp` 时仍必须通过独立变更把 Server、URL配置、Tool Manifest和鉴权模式加入代码固定策略。此处的通用令牌和URL映射不会接受请求或模型提供URL。

`file-service` 继续走 `file_principal_token`、进程内 File MCP bridge、任务沙盒和 File Transfer Context；`tool-mcp` 继续不携带 Authorization。SDK 的 allowed tools、strict MCP 配置、审计事件归一化和沙盒策略不改变。

### 6. 协调切换内部接口，不保留混合模式

`principal_token` → `mcp_principal_tokens` 是内部 Secret 接口变更。Control Plane 客户端、Python Runtime 服务、Executor、SDK MCP 配置和测试必须在同一变更中完成切换；本地/部署验证需重建并同时发布 Worker/Control Plane 与 Python Runtime 镜像。

不同时接受旧通用 Header 和新逐 Server Header，因为兼容分支会造成重复凭据、优先级和跨 Server fallback 歧义。回滚时应整体回滚相关镜像到上一版本；本变更没有数据库迁移，也不会改变既有 Job 持久化数据。

## Risks / Trade-offs

- [动态 Header 名可能被代理规范化或遗漏] → 只允许小写连字符 Server code，使用唯一前缀，并在真实 Runtime HTTP/Compose 集成测试中验证 Header 透传、重复检测和大小上限。
- [一个 Job 的业务 MCP 数量增加导致总 Header 变大] → 对单 token、Server 数量和总 Secret Header 字节设置有界上限；超限在 Control Plane 发起 Runtime 请求前失败，不降低 JWT claims 校验。
- [通用签发器被误用于 File 或无认证 Server] → 以显式固定鉴权模式做第一道校验，并为 `tool-mcp`、`file-service`、未知 Server 和无工具快照建立拒绝测试。
- [token scope 与 Job 快照在签发后发生不一致] → JWT TTL 保持不超过 300 秒，MCP Server 每次调用仍重新读取 RUNNING Job、快照和 authorization hash，不只信任 token。
- [批量迁移遗漏单一 `principal_token` 引用] → 增加架构残留扫描和类型检查，要求生产代码中不再出现业务单 token 槽位或 ONES 专用签发方法；File 专用命名除外。
- [多个 Server 的令牌进入日志或账本] → 扩展 Secret key/header 红名单，使用不含值的 `repr`，并以审计、事件、request digest、terminal ledger 和错误序列化回归测试证明无泄漏。
- [该通用化被误解为 DingTalk MCP 已可用] → proposal、spec、UI/运行证据均明确：本变更只提供身份令牌基础能力；DingTalk Server、Tool、Provider Credential 和真实 E2E 必须由后续独立变更交付。

## Migration Plan

1. 先增加固定 MCP Server 鉴权策略和签发/验证单元测试，不改变现有 ONES 调用链。
2. 实现通用业务签发/验证器，将 ONES 测试迁移到 `server_code="ones-mcp"`，确认 claims、scope、授权、审计和拒绝路径等价。
3. 将 Control Plane 的 Runtime Principal 结构和 Secret Header 发送改为按 Server 映射，并补齐缺失、重复、额外、超长和泄漏测试。
4. 将 Python Runtime Secret Context、HTTP 入口、Executor 和 SDK MCP 装配改为按 binding 精确取 token；File 和 `tool-mcp` 回归必须保持不变。
5. 删除旧 `issue_for_job()`、单一 `principal_token` 业务槽位和旧通用 Header，运行残留扫描。
6. 运行身份、MCP、Runtime、File、审计与沙盒聚焦测试，再运行完整 backend、Ruff、Mypy、OpenSpec strict、Compose 配置和真实镜像隔离检查。
7. 在独立测试数据中执行至少一个 ONES MCP Job，并使用测试固定的第二业务 Server fixture 证明同一 Job 的双 token audience/scope 隔离；不得把 fixture 证据表述为 DingTalk MCP 上线。

回滚不需要数据库操作：同时回滚 Control Plane/Worker 与 Python Runtime 镜像和代码。不得仅回滚一侧后启用旧 Header 兼容模式。

## Open Questions

无。未来 `dingtalk-mcp` 的 Tool 集、Provider Credential、服务 URL、审计字段和真实 E2E 由独立 OpenSpec change 决定。
