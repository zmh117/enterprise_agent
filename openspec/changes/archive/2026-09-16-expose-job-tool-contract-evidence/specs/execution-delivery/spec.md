## ADDED Requirements

### Requirement: 每次Runtime调用必须形成不可变工具契约观测
系统 SHALL 对每个 Runtime protocol 1.4 invocation 在首次模型请求前形成并保存一个与 `job_id`、`invocation_id`、`request_digest` 和既有 Job MCP Tool Snapshot hash 绑定的 `tool_contract_observed` 安全事件。该事件 MUST 分别记录 Job frozen、File MCP live、Runtime effective 和 Prompt declaration 四层事实及其 hash、来源和确定性对账状态；Runtime effective 还 MUST 记录传给 SDK 的精确可调用名称。事件不得保存完整 Tool Schema、Tool 描述、完整 Prompt、业务正文、URL、Header、Token、凭据或原始 MCP/SDK payload。

相同 invocation 与 request digest 的重放 MUST 复用同一 observation hash；相同 invocation 携带不同 digest 或不同观测内容 MUST 失败关闭。Worker SHALL 以既有 Runtime event 唯一约束幂等保存该事实，不得用后续 invocation 覆盖或改写既有观测。

#### Scenario: 模型调用前完成四层观测
- **WHEN** Runtime准备执行一个包含File Service冻结工具的protocol 1.4 invocation
- **THEN** Runtime在首次模型请求前完成File MCP live、Runtime effective和Prompt declaration对账并发出`tool_contract_observed`
- **AND** Worker保存的事件能够关联到该Job既有MCP Tool Snapshot而不复制或改写Snapshot

#### Scenario: Runtime恢复相同invocation
- **WHEN** Worker以相同`invocation_id + request_digest`恢复已经保存观测或终态的调用
- **THEN** Runtime和Worker复用相同observation hash且不产生第二套工具事实
- **AND** 不再次询问模型来判断工具是否可用

#### Scenario: 安全事件不泄漏工具或业务载荷
- **WHEN** 操作者、审计测试或运行记录API读取工具契约观测
- **THEN** 只可见有界标识、来源、平台、版本、hash和稳定状态
- **AND** 不存在完整Schema、描述、Prompt正文、MCP原始响应、Principal JWT或业务文件内容

### Requirement: File MCP必须在模型调用前校验实时工具声明
只要Job冻结了`file-service`工具，Python Runtime File bridge MUST 使用当前Job File Principal和部署固定地址建立受控MCP Session，在`initialize`之后、构造Runtime effective工具集之前完整调用一次分页`tools/list`。远端输入Schema hash MUST使用与Job Snapshot相同的规范化算法计算。冻结工具在live声明中缺失、同名输入Schema hash不一致、重复或非法Tool声明、分页不完整或需要观测但无法取得结果时，Runtime MUST 先保存安全漂移观测，再以稳定错误在模型调用前失败关闭。

File MCP live中额外但未冻结的工具 MUST 标记为`EXTRA_REMOTE_IGNORED`且不得进入bridge或SDK；`allowed_tools`、Prompt文字和本地manifest均不得替代该次live观测来证明远端工具存在。

#### Scenario: 冻结提交工具未被远端声明
- **WHEN** Job Snapshot包含`file_create_commit_intent`但同一MCP Session的完整`tools/list`不包含它
- **THEN** observation将该工具标记为`MISSING_REMOTE`并把invocation判为`DRIFT`
- **AND** Runtime不启动模型、不向SDK暴露该工具且返回稳定合同错误

#### Scenario: 同名工具Schema已经变化
- **WHEN** File MCP live声明同名工具但规范化输入Schema hash与Job Snapshot不同
- **THEN** observation将该工具标记为`SCHEMA_MISMATCH`并失败关闭
- **AND** 系统要求通过新Publication和新Job采用新合同，不在旧Job中动态替换hash

#### Scenario: 远端暴露额外工具
- **WHEN** File MCP live比Job Snapshot多声明一个工具
- **THEN** Runtime记录`EXTRA_REMOTE_IGNORED`但不把该工具加入Runtime effective或Prompt declaration
- **AND** 其存在本身不使已冻结且匹配的工具失败

