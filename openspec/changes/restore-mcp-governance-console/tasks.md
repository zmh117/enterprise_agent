## 1. 固定前置基线与恢复清单

- [ ] 1.1 完成 `simplify-platform-with-mcp` 与 `migrate-agent-runtime-to-typescript` 的剩余验收，记录可复现命令、通过证据和仍存在的环境限制
- [ ] 1.2 在用户分别明确验收两个前置 change 后同步/归档它们，并复核本 change 的 delta spec 仍能严格校验，禁止从 `master` 覆盖当前 MCP 基线
- [x] 1.3 盘点 `bak/frontend` 与当前前端，形成逐页面“复用展示组件、重写数据层、永久排除”清单
- [x] 1.4 建立控制台页面、后端 API、代码拥有权限、审计动作和负向授权测试的端到端矩阵
- [x] 1.5 增加静态与路由回归检查，禁止 API Capability、Handler、Connection、Resource Mapping、Internal API Platform、旧 fixture 和旧 API Client 返回构建产物
- [x] 1.6 复核数据库迁移计划只复用当前用户/RBAC/身份/MCP/Resource/Secret/Job 表，不创建或迁移旧 Capability、Handler、Connection、Mapping 数据

## 2. 统一管理权限与安全 API 基础

- [x] 2.1 扩展服务端代码拥有的管理权限目录，覆盖 Dashboard、用户、角色、身份、渠道、Job、MCP Server、Tool、Resource 和 Credential 的读写边界
- [x] 2.2 为新增权限补 `platform-admin` 自动管理权限、其他角色默认拒绝和服务账号不得获得 Web 管理权限测试
- [ ] 2.3 为管理 API 统一接入 Session、CSRF、对象范围、expected revision/version、幂等键、稳定冲突码和安全审计中间件
- [ ] 2.4 定义面向浏览器的安全 DTO 白名单，集中排除密码 Hash、Session Token、Secret Ref/Value/Ciphertext、Provider Token、MCP Authorization、连接敏感字段和原始 Payload
- [ ] 2.5 为列表 API 统一实现范围过滤、稳定分页、确定性排序和不可枚举详情语义
- [ ] 2.6 增加敏感字段回归测试，覆盖成功响应、校验错误、异常日志、审计、Outbox、Job、Tool Call 和前端状态

## 3. 恢复多 Agent 与多 Application 治理

- [ ] 3.1 验收并补齐多 Agent 列表/详情/Draft/校验/Publication/历史/回退管理 API，移除默认 Agent 的前端特殊限制
- [ ] 3.2 验收并补齐多 Application 列表/详情/Draft/校验/Publication/历史/回退/环境激活/停用管理 API
- [ ] 3.3 为 Agent 与 Application mutation 补对象范围、发布权限、revision、config hash、幂等和审计测试
- [ ] 3.4 恢复 Agent 工作区并接入真实 API，验证切换 Agent 时 Draft、Publication 和历史完全隔离
- [ ] 3.5 恢复 Application 工作区并接入真实 API，明确展示已发布版本与各环境活动版本
- [ ] 3.6 增加多 Agent、多 Application、并发发布、回退、激活和停用的前后端集成测试

## 4. 恢复人员、角色与身份治理

- [x] 4.1 补齐用户目录的列表、查询、详情、新建、编辑、启停、Session 摘要/撤销、角色和身份安全摘要 API
- [ ] 4.2 补齐角色列表/详情/成员/管理权限/Application 使用/数据范围/有效权限模拟 API，删除请求和响应中的 API Capability 字段
- [ ] 4.3 将角色有效运行权限实现为 Application 使用与数据范围和当前 Publication MCP 上限的交集，并补多角色并集、显式拒绝与防自提权测试
- [x] 4.4 恢复人员与账号页面，复用统一 `app_user`、角色成员和 External Identity 事实，不建立重复用户或授权表
- [ ] 4.5 恢复角色与授权页面，按授权区提供预览、原子提交、成员维护和 Application/数据范围配置
- [x] 4.6 恢复“我的外部身份”和管理员身份治理入口，保证管理员不能代用户提交 ONES 密码、Token、user UUID 或任意钉钉 subject
- [ ] 4.7 恢复未绑定钉钉候选列表、徽标、筛选、人员选择/新建、初始角色和历史身份恢复流程
- [ ] 4.8 增加钉钉候选可信绑定、ONES 本人两阶段验证、同一 `app_user` 关联、身份冲突/撤权和 Credential 不泄漏集成测试

