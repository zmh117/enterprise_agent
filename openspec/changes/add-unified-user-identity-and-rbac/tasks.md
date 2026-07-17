## 1. 配置、依赖与加法迁移

- [x] 1.1 增加统一身份、Web认证和published Agent runtime功能开关及安全默认值，生产默认禁用test-only身份请求头
- [x] 1.2 增加密码哈希、服务端session和前端构建所需依赖，并更新Docker构建目标与Compose服务边界
- [x] 1.3 创建加法迁移，新增内部用户、密码凭证、外部身份、登录session、角色、用户角色关系及必要唯一约束和索引
- [x] 1.4 创建多Agent加法迁移，新增agent definition、draft revision、publication、tool/skill/channel binding，并为agent_job增加内部主体和固定publication字段
- [x] 1.5 实现legacy主体扫描和对账报告，只迁移可唯一确认tenant的user policy/grant，保持历史session/job/audit不被错误合并
- [x] 1.6 增加本地测试seed的管理员、角色、钉钉绑定和`default-diagnostic-agent`等价初始publication，生产migration不写默认密码

## 2. 统一用户与外部身份

- [x] 2.1 建立identity领域对象和repository，实现内部用户增改查、启停、revision和安全公共投影
- [x] 2.2 实现通用external identity repository，按provider+tenant+subject唯一绑定并支持启停、解绑、last-seen和冲突检测
- [x] 2.3 实现IdentityResolver端口和DingTalk adapter，从受信connector解析tenant并把外部身份解析为内部principal
- [x] 2.4 实现管理员手工绑定应用服务，禁止昵称/手机号/邮箱自动匹配和未知钉钉用户自动provisioning
- [x] 2.5 在用户或身份禁用、解绑时撤销相关session并让后续Web/钉钉请求立即fail closed
- [x] 2.6 实现显式首个管理员bootstrap CLI，支持安全交互输入和重复执行保护

## 3. Web认证与会话安全

- [x] 3.1 实现Argon2id密码哈希、密码验证、修改密码和凭证revision，任何API/审计不得暴露哈希或明文
- [x] 3.2 实现高熵session token、数据库token hash、idle/absolute过期、撤销、最后使用时间和用户级全部撤销
- [x] 3.3 实现FastAPI认证middleware/dependency，把内部principal注入请求并在生产拒绝自报`x-admin-user-id`/`x-agent-user-id`
- [x] 3.4 实现HttpOnly/Secure/SameSite cookie、Origin校验和CSRF token防护，并提供显式本地开发配置
- [x] 3.5 实现登录、退出、当前用户、修改密码和session管理API及限速/安全失败审计

## 4. 角色与统一RBAC求值

- [x] 4.1 实现角色和用户角色repository/service，支持启停、revision、membership管理及审计
- [x] 4.2 实现统一AuthorizationEvaluator，展开用户和角色principal、通配符、资源action、平台grant及deny优先语义
- [x] 4.3 为用户、角色、身份、Agent编辑/发布、平台配置、密钥、工具分配和审计读取定义管理action
- [x] 4.4 重构PermissionService和Internal API Platform访问策略，使用内部用户角色与platform access grant而非原始钉钉ID
- [x] 4.5 生成secret-safe授权decision trace，覆盖allow、deny、disabled、范围不足和冲突优先级
- [x] 4.6 增加shadow-mode旧/新权限决策对比与迁移开关，验证一致后切换统一evaluator

## 5. 用户角色和绑定管理API

- [x] 5.1 实现typed用户列表、详情、创建、更新、启停和revision冲突API
- [x] 5.2 实现typed角色、membership和permission管理API，区分`user:manage`与其它管理action
- [x] 5.3 实现钉钉tenant/connector候选、身份绑定、启停、解绑和冲突查询API
- [x] 5.4 将所有写API接入认证principal、RBAC、expected revision、字段级错误和before/after配置审计
- [x] 5.5 将平台配置和workflow写API迁移到可信principal，保留仅测试环境显式启用的header adapter

## 6. 多Agent配置与发布

