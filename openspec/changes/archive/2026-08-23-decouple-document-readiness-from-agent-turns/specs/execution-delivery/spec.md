## ADDED Requirements

### Requirement: Agent Job不得因文档表示处理而等待
系统 MUST 把文档处理运行留在 `file-processing-worker` 与 `file.processing` 队列上，MUST NOT 让 Agent Job 因 `file_processing_run` 处于 `QUEUED`、`SUBMITTED`、`RUNNING` 或 `RETRY_WAIT`，或因 `readability_status=PENDING` 而占用 `WAITING_INPUT` 等待模型启动。`WAITING_INPUT` 仅允许用于本轮已绑定附件的来源下载与 File Service 导入。平台 MUST NOT 因 Docling 容器 healthy、processing 消息已发布或工作区存在处理中文件，就推迟无关文字 Job 的创建或 dispatch。需要 `READABLE_CONTENT` 且表示未就绪时，本轮 MUST 在入队 `agent.jobs` 之前结束；需要 `METADATA` 或 `ORIGINAL` 且原件已保存时，Job MUST 可以进入 `PENDING`。只有文件、没有任何可用用户文字、且本轮绑定集合全部不可读时，系统 MUST 不调用模型。

#### Scenario: 文档处理中出现无关问题
- **WHEN** 工作区有一份文档的 processing run 为 `RUNNING`，用户发送无文件依赖的非空文字
- **THEN** 系统创建 Agent Job 并发布到 `agent.jobs`
- **AND** 该 Job 的自动物化集合不包含这份处理中文档

#### Scenario: Processing run仍在重试
- **WHEN** 本轮绑定文档的原件已保存但 processing run 处于 `RETRY_WAIT`，且所需能力为 `READABLE_CONTENT`
- **THEN** 系统不把该 Job 释放到 Agent 队列
- **AND** 通过原 reply route 发送固定未就绪说明

#### Scenario: 同消息附件仍在从渠道下载
- **WHEN** 本轮绑定的是当前消息附件且来源状态尚未终态
- **THEN** 该 Job 可以保持 `WAITING_INPUT` 直到来源导入终态
- **AND** 来源终态后必须重新执行能力门禁，而不是自动视为表示已就绪

### Requirement: 曾被挡轮次可通知且不得自动重放
系统 MUST 为因 `READABLE_CONTENT` 未就绪而结束的轮次持久化有界被挡事实，至少包含会话、用户消息、精确 `file_version` 集合、原因码和状态。当对应版本的可读表示进入 `AVAILABLE` 或带合规非空 Markdown 的 `PARTIAL` 时，系统 MAY 向原 reply route 发送一次固定就绪通知。系统 MUST NOT 因此自动创建新的 Agent Job、重放原问题或把整份 Markdown 注入上下文。超过工作区有效期或代码固定通知窗口后，未通知事实 MUST 过期且不再投递。普通上传成功完成 MUST NOT 默认向用户发解析完成通知。

#### Scenario: 被挡后表示就绪
- **WHEN** 用户曾因某版本可读内容未就绪收到系统说明，随后该版本 Markdown 表示变为可用
- **THEN** 系统向原会话发送一次「可读内容已经生成，可以继续提问」的固定说明
- **AND** 不自动执行原问题、不创建 Agent Job

#### Scenario: 用户从未被该文件挡住
- **WHEN** 用户只上传文档、从未因该版本被门禁挡住
- **THEN** 表示就绪不向钉钉发送完成通知
- **AND** 后台 processing run 照常结束

#### Scenario: 通知窗口过期
- **WHEN** 被挡事实超过代码固定窗口或工作区已清理
- **THEN** 系统丢弃或过期该通知
- **AND** 不补发、不重放

## MODIFIED Requirements

