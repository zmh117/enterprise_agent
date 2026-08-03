## 1. 实施前边界与契约基线

- [x] 1.1 复核 `stabilize-platform-runtime-foundation` 及其他在途变更，记录内部代码注册表 Handler 与 `cap__*` 声明式外部 Handler 的模块、表名和解析器边界
- [x] 1.2 为 Capability Identifier、Revision、Release、Connection、Authentication Profile、Mapping Plan、Credential、Challenge 和 External Execution Subject Snapshot 建立后端领域类型与枚举测试
- [x] 1.3 定义公开 Input/Output Schema、Mapping AST、编译计划、发布快照和运行时错误的版本化 JSON 契约，并为未知字段/版本补充失败关闭测试
- [x] 1.4 定义 `api_connections.*`、`api_capabilities.*`、`external_credentials.*` 权限种子与授权矩阵，并证明不创建 Capability `use` Grant
- [x] 1.5 明确旧 Agent/Application snapshot schema 的向前兼容读取规则：缺少 Capability 字段时解析为空集合

## 2. 数据库迁移与持久化

- [x] 2.1 新增 API Connection、Connection Revision、Authentication Profile 与 Profile Revision 表、状态约束、不可变字段保护和索引
- [x] 2.2 新增 API Capability、Capability Revision、Handler、Handler Revision、Compiled Mapping Plan、Capability Release 与 Draft/Verify Evidence 表
- [x] 2.3 为 Capability Identifier 全局唯一、`cap__` 保留前缀、同 Identifier 单调 Release Revision、精确 Revision 外键和发布幂等键建立数据库约束
- [x] 2.4 新增 External API Credential 与 Verification Challenge 表，使用密文字段、过期/单次消费状态及每用户单个有效 ONES 账号约束
- [x] 2.5 扩展 Agent Publication 与 Application Publication snapshot，分别冻结 Agent Capability Envelope 与 Application Capability Allowlist
- [x] 2.6 扩展 Agent Job、Tool Call 和 attempt/provenance 持久化，保存非密钥主体快照、Release、数据分级和安全结果摘要
- [x] 2.7 实现各聚合 Repository 与事务端口，并为 Revision 不可变、乐观锁、幂等发布和并发唯一约束编写 PostgreSQL 集成测试
- [x] 2.8 增加非破坏迁移投影，使现有 ONES identity-only 记录显示 credential missing，且不伪造 Token或删除历史身份

## 3. API Connection 与 Authentication Profile

- [x] 3.1 实现 Connection Draft 创建、读取、更新、验证证据失效、发布、禁用和归档应用服务及管理 API
- [x] 3.2 实现 Origin 规范化与校验，拒绝 userinfo、动态 host、完整 Handler URL、生产 HTTP 和跨 Origin 重定向
- [x] 3.3 实现 Connection 受限 HTTP 客户端，覆盖连接/读取超时、响应大小、JSON content 和同 Origin认证传播
- [x] 3.4 实现 Authentication Profile 的固定登录请求、User/Team/Token 提取和认证 Header 注入规则校验
- [x] 3.5 实现首个 ONES Connection 的当前管理员临时自验证，确保密码与 Token 不进入持久化、缓存、日志、审计或响应
- [x] 3.6 实现 Connection Publish 的内容 hash、证据匹配和不可变 Revision，并验证新 Revision 不使旧 Release 漂移
- [x] 3.7 为 HTTPS、本地 Mock HTTP、重定向、超大响应、坏 JSON、字段提取失败和禁用 Revision 编写单元与集成测试

## 4. ONES 外部身份与个人凭据

- [x] 4.1 在 identity bounded context 中实现与平台共享 Secret 分离的 External API Credential 加密、解析、轮换、禁用和 invalid 状态
- [x] 4.2 实现本人绑定第一阶段 API：从认证会话解析当前用户、调用精确发布版本、丢弃密码并创建短时单次加密 Challenge
- [x] 4.3 实现本人绑定第二阶段 API：校验 Challenge 所有者/版本/过期/单次性及 Team候选，并原子保存身份、Team集合、default Team和加密Token
- [x] 4.4 实现重新验证与切换 default Team，强制刷新当前 Team集合且禁止从历史集合直接选择
- [x] 4.5 实现每用户单个有效 ONES主体的幂等重绑、显式换绑和跨内部用户冲突处理
- [x] 4.6 实现本人 self_manage 与管理员 read/disable/unbind API，确保管理员不能代用户登录、读取或轮换Token
- [x] 4.7 实现软解绑同时停用身份和凭据，并实现401使凭据invalid、403保留凭据状态的原子操作
- [x] 4.8 为Challenge重放、过期、跨用户、候选外Team、并发确认、旧身份迁移及密钥不泄露编写测试

