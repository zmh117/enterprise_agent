## 1. 契约基线与依赖隔离

- [x] 1.1 为 `ones-mcp-server` 和 `data-mcp-server` 建立独立包、锁文件与镜像，并精确固定官方 `mcp==2.0.0`
- [x] 1.2 升级 Agent Worker 到 2026-08-08 官方最新版 `claude-agent-sdk==0.2.134`，保持其 `mcp<2.0.0` 依赖边界，并增加构建检查防止三个环境被错误合并
- [x] 1.3 先增加 MCP 1.x 客户端连接 v2 Server 的 Streamable HTTP 协议协商测试，验证当前 Agent Loop 无需升级
- [x] 1.4 定义共享的 MCP Token Claims、Principal、Job Context、Tool Error、Provenance 与 Resource Deployment 契约并生成兼容性测试
- [x] 1.5 建立旧表、交叉外键、保留基础表和删除代码的机器可校验清单，明确不包含备份、导出或数据转换步骤

## 2. 统一身份与新 Provider Credential

- [x] 2.1 增加受信 ONES Provider Instance 与新 `provider_credential` schema，凭据只关联 `app_user`、精确外部身份和 Provider Instance
- [x] 2.2 增加 `REVERIFICATION_REQUIRED` 身份状态及约束，确保保留的 ONES 身份在没有新凭据时不能调用 MCP Tool
- [x] 2.3 为系统账号、钉钉企业 subject、ONES 实例 user UUID 与 `app_user` 的唯一映射增加数据库约束和并发冲突测试
- [x] 2.4 将 ONES 两阶段 Challenge 改为受信 Provider Instance 契约，确保密码请求结束前丢弃且 Token 只加密存在于短时 Challenge
- [x] 2.5 实现 Challenge 确认事务，原子保存身份、最新 Team 集合、默认 Team、新 Provider Credential 和消费状态
- [x] 2.6 实现钉钉短时单次 Challenge 本人绑定，稳定主体只能来自受信钉钉事件且不能由浏览器填写
- [x] 2.7 实现解绑、重新验证、Token 轮换、默认 Team 变化和外部主体冲突状态机，并覆盖本人/管理员权限边界
- [x] 2.8 增加切换测试：保留身份与默认 Team、删除旧 `external_api_credential` 和旧 Challenge、不复制密文、强制本人重新验证

## 3. MCP 服务鉴权与 Agent Runtime

- [x] 3.1 实现平台 MCP Token 签发器，限制 issuer、audience、subject、authorized party、job、scope、JTI 与最多十五分钟有效期
- [x] 3.2 在两个 MCP Server 实现统一鉴权中间件，验证签名、audience、expiry、scope、Job 当前状态与撤销事实
- [x] 3.3 使用 MCP v2 `Resolve` 注入 Principal、Job、ONES Client、Resource Context 和 Provider Client，并证明隐藏字段不进入 Tool Schema
- [x] 3.4 改造 Agent Worker，使其只根据 Job 精确发布事实连接固定 Server 并生成精确 Tool allowlist，不自动发现平台全部 Tool
- [x] 3.5 删除 Agent Worker 的旧进程内 Capability MCP 注册与执行分支，保持 Bash、Write、Edit、WebFetch、WebSearch、Shell 和脚本不可用
- [x] 3.6 实现不可用 MCP Tool 的固定安全提示，确保提示不注册 Tool、不泄露主体/凭据/资源事实且不扩大权限
- [x] 3.7 实现 MCP Tool Call provenance 与有界 attempt 记录，保存版本、Schema Hash、Job、主体/资源/凭据 Revision、结果 Hash、大小和关联 ID
- [x] 3.8 增加伪造 Header、错误 audience、过期 Token、越权 Tool、模型伪造 user/team/resource 和跨 Job 隔离测试

## 4. ONES MCP Server

