# builtin-tool-resource Specification

## Purpose
定义代码注册的 MCP 工具、受治理 Database/Redis/Loki/Knowledge 资源、授权资源发现和只读诊断合同。身份与角色授权见 `identity-access`，业务 Provider 工具见 `governed-api-capability`，文件工具见 `task-file-workspace`，通用运行审计与外部操作确认见 `execution-delivery`。

## 实现依据与验证边界

当前合同以 `backend/app/modules/mcp_tool_runtime/`、`backend/app/modules/agent/infrastructure/tool_manifest.py`、`backend/app/modules/platform_config/application/governed_resources.py`、`resource_scope_bindings.py`、`database_resource_verifier.py`、`backend/app/shared/resource_role.py`、`loki_contract.py`、`backend/docker/setup_oracle_client.sh`、`verify_oracle_client.py`、`backend/app/shared/knowledge_tool_contracts.py`、`backend/app/modules/knowledge/` 和 `services/knowledge_mcp_server/` 的实现为依据。回归依据包括 `backend/tests/test_tool_pagination.py`、`test_resource_scope_bindings.py`、`test_governed_tool_resource_lifecycle.py`、`test_loki_resource_scoped_labels.py`、`test_loki_line_limits.py`、`test_oracle_resource_verification.py`、`test_oracle_image_contract.py` 与 `test_redis_scan_pagination_integration.py`、`test_knowledge_mcp_contract.py`、`test_knowledge_search.py` 与 `test_knowledge_authorization.py`。

这些代码和测试定义可核对的当前实现，规范重建与离线测试不证明部署、真实数据库或 Loki 已验收。Oracle 真实服务端连接、权限、字符集和新 Job 工具链必须另有运行证据；未取得证据时不得记作通过。ONES 与钉钉的真实验收边界见 `governed-api-capability`。

## Requirements

### Requirement: MCP 工具实现与执行元数据必须由代码拥有
系统 MUST 从代码 Manifest 注册稳定 Tool identifier、server code、输入 schema/schema hash、描述、资源类型、effect、confirmation policy 及适用的 operation/risk/target policy。数据库、管理 API、Agent 和 Application MUST NOT 创建任意 executable Tool、URL、SQL 模板、HTTP 请求、Shell 或替换实现。管理工具目录 SHALL 展示代码合同与可用性，授权管理只选择已注册 identifier。

#### Scenario: 发布合法代码工具
- **WHEN** 部署的 Manifest identifier、schema 和执行元数据一致
- **THEN** 固定 MCP Server 注册该实现，管理员可以在授权和发布中选择它
- **AND** 新代码不自动把工具加入旧 Publication、角色或 Job

#### Scenario: mutation 缺少治理元数据
- **WHEN** 工具声明 mutation 但缺少受支持的确认策略，或业务 operation/target policy 与注册表不一致
- **THEN** Manifest 校验失败，不得把该工具伪装为只读工具发布

#### Scenario: 管理端提交动态实现
- **WHEN** 请求提供任意工具实现、Provider 网络控制参数或未注册 identifier
- **THEN** 管理 API 或发布校验拒绝，不生成可执行实现

### Requirement: MCP Server 与鉴权模式必须固定
Python Runtime SHALL 只连接部署固定的 `tool-mcp`、`file-mcp`、`ones-mcp`、`dingtalk-mcp`、`knowledge-mcp`，使用标准 Streamable HTTP。每个 Server MUST 在代码策略中声明唯一鉴权模式；`tool-mcp` 使用受信 Job context，文件、业务和知识 MCP 使用各自 Principal 合同。Runtime MUST NOT 直连业务数据库、Redis、Loki 或知识存储，也不得接受 payload 或 Tool 参数覆盖 Server URL、鉴权模式或 audience。

#### Scenario: 查询资源证据
- **WHEN** Runtime 调用 `query_database`
- **THEN** 固定 `tool-mcp` 执行受治理查询，数据库凭据不进入 Runtime

#### Scenario: 请求改写 Server
- **WHEN** Job 或 Tool Input 提供任意 MCP URL、auth mode 或 credential profile
- **THEN** 系统拒绝动态覆盖，不建立额外执行入口

### Requirement: 每次 MCP 调用必须校验 Job 和精确工具合同
MCP 调用 MUST 绑定有效 RUNNING Job，逐次校验当前用户、业务应用或直接 Agent 的使用授权、当前数据范围、Job 冻结 Tool Snapshot、server/identifier/schema hash 及执行元数据。Application Tool 子集、Agent Publication、角色授权和 Job Snapshot MUST 同时允许；历史 Routing Context 或目标字段不得扩大当前调用权限。

#### Scenario: 精确合同一致
- **WHEN** 当前用户、Job、Publication、Tool 与目标范围均有效且精确匹配代码合同
- **THEN** 调用才可继续资源解析和策略校验

#### Scenario: schema 漂移或未授权
- **WHEN** Job 未冻结该 Tool、schema hash 已变化或当前授权已撤销
- **THEN** 系统在受治理上游访问前失败关闭，不静默升级旧快照

### Requirement: 资源必须具有草稿验证发布生命周期
Database、Redis、Loki Resource SHALL 具有稳定身份、可编辑 Draft、技术验证事实与不可变 Published Revision。连接配置、Secret references 和 `scope_bindings` MUST 共同参与同一内容哈希并通过一次 `DRAFT → VERIFIED → PUBLISHED` 生命周期，不另设范围策略发布物或审核审批环节。

#### Scenario: 修改连接或范围
- **WHEN** 管理员修改连接、Secret reference、数据库表前缀、Redis namespace 或 Loki selector
- **THEN** 同一 Draft revision 变化，旧验证失效，重新验证后才可发布

#### Scenario: 发布未验证草稿
- **WHEN** Draft 无匹配当前内容的成功验证事实
- **THEN** 系统拒绝发布

#### Scenario: 修改已发布版本
- **WHEN** 管理员需要修改 Published Revision
- **THEN** 必须创建新 Draft，已发布内容不能原地改写或普通 CRUD 物理删除，只能按生命周期 disable/archive

### Requirement: 资源连接和范围必须在同一管理表单维护
资源管理界面 SHALL 支持 Database/Redis/Loki 的 Draft 编辑、Secret 选择、技术测试、发布和停用归档，区分草稿、验证、发布与身份状态。已发布详情只读展示实际版本的安全摘要与范围；不得展示不存在的 activation、generation 或 Last Known Good 状态。

#### Scenario: 新建数据库资源
- **WHEN** 管理员选择 Provider、目标、Secret reference 和 Workshop 表前缀
- **THEN** 前端提交一个包含连接与 scope bindings 的 Draft，不提交 Secret 明文

#### Scenario: 保存 Loki 环境基地范围
- **WHEN** Loki 表单残留空串、null 或 undefined 的 workshop_code 占位字段
- **THEN** 前端只在提交副本中去掉该空占位，保留 Environment/Base 与 selector
- **AND** 非空非法 Workshop 和未知字段仍被拒绝；Database/Redis 的 Workshop 字段继续保留

### Requirement: 新建资源可原子创建明确输入的拓扑节点
初始 Resource Draft SHALL 允许选择启用的 Environment/Base/Workshop 或手动输入精确编码。具有平台管理权限的管理员保存时，系统 MUST 按父子路径在同一事务创建明确缺失节点与 Resource/Draft；新 Base 必须有受支持的默认数据库引擎，不得猜测或批量生成其他拓扑。

#### Scenario: 手动输入缺失父子节点
- **WHEN** 管理员输入尚不存在的 Environment/Base/Workshop 精确路径并保存资源
- **THEN** 系统仅创建该路径缺失节点、资源与初始 Draft，并记录审计

#### Scenario: 创建失败或目标停用
- **WHEN** Draft 创建失败，或任一同编码节点已经停用
- **THEN** 前者回滚本次节点创建，后者拒绝保存，不自动启用或新建替代节点