## 5. Capability Draft、Mapping 与发布控制面

- [x] 5.1 建立 `api_capability` bounded context 的模块结构、领域端口、Controller和依赖注入，不修改现有内部Handler注册表职责
- [x] 5.2 实现专用 Capability Identifier校验器，并为合法双下划线、长度、大小写、非法层级和内部Tool前缀冲突编写测试
- [x] 5.3 实现严格公开 Input/Output Schema校验，支持已确认字段约束并拒绝系统拥有字段、未知字段和越界默认值
- [x] 5.4 实现统一 ApiCapabilityDraft 的五区域读写模型、`expected_revision` 乐观锁和内容规范化 hash
- [x] 5.5 实现 Mapping AST 白名单解析与静态检查，覆盖字段投影、对象重组、数组逐项映射、固定默认值和基础标量转换
- [x] 5.6 实现 Mapping 编译器并持久化不可变 schema version、canonical plan与SHA-256，拒绝条件、过滤、拼接、日期、正则、函数、脚本和部分成功
- [x] 5.7 实现 Capability Test，使用当前管理员正式绑定并返回结构性排除认证材料的 Method/relative path/query/body/normalized output预览
- [x] 5.8 实现 Capability Verify，保存绑定 Draft Revision/content hash的安全证据，并在任一相关配置变化时失效
- [x] 5.9 实现单事务幂等 Publish：创建或复用Capability Revision、创建Handler Revision、编译Mapping Plan、冻结依赖并创建单调Release
- [x] 5.10 实现Handler-only、公开Schema和业务含义三类变更的版本规则校验与复制历史Release为新Draft
- [x] 5.11 实现Release ACTIVE/DEPRECATED/DISABLED/ARCHIVED状态、replacement/reason、依赖归档保护和状态审计
- [x] 5.12 为未验证发布、hash漂移、幂等重放、事务回滚、并发保存和发布后原地修改编写应用层与数据库测试

## 6. 固定 http-json-v1 运行时

- [x] 6.1 实现受治理 Capability Release resolver，校验快照完整性并只返回固定 `http-json-v1` 和已编译 Mapping Plan
- [x] 6.2 实现 Input Schema验证与 Request Mapping解释器，严格区分 Agent Input、System Context和固定常量来源
- [x] 6.3 实现当前用户 Credential Resolver和同 Origin认证注入，保证Token不进入领域对象、Tool参数或可序列化预览
- [x] 6.4 实现受限外部HTTP attempt执行、内存JSON解析、Response Mapping和Output Schema全有或全无校验
- [x] 6.5 实现QUERY故障分类与Tool预算内最多两次退避重试，并确保非重试错误不进入Job级重复循环
- [x] 6.6 实现401凭据失效、403保留凭据及400/404/超大/坏JSON/Mapping/Schema错误安全分类
- [x] 6.7 实现每attempt安全记录与一个关联Tool Call汇总，结构性排除请求认证部分、原始响应和业务正文
- [x] 6.8 为所有Mapping节点、转换失败、数组错误、未知计划版本、重试边界、超时预算和无原始响应落盘编写测试

## 7. Agent 与 Application 发布组合

- [x] 7.1 实现ACTIVE Capability Release管理目录投影，返回名称、Identifier、description、Release Revision、状态及管理端release_note
- [x] 7.2 扩展 Agent Draft/Publish API，为同一Identifier最多选择一个精确ACTIVE Release并冻结Agent Capability Envelope
- [x] 7.3 扩展 Application Draft/Publish API，只接受所选精确Agent Publication Envelope的显式子集并冻结Allowlist
- [x] 7.4 实现Application后端越界校验，拒绝客户端自选Release、Agent未拥有Capability和发布时状态漂移
- [x] 7.5 实现Agent升级时的Application子集重验，针对缺失、DEPRECATED和Schema不兼容要求显式替换或移除
- [x] 7.6 实现旧Agent/Application Publication固定旧Release且不随新Release、replacement或新Agent自动升级
- [x] 7.7 实现DEPRECATED历史可运行但新选择不可用、DISABLED/ARCHIVED全面阻断新调用的目录和解析规则
- [x] 7.8 为Agent上限、应用子集、精确版本、显式升级、旧snapshot兼容和无全局功能开关编写测试

## 8. 钉钉入口与 Job 外部主体快照