## 5. 实现 MCP 配置后端治理投影

- [x] 5.1 实现只读受信 MCP Server 注册表 API，展示来源、Transport 摘要、健康状态和脱敏错误，拒绝 Server CRUD 与任意 URL/Header/认证输入
- [x] 5.2 实现服务端 Tool 发现快照和目录 API，拒绝浏览器提交 Tool 名、Schema、Server 归属或未注册工具
- [x] 5.3 实现 Tool Publication 的启用、停用和版本化 mutation，复用当前 Agent/Application Publication 安全边界
- [x] 5.4 实现 Data MCP Tool Publication 到零个或一个精确兼容 Resource Deployment 的绑定/解绑，拒绝字段映射、规则、SQL、查询模板和通配资源
- [ ] 5.5 为 Server 健康检查实现固定受控动作，确保失败只更新健康事实而不改写 Publication、Deployment 或 Last Known Good
- [ ] 5.6 增加未知 Server/Tool、伪造 Schema、错误 Resource kind、停用 Deployment、跨范围绑定和 revision 冲突负向测试

## 6. 恢复 Resource 与 Credential Web 治理

- [x] 6.1 为 Database、Redis、Loki 实现服务端拥有的安全表单 Schema 和 Credential 候选 API，拒绝任意驱动参数、明文密码和通用查询配置
- [x] 6.2 实现 Resource 两态 Web 投影和新建/编辑/启用/停用编排，将操作映射到 Draft、验证、不可变 Revision、Deployment、Generation 与 LKG
- [ ] 6.3 实现 Resource 安全详情投影，区分保存配置、候选验证、当前有效版本、最近装载、依赖和脱敏错误
- [x] 6.4 验证 Resource 编辑/启用失败保留 LKG，停用阻止新 Job/新绑定且不改写历史 Job
- [x] 6.5 实现 Credential Center 列表/详情/创建/轮换/停用/usages API，使用现有仓库外 Master Key 与 AES-256-GCM-AAD Provider
- [x] 6.6 实现浏览器安全 Credential 标识到内部 Secret Ref 的后端解析，确保浏览器 DTO 不含明文、密文、nonce、认证标签、Master Key 或可复制 Secret Ref
- [ ] 6.7 实现 Credential 活动依赖保护，阻止直接停用仍被启用 Resource、Connector 或活动 Publication 使用的版本
- [ ] 6.8 增加 Master Key 缺失/权限错误、Credential 创建/轮换/停用、Resource 选择与解密失败的 fail-closed 和泄漏回归测试
- [x] 6.9 恢复 MCP Server、Tool Publication、Resource、Credential 页面并完成两态 Resource 交互与受影响对象确认

## 7. 恢复渠道、调试、历史和总览

- [ ] 7.1 补齐受信 Connector/Trigger/Delivery 的列表、详情、新建、编辑、启用、停用和受控测试 API，类型与字段 Schema 由服务端拥有
- [x] 7.2 将 Connector Secret 输入统一改为 Credential 安全选择，拒绝 `env:`、`vault:`、`kms:`、任意 Header 模板和动态 adapter
- [x] 7.3 恢复渠道与触发器页面，展示企业归属、方向、发布引用、运行状态和脱敏错误
- [ ] 7.4 补齐范围过滤的 Job/Session 历史列表、详情、Step、MCP Tool Call、Delivery 时间线和可取消状态 API
- [x] 7.5 收紧 Debug Job 创建 DTO，拒绝客户端覆盖主体、Publication、Resource、Credential、MCP Server、Tool allowlist 和任意投递目标
- [x] 7.6 恢复“发起调试”和运行历史页面，确保旧 Job 显示冻结 Publication/Resource Generation 而不跟随当前配置
- [x] 7.7 实现 Dashboard 安全聚合 API，按当前权限聚合 Agent/Application/Channel/Job/MCP/Resource/Credential 健康且防止不可见对象计数泄漏
- [x] 7.8 恢复真实 Dashboard 和当前 MCP 数据链路展示，删除所有静态 fixture、API Platform 节点和伪造成功动作
- [ ] 7.9 增加 Connector 测试不改写发布、Debug 越权、历史不可枚举、Job 取消状态机和 Dashboard 范围聚合集成测试