### Requirement: 工具必须按当前调用目标唯一解析资源
`tool-mcp` MUST 按资源类型、Agent 显式提供并通过当前范围授权的 `environment`、可选 `base/workshop/placement`，从启用 Resource Identity 的最新 Published Revision 中解析恰好一个候选。单次调用使用一致配置与 Secret 解析事实并记录实际 Resource identity/revision；不得使用 Application Resource Mapping、Job 冻结资源版本、YAML topology、第一候选、最近父级猜测或 Last Known Good 回退。

#### Scenario: 环境级资源唯一
- **WHEN** 只提供合法 environment，且该类型存在唯一符合环境级目标的当前资源
- **THEN** 系统使用该 Revision，不要求虚构 base/workshop

#### Scenario: 零命中或多命中
- **WHEN** 没有候选或符合调用目标的候选超过一个
- **THEN** 返回 `mcp_resource_not_resolved` 或 `mcp_resource_ambiguous`，不访问任何候选

#### Scenario: 发布新资源版本
- **WHEN** Resource 发布新的当前 Revision
- **THEN** 后续调用按当前发布事实重新解析，既有 Job 的 Tool Snapshot 不发生隐式修改

### Requirement: placement 是精确资源角色而非授权角色
Database/Redis 的 `placement` SHALL 表示可自定义的资源实例角色，兼容 cloud/edge；规范化后长度为 1–64，允许中文、字母数字及 `_ . : -`，去首尾空白并精确匹配。空值表示未指定，不能用于猜测默认实例。placement MUST NOT 成为用户/组/角色的数据授权维度；Loki MUST 拒绝非空 placement。

#### Scenario: 同目标存在多个角色
- **WHEN** 同一目标存在资源角色“云”和“边”
- **THEN** 目录原样返回角色，明确 placement 的调用命中对应资源，未明确时不得择一

#### Scenario: 同角色重复资源
- **WHEN** 同类型、目标和角色仍有多个资源
- **THEN** 目录显示 AMBIGUOUS，搜索、分页或名称差异不改变该歧义事实

#### Scenario: 非法角色值
- **WHEN** placement 含非法字符、控制字符、超长内容或 Loki 非空角色
- **THEN** 输入或资源校验拒绝，不访问上游

### Requirement: 资源凭据只能在基础设施边界解析
Resource SHALL 仅保存受管 Secret reference，基础设施层在验证或执行时解析当前可用凭据。Secret 缺失、禁用或无法解密 MUST 使依赖它的调用失败关闭，不回退环境变量、空密码、旧 Secret 或旧 Revision；输出、目录、异常、审计和模型上下文不得包含密码、Token 或连接认证材料。

#### Scenario: Secret 被停用
- **WHEN** 已发布 Redis Resource 的 password_ref 无法解析
- **THEN** 依赖该 Revision 的调用返回安全配置错误且不连接 Redis

#### Scenario: Provider 错误包含敏感信息
- **WHEN** 驱动异常含连接串或凭据
- **THEN** 平台返回稳定错误码与安全说明，不持久化或返回原始认证材料

### Requirement: 授权资源目录必须与实际工具授权一致
`list_available_tool_resources` SHALL 分页返回当前 RUNNING Job、当前用户、业务应用、角色访问、Application Tool 子集与精确 Job Snapshot 共同允许的 Database/Redis/Loki 当前 Published Resource 地址。目录自身必须被冻结授权；业务应用内必须在同一条角色应用访问记录中同时满足数据 Tool 与 scope，不得跨角色拼接。仅返回安全地址、可用工具、resolution_status 和白名单数值 effective_limits，不返回 host、port、username、Secret reference 或 scope 内部条件。限制 SHALL 与执行一致，不解析凭据且不得通过上限发现扩大授权。

#### Scenario: 当前应用内发现资源
- **WHEN** Job 冻结目录及相应数据 Tool，且同一访问记录同时允许 Tool 与目标
- **THEN** 目录返回对应非敏感资源地址、有效查询限制及 AVAILABLE 或 AMBIGUOUS 状态

#### Scenario: 资源清单显示名称与编码
- **WHEN** 目录返回当前授权的已发布资源，且 Agent 向用户展示资源清单
- **THEN** 每项包含 Resource Identity 的 `resource_name`（资源名称）及 `resource_code`（资源码），Agent 同时展示两者
- **AND** 名称仅作为展示数据，不用于替代精确目标或 placement；名称缺失时明确显示未提供，不得根据编码编造名称

#### Scenario: 不同角色权限不可拼接
- **WHEN** 角色 A 只有 Tool，角色 B 只有目标 scope
- **THEN** 目录不把两者合成为可见资源

#### Scenario: 直接 Agent Job
- **WHEN** 直接 Job 冻结目录和数据 Tool 且当前用户仍具备既有 Tool/项目 use grant
- **THEN** 目录沿用直接调用的权限边界，不创造额外资源映射或数据授权

### Requirement: 资源目录分页必须绑定当前授权和候选集合
资源目录 SHALL 默认且最多每页 50 项，按稳定地址键执行 keyset 分页。最长 4096 字符的不透明 cursor MUST 绑定 Job/用户/应用、Snapshot 与 authorization hash、Tool/过滤条件以及当前授权候选摘要；每页重新校验当前事实，返回 `next_cursor`、`has_more`、`observed_at` 和有界截断语义。

#### Scenario: 51 项资源
- **WHEN** 同一授权过滤范围有 51 项资源
- **THEN** 首页返回 50 项及 next_cursor，续页返回剩余项且不重复

#### Scenario: cursor 复用或状态变化
- **WHEN** cursor 被用于其他 Job/过滤条件，或授权与资源候选已经改变
- **THEN** 返回 cursor invalid 或 stale，要求从第一页重查，不沿用旧授权

### Requirement: Agent 必须先发现资源再构造目标查询
Agent SHALL 对可用资源清单或不明确目标先调用已冻结的资源目录，并只使用 `AVAILABLE` 地址的精确目标与 placement。目录未冻结时必须要求用户提供精确目标；零命中只证明本次目标不可用，不证明该用户没有任何资源。编写 SQL 前 SHALL 读取对应 schema 目录并使用已知表和字段。

#### Scenario: 目标不明确
- **WHEN** 用户询问有哪些可用数据库且目录 Tool 已冻结
- **THEN** Agent 查询目录并按 cursor 续查，不猜测环境编码

#### Scenario: 精确目标失败
- **WHEN** 目标返回资源零命中或歧义
- **THEN** Agent 查询可用目录或请求补充精确目标，不重复相同失败参数或试探其他环境

### Requirement: 数据库查询必须按固定方言执行结构化只读策略
数据库网关 SHALL 支持代码注册的 MySQL、SQL Server、Oracle Provider，先将 SQL 解析为 AST，只允许单个 SELECT 或只读 WITH，拒绝 DML/DDL、管理语句、存储过程、PL/SQL、多语句及混淆绕过。未实现的数据库 Provider 不得发布为可用资源。

#### Scenario: 只读查询
- **WHEN** 查询只含允许的 SELECT/WITH 且符合目标资源的数据库、schema、表前缀和目录范围
- **THEN** 对应方言 driver 执行受限查询

#### Scenario: 写入或跨范围 SQL
- **WHEN** SQL 包含 INSERT/UPDATE/DELETE/MERGE、CALL/EXEC、BEGIN/DECLARE、多个语句或越界表引用
- **THEN** 策略在执行游标前拒绝，不通过注释或方言差异放宽

#### Scenario: 缺少 PostgreSQL 业务 Provider
- **WHEN** 资源声明没有代码实现与方言策略的 PostgreSQL 业务数据源
- **THEN** 验证和发布失败；平台自身使用 PostgreSQL 不等于支持此业务 Provider

