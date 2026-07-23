## 1. 基线、迁移与功能开关

- [ ] 1.1 记录现有Auth API、Session/CSRF、用户/角色/钉钉身份API、钉钉入口解析、前端静态原型和全部测试基线
- [ ] 1.2 在实施时选择下一个未占用迁移版本，创建`external_identity_connection`、`external_identity_claim`和append-only verification attempt表及索引/约束
- [ ] 1.3 扩展`user_external_identity`的connection、verification status/method、verified actor、Provider上下文、最近验证时间和安全错误码字段
- [ ] 1.4 编写幂等迁移逻辑，从启用的钉钉Stream Connector生成DingTalk Connection，并把可唯一对应的现有钉钉身份迁移为verified/admin_asserted
- [ ] 1.5 对无法唯一找到钉钉Connector的旧身份生成待人工处理记录，禁止猜测tenant或把它错误标记为verified
- [ ] 1.6 增加`FEATURE_EXTERNAL_IDENTITY_MANAGEMENT`、`FEATURE_ONES_IDENTITY_VERIFICATION`、ONES出站超时/响应上限/Host allowlist和本地HTTP例外配置
- [ ] 1.7 增加迁移测试，覆盖空库、已有钉钉绑定、重复迁移、唯一约束、外键、状态约束和现有身份解析兼容性

## 2. 外部身份领域模型与仓储

- [ ] 2.1 建立Connection、ProviderDefinition、ExternalIdentity、Claim、VerificationAttempt和VerifiedExternalSubject领域模型及状态枚举
- [ ] 2.2 实现Connection Provider配置schema，严格限制ONES固定验证模式和DingTalk Connector引用，拒绝任意Method、Path、Header和请求模板
- [ ] 2.3 实现身份可信判定策略，要求human用户、Connection、Identity均enabled且verification status为verified
- [ ] 2.4 实现Claim状态机和expected revision，覆盖pending、verified、conflict、rejected、expired、cancelled及非法转换
- [ ] 2.5 实现Provider上下文schema，ONES只允许去重排序的team UUID列表，DingTalk只保留受控tenant/connector信息
- [ ] 2.6 扩展IdentityRepository，实现Connection CRUD、Claim CRUD/并发更新、verification attempt追加、身份验证字段更新及管理员分页查询
- [ ] 2.7 实现原子“创建或刷新Identity并完成Claim”，在subject属于其它用户时保留原Identity并将Claim转为conflict
- [ ] 2.8 为状态机、可信判定、唯一性、重复验证、并发Claim、服务账号拒绝和Repository事务编写单元/集成测试

## 3. Provider端口与ONES安全验证Adapter

- [ ] 3.1 定义`ExternalIdentityVerifier`端口和短生命周期Verification Proof，保证Proof不能传给Repository或Audit
- [ ] 3.2 实现DingTalk管理员确认Adapter，复用ConnectorRegistry校验启用、ingress方向和tenant一致性
- [ ] 3.3 实现ONES Password Adapter，使用代码内固定登录Path、POST和JSON Content-Type调用受信Connection
- [ ] 3.4 对ONES Connection执行scheme、Host、allowlist、生产HTTPS和显式本地HTTP例外校验，禁止请求级URL和环境代理继承
- [ ] 3.5 禁止ONES请求跟随重定向，设置连接/读取超时和响应大小上限，并严格校验JSON Content与响应schema
- [ ] 3.6 从响应只提取`user.uuid`、允许的显示名称和`teams[].uuid`，在Adapter边界丢弃`user.token`和原始响应
- [ ] 3.7 将401、限流、超时、连接失败、响应过大和协议错误映射为稳定安全错误码，不回显email或上游正文
- [ ] 3.8 实现按内部用户、Connection和来源地址的ONES验证限流，达到上限后不得继续请求ONES
- [ ] 3.9 使用Fake Verifier编写应用测试，并对独立ONES Mock编写可选集成测试，覆盖成功、错误密码、无UUID、无team、重定向、超时、过大响应和重复team
- [ ] 3.10 增加敏感数据契约测试，证明password和ONES Token不进入Identity、Claim、Attempt、Cache、异常、API响应、日志或Audit

## 4. 通用身份服务、权限和管理API

- [ ] 4.1 将现有钉钉专用绑定逻辑重构到通用External Identity应用服务，同时保持旧钉钉端点响应兼容
- [ ] 4.2 实现Connection创建/更新/停用、管理员创建pending Claim、用户自助验证、身份启停/撤销和Claim取消/拒绝用例
- [ ] 4.3 实现冲突治理用例，只允许保留现有绑定、拒绝或取消Claim；禁止一键强制转移
- [ ] 4.4 实现重新验证用例，幂等刷新同一用户Identity的last verified和team上下文，不创建重复身份
- [ ] 4.5 增加`identity_connection:manage`、`identity_conflict:resolve`和`identity:self_verify`权限及本地管理员/普通用户seed
- [ ] 4.6 扩展`/api/auth/me`能力摘要，并增加不含Secret的认证前端配置端点返回Web启用状态和CSRF Cookie名称
- [ ] 4.7 实现Provider目录、Connection、全局Identity/Claim/Conflict、用户Identity/Claim和`/api/me`个人身份API
- [ ] 4.8 所有新请求模型使用`extra=\"forbid\"`、长度/数量限制、Secret类型和expected revision，拒绝客户端提交URL、Token或未知字段
- [ ] 4.9 对管理员API执行对象级RBAC与CSRF，对`/api/me`验证强制当前用户拥有Claim，防止通过路径或请求体代替他人验证
- [ ] 4.10 记录Connection、Claim、验证、冲突、启停和撤销审计，payload只保留actor、资源ID、Provider、Connection、outcome和安全错误码
- [ ] 4.11 增加API契约测试，覆盖401、403、404防枚举、CSRF、422、409、429、功能开关、服务账号和跨用户访问

