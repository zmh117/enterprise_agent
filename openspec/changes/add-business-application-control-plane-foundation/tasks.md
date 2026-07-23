## 1. 基线与数据库模型

- [x] 1.1 记录当前 Agent Publication、Workflow Publication、Channel Connector、Identity/RBAC、Admin API、前端静态原型和全部测试基线，确认现有钉钉/Webhook数据面不读取Business Application
- [x] 1.2 在下一个可用迁移版本中创建`business_application`和`business_application_revision`，补齐状态、revision、负责人、组件引用、策略JSON、validation、hash、审计时间及唯一约束
- [x] 1.3 创建revision级Trigger、Delivery和Capability子表，增加外键、顺序、enabled、规范化routing key、actor policy和必要索引
- [x] 1.4 创建不可变`business_application_publication`和环境级`business_application_deployment`，增加schema version、snapshot、hash、expected revision及`application+environment`唯一约束
- [x] 1.5 创建可事务校验的活动Trigger路由投影或等效唯一性结构，确保并发激活无法产生相同environment、trigger type、connector ID和routing key
- [x] 1.6 增加迁移测试，覆盖空库建表、重复迁移幂等、外键、唯一约束、状态约束和现有数据库升级，并确认两个既有009迁移的排序不受影响

## 2. 领域模型与安全策略

- [x] 2.1 建立`business_application`独立DDD目录和Application、Revision、Trigger、Delivery、CapabilityReference、Publication、Deployment领域模型
- [x] 2.2 实现应用编码、项目、环境、生命周期、actor policy、session policy和execution policy值对象及严格枚举/范围校验
- [x] 2.3 实现Trigger与Delivery的渠道类型校验、规范化routing key和`CURRENT_SENDER`/`SERVICE_ACCOUNT`主体约束
- [x] 2.4 实现策略敏感字段与危险内容拒绝器，阻止URL、DSN、SQL、LogQL、Shell、Password、Secret、Token和底层数据源配置进入草稿
- [x] 2.5 实现canonical JSON和SHA-256生成/验证，确保列表顺序、空值和字典顺序产生稳定snapshot hash
- [x] 2.6 为领域值对象、非法状态转换、危险配置、hash稳定性和未知字段编写单元测试

## 3. 组件端口与持久化仓储

- [x] 3.1 定义Agent Publication、Workflow Publication、Channel Connector、Identity主体和Capability Catalog只读端口，避免业务应用领域直接依赖其他模块Repository
- [x] 3.2 实现现有Agent、Workflow、Channel和Identity组件读取适配器，返回稳定ID、revision、项目、状态和config hash等最小引用
- [x] 3.3 实现初始Capability Catalog适配器：空列表合法，任何非空Capability返回“目录尚未接入”的结构化校验错误，且不得映射为内部ToolRegistry
- [x] 3.4 实现BusinessApplicationRepository的列表、按编码读取、创建、元数据更新、历史revision读取和乐观并发写入
- [x] 3.5 实现一次事务保存完整revision及Trigger、Delivery、Capability子记录，失败时不得留下部分草稿
- [x] 3.6 实现publication、deployment、活动路由投影和历史查询Repository操作，包含幂等发布、激活、重新激活和停用
- [x] 3.7 增加Repository集成测试，覆盖revision冲突、组件子记录顺序、publication不可变、deployment并发和路由唯一性

## 4. 应用服务、发布与Resolver

- [x] 4.1 实现创建应用、更新元数据、保存新草稿revision、停用和归档用例，并拒绝删除历史事实
- [x] 4.2 实现跨组件Validator，聚合应用状态、Agent、Workflow、Channel、Actor、Delivery、Capability、项目范围和策略的全部字段级错误
- [x] 4.3 实现发布用例，在单一事务中验证revision、生成canonical snapshot与hash、创建幂等publication并记录审计
- [x] 4.4 实现环境激活用例，验证publication完整性、expected revision、应用状态和Trigger冲突后原子更新deployment及路由投影
- [x] 4.5 实现历史publication重新激活和环境deactivate，用审计记录旧/新publication但保留全部历史
- [x] 4.6 实现`resolve_active(application_code, environment)`和`resolve_trigger(environment, trigger_type, connector_id, routing_key)`只读端口
- [x] 4.7 Resolver对无匹配、重复匹配、disabled/archived、未激活、hash错误和未知schema返回明确非重试配置错误，且不回退到其他应用
- [x] 4.8 为所有命令和Resolver编写应用层测试，明确断言发布/激活不会创建Agent Job、发布MQ消息或调用现有入口服务

## 5. 权限、审计、功能开关与管理API