### Requirement: 数据库执行必须限制表范围数量时间和响应容量
Database Tool MUST 使用实际 Resource 的数据库/schema 和适用的 Workshop 表前缀，拒绝结构目录外的表。查询默认 100 行、显式最多 10000 行，超限 MUST 拒绝而不静默夹取；执行超时最多 30 秒并与更小平台限制取交集。结果受独立于模型摘要长度的有界序列化容量限制并明确 truncated，不提供通用 cursor。空目录 MUST 返回 `mcp_schema_directory_empty`；字段或语法错误返回可停止的安全错误，不能引导无界猜表、猜字段。

#### Scenario: Workshop 跨表前缀
- **WHEN** Workshop 查询引用其他 Workshop 或缺少要求前缀的表
- **THEN** 请求被只读范围策略拒绝

#### Scenario: 达到结果上限
- **WHEN** 查询达到行数或响应字节上限
- **THEN** 只返回有界结果和截断事实，不提供通用 offset cursor

#### Scenario: 结构目录为空
- **WHEN** 资源没有可用的受限表目录
- **THEN** 系统拒绝执行 SQL，Agent 停止并报告证据不足

#### Scenario: 请求一万行
- **WHEN** 合法只读查询显式请求 10000 行且未超过其他预算
- **THEN** 执行上限为 10000 而非 100；请求 10001 在 Provider I/O 前被拒绝

### Requirement: 数据库资源验证必须证明只读能力
非 local 环境 MUST 在技术验证中证明账号没有禁止的写入或管理权限，并完成只读 session/事务、超时和受限探针。连接失败、权限无法判定或发现禁止权限均不得产生可发布成功事实。仅平台 `environment=local` 的代码策略可允许特权测试账号，并显式记录 `readonly_account=false` 与 `privileged_account_allowed=true`；调用方不能通过请求开启豁免，SQL 只读执行边界仍生效。

#### Scenario: 非本地账号可写
- **WHEN** 权限检查发现写表、DDL 或管理权限
- **THEN** 验证失败且禁止发布

#### Scenario: 本地特权测试账号
- **WHEN** 平台处于 local 且固定验证策略允许该测试账号
- **THEN** 仍执行只读事务与探针并如实记录账号非只读，不把该证据视为非本地生产证明

### Requirement: Schema 目录必须按方言读取有界普通表元数据
SchemaInspectorFactory SHALL 选择匹配数据库引擎的 inspector。MySQL、SQL Server、Oracle 只读系统目录查询 MUST 遵守 database/schema、表前缀和 query，返回普通表、字段名、类型、可空性，不读取业务样例行。SQL Server 默认 schema 为 dbo；Oracle 使用 ALL_TABLES/ALL_TAB_COLUMNS 及 11g 兼容 ROWNUM 语法。

#### Scenario: Oracle schema 预览
- **WHEN** Oracle 11g 资源请求结构目录
- **THEN** inspector 使用 owner 与表范围过滤，不依赖 FETCH FIRST 或 OFFSET FETCH

#### Scenario: 响应安全边界
- **WHEN** schema 查询成功或失败
- **THEN** 响应不包含连接地址、账号、密码、DSN 或原始驱动异常

### Requirement: Schema 分页必须区分下一张表和字段截断
`get_schema_directory` SHALL 默认且最多每页 50 张完整表摘要，使用有界 keyset 表名查询，不为一页无界读取全部字段。cursor MUST 绑定 Job、Tool、精确目标、placement、query 与实际 Resource Revision；每页重新授权并唯一解析。单表字段上限与是否存在下一张表必须独立表达。

#### Scenario: 翻过 50 张表
- **WHEN** 允许目录有 51 张匹配表
- **THEN** 首页返回 50 张与 next_cursor，续页返回第 51 张；Oracle 首页允许空 after_table 下界

#### Scenario: Resource 版本改变
- **WHEN** 续页时唯一解析到的当前 Revision 与 cursor 不同
- **THEN** 返回 stale，不回退旧 Revision

#### Scenario: 只有字段被截断
- **WHEN** 最后一张表字段超过单表上限且没有后续表
- **THEN** 标记字段摘要受限、has_more=false，不生成不存在的表页 cursor

### Requirement: Oracle 固定为单实例 11.2.0.4 与 19c Thick
Oracle Resource MUST 使用结构化 host/port 及 service_name 或 sid 二选一，固定单实例 Oracle 11.2.0.4、AL32UTF8 / AL16UTF16 字符集、匹配进程架构的 64-bit Instant Client 19c 和 python-oracledb Thick。不得接受任意 TNS descriptor、Thin 回退或新版语法假设，查询限界使用 11g 兼容 ROWNUM。

#### Scenario: Service Name 或 SID
- **WHEN** Oracle Draft 明确提供且只提供一种服务定位方式
- **THEN** 验证器与运行时使用固定构造器生成连接参数

#### Scenario: 客户端不合规
- **WHEN** Instant Client 缺失、32 位、架构不匹配、版本不为 19c 或初始化仍为 Thin
- **THEN** 验证与调用失败关闭，不把驱动缺失解释为账号权限失败

### Requirement: Oracle 技术验证必须安全委派给 tool-mcp
API SHALL 校验管理权限后把指定当前 Oracle Draft 的技术验证委派给具备客户端的 `tool-mcp` 内部入口。委派必须用途独立、短时签名、绑定请求/资源/Draft/hash，接收端重验管理权限和资源状态；响应须签名关联、请求时间/大小/并发有界，重放、重定向、非法主机和任意连接配置/SQL/密码输入均被拒绝。该入口不得成为 Agent Tool。

#### Scenario: 当前真实草稿验证成功
- **WHEN** tool-mcp 完成真实连接、11.2.0.4 版本、字符集、只读权限和探针检查
- **THEN** API 只保存匹配请求和当前 Draft 的 PASSED 验证事实

#### Scenario: 验证中草稿或身份变化
- **WHEN** 请求返回时 Draft/hash 已变或资源身份停用
- **THEN** 结果失效，不使旧草稿获得发布资格

#### Scenario: 委派非法或不可用
- **WHEN** 签名/期限/请求绑定无效、票据重放、目标不允许、响应异常或超时
- **THEN** 访问 Oracle 前或保存证据前失败关闭，不创建可发布成功结果

### Requirement: Oracle 验证失败必须分类且不得冒充真实通过
Oracle 技术验证 SHALL 区分客户端不可用、网络、认证、Service Name/SID、服务端版本、字符集、只读权限及未知探针错误，返回稳定安全代码和中文说明。客户端不可用返回 BLOCKED，已识别连接或合同失败返回相应 FAILED；替身测试不得生成真实资源发布依据。

#### Scenario: 驱动认证失败
- **WHEN** 驱动返回账号锁定、过期或认证失败
- **THEN** 返回对应安全认证类别，不暴露原始驱动文本或连接信息

#### Scenario: 只有进程内测试通过
- **WHEN** 验证只使用 Fake driver 或进程内 HTTP 替身
- **THEN** 验收记录明确“真实 Oracle 未验收”，不据此发布真实资源

### Requirement: Oracle 客户端镜像必须隔离且构建可验证
Oracle Instant Client SHALL 仅安装在 tool-mcp 镜像；API、Worker、Agent Runtime 不包含该客户端。构建须处理安装/检测脚本 CRLF 并显式调用解释器；合规客户端安装后实际初始化 Thick 并核对主版本 19。正常未提供客户端可保留 Oracle 不可用状态，ZIP 损坏、检测不能执行、依赖缺失或初始化失败必须终止构建。

#### Scenario: Windows 行尾构建
- **WHEN** 合规客户端及 CRLF 脚本进入构建上下文
- **THEN** 构建规范行尾后执行并验证实际客户端加载，不依赖 shebang 或可执行位

