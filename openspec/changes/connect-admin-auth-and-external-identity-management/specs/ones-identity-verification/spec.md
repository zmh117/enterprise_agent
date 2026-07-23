## ADDED Requirements

### Requirement: ONES验证只通过受信Connection发起
系统 SHALL 使用已启用ONES Connection中的固定Base URL和代码内固定登录Path执行身份验证，MUST NOT接受浏览器或请求体提供的URL、Method、Path、Header或代理。

#### Scenario: 使用已启用ONES Connection
- **WHEN** 用户验证属于自己的pending Claim且Connection启用
- **THEN** 后端向该Connection的`/project/api/project/auth/login`发送固定JSON登录请求

#### Scenario: Connection未启用
- **WHEN** Claim引用disabled、未知或非ONES Connection
- **THEN** 系统拒绝验证且不发起网络请求

#### Scenario: 请求尝试覆盖URL
- **WHEN** 客户端提交Base URL、Path、Header或重定向目标等未定义字段
- **THEN** API返回422并拒绝整个请求

### Requirement: ONES验证材料只存在于单次请求内
系统 MUST 把ONES email和password作为短生命周期Verification Proof，并 MUST NOT将password或登录响应Token写入数据库、Identity、Claim、Verification Attempt、Cache、日志、审计、API响应或浏览器持久化存储。

#### Scenario: 验证成功
- **WHEN** ONES返回包含用户UUID、Token和团队的成功响应
- **THEN** Adapter提取允许字段并丢弃Token和原始响应
- **AND** Service、Repository和前端只接收不含Token的规范化主体

#### Scenario: 验证失败
- **WHEN** ONES拒绝email/password
- **THEN** 系统返回统一凭据失败错误并清空前端密码字段
- **AND** 错误和审计不包含email、password、Token或上游正文

#### Scenario: 运行日志扫描
- **WHEN** 成功或失败验证完成
- **THEN** 日志只包含correlation ID、Connection、actor、outcome和安全错误码
- **AND** 不包含请求体或响应体

### Requirement: ONES响应被严格校验并规范化
系统 SHALL 限制响应大小、要求JSON并校验`user.uuid`、可选展示字段和`teams[].uuid`，MUST 拒绝缺少稳定subject或团队上下文的响应。

#### Scenario: 合法登录响应
- **WHEN** ONES返回非空`user.uuid`、用户展示信息、Token和至少一个team UUID
- **THEN** 系统将`user.uuid`作为external subject ID
- **AND** 只把去重排序后的team UUID列表保存为受控Provider上下文

#### Scenario: 响应缺少user UUID
- **WHEN** 上游返回200但`user.uuid`为空、类型错误或缺失
- **THEN** 系统将响应视为协议错误并不创建Identity

#### Scenario: 响应过大或不是JSON
- **WHEN** 上游响应超过限制或Content不符合JSON契约
- **THEN** 系统中止解析并返回安全上游协议错误

### Requirement: ONES网络访问执行出站安全策略
系统 MUST 校验Connection scheme、Host和allowlist，禁止重定向和环境代理继承，并 SHALL 应用连接超时、读取超时与响应上限。

#### Scenario: 生产HTTPS连接
- **WHEN** 生产Connection使用allowlist中的HTTPS Host
- **THEN** 系统允许固定登录请求并执行证书校验

#### Scenario: 生产HTTP连接
- **WHEN** 生产Connection使用HTTP或Host不在allowlist
- **THEN** 系统拒绝保存或调用该Connection

#### Scenario: 本地Mock连接
- **WHEN** 开发环境显式允许insecure local且Host命中本地开发allowlist
- **THEN** 系统可以调用独立ONES Mock
- **AND** 该例外不能在生产配置中默认启用

#### Scenario: 上游重定向
- **WHEN** ONES登录端点返回重定向
- **THEN** Adapter拒绝跟随并返回安全连接错误

### Requirement: ONES验证具备限流和安全失败分类
系统 SHALL 按内部用户、Connection和来源地址限制验证频率，并 MUST 将凭据失败、限流、超时、连接失败和协议错误映射为不泄露上游细节的稳定错误码。

#### Scenario: 连续错误密码
- **WHEN** 用户在窗口期内超过允许的失败次数
- **THEN** 系统暂时拒绝新的ONES验证并返回429或等效限流错误
- **AND** 不再向ONES发送登录请求直到窗口恢复

#### Scenario: ONES超时
- **WHEN** 连接或读取超过配置时限
- **THEN** 系统返回可重试上游不可用错误
- **AND** Claim保持pending且不创建Identity

#### Scenario: ONES返回401
- **WHEN** 上游拒绝登录
- **THEN** 系统返回统一`ones_credentials_invalid`或等效错误
- **AND** 不说明邮箱是否存在

### Requirement: 成功验证原子绑定ONES身份
系统 MUST 在单一事务中校验Claim revision、内部用户、Connection、唯一subject和现有Identity，然后创建或刷新Identity并完成Claim。

#### Scenario: 新ONES主体验证成功
- **WHEN** 规范化subject尚未绑定且Claim、用户、Connection均有效
- **THEN** 系统创建verified/provider_login Identity并把Claim标记为verified

#### Scenario: 同一用户重复验证
- **WHEN** subject已经属于当前内部用户
- **THEN** 系统幂等刷新last verified和team上下文
- **AND** 不创建第二条Identity

#### Scenario: subject属于其它用户
- **WHEN** subject已经绑定另一个内部用户
- **THEN** 系统把Claim标记为conflict并保留原Identity
- **AND** 不返回另一个用户的敏感详情

### Requirement: ONES团队上下文不等于授权
系统 SHALL 保存经过验证的team UUID列表和last verified时间用于后续身份上下文，MUST NOT把team UUID自动转为内部角色、项目范围、Capability授权或业务调用Token。

#### Scenario: 用户属于多个team
- **WHEN** ONES登录响应包含多个合法team UUID
- **THEN** Identity保存去重后的team列表并在页面展示安全摘要
- **AND** 用户内部RBAC保持不变

#### Scenario: team成员关系变化
- **WHEN** 用户重新验证后team列表发生变化
- **THEN** 系统以新验证结果更新Provider上下文并记录前后数量
- **AND** 不自动删除或新增平台授权

### Requirement: ONES Mock用于无真实凭据的集成验证
系统 SHALL 支持在开发测试中通过`docker-compose.ones-mock.yml`验证登录、subject/team提取、重复绑定、冲突和错误路径，并 MUST 使用明显的Mock凭据与标识。

#### Scenario: 使用Mock成功验证
- **WHEN** 开发环境指向本地ONES Mock并提交文档中的假凭据
- **THEN** 系统建立`MOCK-*` Identity和team上下文
- **AND** 数据库、日志和审计中不存在Mock返回Token

#### Scenario: 仓库敏感信息扫描
- **WHEN** 执行交付检查
- **THEN** 新增代码、测试、fixture和文档不包含真实ONES IP、邮箱、用户UUID、团队UUID或Token
