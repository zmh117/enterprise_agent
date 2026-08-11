## REMOVED Requirements

### Requirement: ONES 凭据和令牌不得持久化
**Reason**: Agent 查询 ONES 需要可续期的用户凭据；完全丢弃 Token 和密码会在 Token 失效后强制人工重绑。

**Migration**: 旧身份事实继续保留但运行时不可用，用户必须本人重新验证一次；新流程只把邮箱、密码和 Token 保存为专用 AES-GCM 密文，所有公开投影与审计仍保持零秘密。

### Requirement: 本阶段不接入 ONES 业务能力
**Reason**: 本变更明确接入唯一只读 `ones_work_item_search` MCP Tool。

**Migration**: 不恢复旧 API Capability、Connection 或写操作；只有重新发布且显式选择该 MCP Tool 的 Agent/Application 才能调用。

## MODIFIED Requirements

### Requirement: ONES 身份通过服务端登录验证
系统 SHALL 允许已认证的人类用户本人使用服务端配置的受信任 ONES 实例和固定登录端点验证自己的 ONES 邮箱与密码，并 SHALL 使用响应中的用户 UUID 作为外部身份标识。管理员只能查看、停用和审计，不得代用户提交邮箱、密码、Token、Team 或目标 URL。

#### Scenario: ONES凭据验证成功
- **WHEN** 当前用户提交自己的 ONES 邮箱和有效密码
- **THEN** 系统调用固定 `/project/api/project/auth/login`，校验响应结构，并创建短期 challenge，包含已验证用户 UUID、显示名称、Team 候选和加密登录材料/Token

#### Scenario: ONES凭据无效
- **WHEN** ONES 登录接口拒绝邮箱或密码
- **THEN** 系统返回安全验证失败，不创建身份或当前 credential，且不记录邮箱、密码、Token 或原始响应

#### Scenario: 客户端提交可信字段
- **WHEN** 请求包含手工 ONES UUID、Token、Team、目标 URL、Header 或 Provider 配置
- **THEN** 系统拒绝请求，可信身份与凭据字段只能来自固定 Adapter 响应和后续 Team 确认

#### Scenario: ONES身份属于其它用户
- **WHEN** 经验证 ONES UUID 已绑定另一内部用户
- **THEN** 系统返回冲突，不覆盖、转移或共享身份和 credential

### Requirement: 外部身份写操作受统一安全控制
本人 ONES 绑定、重验和解绑 SHALL 使用当前登录用户、CSRF、防重放 challenge、revision 和安全审计；管理员对身份的只读/停用操作 SHALL 使用管理端认证与细粒度身份权限。服务账号不得绑定个人 Provider 身份。

#### Scenario: 用户绑定本人ONES
- **WHEN** 已认证人类用户携带有效 CSRF 发起并确认自己的 ONES challenge
- **THEN** 系统只修改该用户的 ONES 身份和 credential

#### Scenario: 管理员代绑ONES
- **WHEN** 管理员尝试为其它用户提交 ONES 邮箱、密码或确认 challenge
- **THEN** 系统拒绝请求且不得访问 ONES 登录端点

#### Scenario: 成功或失败的身份操作
- **WHEN** 用户绑定/重验/解绑或管理员停用 ONES 身份
- **THEN** 系统记录操作者、目标身份、动作、credential revision、结果和安全错误码，不记录任何认证材料

### Requirement: ONES Mock 支持身份绑定验证
开发测试环境 SHALL 提供独立 ONES Mock，用于验证成功登录、无效凭据、异常响应、工作项查询和 Token 失效后的重新登录，不得依赖真实 ONES 凭据。

#### Scenario: 使用Mock完成ONES绑定与查询
- **WHEN** 测试使用约定账号完成本人绑定、选择默认 Team 并通过 `ones-mcp` 查询
- **THEN** 系统创建字段白名单内的身份和加密 credential，并返回 Mock 的有界工作项结果

#### Scenario: Mock返回无效凭据
- **WHEN** 测试使用错误密码调用 Mock
- **THEN** 系统返回验证失败且数据库不出现该次失败产生的身份或 credential

#### Scenario: Mock拒绝旧Token
- **WHEN** Mock 使已保存 Token 返回401但邮箱密码仍有效
- **THEN** `ones-mcp` 自动登录、更新加密 Token、最多重试一次并留下脱敏审计

## ADDED Requirements

### Requirement: ONES登录材料和Token只允许加密持久化
系统 SHALL 使用平台主密钥、随机 nonce 和 credential/challenge 绑定 AAD 加密 ONES 邮箱、密码和 Token；明文 MUST 只在当前请求或 Provider 调用内存中短暂存在。确认绑定后 SHALL 原子写入当前 credential 并清除 challenge 密文。

#### Scenario: 确认默认Team
- **WHEN** 用户确认未过期 challenge 中的默认 Team
- **THEN** 身份绑定、credential 写入、challenge 消费和审计在同一事务完成

#### Scenario: Challenge过期
- **WHEN** challenge 已过期或已消费
- **THEN** 系统拒绝确认，不创建当前 credential，并不得从 challenge 恢复登录材料

#### Scenario: 公开投影
- **WHEN** 用户或管理员查看 ONES 状态
- **THEN** 响应最多显示 credential 是否已配置、状态、revision 和安全时间，不显示邮箱、密码、Token、密文或 nonce

### Requirement: ONES身份状态参与MCP查询解析
`ones-mcp` SHALL 只为有效 Principal JWT 对应的启用内部用户解析其唯一启用 ONES 身份、默认 Team 和 ACTIVE credential，并在任何事实缺失或冲突时失败关闭。

#### Scenario: 已绑定用户查询ONES
- **WHEN** 有效 Job 的当前用户已完成新凭据重验且 Tool 已授权
- **THEN** MCP 以该用户的 ONES User ID、默认 Team 和当前 Token 执行查询

#### Scenario: 只有历史身份事实
- **WHEN** 用户存在迁移前 ONES 身份但没有 ACTIVE credential
- **THEN** MCP 返回需要本人重新验证的安全提示且不调用 ONES