#### Scenario: libaio t64 兼容
- **WHEN** 发行版仅提供 libaio.so.1t64 而客户端需要 libaio.so.1
- **THEN** 安装目录提供受控兼容链接，不覆盖系统库，并继续验证 Thick 初始化

#### Scenario: 构建成功边界
- **WHEN** 镜像成功加载客户端
- **THEN** 该证据仅证明客户端可加载，不证明真实 Oracle 服务端连接或业务验收

### Requirement: Redis 连接合同与只读范围必须统一
Redis Resource SHALL 使用 host/port/database、可选 username、password_ref 与受控 TLS，支持默认 standalone 及显式 cluster startup nodes；cluster 不依赖逻辑 database 索引。执行只允许 GET/SCAN，两种模式都应用完整 namespace 前缀和数量限制，不提供任意 Redis 命令。

#### Scenario: Cluster 缺少节点
- **WHEN** cluster 配置没有可用 startup nodes
- **THEN** 配置或解析在连接前拒绝

#### Scenario: GET 或 SCAN 越界
- **WHEN** key 不在允许 namespace，或 pattern 为全局星号、在完整前缀前出现通配符或包含禁止模式
- **THEN** 调用拒绝，不扩大到整个 Redis

#### Scenario: namespace 含方括号
- **WHEN** 允许的业务 namespace 含字面量方括号
- **THEN** SCAN 对其做字面转义，不能把它解释为 glob 字符类

### Requirement: Redis SCAN 必须保留有界 continuation
`query_redis_scan` SHALL 把 Provider continuation 包装为 Job、Tool、目标、placement、pattern、limit 策略和实际 Revision 绑定的不透明 cursor。每页重新授权、解析与检查 namespace/数量/字节。Cluster 逐主节点扫描，cursor 不暴露节点地址；拓扑变化必须使旧 cursor 失效。

#### Scenario: 批次超过页面上限
- **WHEN** Provider 单批键数超过 limit，包括 cursor 为零的末批
- **THEN** 当前页仅返回 limit 项，continuation 保留余项，重读批次发生变化时返回 stale

#### Scenario: 空批仍有后续
- **WHEN** Provider 返回空键批但 cursor 非零，或 Cluster 尚有主节点未扫描
- **THEN** has_more=true 并保留 continuation，不误报完成

#### Scenario: cursor 绑定变化
- **WHEN** pattern、目标、角色、授权、资源版本或拓扑与 cursor 不匹配
- **THEN** 调用在 Redis 访问前拒绝，不借游标改变 namespace

### Requirement: Loki 连接范围与固定标签范围必须显式配置
Loki Resource SHALL 只使用 global 或精确 Environment 连接范围，字段统一为 base_url、可选 tenant_id、认证 Secret reference、超时与查询上限。同一 Revision 以非空精确 selector bindings 映射 Environment 或 Environment/Base；不得以 Workshop 或 placement 作为连接范围，也不得由业务编码自动推断同名日志标签。

#### Scenario: 平台目标与日志标签不同名
- **WHEN** 一个环境基地的真实日志以 cluster/namespace/app 等标签标识
- **THEN** 管理员在 Draft 显式保存其精确 AND 条件，运行时按该绑定查询

#### Scenario: 目标含 Workshop
- **WHEN** Tool 目标包含一个 Workshop
- **THEN** Loki 仍使用允许的 Environment/Base 固定绑定，不自动注入 workshop、replica 或 role 标签，也不声称这些标签提供 Workshop/placement 授权隔离

### Requirement: Loki Draft 标签发现必须受验证上下文约束
管理员 SHALL 在连接测试成功后，在同一有界技术验证上下文发现合法 label keys，再用已选精确条件级联查询 values。发现结果只是填写辅助，不自动保存完整标签目录或扩大 Published selector；Draft 变化须重新测试。

#### Scenario: 级联选择标签
- **WHEN** 管理员已选择一个精确 label=value 后发现下一个标签取值
- **THEN** 请求按已选条件收窄并返回有界、排序去重的候选与截断标记，不读取日志正文

#### Scenario: 非法 selector 或无测试上下文
- **WHEN** 输入含正则/否定/OR/任意 LogQL/重复 key/空 value，或验证上下文失效
- **THEN** 保存或发现请求被拒绝

#### Scenario: 发现后未保存
- **WHEN** 管理员关闭页面或新值随后出现在 Loki
- **THEN** 不产生新运行配置，不自动改变已发布范围

### Requirement: Loki 运行查询和诊断必须共用固定范围
`query_loki`、`diagnose_loki_labels`、`diagnose_loki_label_values`、`diagnose_loki_probe` MUST 在 Provider I/O 前要求唯一 Published Resource 的非空固定 selector 和相同 tenant/授权/时间边界。Agent 只能追加合法非固定标签的精确匹配；label 名称由语法约束，不采用静态名称白名单，也不特殊解释 customer/workshop 等名字为授权。

#### Scenario: 追加自定义标签
- **WHEN** 资源固定 customer/workshop，Agent 只提供 app/logtype 或其他合法标签
- **THEN** 最终 selector 为固定条件与追加条件的 AND，空对象表示只用固定范围

#### Scenario: 重复固定标签
- **WHEN** Agent 追加条件包含固定 key，即使值相同
- **THEN** 返回固定标签冲突中文错误，不静默覆盖或合并

#### Scenario: 缺少固定条件
- **WHEN** 解析资源没有有效固定 selector
- **THEN** 四类工具均失败关闭，不回退全局 label/value 枚举或无范围查询

### Requirement: Loki 标签与查询边界必须明确且共享
标签名 MUST 为 1–128 位字母数字下划线且不能以数字开头；精确值为 1–256 位非空文本，禁止首尾空白、控制字符和匹配表达式。每个 selector 输入最多 8 项。请求和响应必须遵守时间、条数、字节约束；非法 label 返回稳定中文参数错误，不用通用安全错误掩盖原因。

#### Scenario: 枚举资源固定标签的值
- **WHEN** 资源固定 customer=A，用户枚举 customer 的 values
- **THEN** 仍带固定条件，只返回该范围内有界值

#### Scenario: 空结果与上游失败
- **WHEN** 查询或 probe 成功但没有流或日志
- **THEN** 返回 stream_count/line_count、时间窗及安全 empty hints；上游连接/认证失败须单独分类，不能伪装为空结果

### Requirement: Loki 单次行数采用平台和资源较小值
平台 Loki 单次行数默认上限 SHALL 为 10000，Web 新建资源默认 max_lines=1000，管理 API/Web 对新建编辑统一限制 1–10000。调用以平台限制与已发布资源 max_lines 的较小值校验，省略 limit 使用 100；超限请求不得自动夹取或分页。该值不是 Job 累计行数预算。

#### Scenario: 请求超过有效上限
- **WHEN** 平台 10000、资源 1000，Agent 请求 1001 条
- **THEN** Provider I/O 前拒绝且说明 1000 为有效上限；资源发布为 10000 后允许合法的 10000 条请求

#### Scenario: 多次合法查询
- **WHEN** 同一 Job 多次调用各自均未超过有效上限
- **THEN** 不因累计行数超过 10000 而拒绝，原工具次数、时间与容量限制仍生效

#### Scenario: 已有显式配置
- **WHEN** 已存在显式平台限制或已发布资源配置
- **THEN** 默认值不改写它们，运行继续取较小值；资源重新编辑验证时适用当前输入范围

### Requirement: Loki 响应字节保护由代码统一管理
Loki 资源表单与 Provider 配置合同 MUST 不再提供 max_response_bytes 配置，查询、标签发现及 selector 技术验证 MUST 统一使用代码级 8 MiB 上游响应限制。旧草稿或已发布版本的该字段 SHALL 兼容忽略，不修改不可变历史版本；新保存的草稿 MUST 不保留该字段。其他未知配置仍拒绝，时间、行数、授权和超时规则不变。