## 5. 前端Router、认证与统一API Client

- [ ] 5.1 增加React Router和TanStack Query依赖并更新lockfile，建立`app/router`、`contexts/auth`和`shared/api`目录
- [ ] 5.2 实现统一API Client，默认同源`credentials: include`，根据公开Auth配置读取CSRF Cookie并为写请求发送Header
- [ ] 5.3 实现结构化API错误，区分401、403、404、409、422、429和后端不可用，禁止自动无CSRF重试
- [ ] 5.4 实现`auth.me`查询和unknown/authenticated/anonymous状态机，Session恢复期间不得渲染受保护业务数据
- [ ] 5.5 实现受保护路由、权限路由、站内return path校验、登录后回跳和已登录访问登录页重定向
- [ ] 5.6 实现登录页，包含限流/错误状态、防重复提交、密码字段清理、窄屏和键盘/辅助技术支持
- [ ] 5.7 实现认证后的Platform Shell、用户菜单和基于能力的导航；后端授权仍为最终安全边界
- [ ] 5.8 实现全局401处理清除认证与敏感Query缓存，403保持登录态并显示无权限页
- [ ] 5.9 实现安全设置页，连接修改密码、Session列表、自助撤销和退出；修改密码或退出后返回登录页
- [ ] 5.10 增加认证测试，证明前端不把Session Token放入Local/Session Storage、URL、Query Cache、日志或页面

## 6. 用户与多Provider外部身份真实工作区

- [ ] 6.1 建立users和external-identities的domain/application/infrastructure/presentation分层及Zod响应边界
- [ ] 6.2 实现真实用户列表和用户详情，展示状态、账号类型、角色摘要、Identity、Claim和Session，不使用Dashboard用户fixture
- [ ] 6.3 实现用户创建、编辑、启停和管理员Session撤销，全部携带expected revision并处理409
- [ ] 6.4 实现Connection列表、创建、编辑和停用页面，ONES只允许受控Base URL/Host策略，DingTalk只允许选择受信Connector
- [ ] 6.5 实现管理员为用户创建pending Claim、审核钉钉身份、启停/撤销Identity和查看验证历史
- [ ] 6.6 实现全局Identity/Claim/Conflict治理页，展示安全摘要且不提供强制转移按钮
- [ ] 6.7 实现“我的外部身份”，普通用户只能查看自己的Identity/Claim并对自己的ONES Claim发起验证
- [ ] 6.8 实现ONES验证表单，password不进入URL、history state、Query Cache、Toast详情或遥测，提交完成后立即清空
- [ ] 6.9 展示Provider、Connection、subject、验证状态/方法、last verified和team数量，并明确“身份关联不等于授权”
- [ ] 6.10 将Dashboard身份原型的“管理关联”入口连接到真实路由，保留产品说明但不得用fixture冒充管理数据
- [ ] 6.11 为用户、Connection、Claim、ONES验证、冲突、权限、revision错误和敏感字段边界增加前端测试
- [ ] 6.12 验证桌面/窄屏、键盘焦点、Dialog/Select交互、错误摘要、状态文字和不依赖颜色的可访问性

## 7. Compose、Mock、Seed与文档

- [ ] 7.1 更新`.env.example`和Compose环境变量，默认关闭新增功能；为容器访问本地ONES Mock提供明确且不影响生产的Host方案
- [ ] 7.2 提供幂等本地seed，创建明显的Mock ONES Connection和pending Claim，但不得写入真实地址、账号或Token
- [ ] 7.3 更新前端README，移除“无登录、无API”的旧边界并说明同源Cookie、CSRF、权限导航和开发登录流程
- [ ] 7.4 编写外部身份运维文档，说明Connection、Claim、验证、冲突、停用、迁移和审计排障流程
- [ ] 7.5 编写ONES身份验证文档，明确只保存UUID/team上下文，不保存Token，业务查询必须等待API Capability
- [ ] 7.6 编写现有钉钉绑定迁移与回滚说明，要求迁移前后按真实`senderStaffId`验证同一内部用户和权限

## 8. 端到端与安全验收

- [ ] 8.1 运行迁移和seed两次，证明幂等且现有用户、角色、Session、钉钉Identity和Job不被错误改写
- [ ] 8.2 启动PostgreSQL、API、Admin Web和独立ONES Mock，验证登录→Session恢复→用户详情→ONES Claim→自助验证→Identity/team上下文完整链路
- [ ] 8.3 验证同一用户重复ONES登录幂等、另一个用户验证相同subject产生conflict且原Identity不变
- [ ] 8.4 验证Connection/Identity/用户任一停用都会阻止新验证或解析，并且重新启用不会绕过Identity自身状态
- [ ] 8.5 验证错误密码、重定向、超时、协议错误、响应过大、限流和功能开关关闭均fail closed且无敏感回显
- [ ] 8.6 回归钉钉Stream已绑定用户可以继续创建Job，未知/disabled/conflict身份仍在持久化和MQ发布前被拒绝
- [ ] 8.7 运行后端ruff、mypy和全部pytest，以及前端lint、typecheck、测试和production build
- [ ] 8.8 使用真实浏览器检查登录、Session过期、权限导航、用户/身份管理、ONES密码清理、桌面与移动端行为和Network请求
- [ ] 8.9 扫描数据库、API响应、日志、审计、前端存储、代码、fixture和文档，确认不存在真实ONES IP/邮箱/UUID/Token或任何验证密码
- [ ] 8.10 执行`openspec validate connect-admin-auth-and-external-identity-management --strict`并逐项核对三份规格中的全部场景