- [x] 6.1 实现Agent definition/revision/publication repository和service，所有查询按agent code隔离并支持多Agent
- [x] 6.2 实现默认诊断Agent草稿DTO，覆盖业务指令、模型策略、执行限制、已有只读工具、Skill及Channel/Delivery绑定
- [x] 6.3 实现发布校验，拒绝未注册/禁用/非只读工具、无效Skill/connector、secret明文和试图覆盖平台安全规则的配置
- [x] 6.4 实现不可变publication snapshot、schema version、config hash、发布指针、发布历史和回滚
- [x] 6.5 实现默认Agent的typed读取、保存草稿、校验、发布、回滚、有效配置预览和历史API
- [x] 6.6 创建job时解析并事务固定默认Agent publication ID/revision/hash，未发布或无效配置时fail closed
- [x] 6.7 修改worker、AgentContextBuilder和Claude runtime只读取job固定snapshot，并在外层叠加强制安全规则
- [x] 6.8 修改ToolRegistry，使可用工具为代码注册、工具启用、Agent分配、用户/角色授权和平台数据范围的交集

## 7. 钉钉统一身份接入

- [x] 7.1 扩展Channel外部身份描述，保留provider、tenant、subject、connector和安全display metadata，不直接把subject当内部actor
- [x] 7.2 修改DingTalk Stream adapter优先解析`senderStaffId`并从connector获取tenant/corp，保留senderId/unionId/openId扩展字段
- [x] 7.3 在connector/project许可和job创建前执行IdentityResolver与统一RBAC，未绑定、冲突或disabled身份不得创建session/job
- [x] 7.4 新job/session/message/audit保存内部requester及external_identity_id，私聊session key使用内部用户ID与bot identity
- [x] 7.5 实现未绑定和无权限钉钉用户的快速安全ACK、审计和零queue publish行为

## 8. 管理端Web

- [x] 8.1 创建独立React+TypeScript+Vite前端工程，配置API client、TanStack Query、路由、组件体系、测试和生产静态资源交付
- [x] 8.2 实现登录页、认证恢复、退出、CSRF处理、权限感知导航和统一401/403/409错误体验
- [x] 8.3 实现用户列表/详情、启停、角色分配、活动session和钉钉身份绑定管理页面
- [x] 8.4 实现角色列表/详情、用户membership和管理/Agent/工具/平台范围权限编辑页面
- [x] 8.5 实现默认诊断Agent页面：基础信息、业务指令、模型/限制、只读工具、Skill、Channel/Delivery和有效配置预览
- [x] 8.6 实现Agent草稿校验、发布确认、发布历史和回滚页面，显示revision/hash/actor/time及并发冲突
- [x] 8.7 第一版隐藏多Agent列表、新建和删除入口，并添加测试证明后端存在其它Agent时UI仍只开放默认诊断Agent
- [x] 8.8 实现安全审计查询页面，只显示脱敏身份、权限、绑定和Agent发布事件

## 9. 安全、迁移与端到端验证

- [x] 9.1 补齐密码哈希、session token hash/过期/撤销、CSRF、伪造actor header、登录枚举和用户禁用安全测试
- [x] 9.2 补齐tenant隔离、重复绑定、未知身份、禁用身份、解绑、legacy歧义和钉钉payload脱敏测试
- [x] 9.3 补齐用户/角色allow/deny、priority、工具分配交集、平台数据范围和管理action矩阵测试
- [x] 9.4 补齐Agent草稿并发、发布校验、不可变snapshot、回滚、job版本固定、retry固定版本和安全指令不可覆盖测试
- [x] 9.5 补齐管理API contract、字段级错误、revision冲突、secret-safe响应和配置审计测试
- [x] 9.6 运行PostgreSQL真实迁移与legacy对账，验证既有permission/grant、历史job/session/audit和默认Agent等价行为
- [x] 9.7 运行完整后端测试、ruff、mypy、前端lint/typecheck/unit test、生产构建、Compose配置和OpenSpec严格校验
- [x] 9.8 使用浏览器完成登录、用户/角色/绑定、默认Agent编辑/发布/回滚和权限拒绝端到端测试
- [ ] 9.9 使用真实脱敏钉钉用户验证绑定前拒绝、绑定后共享Web角色权限、工具范围、用户禁用和原会话结果投递
- [x] 9.10 更新README和运维文档，说明首个管理员bootstrap、身份绑定、权限模型、session安全、Agent发布/回滚、feature flags和故障恢复