#### Scenario: 编辑带旧字节设置的资源
- **WHEN** 管理员打开并保存带 max_response_bytes 的旧 Loki 草稿
- **THEN** 界面不显示该输入项，保存不再保留该字段且不因该旧字段报错

#### Scenario: 使用旧发布版本
- **WHEN** 旧 Loki 发布版本仍保存自定义 max_response_bytes
- **THEN** 不改写发布版本，运行时忽略该值并使用统一代码级限制，超限安全失败

### Requirement: Loki 时间配置与错误必须展示有效边界
资源及平台最大查询分钟 MUST 支持配置 1–43200，默认 60、已有值不变，实际按两者较小值执行。四个 Loki 工具超限 MUST 返回稳定安全中文错误及具体有效上限。

#### Scenario: 平台仍为六十分钟
- **WHEN** 资源配置 43200、平台配置 60
- **THEN** 目录暴露有效 60 分钟且大于 60 的请求被拒绝，不声称可查询 30 天

### Requirement: Loki 正文不可按摘要字符预算丢弃
query_loki 与 diagnose_loki_probe MUST 保留本次有界 Provider 返回的每条脱敏日志，不再按 4000 字符省略 highlights。实际返回条数触及 limit MUST 标注查询可能未穷尽，不把 truncated=false 当作查全的替代。Provider 响应字节超限 MUST 失败；结果文件完整保存与查询覆盖完整性 MUST 分别表达。

#### Scenario: 单行超过四千字符
- **WHEN** 单行脱敏后超过 4000 字符但在字节及沙盒容量范围内
- **THEN** 该行完整保留在结果文件，不返回空 highlights 冒充正文

#### Scenario: 短日志顶满行数
- **WHEN** 返回 50 条短日志且 limit=50
- **THEN** 标记 line_limit_reached，不宣称已经查全

### Requirement: 数据库结果和 Loki 日志不提供通用分页
`query_database` 与 `query_loki` MUST 保留只读、范围、时间、行数、字节及截断限制，不把 offset、旧结果或上游 continuation 自动变为通用游标。需要更多证据时，Agent SHALL 以已知字段构造更窄稳定的 keyset SQL 条件或缩小 Loki 时间窗，后续查询仍独立授权。

#### Scenario: 日志达到行数上限
- **WHEN** Loki 查询触及当前限制
- **THEN** 返回有界截断结果，不返回可绕过当前范围的通用 cursor

### Requirement: 资源工具审计必须先于访问且保留精确关联
tool-mcp MUST 通过通用 MCP Operation Audit 记录 server/tool/schema、Job/Session、actor、授权决定、实际 Resource identity/revision、耗时、输入输出大小与安全结果。审计建立失败时不得访问受治理上游；结果 `_meta` SHALL 返回精确关联标识。认证材料必须排除，完整有界业务载荷仅按该审计合同和保留期存储。

#### Scenario: 审计不可用
- **WHEN** 调用开始前审计数据库不可用
- **THEN** 调用失败关闭，数据库/Redis/Loki 访问次数为零

#### Scenario: 同工具使用不同版本
- **WHEN** 连续调用解析到不同 Resource Revision
- **THEN** 两次操作各自记录实际版本，Runtime 可通过 MCP 元数据准确关联

### Requirement: 资源重置必须采用有清单的维护流程
资源维护命令 SHALL 提供 report/prepare/apply/verify，限定 Database/Redis/Loki Resource 与 revision，保留 Provider、Secret、身份、角色、应用、Job、Delivery 与审计。prepare 必须排空依赖任务，apply 校验备份引用、operation 与精确清单摘要并要求明确确认；并发状态变化须拒绝。

#### Scenario: 排空失败或清单变化
- **WHEN** 仍有运行依赖任务或 apply 前清单摘要已变
- **THEN** 维护中止，不强杀任务或沿用旧清单删除

#### Scenario: 精确清单获确认
- **WHEN** 用户确认匹配的维护 operation、备份与资源清单
- **THEN** 受控事务只清理指定资源领域，verify 核对保留对象与清理结果

### Requirement: 知识资源与固定目录检索必须执行当前双重授权
系统 SHALL 通过已验证、已发布且当前启用的知识资源和代码固定 `knowledge_list_bases`、`knowledge_search` 提供入库内容读取。发布 SHALL 只确认知识库及其来源、存储、模型和分块配置可用，不冻结成员、数量或内容摘要；正常内容更新不得改变发布修订或要求重新发布。Knowledge MCP MUST 验证自身 audience/scope、RUNNING Job、冻结工具合同、当前用户/应用/角色 KB 范围及资源发布配置；命中 MUST 再校验当前知识库成员、文档修订和索引证据。部署配置 `KNOWLEDGE_ACCESS_MODE` SHALL 仅接受 `online` 或 `offline`，未设置时默认 `online`，非法值 MUST 阻止启动。对于 ONES 来源，在线检索 MUST 在平台知识库授权基础上逐项核验本人 ONES 当前可读性，403/404 项不得返回，身份、权限或服务核验失败 MUST 整次报错，禁止自动降级；只有显式 `offline` 才仅依据知识库授权读取入库内容，不依赖 ONES。代码来源 MUST 采用当前知识库授权、发布的代码来源/业务投影策略和固定源码版本范围，不依赖个人 ONES 身份，也不得借代码来源绕过 ONES 访问拒绝。模型参数 MUST NOT 覆盖部署模式或来源身份。目录仅表示平台 KB 可见性，不保证在线命中均可读。新工具、收录、索引和目录变化 MUST NOT 自动扩大旧 Publication 或 Job 的知识库范围；内容返回合同变更 MUST 更新正式发布，不改写历史快照。

#### Scenario: 发现当前知识库
- **WHEN** 当前 Job 获准调用知识目录
- **THEN** 每页最多返回 50 个当前可用知识库的安全身份、名称和状态，提供有界续页，不返回正文或文档计数

#### Scenario: 授权或发布配置变化
- **WHEN** 用户/应用/角色 KB 权限撤销、资源停用或发布配置变化
- **THEN** 目录或检索失败关闭，不回退旧配置；普通内容更新不触发发布配置变化错误

#### Scenario: 历史代码知识库授权不阻断新任务
- **WHEN** 新任务同时具有可用代码知识库和已停用、未发布或当前不可用代码知识库的历史授权
- **THEN** 模型调用前的源码能力准备与当前知识库目录使用相同的资源可用性筛选，失效条目不进入源码能力集合，也不得阻断其他可用知识库；全部不可用时允许返回空集合，由 Agent 说明无可用代码来源
- **AND** 不自动启用资源、撤销历史授权或回退旧发布；身份、存储故障和未知异常仍失败关闭；执行中的源码能力变化仍须在实际读取或续租前拒绝

#### Scenario: 显式离线模式
- **WHEN** 部署显式配置 offline，用户和业务应用具有该知识库权限，但 ONES 不可达、未绑定本人身份或未授权详情工具
- **THEN** 目录与检索仍可返回该库当前有效的入库内容，查询路径不调用 ONES

#### Scenario: 默认在线模式与故障拒绝
- **WHEN** 配置未设置或为 online，ONES 来源的身份、当前权限或来源服务核验失败
- **THEN** 检索整体失败，不降级返回离线内容；只有明确通过逐项核验的命中才可返回

#### Scenario: 非法部署配置
- **WHEN** 配置为空、拼写错误或不是 online/offline
- **THEN** 知识服务拒绝启动，不选择较宽松的模式

#### Scenario: 当前成员或修订变化
- **WHEN** 检索途中知识库授权被撤销、命中文档被移出库或修订与索引证据变化
- **THEN** 返回前复核失败并丢弃整次结果，不返回跨库或过期修订内容

