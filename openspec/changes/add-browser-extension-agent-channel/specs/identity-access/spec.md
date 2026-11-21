## ADDED Requirements

### Requirement: 浏览器插件授权绑定当前平台自然人

平台 SHALL 通过本站已认证的自然人 Session 向发行版插件授权。平台和插件 MUST 内置匹配的公开客户端身份和固定 Chrome 回调，使用请求对应的内网 HTTP Origin（含有效端口）。用户和部署方无需手动登记插件 ID 或平台地址。授权操作 MUST 执行本站 Origin 和 CSRF 校验。一次性授权码 MUST 绑定原 Session、精确插件和回调、有效期及 PKCE S256 challenge，原子兑换为仅用于插件业务 API 的短期凭据。插件 MUST 校验 state；凭据不经 URL、网页脚本、持久化浏览器存储或日志传递。

#### Scenario: 用户从插件登录
- **WHEN** 启用的自然人在平台完成授权，发行版插件在有效期内使用对应 verifier 兑换
- **THEN** 服务端将业务请求绑定到该用户，继续按当前角色检查应用和工具权限；插件凭据不能访问管理 API

#### Scenario: 兑换不可信或过期授权码
- **WHEN** 回调、来源、verifier、父 Session 或有效期不匹配，或同一码再次兑换
- **THEN** 服务端拒绝；两个并发的有效兑换至多一个成功，插件丢弃 state 不匹配的响应

#### Scenario: 仅提供 HTTP 的内网平台首次登录
- **WHEN** 用户在没有既有 Cookie 的浏览器中选择其访问系统的非 localhost 内网 HTTP 平台并首次授权
- **THEN** 平台 MUST 支持在该 HTTP Origin 完成登录、授权与兑换。HTTP 授权会话只可用于插件授权，管理接口拒绝该会话。Origin、CSRF、PKCE、过期和撤销校验继续生效

#### Scenario: 平台地址改变或重定向
- **WHEN** 业务 API 重定向到其他协议、主机或端口，或用户切换配置的平台
- **THEN** 插件 MUST 阻止旧凭据被发送给新 Origin；用户主动切换后重新授权

### Requirement: 插件读写使用当前授权并隔离本人结果

应用列表、录制初始化、分片、发布与进度恢复、提问、会话读取、回答流建立及继续发送数据前 MUST 校验当前插件授权、账号和应用访问；读取历史、增量或终态还 MUST 校验同租户、同用户、同应用和原插件会话归属。服务端 MUST 在撤销、过期或停用后阻止数据继续外发，保留已有 Job 的正常生命周期。

#### Scenario: 回答生成期间原凭据失效
- **WHEN** 用户退出父 Session、被停用、短期凭据到期或失去应用权限
- **THEN** 原订阅停止发送业务数据，持失效凭据的新请求和重连被拒。仅凭据到期可静默换证，父 Session 失效须重新登录，停用或撤销业务权限须停止访问

#### Scenario: 另一个用户持有同一应用的使用权
- **WHEN** 该用户以已知会话 ID 或 Job ID 请求另一人的历史、事件或终态
- **THEN** 服务端拒绝且不返回内容或能区分目标是否存在的信息

#### Scenario: 他人获取录制引用或用户在上传期间失去授权
- **WHEN** 请求者尝试在其他租户、用户、应用、Connector、发布或执行范围内恢复上传或绑定同一引用，或本人权限已撤销
- **THEN** 平台拒绝取回进度、接收分片、发布或绑定，不透露其他边界下录制是否存在

### Requirement: 插件仅凭有效登录会话与既有授权静默续期

插件 SHALL 在有待发问题、在途上传或活动订阅时按平台返回的实际有效期提前续期，错过续期窗口可在恢复业务前静默换证。平台 MUST 在原 Origin 复核有效父 Session、同一用户、发行版插件与固定回调、有效同意范围，以新的 state 和 PKCE 一次性授权码完成兑换。每张凭据最长 15 分钟且受父 Session 剩余有效期限制。插件 MUST 只在内存持有业务凭据，无需长期刷新令牌，空闲时不得以后台续期维持登录。