#### Scenario: File MCP连接时无法完成观测
- **WHEN** Job需要File Service工具但MCP初始化、分页或Schema规范化无法安全完成
- **THEN** invocation以`DRIFT`和稳定可重试分类或合同分类失败关闭
- **AND** 不把缺失观测显示为`MATCH`

### Requirement: Runtime有效工具和Prompt声明必须来自同一注册表
Python Runtime SHALL 在File MCP校验和代码内工具注册完成后构造唯一Runtime effective registry，并由该registry同时生成SDK Tool Schema、审批边界和Prompt中的当前可调用工具声明。每项 MUST 标记为`frozen_mcp`、`runtime_derived`或`sdk_builtin`，并包含逻辑Tool名、SDK精确可调用名、输入Schema hash和授权结果。

`select_sandbox_output` MUST仅在Job冻结`file_create_commit_intent`且文件格式策略允许时注册为`runtime_derived`；它不需要出现在Job MCP Snapshot或File MCP `tools/list`中。未获冻结或策略授权的工具进入Runtime effective时 MUST标记`UNAUTHORIZED_EFFECTIVE`并失败关闭；Prompt当前可调用声明包含Runtime effective中不存在的工具时 MUST标记`PROMPT_OVERCLAIM`并在模型调用前失败关闭。静态Prompt不得人工维护第二份当前可调用工具名单。

File MCP输入Schema MUST使用当前固定Claude Agent SDK及其bundled CLI能够完整注册的受支持子集。无法由该子集表达的跨字段业务不变量 MUST由File Service在创建Intent或其它副作用前重新校验，不得为了兼容CLI而取消业务约束。发布合同测试 MUST启动真实bundled CLI，使用生产File Tool名称、描述和输入Schema，并证明`file_create_commit_intent`同时出现在CLI初始化工具清单和实际ToolUse路由中；仅直接调用进程内MCP Session不构成该事实的验收证据。

#### Scenario: Runtime派生输出选择器
- **WHEN** Job冻结且live校验通过`file_create_commit_intent`并允许TXT或Markdown输出
- **THEN** Runtime effective包含来源为`runtime_derived`的`select_sandbox_output`及其SDK精确名称
- **AND** 该工具不因未出现在File MCP live或Job Snapshot而被判为缺失

#### Scenario: Prompt仍声明旧提交工具
- **WHEN** Runtime effective不包含`file_create_commit_intent`但Prompt contract把它声明为当前可调用工具
- **THEN** invocation记录`PROMPT_OVERCLAIM`并以`DRIFT`失败关闭
- **AND** 模型不会收到互相冲突的Prompt和函数Schema

#### Scenario: allowed_tools引用不存在的工具
- **WHEN** SDK审批配置引用一个未进入Runtime effective的工具
- **THEN** 系统不得据此把该工具判为存在或`MATCH`
- **AND** 未授权或陈旧审批引用按安全合同错误处理并记录来源

#### Scenario: CLI无法注册提交工具Schema
- **WHEN** File MCP live与Job Snapshot匹配，但当前SDK或bundled CLI会因提交工具输入Schema而把`file_create_commit_intent`从初始化工具清单移除
- **THEN** 真实CLI发布合同测试失败且对应Runtime镜像不得晋级
- **AND** 系统不得用`allowed_tools`、Prompt声明或直接内存Session调用把该工具判为CLI可调用

### Requirement: 运行记录必须展示确定的工具契约对账
授权用户读取运行记录时，列表 SHALL 展示Job工具契约汇总状态`MATCH`、`DRIFT`或`NOT_OBSERVED`，详情 SHALL 按invocation展示组件构建身份、Job frozen、File MCP live、Runtime effective、Prompt模板版本与contract hash以及逐工具状态矩阵。状态 MUST由保存的Snapshot和Runtime事件确定计算，不得采用模型文字回答、当前MCP状态回填历史或客户端自行推断。

Job汇总状态 MUST按`DRIFT`高于`MATCH`高于`NOT_OBSERVED`计算：任一invocation曾漂移则保持`DRIFT`；否则存在且全部1.4观测匹配时为`MATCH`；尚无1.4观测或历史1.3 Job为`NOT_OBSERVED`。详情必须明确区分远端MCP工具和Runtime派生工具。