#### Scenario: 内容独立生效
- **WHEN** 已发布知识库新增文档完成向量处理
- **THEN** 该文档可参与检索，资源发布修订及未变更文档保持不变

#### Scenario: 代码知识不依赖个人 ONES 身份
- **WHEN** 用户只有代码知识库与业务投影的合法权限且未绑定 ONES
- **THEN** 系统按代码来源策略提供授权的版本化结论，不调用 ONES，不向用户开放源码目录或其他来源内容

### Requirement: 知识检索必须有界且明确返回入库内容快照
`knowledge_search` SHALL 接受且仅接受 `knowledge_base_id` 或资源页面的 `resource_code` 二者之一、1–2000 字符非空查询和默认 10、范围 1–20 的 `top_k`，不得允许覆盖身份、Team、filter、collection、向量或服务地址。代码来源 MUST 要求用户显式提供数字 SVN revision，并支持固定 exact/next_higher_hint 两阶段查询，由服务解析发布来源下的仓库/分支与候选版本，模型不得设置索引过滤表达式。目录和检索 SHALL 受最多 360 秒及当前 Job 剩余预算共同约束。ONES 检索 SHALL 返回文档/修订/索引/来源/工作项引用、原来源编号、完整标题、原状态、来源项目、来源更新时间、入库时间、排序和每项最多三条带位置/hash 的已入库文本片段；每片段最多 1200 字符，总响应最多 512 KiB，超限明确失败，不悄悄丢弃标题。代码检索 SHALL 在相同 top_k、片段及总响应边界内返回答案/修订/来源/索引引用、标题、结论支持状态、适用条件摘要、覆盖与未知项标记、已解析 SVN 身份及证据投影引用；片段不得冒充完整规则。结果 MUST 标明来源对应的 `access_mode`、`ingested_snapshot` 与 `matched_chunks`，不得宣称完整文档、来源最新状态或完整检索结果；入库时间不得冒充来源更新时间或最近采集时间。零命中、受限部分结果和依赖失败 MUST 分别表达，认证材料、查询原文和业务正文不得复制到普通安全摘要或日志。ONES 在线模式复用当前用户已授权的 ONES 详情能力作实时可读性核验，通过后仍返回带来源时间和入库时间的快照片段；实时权限不意味着快照是最新正文。离线模式不要求 ONES 详情能力。代码检索 MUST NOT 因版本缺失隐式申请整版业务预提取。

#### Scenario: 合法检索
- **WHEN** 合同、索引与当前知识库权限均有效且存在命中
- **THEN** 按来源与部署模式完成所需权限核验后返回当前入库修订的有界内容片段和元数据，说明实际模式、快照时间与范围

#### Scenario: 预算或依赖失败
- **WHEN** 总预算耗尽、依赖异常或读取投影不完整
- **THEN** 返回稳定失败；正常有界搜索产生部分结果时明确 `partial`，不能将依赖失败报告为空库

#### Scenario: 代码版本尚无答案
- **WHEN** 固定 SVN 版本下没有已就绪答案，但来源和检索服务正常
- **THEN** 返回带固定版本的正常未命中事实，不申请整版构建；后续只能通过单独授权的问题核验操作补充证据

#### Scenario: 按资源编码直接检索
- **WHEN** 用户提供明确资源编码，例如 mes_story
- **THEN** Agent 可直接调用 knowledge_search(resource_code=编码)，无需先提供 UUID 或查询目录；服务在当前 Job 授权范围内精确解析后复用全部来源、发布、索引和版本校验，结果返回规范 knowledge_base_id
- **AND** 目录 code 与资源页面编码一致，不使用底层内容库编码替代

#### Scenario: 编码不存在或未授权
- **WHEN** 资源编码不存在或对应知识库不在当前授权范围
- **THEN** 返回同一安全拒绝，不查询正文、向量或其他知识库；同时提供编码和 ID 或均未提供时拒绝参数

#### Scenario: 编码指向失效资源
- **WHEN** 已授权编码对应资源停用、未发布，或解析过程中该知识库被另一资源接替
- **THEN** 拒绝该编码检索，不将其自动映射到另一启用资源；调用期间权限及发布变化仍按原有规则拒绝

#### Scenario: 代码库按编码检索
- **WHEN** 用户通过资源编码查询代码知识库
- **THEN** 仍须明确环境和 SVN 数字版本，保持同版本优先及更高版本仅作线索；后续核验使用结果中的知识库 ID

### Requirement: 知识检索必须记录安全的阶段耗时与预算来源
系统 SHALL 为进入统一工具审计的知识读取记录有效截止、入口剩余预算、截止来源、固定阶段耗时和停止阶段，成功与失败均保留。重排 SHALL 区分排队与计算耗时，并通过随机请求标识关联安全服务事件。观测 MUST NOT 包含凭证、查询原文、候选正文或任意远端字段；未收到重排计时不得当作零耗时。观测 MUST NOT 延长预算、弱化当前授权或改变工具结果合同。

#### Scenario: 重排中预算耗尽
- **WHEN** 知识检索在重排排队或计算中超时
- **THEN** 工具失败审计保留停止阶段、截止与已知耗时，可按请求标识核对重排安全事件；未收到的细分计时明确未知

#### Scenario: 成功在线检索
- **WHEN** 检索完成本人 ONES 可读性检查并返回入库快照
- **THEN** 成功审计分别包含向量检索、重排及可读性耗时，返回的知识内容合同保持不变

#### Scenario: 较短上游或任务截止
- **WHEN** 上游截止或当前 Job 剩余时间比单次 360 秒更短
- **THEN** 审计反映实际生效的较短截止来源，后续阶段和续期不得重置截止

### Requirement: 代码问答必须提供用户指定的 SVN 版本
代码问答 MUST 在用户提供明确数字 svn_revision 后才进行知识检索或源码分析；缺失时返回 SVN_REVISION_REQUIRED 并引导补充，不能用默认配置、现场绑定、checkout 当前版本或 HEAD 代替。来源/仓库 UUID/分支由发布的代码 KB 配置确定；查询、更新、保存及回答必须保留用户 requested_revision。直接复用的答案 MUST 同时满足相等版本、当前权限、有效知识修订、业务条件和足够证据，不凭相似度跨版本认定规则相同。

#### Scenario: 未提供版本
- **WHEN** 用户询问代码业务规则但未给 SVN 数字版本
- **THEN** 先要求补充，不检索、update 或创建带猜测版本的缓存；页面和 Skill 都提示版本必填

#### Scenario: r100 与 r101 不同
- **WHEN** 用户明确询问 r100，而缓存中 r101 允许 A 为空
- **THEN** r101 不作为 r100 的直接答案，响应和最终知识始终分别标明请求版本与证据版本

#### Scenario: 目录已更新
- **WHEN** 本地目录从 r100 更新到 r101 后用户查询已有 r100 答案
- **THEN** r100 可按自身身份及适用条件复用，不要求工作副本停在 r100，不读取当前文件冒充旧证据

### Requirement: 版本回退必须只提供最近更高版本的核验线索
knowledge_search MUST 先执行 exact 并用 svn_revision=N 硬过滤；无适用证据时才允许 next_higher_hint，关联同 Job 的成功 exact search_id、相同 KB/问题/用户版本和缺证据理由。服务端 SHALL 从同仓库/分支及当前授权、就绪知识版本中选择最小 R>N，只查询该版本一次；无相关线索时转查 N 的源码，不无限遍历其他版本或自动查较低版本。回退结果 MUST 包含 requested_revision=N、matched_revision=R、match_kind=higher_revision_hint、requires_verification=true 及差值。完整答案读取也必须保留搜索上下文和这些标记，不能通过直接读答案 ID 消除核验要求。相等结果与较高结果不混合排序。

#### Scenario: 选择最近更高版本
- **WHEN** r100 无适用证据，同来源授权就绪版本中有 r101 和 r105
- **THEN** 只将 r101 的相关命中作为线索，即使 r105 相似度更高也不越过版本选择；r101 无相关线索则查 r100 代码

