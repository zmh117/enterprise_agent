## ADDED Requirements

### Requirement: Principal JWT 必须由受信 Job 事实派生
Identity Service SHALL 只为当前运行中的 Agent Job 签发 Principal JWT，并 MUST 从 Job、内部用户、Agent/Application Publication、MCP Tool 快照和当前授权事实派生 `sub`、`aud` 与 `scope`；调用方不得提交这些 claims 的最终值。

#### Scenario: Worker为ONES Tool申请JWT
- **WHEN** Worker 执行包含 `ones-mcp:ones_work_item_search` 的运行中 Job
- **THEN** Identity Service 签发 `sub` 等于该 Job 内部用户、`aud=ones-mcp` 且 scope 只包含查询 Tool 所需权限的 JWT

#### Scenario: 请求扩大scope
- **WHEN** 调用方请求 Job 快照之外的 scope、其它用户或其它 audience
- **THEN** Identity Service 拒绝签发并记录安全审计，且不返回任何 JWT

### Requirement: Principal JWT 必须使用短期非对称签名
Identity Service MUST 使用 Ed25519 私钥和 `alg=EdDSA` 签发 JWT，MCP MUST 使用按 `kid` 选择的 JWKS 公钥验证；JWT 最长有效期 SHALL 为五分钟，并包含 `iss`、`sub`、`aud`、`azp`、`job_id`、`session_id`、Publication、scope、授权摘要、`jti`、`iat`、`nbf` 和 `exp`。

#### Scenario: 合法JWT被ONES MCP接受
- **WHEN** JWT 使用活动私钥签名、`kid` 存在、claims 完整且尚未过期
- **THEN** ONES MCP 验证签名、issuer、audience、时间和查询 scope 后建立平台 Principal

#### Scenario: HS256或未知kid
- **WHEN** JWT 使用 HS256、`alg=none`、未知 `kid` 或共享密钥签名
- **THEN** ONES MCP 拒绝请求且不读取身份、凭据或调用 ONES

#### Scenario: JWT过期
- **WHEN** `exp` 已到或 `nbf` 尚未到
- **THEN** ONES MCP 返回统一认证失败且不刷新 ONES Token

### Requirement: Principal JWT 不得携带Provider凭据
Principal JWT MUST NOT 包含外部身份 ID、ONES User ID、Team、邮箱、密码、ONES Token、平台 Secret、模型密钥或其它可重放 Provider 凭据。

#### Scenario: 检查签发claims
- **WHEN** 测试解码签发的 JWT payload
- **THEN** payload 只包含平台 Principal、Job、Publication、scope、授权摘要和标准时间 claims
- **AND** 不包含 identity、credential、email、password、team 或 provider token 字段

### Requirement: Runtime只在内存转交Principal JWT
Worker SHALL 通过不进入执行 JSON 的内部 Header 把 Principal JWT 交给 Runtime；Runtime MUST 只在当前 invocation 内存中保存它，并只向匹配 audience 的固定 MCP 服务发送 Bearer Header。

#### Scenario: Runtime调用ones-mcp
- **WHEN** Job 快照包含 ONES 查询且 Runtime 收到合法 Principal JWT
- **THEN** Runtime 只向固定 `ones-mcp` 请求加入该 Bearer Token
- **AND** `tool-mcp` 请求不携带该 Token

#### Scenario: 检查digest和ledger
- **WHEN** 同一 invocation 使用重新签发但 claims 等价的短期 JWT 重试
- **THEN** request digest 保持不变，Runtime request/terminal ledger、事件和日志均不包含 JWT

### Requirement: MCP必须实时复核可撤权事实
成功验证 JWT 后，ONES MCP SHALL 重新读取 Job、用户、外部身份和冻结 Tool 快照，并 MUST 在任一事实已停用、过期、不匹配或发生 schema drift 时失败关闭。

#### Scenario: 用户在JWT有效期内被停用
- **WHEN** JWT 尚未过期但 `sub` 对应用户已停用
- **THEN** ONES MCP 在外部调用前拒绝请求并记录撤权审计

#### Scenario: JWT与Job用户不一致
- **WHEN** JWT `sub`、`job_id` 和数据库 Job 的内部用户不一致
- **THEN** ONES MCP 拒绝请求且不尝试寻找其它身份