- [x] 8.1 扩展钉钉路由解析，以启用连接器、唯一活动Application Publication和每条消息实际sender解析应用访问
- [x] 8.2 移除钉钉Application Access对额外应用用户白名单/角色及Capability use Grant的依赖，同时保持其他Trigger既有策略
- [x] 8.3 为未绑定钉钉身份、停用内部用户和无活动应用路由实现安全中文回复，且不创建错误Job
- [x] 8.4 在Job创建事务中冻结Agent/Application引用、Capability Allowlist及ONES User ID/default Team快照，不复制Token
- [x] 8.5 在每次外部调用前复核当前绑定主体、最新Team集合和当前Token，禁止重绑/解绑/Team变化导致旧Job漂移
- [x] 8.6 保证RabbitMQ消息仍只携带job_id/correlation_id，新增主体与发布事实全部从数据库Job快照读取
- [x] 8.7 为私聊、同群多发送人、Team切换、账号换绑、仅Token轮换和停用/解绑竞态编写集成测试

## 9. Claude Tool Catalog 与组合调用

- [x] 9.1 扩展Agent Context/Tool Catalog Builder，计算内部Tool与Agent Envelope、Application Allowlist、Release状态和用户Provider可用性的交集
- [x] 9.2 为精确允许的 `cap__*` QUERY能力生成模型Tool定义，使用公开Input Schema和业务description，排除release_note与系统字段
- [x] 9.3 扩展内嵌SDK MCP注册与路由，使内部Tool继续走ToolRegistry、`cap__*`走受治理Capability Executor
- [x] 9.4 更新SDK `allowed_tools`/`can_use_tool`，只批准当前Job解析出的内部只读Tool和受治理QUERY Tool，继续禁止Bash/Write/Edit/WebFetch
- [x] 9.5 在Tool调用入口再次复核完整治理交集，覆盖Catalog构建后Release禁用或用户解绑的竞态
- [x] 9.6 将外部规范化文本封装为不可信Tool data，验证其不能修改系统提示、Tool定义或权限集合
- [x] 9.7 增加测试专用双Capability fixture，验证模型用Tool A规范化输出组织Tool B输入且两次调用独立治理
- [x] 9.8 扩展成功/失败Tool事件，保存Release、分类和attempt安全摘要而不保存私有推理、认证材料或原始HTTP正文
- [x] 9.9 为应用未选、用户未绑定、未知cap Tool、提示注入文本、顺序组合和现有内部Tool回归编写Claude Runtime测试

## 10. ONES 工作项搜索 Capability

- [x] 10.1 定义 `cap__ones__work_item__search` 的固定QUERY/INTERNAL Capability Revision、业务description和发布种子/初始化方式
- [x] 10.2 实现只公开keyword、`demand|task|defect` issue_type及1–50 limit的Input Schema
- [x] 10.3 实现只返回number/name/type条目、total和truncated的有界Output Schema与Mapping
- [x] 10.4 配置并验证固定GraphQL POST query，拒绝mutation、多operation歧义、动态document及Agent提供query
- [x] 10.5 将User ID和default Team只从Job System Context注入，将Token只从当前个人Credential Resolver注入
- [x] 10.6 扩展ONES Mock覆盖登录、多个Team、搜索、401、403、429、5xx、坏JSON、超大响应、缺字段和Team撤销
- [x] 10.7 为搜索契约、截断、全有或全无输出、用户/Team隔离、重试与安全失败编写单元和集成测试

## 11. 管理端与用户端界面

- [x] 11.1 在平台治理导航增加“API Capability配置”入口，不增加全局功能开关页面
- [x] 11.2 实现统一工作台五区域、单一保存/Verify/Publish流程、Revision冲突恢复和字段级校验展示
- [x] 11.3 实现Connection/Auth Profile Draft、首连接临时自验证、发布历史、禁用/归档和真实生效状态界面
- [x] 11.4 实现Capability Test表单和预览，完整显示普通业务字段并从数据结构排除密码、Token、Cookie、认证Header和原始响应
- [x] 11.5 实现Capability Release历史、ACTIVE/DEPRECATED/DISABLED/ARCHIVED操作、replacement/reason和复制为Draft
- [x] 11.6 扩展Agent配置界面，展示Capability名称、Identifier、description、Release Revision、状态及ACTIVE旧版本选择
- [x] 11.7 扩展Application配置界面，仅勾选所选Agent Publication冻结的精确Release子集，并展示无能力/不兼容升级原因
- [x] 11.8 扩展现有ExternalIdentityPanel的本人模式和管理员治理模式，不新建第二套ONES绑定组件
- [x] 11.9 新增普通用户“我的外部身份”路由并复用本人模式，确保不能导航或请求人员、角色、会话和其他用户数据
- [x] 11.10 实现两阶段ONES绑定、多个Team默认选择、重新验证切Team、credential missing/invalid和解绑交互
- [x] 11.11 为工作台、预览敏感字段缺席、Agent/Application选择边界及外部身份两种模式编写Vitest/组件测试
- [x] 11.12 向受保护前端路由暴露当前会话用户ID；原主体相等模式判定已由11.16确认的入口语义替代
- [x] 11.13 扩展本人外部身份读模型，只读展示当前钉钉身份，并通过`external_identity_id`精确关联当前ONES身份与个人凭据，不返回`unbound`历史
- [x] 11.14 将治理模式拆分为当前身份主区域和默认折叠的只读历史区域，并保留钉钉`restore_required`候选定位恢复能力
- [x] 11.15 增加后端和前端回归测试，覆盖双入口同一绑定事实、管理员查看本人、本人钉钉只读、历史ONES排序在前及身份凭据不一致失败关闭
- [x] 11.16 将外部身份模式改为入口语义：`/me/external-identities`固定本人模式，`/users/:userId`在治理授权后固定治理模式，包括管理员查看本人
- [x] 11.17 增加回归测试，证明管理员查看本人可治理钉钉但不能直接编辑来源字段，且独立本人入口仍保持钉钉只读

