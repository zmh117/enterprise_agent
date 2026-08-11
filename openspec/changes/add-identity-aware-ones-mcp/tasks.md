## 1. 迁移前事实与边界门禁

- [ ] 1.1 记录当前 `mcp_new` 分支、未提交修改、活动 OpenSpec、迁移 038-041、现有 ONES 身份数量和运行中 Job，确认本变更不覆盖既有退役工作
- [ ] 1.2 增加架构残留门禁：允许新的 EdDSA Principal JWT，但继续禁止旧 `runtime-tool-mcp`、HS256 MCP signing key、任意 MCP URL、API Capability/Connection 和通用 HTTP/GraphQL Tool 回归
- [ ] 1.3 固定第一阶段 Tool/Provider 契约：仅 `ones-mcp:ones_work_item_search`，生产 HTTPS allowlist，本地仅显式允许 `ones_mock` HTTP

## 2. 外部身份凭据数据与加密

- [ ] 2.1 新增前向数据库迁移，创建一对一 `external_identity_credential`，包含 Provider、状态、revision、登录材料/Token 密文、nonce、key ID、算法和安全生命周期时间
- [ ] 2.2 扩展 ONES verification challenge 以暂存绑定 challenge 的加密登录材料与 Token，并保证消费、过期或失败后秘密不可继续使用
- [ ] 2.3 新增 `mcp_operation_audit` 及 Job、actor、jti、identity、credential revision、correlation 和时间索引，不删除既有身份/Job/Tool Call/Audit 历史
- [ ] 2.4 实现带 credential/challenge purpose AAD 的 AES-256-GCM cipher，复用平台主密钥加载与 key ID 规则并覆盖篡改、错 key、错 AAD 和空值失败
- [ ] 2.5 实现通用外部 credential repository：原子 upsert、optimistic revision Token 轮换、REAUTH_REQUIRED、停用、解绑清密文和只读安全投影
- [ ] 2.6 验证 SQLite 测试库与 PostgreSQL 迁移的空库、新库升级、幂等、外键和索引行为

## 3. ONES本人绑定与统一身份服务

- [ ] 3.1 扩展 ONES 登录 Adapter 的规范结果，使 Token 只在受信服务内部可用且 `repr`、异常和公开模型不泄漏秘密
- [ ] 3.2 修改本人验证开始流程，在固定登录成功后创建含加密登录材料/Token 的短期 challenge，公开响应仍只返回 subject、Team 和时间
- [ ] 3.3 修改确认流程，在一个事务中消费 challenge、绑定/重验身份、校验默认 Team、创建/轮换 ACTIVE credential 和写审计
- [ ] 3.4 实现显式换绑、重复确认、过期 challenge、其它用户 subject 冲突和服务账号绑定失败关闭
- [ ] 3.5 修改本人软解绑和管理员停用边界，使运行时 credential 立即不可用；管理员继续不能代绑、重验或解绑
- [ ] 3.6 扩展本人/管理员 ONES 状态投影，只显示 credential configured/status/revision/安全时间，不返回邮箱、Token、密文、nonce 或 key ID
- [ ] 3.7 增加绑定、重验、换绑、停用、解绑和失败路径的 API/事务/并发/脱敏回归

## 4. Principal JWT签发与公钥分发

- [ ] 4.1 实现 Ed25519 私钥/JWKS 加载、文件权限/格式校验、`kid` 公钥指纹和多公钥轮换读取，生产缺失配置必须失败关闭
- [ ] 4.2 实现 `PrincipalTokenIssuer`，只从运行 Job、内部用户、session、Publication、MCP Tool 快照和当前授权派生 claims，最长有效期五分钟
- [ ] 4.3 实现 `PrincipalTokenVerifier`，严格校验 `alg=EdDSA`、kid、issuer、audience、scope、iat/nbf/exp、jti 和 claim 类型
- [ ] 4.4 增加 Principal JWT 安全投影/JWKS 读取接口或部署只读 JWKS 文件，并确保私钥只挂载到可信 Worker 签发进程
- [ ] 4.5 审计 JWT 签发成功、签发拒绝和验证拒绝，只保存 kid、jti、Job、audience/scope hash、时间和安全错误码
- [ ] 4.6 覆盖伪造签名、HS256、alg none、未知 kid、错误 issuer/audience、scope 扩大、过期/未生效、Job 用户不匹配和用户停用测试