#### Scenario: 高版本规则与目标相反
- **WHEN** r101 线索允许 A 为空，而实际核验 r100 要求非空
- **THEN** 最终回答与新知识保存 r100 的真实规则，r101 原记录保持原身份，不把较高答案复制成 r100

#### Scenario: 无法核验用户版本
- **WHEN** 只能找到较高版本线索且 r100 不可取得、无代码权限或关键证据不足
- **THEN** 明确不能确认 r100，不直接将 r101 的结论作为 r100 答案，不写入 r100 的确定答案索引

#### Scenario: 前置故障或越权版本
- **WHEN** exact 阶段故障，或较高版本仅存在于未授权 KB/分支
- **THEN** 故障不转成无命中；越权版本既不能被选择也不能泄露存在性，两个阶段共用总预算

### Requirement: 查代码必须由同一问答 Job 在知识证据不足后执行
系统 SHALL 先通过知识检索检查同版本答案，正常未命中、条件不符、关键证据不足或冲突时，才允许当前问答 Agent 使用来源授权的 SVN 工具和源码读取。`knowledge_svn_update` MUST 关联同 Job 的成功检索记录、相同知识库/来源/requested_revision/问题及缺证据理由，重新检查当前用户/应用/角色与来源策略。核验 MUST 在原问答 Job 中执行，不创建独立提取 Agent、专用服务账号 Job 或整包构建。访问拒绝、索引故障和依赖失败不能作为代码兜底理由。

#### Scenario: 首次问题无答案
- **WHEN** 合法检索在确定版本下正常未命中且应用允许代码分析
- **THEN** 原 Agent 请求更新/检查工作副本并在授权后读取代码，同一 Job 输出回答，不派发另一模型任务

#### Scenario: 命中但缺条件
- **WHEN** 检索结果缺少当前问题的关键分支证据
- **THEN** 可关联该成功搜索进行补证，不能只因存在相似文本就阻止查代码

#### Scenario: 检索失败或请求改变版本
- **WHEN** 前置搜索失败或 update 请求与搜索的知识库/来源/版本不一致
- **THEN** 拒绝读代码准入，保留原失败或要求对正确版本重新检索，不绕过权限和版本选择；较高版本线索的 matched_revision 不能成为 update 目标

### Requirement: SVN 工具必须复用固定 Knowledge MCP 和执行器
系统 SHALL 在现有 Knowledge MCP 提供 `knowledge_svn_update`、`knowledge_svn_info`、`knowledge_svn_log`、`knowledge_svn_diff`、`knowledge_svn_blame`、`knowledge_get_source_operation`，通过已认证控制面桥接交由 knowledge-sync 执行。工具 MUST 仅接受已登记知识库/来源/checkout、受控相对路径、版本/时间/行范围及操作标识，不接受任意 URL、宿主路径、凭据、可执行文件或 Shell 参数。update SHALL 声明受限工作副本修改副作用，在正式发布与来源授权下自动执行，但不提供仓库 commit/merge/revert/switch 或业务 mutation 确认豁免。

#### Scenario: Runtime 请求更新
- **WHEN** Agent 请求将已登记工作副本更新到确定 N
- **THEN** knowledge-sync 在取得独占写权限后执行固定参数 update，Runtime 自身只读挂载不变；若已在 N 且无写者则只检查并加入共享读取，不实际 update

#### Scenario: 同一目录已在分析
- **WHEN** 多个分析持有 N 的读占用，又请求实际 update 或切换到 N+1
- **THEN** 修改请求返回 WORKSPACE_BUSY；其他获授权 N 版本分析仍可共享读取，不抢占现有读者

#### Scenario: 非法目标
- **WHEN** 参数含任意绝对路径、未登记仓库、路径穿越或命令串
- **THEN** 在执行前拒绝，不将模型输入拼接为 Shell 命令

#### Scenario: 提交包含越权路径
- **WHEN** log -v 同时包含授权范围外的路径或复制来源
- **THEN** 返回前过滤并标明范围限制，无法安全投影的提交说明省略，不能沿复制信息越权读取

### Requirement: SVN 历史必须明确时间修订与文件身份语义
log SHALL 支持最近 N 次、单 revision、含两端 revision_range、明确时区的 time_range，并可限定文件/目录；返回授权内的 revision、时间、作者、说明及 A/M/D/R 路径。时间 SHALL 按实际提交时间的半开区间过滤，日期范围包含用户选择的结束日全天，不能假设 revision 时间单调。每次分析的数字版本上限、peg 和历史范围 MUST 固定，分页不得漂移；缺失元数据明确未知。info SHALL 区分仓库 revision、文件 last_changed_revision、选中项 operative revision 范围及 mixed/modified/switched。

#### Scenario: 最近一百条与分页
- **WHEN** 查询最近 100 次提交且查询后出现新提交
- **THEN** 结果同时包含允许的时间/作者/说明/文件列表，续页保持原数字上限，不混入新 revision

#### Scenario: 包含结束日
- **WHEN** 查询 Asia/Shanghai 下 2026-10-01 至 2026-11-09
- **THEN** 使用 [2026-10-01T00:00:00+08:00,2026-11-10T00:00:00+08:00)，不漏掉结束日白天，不把日期定位得到的区间外提交当命中

#### Scenario: 含端点范围与升级新增提交
- **WHEN** 查询 51000..52089 日志或询问从 51000 升到 52089 新增的提交
- **THEN** 前者包含两端，后者使用 51001..52089；返回实际覆盖，不能用端点 diff 代替提交记录

#### Scenario: 本地 import 不含原历史
- **WHEN** 本地 SVN 只包含 import 后的新历史而请求原公司 revision
- **THEN** 根据真实 UUID 和历史起点报告不可用，不伪造本地与原仓库数字版本的对应关系

### Requirement: 差异和行归属必须绑定确定版本并有界返回
diff SHALL 支持单提交 N-1→N、明确两端 revision 的文件摘要/单文件文本，不比较未提交本地修改；blame SHALL 使用指定版本的原文件行号。结果 MUST 关联实际路径、两端/peg、观察时间与摘要；处理删除重建和授权内重命名，不隐式回退 HEAD。log 默认 100、每页最多 200 条；diff 文本最多 256 KiB、blame 每次最多 400 行，MCP 响应最多 512 KiB，所有命令受执行时间及 Job 剩余预算约束。超限、不可用、部分覆盖和无变化 MUST 分别表达，cursor 绑定授权/路径/版本/筛选与结果身份。

#### Scenario: 修改后恢复原样
- **WHEN** 两端内容相同但中间存在修改提交
- **THEN** diff 可为空、log 仍有历史，Agent 不据空 diff 宣称期间没有变化

#### Scenario: 文件重建与行归属
- **WHEN** 同路径被删除重建或 blame 显示格式调整提交
- **THEN** 使用 peg/operative 区分对象；行最后修改归属不能单独证明业务变化点或个人责任

#### Scenario: 超限或游标越界
- **WHEN** 大型提交达到路径/时间预算，或 cursor 被用于另一版本/权限范围
- **THEN** 前者明确 partial/paths_truncated 及实际覆盖，后者拒绝，不输出伪完整证据

### Requirement: 结果保存必须通过受控答案工具校验证据
系统 SHALL 提供 `knowledge_save_code_answer`，接收当前 analysis_id、幂等键及有界的结论/条件/证据引用/覆盖/未知项，在有效读取占用内完成版本和实际工具读取记录核对后保存。Job、仓库、版本和验证状态 MUST 来自服务端绑定，模型不得覆盖或直接写库。该工具声明受限知识派生副作用，沿用当前发布/来源策略；一次分析完成后撤销该 Job 的 grant 并只释放其读占用，不影响其他读者。数据保存与向量就绪 SHALL 分开返回；partial/conflicted 不进入确定答案索引。