#### Scenario: 重试后匹配不掩盖先前漂移
- **WHEN** 同一Job的第一次invocation为`DRIFT`而显式重试的新invocation为`MATCH`
- **THEN** 列表汇总仍显示`DRIFT`
- **AND** 详情分别展示两次不可变观测及其原因

#### Scenario: 历史protocol 1.3 Job
- **WHEN** 用户查看升级前没有`tool_contract_observed`事件的终态Job
- **THEN** 列表和详情显示`NOT_OBSERVED`并说明该状态不等于健康
- **AND** 系统不使用当前File MCP live结果伪造历史观测

#### Scenario: 未授权用户读取运行记录
- **WHEN** 调用方无权读取目标Job、Application或Session运行记录
- **THEN** API继续按既有资源授权拒绝
- **AND** 不泄漏Tool名称、构建身份、hash或漂移原因

## MODIFIED Requirements

### Requirement: Python Runtime必须实现版本化执行协议
Python Runtime MUST 只实现`python-v1` protocol 1.4的执行、事件、取消、终态恢复和错误schema。协议 SHALL 固定runtime kind、invocation、attempt、request digest、Publication/hash、模型连接、执行限制、Tool allowlist、correlation ID、schema v5文件上下文、工具契约观测和安全构建身份；Runtime URL不得来自Agent、Application、外部请求或模型输出。Worker、Runtime健康声明、合同生成代码和恢复路径不得支持、协商或投影protocol 1.0、1.1、1.2或1.3。

#### Scenario: 合同用例运行于Python Runtime
- **WHEN** contract suite以protocol 1.4对Python Runtime执行accepted、tool、工具契约观测、completed、failed、cancel、有文件和无文件fixture
- **THEN** Runtime返回schema合法、sequence单调且唯一终态的结果

#### Scenario: Runtime协议版本不受支持
- **WHEN** Worker或Runtime收到1.4以外的协议版本、非`python-v1` runtime kind、非schema v5文件上下文或超限事件
- **THEN** 调用以稳定协议错误失败关闭且不执行模型

#### Scenario: 请求尝试指定任意Runtime地址
- **WHEN** Agent/Application配置或外部payload包含自定义Runtime URL
- **THEN** 系统拒绝该字段，只使用平台固定Python Runtime client

#### Scenario: 健康检查声明合同
- **WHEN** 运维读取Python Runtime无副作用健康信息
- **THEN** 响应只声明`python-v1` protocol 1.4和Manifest schema v5
- **AND** 不把旧协议列为可接受、可恢复或降级目标

### Requirement: Agent Job 固定文件清单但实时复核访问
Agent Job创建事务 MUST 固定任务工作区ID、schema v5 Job File Manifest、`workspace_catalog_revision_id`以及当前附件、明确引用和已选Working Set中的精确File/Version ID；对需转换文档还 MUST 固定精确Markdown Representation ID、kind、size和SHA-256。该清单 SHALL 以有界、无正文、无凭据、无对象位置形式原样交给Python Runtime protocol 1.4，不得投影为旧Manifest。Runtime按需物化或交付时 MUST 由File Service重新检查RUNNING Job、当前内部用户、Business Application访问、私聊所有者或同群会话边界、source Version与representation血缘；不得读取清单外、Working Set上限之外、之后产生或已经内容不可用的版本/表示。

#### Scenario: 执行期间当前版本或表示变化
- **WHEN** Job固定source V3和representation R1后另一Job提交V4或处理器产生R2
- **THEN** 当前Runtime仍只把R1用于阅读并把V3用于原件身份
- **AND** 基于V3的后续提交按正常并发规则得到冲突

#### Scenario: Representation与源版本不匹配
- **WHEN** Manifest或传输请求把属于另一source Version的representation绑定到当前文件
- **THEN** File Service在读取对象前拒绝并记录安全完整性错误

#### Scenario: 执行期间当前版本变化
- **WHEN** Job固定V3后另一Job提交V4
- **THEN** 当前Runtime仍只物化V3
- **AND** 基于V3的后续提交按正常并发规则得到冲突

