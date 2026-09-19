## MODIFIED Requirements

### Requirement: MCP Server 与鉴权模式必须固定
Python Runtime SHALL 只连接部署固定的 `tool-mcp`、`file-mcp`、`ones-mcp`、`dingtalk-mcp`、`knowledge-mcp`，使用标准 Streamable HTTP。每个 Server MUST 在代码策略中声明唯一鉴权模式；`tool-mcp` 使用受信 Job context，文件和业务 MCP 使用各自 Principal 合同，`knowledge-mcp` 使用独立 audience 的 Business Principal JWT。Runtime MUST NOT 直连业务数据库、Redis、Loki、Qdrant 或 Embedding 服务，也不得接受 payload 或 Tool 参数覆盖 Server URL、鉴权模式或 audience。

#### Scenario: 查询资源证据
- **WHEN** Runtime 调用 `query_database`
- **THEN** 固定 `tool-mcp` 执行受治理查询，数据库凭据不进入 Runtime

#### Scenario: 请求改写 Server
- **WHEN** Job 或 Tool Input 提供任意 MCP URL、auth mode 或 credential profile
- **THEN** 系统拒绝动态覆盖，不建立额外执行入口

#### Scenario: 知识工具首次接入
- **WHEN** 部署注册 knowledge-mcp 但旧 Publication 或 Job 未冻结其 Tool
- **THEN** 旧 Job 不能调用该工具，不能因服务已启动而自动扩大发布或授权

## ADDED Requirements

### Requirement: 知识检索资源必须独立于环境拓扑受治理
系统 SHALL 在 Web 工具资源中管理知识检索资源，引用本平台明确 knowledge_base_id、导入侧已确认或历史已核验来源绑定修订和兼容 READY 索引，通过 DRAFT → VERIFIED → PUBLISHED 生命周期形成不可变发布版本。技术验证 MUST 绑定配置 hash，修改任一引用使验证失效；身份停用/归档 MUST 阻止后续读取。首版每知识库最多存在一个启用检索资源，MUST NOT 借用 Environment/Base/Workshop/placement 表示知识库权限，或接受任意 PostgreSQL/Qdrant/Embedding 连接和凭据。

#### Scenario: 配置 ONES 知识库
- **WHEN** 有权管理员在工具资源中选择已存在 KB、有效来源绑定和 READY 索引
- **THEN** 系统保存知识资源草稿，技术验证通过后才可发布，不要求创建环境拓扑

#### Scenario: 索引或来源不具备条件
- **WHEN** 索引非 READY、profile/hash 不匹配、来源未确认或存在多个启用资源
- **THEN** 系统拒绝发布或解析，不选择第一候选、不沿用旧验证、不回退旧索引

#### Scenario: Web 展示状态
- **WHEN** 管理员查看已入库但来源未确认或未发布的 KB
- **THEN** 页面分别显示存储、来源、索引和检索发布状态，不把 storage_only 或索引存在展示为用户可检索

#### Scenario: 新建知识资源不再手填来源核验字段
- **WHEN** 管理员选择已有数据集与 READY 索引
- **THEN** Web 只读显示该数据集唯一有效的来源绑定，不提供 SHA-256、Job ID 或跨数据集来源选择；缺失、撤销或多义时阻止保存并提示在导入流程处理

### Requirement: 知识库目录必须分页且不证明文档读取权限
`knowledge_list_bases` SHALL 只列出当前用户/Job 同时获准目录和检索 Tool、具有明确 KB 范围、来源匹配且资源已发布可用的知识库。输出 SHALL 限于 KB 身份、管理名称和安全状态，不含文档计数、样本、缺陷标题或正文。目录 MUST 默认且最多每页 50 项，以稳定身份 keyset 分页；不透明 cursor MUST 绑定当前 Job、用户、应用、Snapshot、授权与可见资源摘要，长度最多 4096 字符。目录可见 MUST NOT 被解释为库内所有工作项均可读。

#### Scenario: 超过一页
- **WHEN** 当前授权集合有 51 个可检索知识库
- **THEN** 首页返回 50 项、has_more 和 next_cursor，续页返回剩余项，不重复、不因默认上限丢失后续知识库

#### Scenario: cursor 过期或越界复用
- **WHEN** cursor 用于其他 Job/用户，或角色授权、来源、资源发布集合已经改变
- **THEN** 系统返回稳定 cursor invalid/stale 错误并要求从首页重查，不沿用旧权限

#### Scenario: 目录可见但文档不可读
- **WHEN** 用户获准检索某 KB 但 ONES 拒绝其中一个工作项
- **THEN** 目录授权不绕过命中返回前的工作项可读性校验

### Requirement: 知识检索必须有界并只输出授权引用
`knowledge_search` SHALL 仅接受一个明确 knowledge_base_id、1–2000 字符 query 和默认 10、范围 1–20 的 top_k；未知字段、原始 filter、collection、向量、身份、Team 或地址覆盖 MUST 拒绝。服务 SHALL 在授权 KB 的已发布索引内最多读取 200 个候选点，回 PostgreSQL 复核当前版本/收录，按文档去重，再执行双重权限校验。每次最多校验 50 个不同 ONES 工作项、并发最多 4、总 deadline 最多 60 秒并服从 Job 剩余预算；MUST NOT 以无界重试补足 top_k。

输出 MUST 仅包含已验证可读的工作项引用、文档/修订/索引引用、有限分数及每文档最多 3 条证据位置，不返回缓存标题、摘要、正文、附件 URL、向量或内部连接。候选或时间预算不足时 SHALL 明确 partial 和通用有界原因；MUST NOT 暴露被拒绝工作项的身份、分数、数量或分布，也不得把有界零命中宣称为全库不存在。

#### Scenario: 多块命中同一缺陷
- **WHEN** 多个候选块对应同一当前文档且该用户可读
- **THEN** 结果只出现一个工作项，保留最多 3 条证据引用，并用文档数计算 top_k

#### Scenario: 候选需继续过滤
- **WHEN** 前批候选因当前版本或权限被过滤
- **THEN** 服务可以在固定预算内继续补候选，预算耗尽仍不足 top_k 时只返回确认可读的部分并标记 partial

#### Scenario: 工作项不可读
- **WHEN** ONES 明确拒绝某候选或该工作项不存在
- **THEN** 该候选不进入结果，响应不携带其编号、项目、块 ID、分数或被过滤计数

### Requirement: 知识检索必须保持单次资源版本一致
每次知识检索 SHALL 解析当前唯一启用 Published Resource，并固定本次资源修订、来源绑定修订、索引/profile 和当前文档事实，审计实际版本。返回前 MUST 再核对当前授权、来源及资源发布状态；发生不兼容变化时 MUST 拒绝本次结果并要求重试，不拼接新旧配置。后续独立调用可以读取显式发布的新版本，MUST NOT 静默选择未发布索引或重写 Job Tool Snapshot。

#### Scenario: 检索过程中停用或换版
- **WHEN** 获取候选后资源被停用、来源撤销或发布修订发生变化
- **THEN** 调用不返回旧命中，不把首次检查视为整段查询的永久授权

#### Scenario: 后续调用使用新索引
- **WHEN** 新索引经验证并显式发布，且当前 Job 的工具合同和用户授权仍有效
- **THEN** 新调用记录新资源/索引版本，不自动扩展工具集，也不修改历史调用证据