- [x] 4.1 建立 ONES MCP 健康检查、结构化错误和代码拥有的 Tool Registry，不执行真实业务查询作为进程健康条件
- [x] 4.2 按新契约重新实现已验收的 ONES 工作项只读 Tool 及严格输入输出 Schema，不读取旧 Capability/Handler/Mapping 数据
- [x] 4.3 实现服务端主体解析，按 `sub + job_id` 复核 app_user、ONES Identity、默认 Team、binding revision 与新 Provider Credential
- [x] 4.4 实现 ONES Client 隐藏依赖，确保个人 Token 不进入 Agent Worker、Tool 参数、前端、日志或持久化请求体
- [x] 4.5 实现 ONES 401 原子标记凭据 `INVALID` 且停止重试、403 保持凭据有效的错误分类
- [x] 4.6 为结果条数/字节上限、超时、不可信文本标记、提示注入和原始响应不落库增加契约测试
- [x] 4.7 覆盖用户未重新验证、身份禁用、默认 Team 改变、Token 轮换和 Job 主体快照不匹配的失败关闭测试

## 5. Data MCP Server 与 Resource Runtime

- [x] 5.1 建立 Data MCP 健康检查、Resource Resolver、连接池接口和代码拥有的 DB/Redis/Loki Tool Registry
- [x] 5.2 按新契约重新实现允许的数据库 Schema/描述/有界诊断 Tool，禁止任意 SQL、DDL、DML 和连接参数输入
- [x] 5.3 按新契约重新实现 Redis 前缀内只读诊断 Tool，禁止任意命令、写入、跨前缀扫描和连接参数输入
- [x] 5.4 按新契约重新实现 Loki 结构化只读查询 Tool，服务端注入范围、时间窗和上限并禁止自由 LogQL
- [x] 5.5 实现稳定 Resource Identity、Draft、内容 Hash Verification、不可变 Revision 与唯一 MCP Resource Deployment schema
- [x] 5.6 实现按 Deployment、精确 Resource Revision 与 Secret active version 构建不可变 generation 并原子热切换
- [x] 5.7 实现同一 Resource Revision 的精确 Last Known Good，禁止 Job 浮动到其他 Revision
- [x] 5.8 增加未配置、取消发布、多个活动 Deployment、Secret 失效、精确 LKG 缺失、结果超限和只读权限测试

## 6. platformctl 与声明式运维

- [x] 6.1 实现 `platformctl` 登录、Session/CSRF 获取与 `0600` 本地会话存储，禁止在输出和日志记录认证材料
- [x] 6.2 定义 DB、Redis、Loki Manifest Schema 与脱敏 diff，客户端和服务端均拒绝明文 Secret、`env:`、`vault:`、`kms:` 和未知字段
- [x] 6.3 实现 `resource plan/apply/verify/publish/status/unpublish/draft-from-revision`，所有写入经过 RBAC、expected revision、幂等键和审计
- [x] 6.4 实现 `secret create/rotate/disable/usages`，明文只从 stdin 或受保护文件描述符读取且不进入命令历史
- [x] 6.5 实现 Secret active version 变更触发 runtime generation，Resource Ref 未变化时不得强制重发 Revision
- [x] 6.6 实现 `mcp status/tools` 的只读 Server 版本、Schema Hash、健康与允许集合检查
- [x] 6.7 实现 `cutover check/clean/verify` 维护命令，要求精确对象清单、停机断言和显式不可恢复确认，但不得创建备份或导出
- [x] 6.8 增加 CLI 并发冲突、未授权、重复请求、输出脱敏、Manifest 明文扫描和取消发布 E2E 测试

## 7. 轻量用户门户

- [x] 7.1 收缩路由与导航，只保留登录/退出/修改密码/Session、本人身份、会话/Job 历史、MCP Tool Call 与 Delivery 调试
- [x] 7.2 实现本人钉钉 Challenge、ONES 两阶段验证、默认 Team、重新验证和解绑页面，浏览器不得提交目标 user ID 或显示 Token
- [x] 7.3 将历史页面改为展示 MCP Server/Tool/Resource/Credential 的脱敏 provenance、步骤、结果摘要和投递状态
- [x] 7.4 删除 Agent、Capability、Handler、Connection、Resource、Secret、角色授权、Runtime Config 和 Business Application 工作台页面及其 API Client
- [x] 7.5 为旧管理 URL 提供明确已移除结果，并删除隐藏表单、静态 fixture、悬空导航和已退役模块的查询缓存
- [x] 7.6 增加未认证、防枚举、本人/他人数据隔离、revision 冲突、敏感字段扫描、键盘操作、窄屏和生产构建测试

