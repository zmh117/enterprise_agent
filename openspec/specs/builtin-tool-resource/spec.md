# builtin-tool-resource Specification

## Purpose
定义代码注册的 MCP 工具、受治理 Database/Redis/Loki 资源、授权资源发现和只读诊断合同。身份与角色授权见 `identity-access`，业务 Provider 工具见 `governed-api-capability`，文件工具见 `task-file-workspace`，通用运行审计与外部操作确认见 `execution-delivery`。

## 实现依据与验证边界

当前合同以 `backend/app/modules/mcp_tool_runtime/`、`backend/app/modules/agent/infrastructure/tool_manifest.py`、`backend/app/modules/platform_config/application/governed_resources.py`、`resource_scope_bindings.py`、`database_resource_verifier.py`、`backend/app/shared/resource_role.py`、`loki_contract.py`、`backend/docker/setup_oracle_client.sh` 和 `verify_oracle_client.py` 的实现为依据。回归依据包括 `backend/tests/test_tool_pagination.py`、`test_resource_scope_bindings.py`、`test_governed_tool_resource_lifecycle.py`、`test_loki_resource_scoped_labels.py`、`test_loki_line_limits.py`、`test_oracle_resource_verification.py`、`test_oracle_image_contract.py` 与 `test_redis_scan_pagination_integration.py`。

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
Python Runtime SHALL 只连接部署固定的 `tool-mcp`、`file-mcp`、`ones-mcp`、`dingtalk-mcp`，使用标准 Streamable HTTP。每个 Server MUST 在代码策略中声明唯一鉴权模式；`tool-mcp` 使用受信 Job context，文件和业务 MCP 使用各自 Principal 合同。Runtime MUST NOT 直连业务数据库、Redis 或 Loki，也不得接受 payload 或 Tool 参数覆盖 Server URL、鉴权模式或 audience。

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
`list_available_tool_resources` SHALL 分页返回当前 RUNNING Job、当前用户、业务应用、角色访问、Application Tool 子集与精确 Job Snapshot 共同允许的 Database/Redis/Loki 当前 Published Resource 地址。目录自身必须被冻结授权；业务应用内必须在同一条角色应用访问记录中同时满足数据 Tool 与 scope，不得跨角色拼接。只返回安全地址、可用工具和 resolution_status，不返回 host、port、username、Secret reference 或 scope 内部条件。

#### Scenario: 当前应用内发现资源
- **WHEN** Job 冻结目录及相应数据 Tool，且同一访问记录同时允许 Tool 与目标
- **THEN** 目录返回对应非敏感资源地址及 AVAILABLE 或 AMBIGUOUS 状态

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
Database Tool MUST 使用实际 Resource 的数据库/schema 和适用的 Workshop 表前缀，拒绝结构目录外的表。查询行数最多 100，执行超时最多 30 秒并与更小平台限制取交集；结果受序列化容量限制并明确 truncated。空目录 MUST 返回 `mcp_schema_directory_empty`；字段或语法错误返回可停止的安全错误，不能引导无界猜表、猜字段。

#### Scenario: Workshop 跨表前缀
- **WHEN** Workshop 查询引用其他 Workshop 或缺少要求前缀的表
- **THEN** 请求被只读范围策略拒绝

#### Scenario: 达到结果上限
- **WHEN** 查询达到行数或响应字节上限
- **THEN** 只返回有界结果和截断事实，不提供通用 offset cursor

#### Scenario: 结构目录为空
- **WHEN** 资源没有可用的受限表目录
- **THEN** 系统拒绝执行 SQL，Agent 停止并报告证据不足

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
平台 Loki 单次行数默认上限 SHALL 为 10000，Web 新建资源默认 max_lines=1000，管理 API/Web 对新建编辑统一限制 1–1000。调用以平台限制与已发布资源 max_lines 的较小值校验，省略 limit 使用 100；超限请求不得自动夹取或分页。该值不是 Job 累计行数预算。

#### Scenario: 请求超过有效上限
- **WHEN** 平台 10000、资源 1000，Agent 请求 1001 条
- **THEN** Provider I/O 前拒绝；1000 为合法边界

#### Scenario: 多次合法查询
- **WHEN** 同一 Job 多次调用各自均未超过有效上限
- **THEN** 不因累计行数超过 10000 而拒绝，原工具次数、时间与容量限制仍生效

#### Scenario: 已有显式配置
- **WHEN** 已存在显式平台限制或已发布资源配置
- **THEN** 默认值不改写它们，运行继续取较小值；资源重新编辑验证时适用当前输入范围

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