#### Scenario: 无关Job不自动物化处理中文档
- **WHEN** 工作区存在一份 `PENDING` 可读表示的文档，新 Job 的本轮依赖集合为空
- **THEN** Manifest 不得把该文档标为自动物化
- **AND** 该 Job 仍可执行

#### Scenario: 历史召回项在本 Job 清单内可按需读取
- **WHEN** 本 Job Manifest 含一份时段召回的保留版本，内容仍为 `AVAILABLE`，Agent 使用冻结的 File/Version ID 调用物化
- **THEN** File Service 在复核 RUNNING Job、当前用户和会话归属后允许物化
- **AND** 不得因该文件未挂接当前工作区而返回清单外拒绝

#### Scenario: 未写入本 Job 清单的历史附件仍不可读
- **WHEN** 同一 Session 另有一份仍在保留期但不在当前 Job Manifest 中的历史附件
- **THEN** Runtime 使用其 File/Version ID 请求物化必须被拒绝
- **AND** 不得把 360 天附件库当作当前工作区目录

#### Scenario: 从冻结目录追加精确旧版本
- **WHEN** Job冻结的目录revision包含V3，当前工作区后来选择V4，但Agent从冻结分页结果精确选择仍可访问的V3
- **THEN** File Service可把V3追加为该Job工作集事实并按V3物化
- **AND** 不自动替换为V4；若V3内容不可用则失败关闭

#### Scenario: Worker尝试投影旧Manifest
- **WHEN** Agent Worker准备protocol 1.4请求时取得的Job File Manifest不是schema v5
- **THEN** Worker在调用Python Runtime前以稳定合同错误终结执行
- **AND** 不进行v5到v4或任意旧schema投影

#### Scenario: 空文件上下文执行普通文字Job
- **WHEN** Job没有任务工作区附件、明确引用或已选Working Set
- **THEN** Worker发送合法的schema v5空文件上下文
- **AND** Runtime正常执行模型且不构造旧格式占位值

### Requirement: Runtime 通过受控文件桥完成物化和提交
Runtime MUST通过File Service受控流式接口下载Job初始Manifest或追加工作集中的精确文本File Version或精确Markdown Representation，并上传Agent显式选中的受支持沙盒文本文件。PDF、Office、图片原始二进制和Docling JSON不得进入Agent Sandbox。File MCP只创建物化或提交意图并返回不透明标识，完整文件字节 MUST NOT进入模型上下文、MCP JSON、Tool事件或审计。Runtime不得获得MinIO凭据、Bucket、对象键或可供模型使用的上传URL。

Python Runtime MUST使用代码注册的进程内File MCP bridge代理Job冻结的部署固定File Service工具，并在远端ToolResult交回模型前处理隐藏传输控制信息。bridge MUST使用当前Job File Principal JWT和固定内部流式路径；文档传输控制信息还 MUST绑定精确representation ID、source Version、size和SHA-256。bridge不得接受模型提供的URL、Header、Token、绝对路径、对象位置或冻结目录revision外的representation；SDK消息返回后再处理的旁路不满足本要求。

Agent Worker MUST验证Manifest v5 hash后，将schema v5文件上下文原样传给Runtime protocol 1.4，MUST NOT投影、生成或读取Manifest v1-v4。对所有`auto_materialize=true`项，Control Plane MUST在创建Job和outbox前按不同File/Version数量及待进入Sandbox的实际字节执行完整预检；Runtime MUST在首次模型请求前先为全部不同File/Version取得File Service基于冻结事实签发的隐藏传输控制及精确预期大小，在任何下载发生前整批预留，再主动物化全部精确文本版本或Markdown表示。任何prepare、整批预留或下载失败均使Job失败关闭且不得形成部分可见输入。其余文件只能由Agent先查询Manifest冻结的目录revision，再以精确File/Version请求并追加工作集；File Service从同一冻结事实解析可用文本版本或Markdown representation。

自动物化、File MCP按需物化、Write/Edit和内部临时文件 MUST全部通过同一个Job Sandbox预算与预留服务。自动物化bridge MUST先准备完整批次、再原子预留完整批次，只有整批预留成功后才可开始首个下载；File MCP bridge MUST在创建目标文件或下载首字节前预留`inputs`槽位与容量，并在失败、取消或完整性不匹配时清理部分文件并释放预留；不得因File Service已授权transfer而绕过40项输入、64文件分区或224MiB总容量。