## 5. MCP Tool目录、发布与Job快照

- [ ] 5.1 扩展代码 MCP Manifest，使每个 Tool 固定 `server_code`；加入 `ones-mcp:ones_work_item_search` 输入 schema、模型描述、只读风险和稳定 schema hash
- [ ] 5.2 移除 Agent/Application MCP 组合和仓储中对 `server_code='tool-mcp'` 的硬编码，持久化并返回精确 server code
- [ ] 5.3 修改发布校验、管理目录、角色 Tool grant 和有效权限预览，使 ONES 查询遵守 Agent Envelope、Application 子集和角色授权交集
- [ ] 5.4 修改 Job MCP Tool snapshot/verify/runtime binding，冻结并校验 `ones-mcp` server code、identifier 和 schema hash，继续不冻结 Token、邮箱或 URL
- [ ] 5.5 增加未选 Tool、应用未选、角色未授权、schema drift、旧 publication 和现有 `tool-mcp` 不变的回归

## 6. Worker与双Runtime Principal转交

- [ ] 6.1 修改 Worker Runtime client，在 Job 含 ONES Tool 时签发 Principal JWT，并通过 `X-MCP-Principal-Token` Header 发送；执行 JSON、request digest 和 Runtime Grant claims 不包含 JWT
- [ ] 6.2 扩展共享 Runtime JSON schema、生成的 Python/TypeScript 类型与 validators，使固定 server code 只允许 `tool-mcp|ones-mcp` 且请求仍不含 Server URL
- [ ] 6.3 修改 TypeScript Runtime request handler/invocation registry，以 invocation 内存 secret context 接收 JWT，不写 logger、event 或 terminal ledger
- [ ] 6.4 修改 TypeScript Claude Runtime 的固定 per-server URL/alias/Header 注册，只有 `ones-mcp` 收到 Authorization，`tool-mcp` 保持无 Principal Token
- [ ] 6.5 修改 Python Runtime service/registry/sdk executor，以等价内存 secret context、固定 URL/alias 和 Header 调用两个 MCP 服务
- [ ] 6.6 更新双 Runtime 配置/readiness：检查 `ONES_MCP_SERVER_URL` 与 allowlisted host，但不得加载 Principal 私钥或个人凭据主密钥
- [ ] 6.7 覆盖 JWT Header 不进入 digest/ledger/event/log、缺失 Token 失败、任意 URL/未知 server 拒绝、精确 Tool allowlist 和调用预算测试

## 7. ONES MCP查询与Token自动刷新

- [ ] 7.1 新建 `ones-mcp` 应用与 health/Streamable HTTP 入口，只注册 `ones_work_item_search`，限制 Host/Origin、请求体、超时和公开 Tool schema
- [ ] 7.2 实现 MCP Bearer 解析和 Principal JWT 验证，禁止 Header 缺失、重复 Authorization、错误 audience/scope 和任何 Tool 身份参数
- [ ] 7.3 实现实时 Principal 解析：校验运行 Job、Job 用户、Tool 快照、当前授权、启用用户、唯一启用 ONES 身份、默认 Team 和 ACTIVE credential
- [ ] 7.4 实现凭据解密与固定 ONES Base URL/host/HTTPS/无代理/无重定向网络边界，禁止请求输入控制 URL、Header 或 GraphQL document
- [ ] 7.5 实现固定只读 GraphQL 查询、issue type 映射、有界输入、响应 schema 校验、字段白名单和 `untrusted_data=true` 输出
- [ ] 7.6 实现首次401后的本地 credential 锁、revision 重读、固定登录、subject/Team 复核、Token CAS 更新和原查询最多一次重试
- [ ] 7.7 实现登录失败、subject变化、Team消失、并发 revision 冲突、403、429/5xx、超时、重定向、超大/非法响应和第二次401的稳定失败分类
- [ ] 7.8 覆盖未绑定、只有旧身份无 credential、多个身份、停用用户/身份、Tool撤权和禁止管理员/共享身份回退测试