#### Scenario: 多个操作同时跨过凭据有效期
- **WHEN** 同一身份的提问、上传分片和订阅同时需要换证，且原平台登录与插件授权仍有效
- **THEN** 客户端合并为一次非交互换证，不提示输入密码；迟到的旧凭据失败响应不能清除新凭据或触发循环换证。续期沿用同一 HTTP Origin 的插件专用父 Session

#### Scenario: 需要登录或需要确认授权
- **WHEN** 父 Session 已退出、闲置或绝对过期，或被撤销
- **THEN** 平台拒绝静默签发，插件暂停并提示用户重新登录。若仍已登录，仅缺少用户同意，则由用户主动重新授权。重新认证后仅可用同一身份和仍有效的业务范围恢复原工作

#### Scenario: 网络故障、账号切换与权限拒绝
- **WHEN** 网络暂时不可用、用户换成另一账号，或当前账号停用、插件禁用、业务权限被撤销
- **THEN** 暂时离线保留进度供有限重试；另一账号不得自动继承或重放原操作。权限拒绝停止相应操作，不进入自动登录或换证循环

#### Scenario: 换号后才收到旧换证结果
- **WHEN** 同一浏览器先为账号 A 静默授权，再切换到 B，而 A 的回调或兑换结果较晚返回
- **THEN** 双方 MUST 按发起时的 Origin、state 和账号边界处理，插件丢弃失效流程的结果。只有 credential_expired 进入一次自动换证；login_required、consent_required、access_denied 分别进入登录、确认或停止流程

## MODIFIED Requirements

### Requirement: File Principal 与内部 Service Principal 保持独立边界
File Principal SHALL 使用专用签发与验证路径，绑定用户、租户、RUNNING Job、Session、两个 Publication、授权快照和精确 File Tool scope，并复核任务工作区。既有内部文件调用 SHALL 使用固定角色 `file-worker`、`file-processing-worker`、`delivery-worker` 的 Service Principal；它们共享平台签名信任根和公开 JWKS，但使用独立 issuer、`aud=file-service-internal`、相同 sub/azp 角色和完整固定 scope，TTL 均不超过 300 秒。

浏览器录制仅增加两项资源级委派。平台 SHALL 在用户确认的上传范围内签发单片写授权，绑定录制、片号、摘要与当前应用范围。工具查询单条明细时 SHALL 绑定 RUNNING Job、本轮录制和精确证据 ID，签发前及读取时复核冻结工具与当前权限。两者复用平台签名与 File Service 的公开 JWKS，按调用角色和 scope 独立验证，最长有效期 60 秒。插件、模型和 Runtime 均不得获得内部授权。

#### Scenario: Worker 获取内部身份
- **WHEN** Worker 用自己独立 bootstrap credential 调用内部身份接口
- **THEN** 只签发该角色固定 scope 的短期 Token，Worker 按需在内存刷新，不持有平台签名私钥、其他角色凭据或预生成长期 JWT

#### Scenario: 跨角色或跨认证面调用
- **WHEN** Delivery Token 调用附件导入，Service Principal 调普通 File MCP，或 Business Principal 调文件内部接口
- **THEN** 独立验证策略拒绝，共享 JWKS 不使权限互通

#### Scenario: File Principal 到期
- **WHEN** 仍在运行的 Job 通过受控刷新通道申请新 File Principal
- **THEN** 平台重新校验 Job、租户、工作区与当前授权后签发，不用业务 MCP Token 作为 fallback


#### Scenario: 替换分片或证据
- **WHEN** 调用者替换片号、摘要、应用范围、Job 或证据 ID，或将写授权用于读取
- **THEN** File Service 在访问对象前拒绝，既有 Worker 身份不能换取录制明细

#### Scenario: 工具在权限变化后读取
- **WHEN** 授权签发后 Job 终止、用户撤权、应用发布改变或录制过期
- **THEN** File Service 重新核验时拒绝返回明细，平台与工具日志仅记录安全状态