### Requirement: Agent Job 固定文件清单但实时复核访问
Agent Job 创建事务 MUST 固定任务工作区ID和Job File Manifest中的精确File/Version ID，并将该清单以有界、无正文、无凭据形式交给所选Runtime。自动物化集合 MUST 只包含本轮确定性绑定且所需能力已经就绪的精确版本或 Markdown 表示；工作区其它文件只提供不含正文、凭据和对象位置的元数据候选。Runtime按需物化时 MUST 由File Service重新检查RUNNING Job、当前内部用户、Business Application访问、私聊所有者或同群会话边界；不得读取清单外或之后产生的版本。处理中文档 MUST NOT 仅因出现在工作区就被写入 `auto_materialize=true`。

#### Scenario: 执行期间当前版本变化
- **WHEN** Job固定V3后另一Job提交V4
- **THEN** 当前Runtime仍只物化V3
- **AND** 基于V3的后续提交按正常并发规则得到冲突

#### Scenario: 无关Job不自动物化处理中文档
- **WHEN** 工作区存在一份 `PENDING` 可读表示的文档，新 Job 的本轮依赖集合为空
- **THEN** Manifest 不得把该文档标为自动物化
- **AND** 该 Job 仍可执行

### Requirement: Runtime 通过受控文件桥完成物化和提交
Runtime MUST 通过 File Service 受控流式接口下载 Job File Manifest 中的精确版本和上传显式选中的沙盒文件。File MCP 只创建物化或提交意图并返回不透明标识，完整文件字节 MUST NOT 进入模型上下文、MCP JSON、Tool 事件或审计。Runtime 不得获得 MinIO 凭据、Bucket、对象键或可供模型使用的上传 URL。

Python Runtime MUST 使用代码注册的进程内 File MCP bridge 代理 Job 冻结的部署固定 File Service 工具，并在远端 ToolResult 交回模型前处理隐藏传输控制信息。bridge MUST 使用当前 Job File Principal JWT 和固定内部流式路径，不得接受模型提供的 URL、Header、Token、绝对路径或对象位置；SDK 消息返回后再处理的旁路不满足本要求。

Agent Worker MUST 将有界且无正文的 Job File Manifest 投影交给 Runtime。Runtime MUST 在模型请求前主动物化所有 `auto_materialize=true` 精确版本或已冻结 Markdown 表示并向模型提供已校验的安全沙盒元数据；任何自动物化失败 MUST 使 Job 失败关闭。其余候选只能由 Agent 使用 Manifest 中的精确 File/Version ID 按需物化。当 `file_prepare_materialization` 因可读表示未就绪或处理失败而拒绝时，Runtime MUST 把结构化错误交回模型，MUST NOT 把拒绝当成可重试的传输故障并臆造文件内容；该拒绝 MUST NOT 单独把无关 Job 标为 Agent 运行时崩溃。

#### Scenario: 当前消息附件在模型执行前已进入沙盒
- **WHEN** Job File Manifest 包含一个合法 `auto_materialize=true` 的当前消息文件版本或已就绪 Markdown 表示
- **THEN** Runtime 在首次模型请求前通过受控 File bridge 完成下载、大小和 SHA-256 校验及 sandbox entry 登记
- **AND** 模型可直接从安全相对路径读取该文件而无需先发现 File ID

#### Scenario: Agent显式提交沙盒文件
- **WHEN** Agent 调用已冻结的文件提交工具并选择一个受控沙盒文件
- **THEN** Runtime 使用当前 Job 绑定流式上传内容到 File Service
- **AND** Tool 事件只保留文件身份、版本、大小、哈希摘要和结果

#### Scenario: Runtime在模型看到结果前物化文件
- **WHEN** File Service 为 `file_prepare_materialization` 返回合法隐藏传输控制信息
- **THEN** Runtime bridge 在该 ToolResult 返回模型前完成流式下载、大小与 SHA-256 校验和 sandbox entry 登记
- **AND** 模型只收到安全相对路径、不透明 handle、大小和摘要

#### Scenario: Agent按需物化仍在处理的文档
- **WHEN** Agent 对 Manifest 中一份可读表示未就绪的候选调用 `file_prepare_materialization`
- **THEN** File Service 在读取对象前拒绝并返回稳定未就绪错误码
- **AND** Runtime 不把该结果升级为自动物化失败，也不向模型提供伪造正文