#### Scenario: 当前消息文档在模型执行前已进入沙盒
- **WHEN** Job File Manifest包含一个合法`auto_materialize=true`的当前消息文档和Markdown representation
- **THEN** Runtime在首次模型请求前通过受控File bridge下载表示、校验大小与SHA-256并登记sandbox entry
- **AND** 模型只看到安全Markdown相对路径、原件身份和只读动作

#### Scenario: Agent显式提交沙盒文本文件
- **WHEN** Agent调用已冻结的文件提交工具并选择一个受控沙盒TXT或可写Markdown文件
- **THEN** Runtime使用当前Job绑定流式上传内容到File Service
- **AND** Tool事件只保留文件身份、版本、大小、哈希摘要和结果

#### Scenario: Runtime在模型看到结果前物化文档
- **WHEN** File Service为`file_prepare_materialization`返回绑定冻结目录revision和工作集事实的合法隐藏传输控制信息
- **THEN** Runtime bridge在该ToolResult返回模型前完成预算预留、流式下载、大小与SHA-256校验和sandbox entry登记
- **AND** 模型只收到安全Markdown相对路径、不透明handle、大小和摘要

#### Scenario: Runtime尝试物化原件或Docling JSON
- **WHEN** Runtime传输请求指向PDF、Office、图片原件或Docling JSON
- **THEN** File Service在返回字节前失败关闭
- **AND** 不因该对象属于同一source Version而扩大Agent读取能力

#### Scenario: 当前消息文本附件在模型执行前已进入沙盒
- **WHEN** Job File Manifest包含合法`auto_materialize=true`的当前消息TXT、LOG或Markdown精确版本
- **THEN** Runtime在首次模型请求前通过受控File bridge完成下载、format、大小和SHA-256校验及sandbox entry登记
- **AND** 模型只从安全相对路径读取且LOG entry不包含写操作

#### Scenario: Agent显式提交Markdown沙盒文件
- **WHEN** Agent调用已冻结的文件提交工具并选择一个受控`.md` sandbox handle
- **THEN** Runtime使用当前Job绑定流式上传内容到File Service
- **AND** Tool事件只保留文件身份、format、版本、大小、哈希摘要和结果

#### Scenario: Agent尝试提交LOG沙盒文件
- **WHEN** Agent把`.log`路径或handle传给输出选择器或提交工具
- **THEN** Runtime与File Service均在接收正文前拒绝
- **AND** 不创建Commit Intent、staging、版本或Delivery

#### Scenario: Runtime在模型看到结果前物化文件
- **WHEN** File Service 为 `file_prepare_materialization` 返回合法隐藏传输控制信息
- **THEN** Runtime bridge 在该 ToolResult 返回模型前完成流式下载、大小与 SHA-256 校验和 sandbox entry 登记
- **AND** 模型只收到安全相对路径、不透明 handle、大小和摘要

#### Scenario: 当前消息附件在模型执行前已进入沙盒
- **WHEN** Job File Manifest 包含一个合法 `auto_materialize=true` 的当前消息文件版本或已就绪 Markdown 表示
- **THEN** Runtime 在首次模型请求前通过受控 File bridge 完成下载、大小和 SHA-256 校验及 sandbox entry 登记
- **AND** 模型可直接从安全相对路径读取该文件而无需先发现 File ID

#### Scenario: Agent显式提交沙盒文件
- **WHEN** Agent 调用已冻结的文件提交工具并选择一个受控沙盒文件
- **THEN** Runtime 使用当前 Job 绑定流式上传内容到 File Service
- **AND** Tool 事件只保留文件身份、版本、大小、哈希摘要和结果

#### Scenario: Agent按需物化仍在处理的文档
- **WHEN** Agent 对 Manifest 中一份可读表示未就绪的候选调用 `file_prepare_materialization`
- **THEN** File Service 在读取对象前拒绝并返回稳定未就绪错误码
- **AND** Runtime 不把该结果升级为自动物化失败，也不向模型提供伪造正文

