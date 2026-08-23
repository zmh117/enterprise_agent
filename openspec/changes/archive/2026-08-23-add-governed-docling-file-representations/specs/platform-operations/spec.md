## ADDED Requirements

### Requirement: Docling服务固定版本并保持内部隔离
默认Compose MUST 使用固定tag与digest的官方`docling-serve`镜像，禁用UI、远程services、HTTP URL source、Callback、自定义VLM/图片描述配置和外部插件；服务不得映射宿主端口，只能由`file-processing-worker`通过专用内部网络和独立API Key访问。容器 MUST 使用非root、只读根文件系统、受控scratch、CPU、内存、PID和时间限制，并在运行前准备所需模型artifacts而不是运行时访问互联网。

#### Scenario: 检查Docling Compose配置
- **WHEN** 运维渲染默认Compose配置
- **THEN** `docling-serve`使用固定镜像digest、无宿主端口、UI关闭且远程/自定义能力关闭
- **AND** 不存在PostgreSQL、RabbitMQ、MinIO或平台Principal Secret

#### Scenario: Docling模型尚未就绪
- **WHEN** `/health`成功但`/ready`因模型加载或内部编排器失败返回非就绪
- **THEN** 平台文档处理状态不得报告READY
- **AND** processing worker不得把请求发送到未就绪实例

### Requirement: 文件处理队列具有独立有界拓扑
平台 SHALL 为文档processing request提供版本化durable主队列、延迟重试队列和dead-letter队列，并由`file-processing-worker`独占消费；拓扑 MUST 与附件下载、Agent Job和Delivery队列分离。消息与dead-letter摘要只能包含稳定run/source身份、attempt、Profile hash、correlation和安全错误码。

#### Scenario: Processing Worker暂时不可用
- **WHEN** processing request已经发布但Worker停止
- **THEN** 消息保留在durable队列且运维状态显示有界积压
- **AND** 原始附件、正文、对象键和凭据不进入队列

#### Scenario: 处理重试耗尽
- **WHEN** run达到固定最大attempt
- **THEN** 消息进入dead-letter且run进入确定失败
- **AND** 不影响附件下载队列或Agent Job队列

## MODIFIED Requirements

### Requirement: Compose 部署 File Service 并以 File Worker 替换附件 Worker
默认Compose SHALL 保持`file-service`与替换旧`attachment-worker`的`file-worker`，并新增内部`docling-serve`和独立`file-processing-worker`；不得长期并存两个附件消费者，也不得新增独立`file-mcp`容器。`file-service`同时承载内部REST与File MCP接口；`file-worker`继续消费原附件队列并承担来源下载/导入、工作区过期、保留内容和提交暂存清理；`file-processing-worker`只消费文档处理队列并编排Docling；现有Agent Worker和Delivery Dispatcher继续独立运行。

#### Scenario: 从现有部署升级
- **WHEN** 现有附件或processing队列中存在ready/unacked消息并部署新版本
- **THEN** `file-worker`保持兼容附件队列，`file-processing-worker`按独立版本化拓扑消费processing消息
- **AND** 不因服务变化删除队列、丢失消息、重复导入原件或发布重复representation

#### Scenario: Compose服务清单检查
- **WHEN** 运维启动启用文档处理的默认文件工作区部署
- **THEN** 服务包含`file-service`、`file-worker`、`file-processing-worker`和`docling-serve`
- **AND** 不包含独立`file-mcp`、长期`attachment-worker`、Docling RQ/Redis或Ray服务

### Requirement: File Service与File Worker具有真实就绪和积压观测
File Service readiness MUST 验证PostgreSQL schema、MinIO私有bucket访问、Principal JWKS、Manifest v4、representation staging和内部流式接口依赖；File Worker readiness MUST 验证附件RabbitMQ队列契约、File Service内部API和清理调度；File Processing Worker readiness MUST 验证独立processing队列、File Service、角色Principal和Docling `/ready`；Docling readiness MUST 验证模型与内部编排器可处理请求。平台运维视图 SHALL 展示附件、processing run、representation staging、重试/dead-letter、提交暂存、工作区过期、保留清理和File Domain Outbox的安全积压计数与最近结果，不得仅以容器running或`/health`声明可用。

#### Scenario: MinIO进程可达但bucket无权限
- **WHEN** File Service能连接MinIO endpoint但无法读取或写入受控bucket
- **THEN** readiness返回失败并阻止文件与文档处理能力被宣称为已接线

#### Scenario: File Worker存在清理积压
- **WHEN** 到期内容因瞬时错误等待重试
- **THEN** 运维状态显示有界积压、最早到期时间和安全错误分类
- **AND** 不显示文件名、正文、对象键或凭据

#### Scenario: 文档处理存在积压
- **WHEN** processing run、retry或dead-letter超过受控告警阈值
- **THEN** 运维状态显示数量、最早创建/重试时间、状态、processor/Profile和安全错误分类
- **AND** 不显示文件名、Markdown、JSON、原始错误或凭据

#### Scenario: File Domain Outbox存在待发布事件
- **WHEN** 附件导入、processing run、representation或文件版本事务已提交领域事件但发布尚未完成
- **THEN** 维护/Dispatcher链路按事件类型幂等发布并把Outbox标记为`PUBLISHED`
- **AND** 运维状态显示待发布数量、最早事件时间和安全失败码，不显示文件名、正文、对象键或凭据

#### Scenario: 历史Outbox积压升级后恢复
- **WHEN** 升级前已有长期`PENDING`文件领域事件
- **THEN** 下一次维护周期按确定顺序幂等发布并清空可处理积压
- **AND** 不创建无人消费队列、重复文件版本、processing run或representation

