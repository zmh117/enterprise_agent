## ADDED Requirements

### Requirement: Agent Job按文档可读性终态释放
当本轮绑定需要文档处理的附件时，Job SHALL 只在来源导入未终态时保持`WAITING_INPUT`。平台 MUST NOT因原始对象已保存、Docling容器healthy、processing消息已发布或表示仍为PENDING就把无关文字推迟到`agent.jobs`之外。需要`READABLE_CONTENT`且表示未就绪时 MUST 在入队前结束本轮。`AVAILABLE`及带合规非空Markdown的`PARTIAL`可以释放；`NO_TEXT`、`UNAVAILABLE`或`FAILED`只能形成固定notice。只有文件且没有任何可用文字时 MUST 不调用模型。

#### Scenario: Processing run仍在重试
- **WHEN** 本轮绑定附件原件已保存但processing run处于`RETRY_WAIT`，且所需能力为可读正文
- **THEN** 系统不把该轮释放到 Agent 队列
- **AND** 通过原reply route发送固定未就绪说明，不创建缺少representation的最终Agent Manifest

#### Scenario: 部分结果可用
- **WHEN** processing run为`PARTIAL`且发布了通过校验的非空Markdown
- **THEN** 系统冻结该representation并释放Job
- **AND** Runtime上下文包含固定的不完整性notice

#### Scenario: 只有无文字图片
- **WHEN** Job没有用户正文且所有图片均为`NO_TEXT`
- **THEN** 平台安全终结Job并通过原reply route说明未取得可读文字
- **AND** 不调用模型

### Requirement: 原件交付与表示阅读使用独立身份
系统 SHALL 使用Job冻结或当前授权的原始File Version完成文件下载、保留和Delivery，并只使用冻结Markdown Representation完成Agent阅读。Processing run、representation失败或Agent对Markdown的本地读取不得改变原始File Version、Delivery状态或Agent Job终态；交付原件失败也不得重新执行Docling或Agent。

#### Scenario: 总结后转发原件
- **WHEN** Agent使用Markdown representation完成总结且用户要求转发原PDF
- **THEN** Delivery按精确原始Version创建独立文件交付
- **AND** 不交付representation或重新运行处理任务

#### Scenario: 原件交付失败
- **WHEN** Agent Job已成功但原件Delivery出现可重试错误
- **THEN** 只重试Delivery状态机
- **AND** 不重新执行Agent Job或processing run

## MODIFIED Requirements

### Requirement: Agent Job 固定文件清单但实时复核访问
Agent Job创建事务 MUST 固定任务工作区ID和Job File Manifest中的精确File/Version ID；对需转换文档还 MUST 固定精确Markdown Representation ID、kind、size和SHA-256。该清单 SHALL 以有界、无正文、无凭据、无对象位置形式交给所选Runtime。Runtime按需物化或交付时 MUST 由File Service重新检查RUNNING Job、当前内部用户、Business Application访问、私聊所有者或同群会话边界、source Version与representation血缘；不得读取清单外、之后产生或已经内容不可用的版本/表示。

#### Scenario: 执行期间当前版本或表示变化
- **WHEN** Job固定source V3和representation R1后另一Job提交V4或处理器产生R2
- **THEN** 当前Runtime仍只把R1用于阅读并把V3用于原件身份
- **AND** 基于V3的后续提交按正常并发规则得到冲突

#### Scenario: Representation与源版本不匹配
- **WHEN** Manifest或传输请求把属于另一source Version的representation绑定到当前文件
- **THEN** File Service在读取对象前拒绝并记录安全完整性错误

### Requirement: Runtime 通过受控文件桥完成物化和提交
Runtime MUST 通过File Service受控流式接口下载Job File Manifest中的精确文本File Version或精确Markdown Representation，并上传Agent显式选中的受支持沙盒文本文件。PDF、Office、图片原始二进制和Docling JSON不得进入Agent Sandbox。File MCP只创建物化或提交意图并返回不透明标识，完整文件字节 MUST NOT进入模型上下文、MCP JSON、Tool事件或审计。Runtime不得获得MinIO凭据、Bucket、对象键或可供模型使用的上传URL。

Python Runtime MUST 使用代码注册的进程内File MCP bridge代理Job冻结的部署固定File Service工具，并在远端ToolResult交回模型前处理隐藏传输控制信息。bridge MUST 使用当前Job File Principal JWT和固定内部流式路径；文档传输控制信息还 MUST 绑定精确representation ID、source Version、size和SHA-256。bridge不得接受模型提供的URL、Header、Token、绝对路径、对象位置或Manifest外representation；SDK消息返回后再处理的旁路不满足本要求。

Agent Worker MUST 将有界且无正文的Job File Manifest投影交给Runtime。Runtime MUST 在模型请求前主动物化所有`auto_materialize=true`的精确文本版本或Markdown表示，并向模型提供已校验的安全沙盒元数据；任何自动物化失败 MUST 使Job失败关闭。其余候选只能由Agent使用Manifest中的精确File/Version ID请求，File Service从同一冻结条目解析可用文本版本或Markdown representation。

#### Scenario: 当前消息文档在模型执行前已进入沙盒
- **WHEN** Job File Manifest包含一个合法`auto_materialize=true`的当前消息文档和Markdown representation
- **THEN** Runtime在首次模型请求前通过受控File bridge下载表示、校验大小与SHA-256并登记sandbox entry
- **AND** 模型只看到安全Markdown相对路径、原件身份和只读动作

#### Scenario: Agent显式提交沙盒文本文件
- **WHEN** Agent调用已冻结的文件提交工具并选择一个受控沙盒TXT或可写Markdown文件
- **THEN** Runtime使用当前Job绑定流式上传内容到File Service
- **AND** Tool事件只保留文件身份、版本、大小、哈希摘要和结果

#### Scenario: Runtime在模型看到结果前物化文档
- **WHEN** File Service为`file_prepare_materialization`返回绑定Manifest冻结representation的合法隐藏传输控制信息
- **THEN** Runtime bridge在该ToolResult返回模型前完成流式下载、大小与SHA-256校验和sandbox entry登记
- **AND** 模型只收到安全Markdown相对路径、不透明handle、大小和摘要

#### Scenario: Runtime尝试物化原件或Docling JSON
- **WHEN** Runtime传输请求指向PDF、Office、图片原件或Docling JSON
- **THEN** File Service在返回字节前失败关闭
- **AND** 不因该对象属于同一source Version而扩大Agent读取能力