#### Scenario: 有证据的结论保存
- **WHEN** 原问答 Agent 提交条件完整且证据可核实的结果
- **THEN** 校验和 PG 提交在读占用释放前完成，返回答案引用及 SVN 版本，其他读者继续；模型不执行 SQL/Qdrant 写入

#### Scenario: 伪造证据或目录变化
- **WHEN** 引用未读取文件、错误行号/hash、其他 Job 的证据或本地版本已变化
- **THEN** 拒绝准入，不将其标为确定答案；必要时终止受影响分析

#### Scenario: 成功响应丢失
- **WHEN** PG 已提交并释放本次占用，原合法 Job 重放相同保存请求
- **THEN** 返回已提交的相同结果，不重新读目录、生成重复答案或重复模型执行

### Requirement: 完整答案必须提供当前授权的业务投影
`knowledge_get_code_answer` SHALL 返回最多 512 KiB 的完整结论、条件、覆盖、未知项、支持状态、SVN 身份与证据引用，超限明确失败或有界续取，不能省略条件后声称完整。读取代码答案须关联本 Job 的合法搜索结果并保留 requested_revision/matched_revision 和 requires_verification；源码正文、内部路径与历史明细须独立授权，普通用户只获得发布允许的业务投影。Agent MUST 区分代码规则、未知现场配置和生产事实，返回前复核当前修订及权限。

#### Scenario: 搜索片段遗漏配置例外
- **WHEN** 片段相关但完整答案包含影响结论的配置分支
- **THEN** 读取完整答案后再回答，保留例外与 SVN 版本

#### Scenario: 答案已纠正或撤权
- **WHEN** 答案修订被替代或来源/调用者权限撤销
- **THEN** 不返回旧修订或源码作为兜底，按当前有效状态重新检索

### Requirement: 代码问答默认以业务语言呈现并在后台保留证据
代码问答的 Skill、工具说明和 Runtime 回答约束 MUST 一致要求默认按结论、触发条件、操作影响和必要待确认项组织回答，保留环境、SVN 版本、适用业务端、完整条件、例外和影响结论的未知项。正文 MUST NOT 主动展示源码、文件路径、行号、函数名、内部字段/枚举、接口/工具名、原始错误码、hash、内部 ID 或检索/保存/索引过程；依赖失败影响结论时以业务语言说明实际影响，用户明确要求保存但失败时须如实说明。状态名称、配置和现场根因未经核验不得猜测为事实。仅在用户明确要求技术分析且当前授权允许时可展开相关技术证据，不能借此扩大授权或披露凭据。

保存的业务标题、正文和结论 SHALL 使用业务语言，详细证据继续保存在后台结构化记录中。命中历史知识时 SHALL 按相同规则重述，不照搬历史技术细节，不丢失适用条件。实际采用的完整答案引用 SHALL 通过内部标记关联，平台 MUST 核验同任务、同环境、来源与版本下真实成功读取或保存的记录，并在会话消息、报告、Job 结果和投递前移除标记；不得把候选、失败或未采用的答案自动记为依据。

#### Scenario: 普通用户询问操作被阻止
- **WHEN** 已核验页面操作在某质量状态下被阻止，但该状态业务名称或后续校验尚未确认
- **THEN** 用页面、操作步骤和业务影响解释已确认规则，保留未知范围，不输出代码或把推测名称当事实

#### Scenario: 复用含技术细节的历史答案
- **WHEN** 当前环境、版本和条件匹配的完整答案含文件路径、内部字段或工具回执
- **THEN** 重述为业务解释并保留条件与未知项，详细证据和经核验的引用仍在后台保留

#### Scenario: 隐藏引用但保持可追溯
- **WHEN** 最终结果包含本任务实际采用答案的内部引用
- **THEN** 后台保存经核验的结构化关联，用户可见会话、报告、Job 结果与投递正文不含内部标记和 ID

### Requirement: 重排必须在来源权限与版本筛选后执行
ONES 与代码检索 SHALL 复用已配置的固定重排服务与有界合同；候选进入重排前必须完成各自来源/KB/权限/版本过滤，代码 exact 与 higher hint 分阶段重排，重排分数不能覆盖版本优先级或免除目标版本核验。服务忙、超时或配置不符必须保留失败事实，不能作为零命中转源码兜底。

#### Scenario: 高版本分数更高
- **WHEN** r100 相等版本有适用答案而 r101 文本更相似
- **THEN** 仍使用 r100，不将 r101 混入同批排序或据高分直接覆盖 r100

#### Scenario: 共用服务繁忙
- **WHEN** ONES 与代码候选同时请求重排导致预算耗尽
- **THEN** 返回受限繁忙/超时事实，不误判知识不存在，审计不记录候选正文

### Requirement: 代码知识调用必须绑定用户明确的环境
代码知识目录 SHALL 接受 `source_kind=code` 和明确 `environment` 编码，仅返回当前授权、已发布且关联该启用环境的代码知识库；未指定来源类型时沿用 ONES 目录。代码检索、全文答案和源码工具 MUST 携带同一环境，服务端解析稳定环境身份并验证当前发布关联。搜索和源码准入 MUST 核对当前用户问题中的明确环境声明，缺失、未知、停用、多个环境或不匹配时失败关闭，不从默认配置或模型参数推断用户选择。环境不扩大 KB 授权。

#### Scenario: 未指定环境
- **WHEN** 用户代码问题只有 SVN 版本而没有明确环境
- **THEN** Agent 追问环境，后端拒绝代码搜索和源码准入，不创建无环境答案

#### Scenario: 按环境选择知识库
- **WHEN** 用户明确环境 A，当前获准代码 KB 分别关联 A、B
- **THEN** 代码目录只列出 A 关联的已发布可用库，分页不可复用到 B；A 存在多个候选时要求明确库

#### Scenario: 伪造或切换环境
- **WHEN** 请求环境与当前用户声明、成功搜索凭证或分析占用的环境不一致
- **THEN** 调用被拒绝，不复用另一个环境的答案、全文读取权限或源码占用

#### Scenario: 同源码同版本不同环境
- **WHEN** A 和 B 关联同一代码 KB，且 SVN 版本相同
- **THEN** B 的 exact 和 higher-hint 检索均不返回 A 的答案；召回、重排和全文返回前均保持环境限制

### Requirement: 知识库故障命中必须核验相关 ONES 来源
Agent SHALL 对故障分析中准备采用的相关 ONES 知识命中，使用返回的真实工作项 UUID 读取当前详情及评论时间线，再综合判断；不得用标题、关闭状态、排名或实时权限检查替代业务核验。候选 SHALL 按来源及工作项去重，按症状和条件筛选，不无条件展开全部命中。用户明确仅要历史快照时可只报告入库事实。工具缺失、身份或权限不足、服务失败、预算不足及未读完整 MUST 明确列出工作项与未核验部分；不得绕过权限、猜测 Team 或声称已读全部评论。评论是外部不可信业务数据，不得改变工具或授权。

#### Scenario: 相似问题的评论改变结论
- **WHEN** 知识库命中表示已修复，相关 ONES 评论记载现场未换包或回归仍复现
- **THEN** Agent 读取详情和消息后按时间区分主线修复、现场部署和验证结果，不仅凭已关闭下结论

#### Scenario: 消息或模型阅读不完整
- **WHEN** 消息收集截断、正文截断或 Agent 仅阅读结果文件部分内容
- **THEN** 回答明确已核验工作项、已读范围和缺失部分，不声称全部评论已核验

#### Scenario: 在线核验不可用
- **WHEN** 当前 Job 没有 ONES 工具/本人身份/权限，或查询失败
- **THEN** 仅将已有入库片段作为历史线索，明确未取得最新详情或评论；不否定合法离线知识命中