### Requirement: Compose完整配置Service Principal签发与刷新链路
默认Compose MUST 只维护一套平台Principal签名私钥和公开JWKS：现有平台API身份模块与Agent Worker只在需要签发对应Token时挂载同一私钥，File Service、ONES MCP及后续MCP只挂载同一公开`PRINCIPAL_JWKS`；不得声明或挂载第二套Service Principal私钥/JWKS。平台API还 MUST 挂载角色隔离的File Worker、File Processing Worker和Delivery Worker bootstrap credential，并让每个Worker只挂载自己的bootstrap credential。部署 MUST 使用按需签发和到期前刷新，不得要求宿主机预先提供短时Service JWT文件。密钥初始化 MUST 幂等生成统一Principal密钥/JWKS与全部bootstrap材料、拒绝不完整统一密钥组并保持私钥和bootstrap文件owner-only。Docling API Key MUST 与平台Principal体系分离，只挂载到`file-processing-worker`和`docling-serve`。

#### Scenario: 新环境首次启动
- **WHEN** 运维运行受控密钥初始化后启动默认Compose
- **THEN** 统一Principal密钥/JWKS及File Worker、File Processing Worker、Delivery Worker bootstrap bind source均存在且容器可创建
- **AND** 三个Worker能分别从平台身份接口取得可验证的角色JWT

#### Scenario: 检查角色Secret挂载
- **WHEN** 运维检查API、File Service、三个Worker与Docling的Compose Secret
- **THEN** API拥有统一Principal签名私钥和三份角色bootstrap credential，File Service只有统一公开JWKS
- **AND** 每个Worker只有自己的bootstrap credential，Docling API Key只在Processing Worker与Docling出现，任何组件都没有另一角色Secret

#### Scenario: 短时JWT到期
- **WHEN** 已缓存Service JWT进入刷新窗口或过期
- **THEN** Worker通过固定平台身份地址换取新JWT并继续调用
- **AND** 不回退到静态JWT、共享Token或未认证内部请求

#### Scenario: Docling API Key缺失
- **WHEN** `file-processing-worker`或`docling-serve`无法解析独立API Key
- **THEN** 对应readiness失败且不回退到无认证Docling请求

### Requirement: Job Sandbox容量和隔离配置必须可验证
Python Runtime临时文件系统配置 MUST 支持单个15MiB文本File Version或Markdown Representation及受控多文件物化，并对每个Job实施独立沙盒容量、文件数量、路径和生命周期限制。Compose MUST 根据允许自动物化的文件数、15MiB单文件上限和安全处理开销配置容量，在启动时验证并在健康状态中只显示非敏感上限；PDF、Office、图片原件和Docling JSON不得计入可物化类型或进入沙盒。

#### Scenario: 沙盒容量小于合法最小处理需求
- **WHEN** Runtime配置无法容纳一个15MiB Markdown表示、一个合法输出和必要临时开销
- **THEN** Runtime readiness失败而不是在Agent执行中无界磁盘失败

#### Scenario: 单Job达到沙盒上限
- **WHEN** 继续物化或生成文件会超过当前Job沙盒容量
- **THEN** Runtime在写入前拒绝并返回安全、有界错误

#### Scenario: 原始文档被请求物化
- **WHEN** Runtime尝试把PDF、Office、图片或Docling JSON写入Agent Sandbox
- **THEN** 类型门禁在下载字节前拒绝

### Requirement: 文件工作区验收覆盖真实端到端链路
Compose验收 MUST 使用合成TXT、born-digital PDF、扫描PDF、DOCX、PPTX、XLSX、带文字图片和无文字图片及假凭据，证明钉钉或受控Channel入口、File Worker、File Service、PostgreSQL、MinIO、File Domain Outbox、processing RabbitMQ拓扑、File Processing Worker、Docling、Agent Worker、所选Runtime、Job Sandbox、File MCP、原件Delivery和文本结果形成新鲜链路。验收还 MUST 覆盖Principal/API Key拒绝、越权文件、MIME伪装、加密/损坏/超大小/超页数、PARTIAL、NO_TEXT、Markdown超限、Docling重启、结果取得后Worker崩溃、幂等重试、沙盒/representation staging清理、交付重试和Secret不泄漏；不得以容器healthy替代业务证据。

#### Scenario: PDF总结并交付原件
- **WHEN** 合成用户上传合法PDF并要求总结后转发原件
- **THEN** 证据关联原附件、source Version、processing run、Markdown/JSON representation、Manifest v4、沙盒Markdown读取、Agent结果和原PDF Delivery
- **AND** Agent沙盒、模型上下文和Delivery均未混淆原件与representation

#### Scenario: 扫描件OCR成功
- **WHEN** 合成扫描PDF或带文字图片在固定Profile内完成OCR
- **THEN** Agent只通过Markdown读取提取文字并给出基于该文字的结果
- **AND** 系统不声称获得未提取的视觉语义

#### Scenario: 无文字图片拒绝模型调用
- **WHEN** 只有一张合法但OCR为NO_TEXT的图片
- **THEN** Job不调用模型并通过原reply route返回安全说明

#### Scenario: Docling重启恢复
- **WHEN** Docling在已返回task ID后重启并丢失临时任务
- **THEN** 同一processing run创建受控新attempt并最终成功或确定失败
- **AND** 不产生重复source Version或representation

#### Scenario: 文档处理Secret不泄漏
- **WHEN** 验收检查容器环境、MQ、Job、Tool事件、审计、API和日志
- **THEN** 不存在MinIO Secret、Docling API Key、Service bootstrap credential、原始正文、对象键或真实业务文件