## 8. MCP操作与凭据生命周期审计

- [ ] 8.1 实现 MCP 操作审计 repository/service，在同一 correlation/Job/principal 链记录 Tool、Provider attempt、credential revision、状态、耗时和安全错误
- [ ] 8.2 查询请求只审计 keyword hash/长度、类型、limit；响应只审计 count、total、truncated，不保存 GraphQL、原始正文或工作项完整内容
- [ ] 8.3 将绑定/重验、JWT、Token refresh、REAUTH_REQUIRED、停用/解绑与现有 `audit_event`、`agent_tool_call` 和新 MCP 审计关联
- [ ] 8.4 审计写入失败时 Tool 失败关闭，不把未审计 Provider 成功结果交给 Agent，并记录不含结果正文的安全服务错误
- [ ] 8.5 增加已知邮箱、密码、ONES Token、Principal JWT、Authorization、密文和 nonce 的数据库/日志/事件/响应全文泄漏回归

## 9. Mock、前端与部署

- [ ] 9.1 扩展 `ones_mock` 测试控制，使测试可稳定触发旧 Token 401、新登录 Token、错误凭据、subject/Team变化、403/429/5xx、重定向、超大和非法响应
- [ ] 9.2 更新 ONES Mock 文档，明确绑定、查询和 Token 刷新示例只使用仓库固定假凭据，不接受真实 ONES secret
- [ ] 9.3 更新本人外部身份前端/API 类型，展示 credential 安全状态和重新验证提示，关闭/成功/失败后清空密码且不持久化邮箱密码
- [ ] 9.4 新增 `ones-mcp` Docker target/Compose 服务、只读文件系统、固定私网、Provider egress、数据库、主密钥和只读 JWKS 挂载；不映射宿主端口
- [ ] 9.5 更新 Worker 与双 Runtime Compose 配置/secret/depends_on/readiness，只给 Worker 私钥、只给 `ones-mcp` JWKS 与主密钥、只给 Runtime 固定 URL
- [ ] 9.6 更新 `.env.example`、README 和技术验收文档，说明 EdDSA key 生成/轮换、旧身份需重验、Mock边界及真实 ONES 尚未验收

## 10. 验证与验收

- [ ] 10.1 运行数据库迁移、身份/JWT/ONES MCP/审计聚焦单元与集成测试，确保 `ones_mock` 绑定、查询和401刷新全部通过
- [ ] 10.2 运行 Python Runtime、TypeScript Runtime 生成合约、lint、typecheck 和双 Runtime ONES Tool 等价测试
- [ ] 10.3 运行后端格式、静态检查和全量测试，区分本变更失败与工作树既有失败并保留原始证据
- [ ] 10.4 运行前端测试、类型检查和生产构建，验证绑定状态与秘密清理
- [ ] 10.5 运行 Compose config、受影响镜像构建和 readiness，验证私网端口、secret mounts、host allowlist 与服务依赖
- [ ] 10.6 执行 Mock 正向链及 JWT/授权/身份/credential/Provider 全部负向用例，核对 Job、Tool Call、MCP audit 和 Token revision 数据库证据
- [ ] 10.7 运行敏感信息扫描、旧组件残留扫描、OpenSpec 全量 strict validation 和 `git diff --check`
- [ ] 10.8 记录验收边界：Mock 通过不等于真实 ONES、真实 DingTalk→Runtime→ONES→Delivery E2E 未执行时不得标记生产可用
