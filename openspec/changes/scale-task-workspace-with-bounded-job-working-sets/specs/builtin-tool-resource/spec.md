## ADDED Requirements

### Requirement: File MCP提供冻结且有界的工作区目录发现
File MCP SHALL在代码Manifest中发布`task_workspace_search_files`固定Tool identifier与封闭schema。Agent/Application Publication和Job MUST冻结其精确schema hash后才可调用；服务端必须使用File MCP Principal解析Job、主体、tenant、Session、Publication和workspace，并在每次查询时复核当前角色、Application Tool子集及会话归属。

该Tool每页 MUST最多返回50个不含正文、对象位置和凭据的元数据项，支持代码注册的名称、格式、UTC来源接收时间和可读状态过滤以及不透明游标。Tool结果中的精确File/Version只构成可选择身份，不自动授予MATERIALIZE、EDIT、COMMIT或DELIVER。

#### Scenario: Publication冻结新发现Tool
- **WHEN** RUNNING Job的MCP Tool Snapshot包含`task_workspace_search_files`及匹配schema hash
- **THEN** File MCP按当前Principal和workspace执行有界元数据查询
- **AND** 统一MCP Operation Audit记录过滤摘要、目录revision、返回数量和耗时而不记录正文

#### Scenario: Job没有冻结新发现Tool
- **WHEN** Runtime尝试为未冻结该Tool的Job调用`task_workspace_search_files`
- **THEN** File MCP在目录查询前拒绝
- **AND** 不因服务已经部署新Tool而扩大旧Job能力

#### Scenario: 单页请求超过50项
- **WHEN** Tool输入的limit为51或更大
- **THEN** 封闭schema拒绝参数
- **AND** 不执行数据库查询或静默改写为更大上限

#### Scenario: 发现结果用于准备物化
- **WHEN** 兼容Job把发现结果中的精确File/Version传给`file_prepare_materialization`
- **THEN** File Service先执行工作集晋升、20项上限和实时授权复核，再准备transfer
- **AND** 发现结果本身不绕过任一内容授权检查

### Requirement: 动态文件选择沿用既有Principal与统一审计
Manifest外文件的工作集晋升 MUST只发生在已经冻结兼容发现Tool和`file_prepare_materialization`的同一RUNNING Job内。File Service MUST校验两个Tool的Job Snapshot/schema hash、当前Principal全部绑定事实、精确ACTIVE工作区成员和当前Version，并把允许或拒绝结果写入统一MCP Operation Audit及追加工作集事实。输入与审计 MUST NOT包含文件正文、Principal JWT、MinIO对象位置或凭据。

#### Scenario: 跨工作区精确ID被提交
- **WHEN** Agent把另一个workspace的精确File/Version提交给动态选择路径
- **THEN** File Service在创建工作集事实或transfer前拒绝
- **AND** 审计只保存安全的拒绝码和不透明身份摘要

#### Scenario: 工作集上限拒绝被审计
- **WHEN** 第21个不同内容项触发`job_file_working_set_limit_exceeded`
- **THEN** 统一审计记录Job、Tool、workspace、拒绝码和当前有界计数
- **AND** 不记录正文、对象位置或未受限查询结果