#### Scenario: 自动物化预检失败
- **WHEN** 计划自动物化的输入超过40个不同File/Version或实际Markdown总大小会突破224MiB
- **THEN** Control Plane在Job和outbox创建前完整拒绝并要求缩小工作集
- **AND** 不物化子集、不启动Runtime且不产生不完整Manifest

### Requirement: Job文件工作集选择必须可恢复且不改变Runtime协议
系统 SHALL把Job初始文件Manifest与执行期间追加的精确文件工作集事实分开持久化。Manifest v5 MUST冻结`workspace_catalog_revision_id`以及当前附件、明确引用和预选项，不复制整个工作区目录；追加工作集事实 MUST使用Job、Snapshot、精确File/Version和可选Representation身份保持幂等，并在Worker重试、Runtime断线恢复和相同invocation恢复时复用，MUST NOT重新选择“当前最新”版本或产生第二套内容授权。初始项与追加项按精确File/Version去重后累计 MUST不超过40项；重复选择同一版本不重复计数。

追加工作集事实属于控制面与File Service授权事实，除本变更统一引入的protocol 1.4工具契约观测外，MUST NOT为工作集选择新增或改写Runtime请求、事件或终态字段。Runtime只通过已经冻结的File MCP Tool、短时Principal和受控transfer取得动态选择内容，仍不得接收MinIO凭据、对象位置或原始二进制。

#### Scenario: Runtime断线后恢复同一Job
- **WHEN** Job已经追加选择V3及Representation R1并创建受控transfer，Worker在Runtime终态前断线
- **THEN** 恢复继续使用相同Job工作集事实和精确V3/R1
- **AND** 不重新解析当前V4或Representation R2

#### Scenario: 并发重复选择同一版本
- **WHEN** 同一Job并发两次选择相同File/Version
- **THEN** 唯一约束和事务只保留一个追加工作集事实
- **AND** 两次调用得到一致身份且工作集计数只增加一次

#### Scenario: Runtime合同仍使用受支持版本
- **WHEN** 兼容大工作区Job执行搜索、动态选择和物化
- **THEN** Worker与Python Runtime仍使用当前Runtime protocol 1.4合同
- **AND** Runtime schema不因动态工作集内容新增另一套文件字段

#### Scenario: Job重试时权限已经撤销
- **WHEN** 追加工作集事实仍存在但当前用户或Application访问在重试前被撤销
- **THEN** File Service在再次物化前失败关闭
- **AND** 不把追加事实解释为长期访问授权

### Requirement: 当前执行合同不得包含旧协议实现
活动执行代码、生成合同、容器镜像和测试矩阵 MUST 只包含Runtime protocol 1.4与Manifest schema v5的当前可执行实现。protocol 1.0至1.3的执行类型、请求解析器、恢复入口、hash实现、fixture和条件分支 MUST 从Runtime与Worker发布产物删除；仓库级历史Schema和安全只读投影器只可用于展示已经终态的历史审计事实，不得构造请求、恢复Job或调用模型。migration和OpenSpec中的历史标识只可用于说明历史事实、拒绝或删除结果。

#### Scenario: 构建当前Runtime镜像
- **WHEN** CI构建Agent Worker和Python Runtime镜像并检查安装内容
- **THEN** 只存在protocol 1.4合同与Manifest v5执行代码
- **AND** 不包含protocol 1.0至1.3可执行模块或Manifest v1-v4运行fixture

#### Scenario: 查看protocol 1.3终态历史
- **WHEN** 授权用户查看升级前已经终态的protocol 1.3 Job和安全Runtime事件
- **THEN** 系统通过仓库级只读历史投影展示原事实并把工具契约状态标为`NOT_OBSERVED`
- **AND** 当前Runtime不提供该Job的恢复、重放或模型执行入口

#### Scenario: 切换前仍有旧协议非终态事实
- **WHEN** 部署预检发现protocol 1.3的RUNNING、PENDING、WAITING、RETRY、未终态Outbox或相关队列积压
- **THEN** protocol 1.4切换失败关闭并输出按类别聚合的安全计数
- **AND** 不启动双协议消费者或把旧请求投影到1.4