## 12. 审计、安全与数据来源

- [x] 12.1 扩展控制面审计，记录actor、对象、Revision、hash、动作、结果和correlation id而不记录配置正文或凭据
- [x] 12.2 扩展运行时审计，关联DingTalk event、Application/Agent Publication、Job、主体快照、Capability Release、Tool Call、attempt和Delivery
- [x] 12.3 为日志、异常、API响应、测试预览和审计增加结构性敏感字段断言，证明Token/Cookie/Auth Header/密码/原始响应不可达
- [x] 12.4 为规范化INTERNAL结果保存user、Application Publication、Capability Release和classification来源及现有Job访问控制
- [x] 12.5 验证`session_policy.retention_days`仍仅保存不执行，且本变更未增加正常Tool结果定时清理任务
- [x] 12.6 验证管理状态准确描述固定Origin边界，不声称实现完整网络区/CIDR/DNS SSRF防护

## 13. 端到端验收与回归

- [x] 13.1 使用ONES Mock完成管理员首Connection临时自验证、发布以及管理员正式本人绑定/default Team选择
- [x] 13.2 完成管理员配置、Test、Verify、幂等Publish `cap__ones__work_item__search` 的端到端测试
- [x] 13.3 完成Agent精确选择Release并发布、Application选择Agent和Capability子集/钉钉连接器并发布激活的端到端测试
- [x] 13.4 完成普通钉钉用户自助绑定后在私聊和群聊查询，并验证使用该发送人自己的User/Team/Token及规范化结果
- [x] 13.5 验证Agent未选时应用不能配置、应用未选时模型不能调用，以及未绑定、401、403、Team撤销和Release禁用全部失败关闭
- [x] 13.6 验证旧Job不因账号重绑/default Team切换而漂移，且同主体/Team的Token轮换可继续
- [x] 13.7 验证测试双Capability fixture的模型侧组合，并证明生产目录不包含fixture
- [x] 13.8 回归全部现有内部Tool、旧Agent/Application Publication、Job重试、钉钉投递和外部身份治理流程
- [ ] 13.9 使用普通用户和管理员会话完成“我的外部身份”、管理员本人用户详情和他人用户详情浏览器验收，证明入口模式边界、当前/历史分层及钉钉本人只读/治理可操作边界

## 14. 质量门与交付

- [x] 14.1 运行新增模块的领域、应用、API、Repository和安全测试，并修复所有失败
- [x] 14.2 使用 `.venv/bin/pytest` 运行相关后端回归与PostgreSQL集成测试，记录可复现命令和结果
- [x] 14.3 运行前端Vitest、TypeScript检查和生产构建，确认普通用户与管理员路由权限无回归
- [x] 14.4 运行迁移升级/回退演练，确认旧snapshot可读、现有身份不丢失且Release禁用可作为运行时回退
- [x] 14.5 更新管理API、运维状态、错误码和完整钉钉到ONES发布链文档，并明确延期范围
- [ ] 14.6 执行 `openspec validate add-governed-api-capability-handlers --strict` 及仓库静态质量门，确保实现与全部规格场景一致

## 15. 企业内网明文 HTTP Connection

- [x] 15.1 更新 ADR、设计、Connection 规格和运维文档，明确 HTTPS 默认、HTTP 显式授权及明文链路风险
- [x] 15.2 增加 026 兼容迁移和 `allow_plain_http` 后端契约，接受旧字段输入但统一输出新语义
- [x] 15.3 更新管理端字段、警告和 Authentication Profile Mock 默认值，使企业内网与本地 ONES 配置可直接验证
- [x] 15.4 增加生产 HTTP、未授权拒绝、HTTPS 规范化、旧字段兼容和迁移测试，并运行相关质量门
- [x] 15.5 将 026 应用到当前运行环境，重新构建 API/Worker/管理端并完成 ONES Mock Connection 冒烟验证