## 8. 前端 Shell、安全与可用性验收

- [x] 8.1 重建权限感知管理 Shell 和路由守卫，按确认的信息架构组织导航且保持登录/Session/CSRF 安全
- [x] 8.2 只从 `bak/frontend` 选择表格、表单、确认框和布局组件，重写 API Client、查询缓存、mutation 和错误处理
- [ ] 8.3 为所有 mutation 实现 expected revision/version、幂等键、未保存更改提示、冲突刷新和受影响对象确认
- [ ] 8.4 为无权限、未认证、对象不存在、配置冲突、Secret 不可用和 MCP 运行异常提供中文安全错误，不展示堆栈或原始上游正文
- [ ] 8.5 验证桌面和窄屏布局、键盘操作、焦点顺序、Dialog/Popover、状态非颜色表达和基础无障碍名称
- [ ] 8.6 增加前端单元/组件测试和真实 API mock contract 测试，禁止静态业务 fixture 进入生产代码路径

## 9. Compose 与真实链路验收

- [ ] 9.1 构建受影响前后端镜像并启动干净 Docker Compose，确认没有 Internal API Platform orphan/service/network/route 依赖
- [ ] 9.2 通过 Web 分别创建 Credential 和 Database/Redis/Loki Resource，执行编辑、启用、失败保留 LKG、停用和依赖保护验收
- [ ] 9.3 验证受信 MCP Server/Tool 目录、Tool Publication 精确 Resource Deployment 绑定和未知 URL/Tool/Mapping 拒绝
- [ ] 9.4 使用合成数据执行 Debug → Worker → TypeScript Runtime → MCP Server → Resource Generation → Tool Call 历史全链路验收
- [ ] 9.5 执行钉钉未绑定候选 → 人员/角色/身份绑定 → Application 授权 → Job → MCP → Delivery 全链路验收
- [ ] 9.6 使用测试 ONES 账号执行本人两阶段验证和 ONES MCP 调用，确认密码一次性丢弃且 Token 不进入 Worker、模型、前端、日志或审计
- [ ] 9.7 验证多 Agent、多 Application、环境激活/停用、历史 Publication 和冻结 Job 在重启后仍保持确定语义
- [ ] 9.8 扫描前端产物、API Schema、数据库对象、Compose 和运行日志，确认 API Capability、Resource Mapping 与 Internal API Platform 未恢复
- [x] 9.9 运行后端、TypeScript Runtime、前端和 OpenSpec 的全量适用测试，记录已知仓库级失败与本变更回归的区分证据
- [x] 9.10 执行 `openspec validate restore-mcp-governance-console --strict`、`git diff --check` 和未勾选任务复核，形成最终验收报告

## 10. 可观测性后续边界记录

- [x] 10.1 在运行链路文档中记录未来 W3C Trace Context 的 Worker → TypeScript Runtime → MCP 传播点和 OTLP Collector 接入点
- [x] 10.2 记录 OpenTelemetry 默认禁止采集 Prompt、回复正文、Tool 参数/结果、数据库语句、Token 和 Credential 的字段策略
- [x] 10.3 确认本变更未新增 OpenTelemetry SDK、Collector、存储或 Dashboard 运行依赖，并为后续独立 OpenSpec 留出验收入口