## 8. 旧平台代码与数据彻底退役

- [x] 8.1 编写破坏性 schema 清理，直接删除 Capability、Handler、Connection、Authentication Profile、Mapping、Release、Capability Publication 组合及专属审计数据
- [x] 8.2 在同一清理中删除 Internal API Platform Resource/Revision/Runtime Snapshot、旧协议 Tool、HTTP attempt、Capability provenance 与阻塞外键
- [x] 8.3 删除依赖旧 Runtime 的 Job、Step、Tool Call、attempt、result 和专属 Delivery 关联，不转换、不重试、不隔离保存
- [x] 8.4 删除旧 `external_api_credential`、旧 ONES Challenge 和密文 Token，并验证清理过程没有备份、导出、解密或 Provider Credential 回填
- [x] 8.5 为 `app_user`、密码 Hash、Session、钉钉/ONES 稳定身份、默认 Team 元数据及通用 Ingress/Outbox/Delivery 建立保留断言
- [x] 8.6 删除 `api_capability` 与 `internal_api_platform` 后端模块、路由、客户端、权限、测试和可重新启用旧路径的 Feature Flag
- [x] 8.7 删除 Internal API Platform Compose 服务、环境变量、依赖包和网络路由，并更新 `.env.example` 与部署文档
- [x] 8.8 增加静态扫描和数据库检查，证明旧表/列/路由/Tool 名/Compose 服务/前端导入均不存在且旧历史不可查询

## 9. 部署、安全与可观测性

- [x] 9.1 将 ONES MCP 和 Data MCP 加入 Compose，配置独立健康检查、资源限制、超时、请求大小、网络与重启策略
- [x] 9.2 为 API/Worker/MCP 服务配置最小数据库权限和独立服务身份，Master Key 只读挂载到实际解密服务且不进入前端、Worker 或代理
- [x] 9.3 固定 MCP Server 地址与允许 Server Code，配置 TLS/服务鉴权边界且不引入动态 Gateway 或第三方 MCP 注册
- [x] 9.4 增加不执行真实业务查询的 readiness、generation 状态、degraded/LKG、调用耗时、错误分类和 correlation ID 指标
- [x] 9.5 增加日志、审计、API、CLI、前端构建产物与 Tool 结果的 Secret/Token/Header/连接信息扫描

## 10. 破坏性切换与验收

- [x] 10.1 编写维护窗口 Runbook，明确停止入口与 Worker、拒绝新 Job、检查旧进程退出、执行不可恢复删除和恢复入口条件
- [ ] 10.2 在可丢弃测试环境完整演练清空旧数据、初始化新 schema、从空状态创建 Secret/Resource/Deployment 和用户重新验证流程
- [ ] 10.3 验证旧数据为空时，系统登录、Session、钉钉 Challenge、ONES 重新验证、默认 Team 与渠道身份仍能正确工作
- [ ] 10.4 验证 Agent Worker 到 ONES MCP 和 Data MCP 的 ONES/DB/Redis/Loki 只读链路、精确 allowlist、取消发布和凭据轮换
- [ ] 10.5 验证 Runtime → Inbox → Outbox → RabbitMQ → Job → Worker → MCP → Delivery 的完整真实链路及失败诊断
- [ ] 10.6 验证服务重启、MCP Token 过期、Provider 401/403、Resource generation 失败和 Delivery 重试均保持失败关闭与安全审计
- [ ] 10.7 只有测试环境破坏性演练与全部新链路验收通过后，才允许在用户明确安排的生产维护窗口执行同一不可恢复清理
- [x] 10.8 切换后确认旧历史为空属于预期、轻量门户无悬空入口、`/api/ready` 与各 MCP 健康状态正常，并记录最终验收证据