- [x] 5.1 增加`FEATURE_BUSINESS_APPLICATION_CONTROL_PLANE`设置、示例环境配置和安全默认值，关闭时不得暴露可执行写入口
- [x] 5.2 将Business Application Repository、组件适配器、服务和Resolver注册到Bootstrap容器及API应用，不修改钉钉/Webhook/Worker依赖链
- [x] 5.3 在管理能力目录和本地RBAC seed中增加`business_application`的read、create、edit、publish、activate权限，保持项目/对象级过滤
- [x] 5.4 实现严格Pydantic请求/响应模型，拒绝未知字段并限制编码、文本、策略、binding数量和分页参数
- [x] 5.5 实现应用列表、详情、创建、元数据更新、草稿保存、校验、发布、发布历史、激活、停用和effective配置管理API
- [x] 5.6 对所有读接口执行应用级防枚举授权，对所有写接口执行Web Session、细粒度RBAC与CSRF校验
- [x] 5.7 将revision冲突、字段校验、权限、未找到、依赖错误和完整性错误映射为稳定安全的HTTP契约
- [x] 5.8 记录created、updated、draft_saved、validated、published、activated、deactivated和status_changed审计，确认payload无Secret和完整敏感配置
- [x] 5.9 增加API契约与安全测试，覆盖401、403/404、防枚举、缺CSRF、422未知字段、409并发、发布失败和功能开关关闭

## 6. 前端路由、API边界与状态管理

- [x] 6.1 增加React Router和TanStack Query依赖并建立`app/router`、`shared/api`及applications的domain/application/infrastructure/presentation目录
- [x] 6.2 实现统一API Client，默认`credentials: include`，写请求注入现有CSRF Cookie，解析401、403、404、409和字段校验错误
- [x] 6.3 定义Business Application、Revision、Validation、Publication和Deployment前端领域类型及Zod边界解析
- [x] 6.4 实现查询key、列表/详情queries和创建、保存、校验、发布、激活、停用mutations，成功后按资源精确失效缓存
- [x] 6.5 将现有Dashboard保留为总览路由，并把“业务应用”菜单改成可导航的真实工作区；其他规划菜单继续禁用
- [x] 6.6 增加功能开关关闭、未登录、无权限和后端不可用的独立页面状态，不回退到静态应用fixture

## 7. 业务应用真实工作区

- [x] 7.1 实现业务应用列表，展示名称、编码、项目、状态、最新revision/publication、环境激活摘要及加载/空/错误状态
- [x] 7.2 实现业务应用创建和元数据编辑表单，使用严格字段、权限和expected revision并展示409刷新提示
- [x] 7.3 实现应用详情Shell和概览，展示负责人、组成摘要、运行时未接线状态和最近校验/发布信息
- [x] 7.4 实现组成配置表单，通过目录选择Agent Publication、Workflow Publication、允许方向的Channel Connector、Trigger、Delivery和受控策略
- [x] 7.5 Capability区域在目录未接入时只展示空状态与后续建设说明，不提供任意编码、HTTP、SQL、Redis、Loki或工具名输入
- [x] 7.6 实现校验结果视图，将字段、binding和组件错误定位到对应配置区域，并在校验失败时禁用发布/激活
- [x] 7.7 实现publication历史、snapshot摘要、hash、发布人、发布时间和环境deployment视图，不展示Secret或完整敏感配置
- [x] 7.8 实现发布、激活历史版本和deactivate确认流程，明确提示`runtime_wired=false`且操作不会接管钉钉/Webhook
- [x] 7.9 为列表、详情、表单、校验、并发、权限、Capability安全边界和发布历史增加前端组件与集成测试
- [x] 7.10 验证桌面/窄屏布局、键盘焦点、表单标签、错误摘要、禁用原因和不依赖颜色的状态表达

## 8. Seed、文档与迁移验收

- [x] 8.1 提供幂等本地seed或CLI，在依赖Publication存在时创建未激活的`default-diagnostic-application`草稿，生产迁移不得自动激活
- [x] 8.2 编写控制面文档，说明Business Application与Agent Profile、Workflow、Channel、Capability、Identity及数据面的边界
- [x] 8.3 编写API示例和发布/激活/回退操作手册，所有示例使用假标识且不包含密码、Token、Webhook URL或真实业务数据
- [x] 8.4 编写后续数据面接线前置清单，要求单独变更、入口binding迁移、灰度开关、回退路径和端到端钉钉/Webhook验证

## 9. 端到端验证与交付

- [x] 9.1 运行数据库迁移、seed两次和Repository测试，证明升级幂等、约束有效且没有修改现有Agent/Workflow/Job记录
- [x] 9.2 运行后端ruff、mypy和全部pytest，覆盖创建→保存→校验→发布→激活→Resolver→回退→停用完整链路
- [x] 9.3 运行前端lint、typecheck、测试和production build，确认没有静态业务应用fixture回退或未受控网络调用
- [x] 9.4 使用真实浏览器验证业务应用列表、详情、编辑、校验、发布历史、401/403、409、桌面和窄屏行为
- [x] 9.5 在功能开关关闭和开启两种配置下执行Compose/API烟测，验证关闭时无写入口、开启时控制面可用
- [x] 9.6 回归钉钉Stream、Webhook触发、RabbitMQ Worker、Agent Job、只读工具和Delivery测试，证明现有数据面结果与变更前一致
- [x] 9.7 扫描新增数据库、API响应、审计、前端和文档，确认不存在Secret、真实ONES凭据、数据库/Redis/Loki连接或任意查询入口
- [x] 9.8 执行`openspec validate add-business-application-control-plane-foundation --strict`并逐项核对三份规格中的全部场景
