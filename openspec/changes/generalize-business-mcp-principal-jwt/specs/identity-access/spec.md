## ADDED Requirements

### Requirement: 身份服务按业务 MCP Server 签发 Job Principal JWT
平台身份服务 SHALL 提供统一的业务 MCP Principal 签发能力，输入只能是内部 `job_id` 和代码固定的 `server_code`。签发服务 MUST 读取并验证 RUNNING Job、有效内部用户、Session、Agent Publication、Business Application Publication、Job MCP 工具快照和 authorization hash，只筛选该 Server 冻结且 schema 未漂移的 Tool，并在逐项复核现有 Business Application Tool 授权后生成排序、唯一且非空的 `mcp:<server_code>:<tool_identifier>:invoke` scope。JWT MUST 使用统一 Principal Ed25519 信任根，TTL不得超过300秒，并绑定固定issuer、`aud=server_code`、authorized party、主体、Job、Session、两个Publication、完整scope、authorization hash、JTI和时间声明。

#### Scenario: 为 ONES Job 签发通用业务 Principal
- **WHEN** RUNNING Job冻结了合法 `ones-mcp` Tool且当前用户仍具有对应业务Tool授权
- **THEN** 身份服务签发 `aud=ones-mcp` 且scope只包含该Job冻结 ONES Tool的短时JWT
- **AND** 签发调用使用统一业务MCP方法而不是ONES专用方法

#### Scenario: 同一 Job 包含两个业务 MCP
- **WHEN** RUNNING Job冻结了两个代码固定业务MCP Server各自的合法Tool
- **THEN** 身份服务可分别按两个`server_code`签发两个audience不同、scope互不混合的Principal JWT

#### Scenario: Server 不允许使用业务 Principal
- **WHEN** 调用方请求为`tool-mcp`、`file-service`、未知Server或未声明为`business-principal-jwt`的Server签发业务Principal
- **THEN** 身份服务在签名前失败关闭并写入不含Token的拒绝审计

#### Scenario: 冻结工具集合无效
- **WHEN** 指定业务Server在Job快照中没有Tool、存在重复Tool、schema或Server漂移、authorization hash无效或任一Tool不再授权
- **THEN** 身份服务拒绝签发且不得缩小、扩大、猜测或跨Server补充scope

#### Scenario: JWT 包含下游凭据
- **WHEN** 待签发claims包含ONES Token、钉钉Token、密码、Cookie、MCP URL、Header、Tool参数、Prompt或其它下游Secret
- **THEN** 签发失败且审计、日志和错误不得记录原值

### Requirement: 业务 MCP Principal 验证固定 audience 和完整 Job 事实
每个业务MCP Server MUST 使用自身代码固定的expected audience验证Principal JWT，不得从未验证claims、请求参数、Tool输入或Header后缀选择信任策略。验证 MUST 覆盖EdDSA算法、JWKS kid、issuer、audience、authorized party、claims白名单、TTL、时间、JTI和required scope，并重新读取当前RUNNING Job、有效用户、Session、两个Publication、冻结Tool/schema和authorization hash；token的scope MUST 恰好等于该Server在当前Job快照中已授权的scope集合。

#### Scenario: 正确 audience 调用冻结 Tool
- **WHEN** 业务MCP收到平台签发、audience匹配且包含当前Tool精确scope的有效JWT
- **THEN** 服务在复核当前Job、用户、Publication、快照和授权摘要后进入业务调用

#### Scenario: ONES token 被送往另一业务 MCP
- **WHEN** `aud=ones-mcp`的JWT被送往expected audience为其它Server的业务MCP
- **THEN** 服务在读取Provider Credential或访问上游业务系统前拒绝

#### Scenario: token scope 是快照的子集或超集
- **WHEN** JWT scope与该Server当前冻结且已授权的完整Tool scope集合不完全一致
- **THEN** 服务失败关闭且不得仅因当前调用Tool出现在scope中而继续

#### Scenario: 下游 Provider Credential 与平台 Principal 分离
- **WHEN** 业务MCP需要使用ONES、钉钉或其它Provider Credential访问上游
- **THEN** 服务根据已验证平台主体和自身固定身份规则解析凭据，且Provider Credential不得来自Principal JWT、Prompt或Tool参数

### Requirement: File Principal 保持独立签发与验证边界
`file-service`的用户/Job Principal MUST 继续由专用File签发路径绑定租户、任务工作区和精确文件操作权限，并由独立File验证策略复核；通用业务MCP签发器、业务token映射或业务audience验证器 MUST NOT替代、包装或放宽该路径。

#### Scenario: 同一 Job 同时使用业务 MCP 和 File MCP
- **WHEN** Job同时冻结业务MCP Tool和File Tool
- **THEN** 平台分别签发按Server隔离的业务Principal和独立File Principal
- **AND** 两类令牌不得互相作为fallback或通过对方验证策略

#### Scenario: 通用业务签发器收到 file-service
- **WHEN** 调用方以`server_code=file-service`请求通用业务Principal
- **THEN** 身份服务拒绝并要求使用现有File专用签发路径

## MODIFIED Requirements

### Requirement: 本阶段不接入 ONES 业务能力
ONES身份绑定 SHALL 独立于工具运行时，不创建API Capability、API Connection、长期业务调用Token、MCP Tool授权或Job Principal。完成身份绑定本身不得自动授予或触发ONES业务调用；只有独立发布并授权的Business Application Tool被当前RUNNING Job冻结后，平台才可通过本变更定义的通用业务MCP Principal签发路径为该Job提供短时调用身份。

#### Scenario: 完成 ONES 身份绑定
- **WHEN** 用户完成绑定或重新验证但没有经Business Application发布、授权并冻结到Job的ONES Tool
- **THEN** 系统只更新身份事实，不授予、不签发也不触发任何ONES业务调用能力

#### Scenario: 已绑定用户执行授权 ONES Job
- **WHEN** 用户身份有效且当前RUNNING Job冻结了经发布和授权的`ones-mcp` Tool
- **THEN** 身份服务可按独立业务MCP规范为该Job签发短时Principal
- **AND** 该签发不得反向改变用户绑定、内部角色或数据范围
