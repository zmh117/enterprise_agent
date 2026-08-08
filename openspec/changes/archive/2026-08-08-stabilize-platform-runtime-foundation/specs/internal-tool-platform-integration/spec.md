## MODIFIED Requirements

### Requirement: Internal API requests include execution context
The system SHALL send the persisted Job ID and correlation ID with every Internal API Platform tool request and MUST authenticate with a required service Bearer Token loaded from a file. User, application, project and scope headers MAY be included only for server-side consistency checks.

#### Scenario: Tool request carries authoritative lookup keys
- **WHEN** Agent calls any read-only tool through `HttpInternalApiClient`
- **THEN** the request includes `X-Agent-Job-Id` and `X-Correlation-Id`, plus any non-authoritative consistency headers

#### Scenario: Tool request uses required authorization
- **WHEN** a non-test Worker starts with real internal tools
- **THEN** it loads the service Token from `INTERNAL_API_AUTH_TOKEN_FILE`, sends `Authorization: Bearer <token>`, and never writes the Token to logs, audit or summaries

#### Scenario: Required Token file is absent
- **WHEN** a non-test Worker or Internal API Platform starts without its required Token file
- **THEN** startup must fail instead of accepting unauthenticated tool traffic

## ADDED Requirements

### Requirement: Internal API Platform 必须重新读取 Job 授权事实
Internal API Platform MUST use the authenticated Job ID to load current Job state and its immutable application publication, Handler, Resource Revision and Execution Scope before every tool operation.

#### Scenario: Service Token 有效但 Job 不属于请求范围
- **WHEN** request headers attempt to name a resource outside the loaded Job scope
- **THEN** the platform rejects the request without opening an upstream connection

### Requirement: Internal API 服务 Token 必须支持受控轮换
系统 SHALL 支持 current/next Token 在短暂维护窗口重叠，并使用常量时间比较；完成轮换后 MUST 移除旧 Token。

#### Scenario: 轮换窗口内使用 next Token
- **WHEN** next Token 已部署到服务端并开始逐个更新调用方
- **THEN** current 和 next 均可通过认证，且审计不记录 Token 内容

#### Scenario: 轮换完成
- **WHEN** 所有调用方已切换到 next Token
- **THEN** 运维必须将其提升为 current 并撤销旧 Token
