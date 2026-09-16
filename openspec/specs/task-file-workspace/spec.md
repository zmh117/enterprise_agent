# task-file-workspace Specification

## Purpose
定义 File Service 的文件权威、工作区周期与归属、本轮文件准入、Manifest v5、冻结目录与有界工作集、Runtime 沙盒、显式提交、日志证据和内容生命周期。文档/OCR 处理见 document-file-processing；Job 与投递状态见 execution-delivery；Principal 信任根与角色隔离见 identity-access。

## Requirements

**文件事实与权限**

### Requirement: File Service 是唯一文件事实入口
系统 MUST 由 `file-service` 统一管理任务工作区、文件、文件版本、配额、生命周期、审计和对象位置，并 SHALL 同时暴露受治理 File MCP 接口与受控内部 API。只有 File Service 基础设施层可以解析 MinIO Secret Reference 并操作 MinIO；Agent、Runtime、`file-worker`、MCP 参数或响应、Job、日志和审计 MUST NOT 接收 MinIO Access Key、Secret Key、Session Token、Bucket 或对象键。

#### Scenario: Agent 通过 File MCP 操作文件
- **WHEN** RUNNING Job 调用已冻结且授权的文件工具
- **THEN** File Service 根据 Job 解析任务工作区和受控对象位置并完成操作
- **AND** Agent 与 Runtime 不获得 MinIO 凭据或任意对象键

#### Scenario: Worker 尝试直接操作 MinIO
- **WHEN** `file-worker` 请求导入附件或清理到期内容
- **THEN** 它必须调用 File Service 内部 API
- **AND** 部署不得向 `file-worker` 注入 MinIO 凭据

### Requirement: File MCP 授权必须绑定当前 Job 与工作区
File Service MUST 使用 identity-access 规定的短时 File Principal/JWKS 与独立内部 Service Principal 策略。每次用户文件调用 MUST 复核 RUNNING Job、内部用户、tenant、Session、Agent/Application Publication、授权 hash、精确 Tool/schema/scope，以及私聊 owner 或同群边界；冻结 Manifest、追加工作集或短期传输意图均不得替代实时授权。内部导入、清理、处理和 Delivery 使用各自角色固定 scope，用户 Principal 与 Service Principal 不得互换。

#### Scenario: 已冻结文件但访问被撤销
- **WHEN** Job/文件身份仍匹配而当前用户或应用访问已经失效
- **THEN** File Service 在返回元数据、创建 transfer 或读取对象前拒绝

#### Scenario: 内部身份被用于 File MCP
- **WHEN** Worker 的 Service Principal 调用用户文件工具或用户 Principal 调用内部接口
- **THEN** 独立 audience、authorized party 与 scope 校验失败关闭

### Requirement: File MCP 参数不声明平台身份和对象位置
File MCP Tool输入 MUST 使用封闭Schema，只允许必要的文件选择、精确版本、沙盒文件句柄和用户业务意图。模型 MUST NOT声明用户、租户、任务工作区、reply route、Bucket、对象键、上传URL、Credential Reference或MCP Server地址；File Service必须从已验证Principal与Job解析这些事实。

#### Scenario: 模型提交任意对象键
- **WHEN** File Tool参数包含Bucket、对象键或跨工作区File ID
- **THEN** schema或授权校验在对象操作前拒绝

### Requirement: 私聊与群聊工作区具有确定归属
私聊任务工作区 MUST 归当前内部用户私有。群聊工作区 SHALL 使用 GROUP_CONVERSATION 归属，授权边界为受信企业、Connector 和外部群会话；活动工作区仍按 session_id 解析，每次操作 MUST 使用当前消息实际发送人的内部身份重新校验业务应用访问和同群边界。不同 Session 不因同一群归属而自动合并工作区。File Service MUST NOT 复制或同步钉钉逐成员 ACL，也 MUST NOT 将群聊解释为共享内部身份或共享个人外部凭据。

#### Scenario: 同群成员继续编辑
- **WHEN** 同一受信群会话中的已绑定用户发起新 Job、复用同一合法 Session/活动工作区且拥有当前业务应用访问权
- **THEN** 该 Job 可以获得该活动工作区的授权文件清单并提交新版本；不同群成员是否复用 Session 由 channel-conversation 的完整身份键决定

#### Scenario: 跨群文件 ID 被提交
- **WHEN** 当前 Job 提供另一个群、私聊、租户或会话的文件 ID
- **THEN** File Service 在读取内容或对象存储前拒绝

#### Scenario: 个人来源文件进入群工作区
- **WHEN** Agent 通过个人 ONES 或其他个人凭据取得文件并准备放入群工作区
- **THEN** 系统必须先取得来源用户明确确认并创建保留来源血缘的群共享副本
- **AND** 不共享个人凭据、不自动同步外部原件也不把群修改写回外部原件

### Requirement: 文件使用稳定身份和不可变版本
每个文件 MUST 具有稳定 File ID、一个或多个不可变 File Version 和至多一个当前版本指针。导入、生成、编辑和外部同步 MUST 创建新版本，不得原地改写历史对象。既有文件提交 MUST 提供 File ID 与基础版本 ID，且只有基础版本仍为当前版本时才能原子切换当前指针。

#### Scenario: 基础版本仍为当前版本
- **WHEN** Agent 基于 V3 提交内容且 V3 仍是当前版本
- **THEN** File Service 创建不可变 V4 并原子把当前版本指向 V4

#### Scenario: 基础版本已经变化
- **WHEN** Agent 基于 V3 提交内容但当前版本已是 V4
- **THEN** File Service 不覆盖 V4且返回版本冲突

### Requirement: 文件格式和配额必须有界
直接文本 SHALL 固定为代码发布的 `text-v2`：TXT、Markdown 可读写，LOG 只读；应用、Job 或 Runtime 不得切换该规则。文本与 Agent 可读 Markdown 单文件最大 15 MiB，必须有效 UTF-8、无 NUL；上传可识别 UTF-8 BOM，Agent 输出必须无 BOM。只有应用发布启用 `docling-layout-ocr-v2` 才接收 PDF、DOCX、XLSX、PPTX、PNG、JPEG、WebP 原件，源文件最大 25 MiB，PDF 最多 300 页。MIME、扩展名与结构 MUST 一致；DOC/XLS/PPT、宏、`.markdown` 和未知格式不得宽松降级或猜测转码。

工作区逻辑文件数使用租户当前有效配置，默认 200 个 ACTIVE 文件、硬上限 1000；计费容量默认 2 GiB、硬上限 10 GiB。File Service MUST 将实际用量与有效预留一并校验，新导入、提交与派生内容超限时不得发布可见版本、表示或错误当前指针。配额不来自 Application Publication，工作区保留周期与配额是不同事实。

#### Scenario: 不支持编码
- **WHEN** TXT、LOG、Markdown 为 GBK、UTF-16 或无效 UTF-8
- **THEN** 安全拒绝，不自动猜测或转码

#### Scenario: 启用文档处理
- **WHEN** 合规 PDF/Office/图片到达且发布固定当前 Profile
- **THEN** 保存精确原件并异步产生表示；Profile 为 NONE 时返回明确未启用，不调用 Docling

#### Scenario: 降低租户配额
- **WHEN** 工作区已有 240 个 ACTIVE 文件而配额降为 200
- **THEN** 已有文件仍可按当前授权读取，新增逻辑文件被拒绝；新版本不能继续扩大已超限维度

#### Scenario: 配额覆盖越界
- **WHEN** 配置请求超过 1000 文件或 10 GiB
- **THEN** 配置保存与 File Service 消费均失败关闭

#### Scenario: LOG 或 Markdown 被读取
- **WHEN** Agent 使用受管 `.log` 或 `.md`
- **THEN** LOG 不可编辑或提交，Markdown 保持不可信纯文本，不渲染 HTML 或获取远程资源

**工作区与本轮准入**

### Requirement: Agent Session 与任务工作区分离
一个 Agent Session SHALL 包含零个或多个任务工作区，同一时刻最多一个任务工作区为 `ACTIVE`。没有活动工作区时，首个文件输入或文件产出请求 SHALL 创建新工作区；普通文字问答 MUST NOT 创建工作区。连续追问和新增文件默认进入当前活动工作区，用户明确开始新任务、结束当前任务或确认 Agent 的切换询问时才切换。

过期或关闭工作区 MUST NOT 被自动恢复为 `ACTIVE`，也 MUST NOT 把旧工作区里的文件重新挂接为当前活动文件。本 Job 按时段硬证据只读召回仍在独立保留期内的精确版本，不属于恢复旧工作区，且 MUST 遵守本能力中「本 Job 可只读召回未挂接当前工作区的保留版本」。
#### Scenario: 普通文字连续问答
- **WHEN** Session 没有活动任务工作区且用户只提出普通文字问题
- **THEN** 系统创建 Agent Job 但不创建任务工作区
#### Scenario: Agent 怀疑用户开始新任务
- **WHEN** Session 已有活动工作区且新请求可能属于另一任务但用户没有明确说明
- **THEN** Agent 必须先询问是否切换
- **AND** 系统不得静默复用或关闭任一工作区
#### Scenario: 过期工作区后的新文件请求
- **WHEN** 先前工作区已经关闭或过期且用户再次请求处理新上传或新生成的文件
- **THEN** 系统创建新任务工作区
- **AND** 不自动把旧工作区改回 `ACTIVE`，也不把旧文件重新 `link` 进新工作区
#### Scenario: 过期后按时段只读召回不是恢复工作区
- **WHEN** 先前工作区已经过期，用户询问「上周的附件」且附件仍在独立保留期内
- **THEN** 系统至多创建本周期新的 `ACTIVE` 工作区作为 Job 容器，并把命中版本只读冻结进本 Job Manifest
- **AND** 不得把旧工作区改回 `ACTIVE` 或恢复其活动文件集合

### Requirement: 工作区自然周期由 Business Application Publication 冻结
任务工作区创建时 MUST 从命中的 Business Application Publication 读取 `DAY`、`WEEK` 或 `MONTH` 保留策略，并按 Asia/Shanghai 自然周期计算固定到期时间。`DAY` 在次日 `00:00` 到期，`WEEK` 在下周一 `00:00` 到期，`MONTH` 在下月一日 `00:00` 到期；用户活动 MUST NOT 滚动延长该时间。旧 Publication 缺少该字段时 MUST 稳定解释为 `WEEK`。

#### Scenario: 周保留工作区持续活跃
- **WHEN** 周三创建的 `WEEK` 工作区在周日仍有用户活动
- **THEN** 到期时间仍为下周一 `00:00`
- **AND** 不因最近活动延长一周

#### Scenario: 到期时仍有非终态工作
- **WHEN** 工作区到期但仍关联非终态 Agent Job、文件提交或文件交付
- **THEN** 清理必须暂缓到这些操作进入终态
- **AND** 暂缓不得修改原到期时间

### Requirement: 入站附件只通过任务工作区形成Agent可读内容
所有消息附件 MUST 先由File Service形成受管原件和不可变版本。TXT、LOG和Markdown只按固定`text-v2`规则形成直接可读内容；Office、PDF和图片只在Publication启用`docling-layout-ocr-v2`时形成受治理Representation。Channel、API和Agent上下文构建器不得进程内提取DOCX、XLSX、PPTX或Markdown正文，也不得从独立附件正文缓存向模型注入内容。

#### Scenario: DOCX附件到达
- **WHEN** 用户发送合法DOCX且应用启用`docling-layout-ocr-v2`
- **THEN** 附件经File Service、processing队列和固定Docling Profile形成Markdown Representation
- **AND** Channel/API进程不使用Office库直接提取正文

### Requirement: Agent Job 本轮文件准入必须形成单一不可变决策
系统 MUST 在创建或补建 Task Workspace、持久化 Agent Job 或系统通知、冻结 Job File Manifest 之前，根据当前消息文字、ingress 输出意图 hint、当前消息附件、显式 File/Version 引用、引用消息、冻结的 Business Application Publication 文件策略、当前活动工作区候选和仍有效的跨会话保留候选，形成单一不可变的本轮文件准入决策。该决策 MUST 同时冻结有效输出意图、文件能力依赖及其绑定原因、Gate action 与安全原因码、Task Workspace 需求、Manifest Working Set 与自动物化计划，以及等待附件完成后重新评估所需的安全事实；后续调用方 MUST 消费该决策，不得重新解析消息或根据 `TIME_WINDOW`、能力类型、候选数量等内部字段推导另一套准入结果。

#### Scenario: 输出请求中的时间词不触发历史附件绑定
- **WHEN** 用户请求“生成 md 文件记录我今天的对话”且没有当前消息附件或显式文件来源
- **THEN** 单一准入决策把该消息识别为文件输出请求并返回 `enqueue_job` 与 `no_file_dependency`
- **AND** 系统不得把“今天”重新解释为历史工作区文件时间窗口

#### Scenario: 输出请求显式指定时间窗口文件来源
- **WHEN** 用户请求“根据今天上传的文件生成汇总.md”且存在仍可访问的时间窗口候选
- **THEN** 单一准入决策返回最多 20 个 `METADATA + TIME_WINDOW` 候选
- **AND** Task Workspace 与 Job File Manifest 消费该决策时不得把候选正文自动物化

#### Scenario: 准入结果统一驱动工作区与 Manifest
- **WHEN** 本轮准入决策要求创建或复用 Task Workspace 并允许创建 Agent Job
- **THEN** Workspace 解析、File MCP Tool Snapshot 启用判断与 Job File Manifest binding plan MUST 消费同一准入决策
- **AND** Agent Job 创建 implementation 不得再次检查绑定原因、能力类型或候选数量来改变 Workspace 或自动物化结果

#### Scenario: 安全通知复用同一准入结果
- **WHEN** 准入决策因非法日期、空时间窗口、候选超限、绑定歧义或文件能力不可用而返回 `system_notice`
- **THEN** 系统 MUST 使用该决策冻结的原因码和安全事实生成既有中文通知且不创建 Agent Job
- **AND** 通知路径不得重新解析原始消息或重新选择文件候选

### Requirement: 文件绑定必须遵循确定性优先级
文件准入 MUST 在已授权候选内按当前消息附件、显式 File/Version 引用、可解析引用消息、完整文件名、显式时间窗口文件来源及代码定义指示语依次解析。完整文件名歧义 MUST 澄清，部分或近似名称不形成正文依赖；引用消息无法解析时不得偷换成最近文件。明确“刚才 N 个”仅在固定 1–20 范围和足量候选下按来源时间等稳定排序选择；无数量的复数指示语有多个候选时澄清。单数指示语只能绑定唯一候选或唯一最新已就绪候选，不能用模型猜测形成执行前权限。

#### Scenario: 当前附件覆盖低优先级线索
- **WHEN** 消息同时含新附件、完整文件名与时间词
- **THEN** 以本条消息附件形成本轮依赖，不把其它线索扩大为自动物化集合

#### Scenario: 引用无法解析
- **WHEN** 引用消息未命中受信同会话候选
- **THEN** 不按“刚才那个”回退选择另一文件

#### Scenario: 单数或复数指示语
- **WHEN** 一个工作区只有一份合规候选，用户询问“这个文件”
- **THEN** 可冻结该精确身份；多个并列候选而无法唯一确定时返回既有中文澄清

### Requirement: 文件发现候选不得等同于正文绑定
显式时间窗口文件来源 SHALL 只返回最多 20 个 `METADATA + TIME_WINDOW` 候选，不含正文、凭据或对象位置，即使只有一个候选也不得自动物化。窗口依据原始 `source_received_at`，不得按导入、编辑、表示或观察时间替换。候选超限、空窗或非法日期 MUST 使用既有中文系统通知且不创建 Agent Job；仅为生成新文件使用的“今天”等会话时间词不构成历史文件来源。Agent 在模型阶段选择候选后，必须用精确 File/Version 进入受治理物化。

#### Scenario: 一个时间窗口候选
- **WHEN** 用户询问上周上传文件内容且只有一份仍有效候选
- **THEN** Job 只冻结元数据候选，Runtime 不在模型选择前物化正文

#### Scenario: 超过窗口上限
- **WHEN** 合法窗口内仍有效候选超过 20
- **THEN** 返回缩小范围通知，不静默截断或创建超限 Job

#### Scenario: 输出请求带时间词
- **WHEN** 用户要求生成 md 记录今天对话，未指定附件来源
- **THEN** 准入为输出请求和零文件依赖，不搜索今天附件

### Requirement: 显式非法文件日期必须 fail closed
文件上下文解析 MUST 区分没有日期表达、合法日期表达和显式非法日期表达。非法日历日期、非法区间端点或结束早于开始的区间 MUST NOT 回退为今天、最近日期或其它猜测范围；当消息同时具有文件语义时，系统 MUST 返回不创建 Agent Job 的安全澄清。

#### Scenario: 用户输入不存在的日期
- **WHEN** 用户请求“2月30日的文件”
- **THEN** 系统返回日期无效的澄清通知且不创建 Agent Job
- **AND** 不查询、选择或绑定今天的文件

#### Scenario: 普通消息包含非法日期但没有文件语义
- **WHEN** 用户讨论“2月30日这个说法”且没有文件、附件或文档语义
- **THEN** 系统不得据此创建文件时间窗口
- **AND** 普通文字消息路径保持不变

### Requirement: 来源等待与文档可读性门禁必须分离
准入 Gate SHALL 返回 `enqueue_job`、`wait_source` 或 `system_notice`。没有依赖的非空文字为 `no_file_dependency`，不因工作区存在处理中文档而等待。`WAITING_INPUT` 只等待本轮绑定附件来源下载/导入；来源就绪后，METADATA/ORIGINAL 与 READABLE_CONTENT 分别判定。需要正文而表示 PENDING 时 MUST 在 Agent 入队前用固定未就绪通知结束本轮；AVAILABLE 或具有合规 Markdown 的 PARTIAL 才能用于阅读，NO_TEXT/FAILED/内容不可用不得伪造正文。纯附件暂存不创建 Agent Job、Manifest 或模型调用。

#### Scenario: 文档处理中出现普通问题
- **WHEN** 工作区文件仍在 RUNNING/RETRY_WAIT，而本轮文字无文件依赖
- **THEN** 创建并调度普通 Job，不自动物化该文档

#### Scenario: 需要正文但尚未生成
- **WHEN** 已保存原件而 Markdown 尚未就绪
- **THEN** 当前正文请求得到安全系统通知，不能让 Agent Job 等 Docling；原件/元数据操作仍按其自身授权判断

#### Scenario: 来源下载后重新评估
- **WHEN** WAITING_INPUT 的附件导入进入终态
- **THEN** 使用冻结依赖身份刷新来源/可读状态，不重新解析文字或纳入后来出现的新文件

### Requirement: 等待中的文件准入必须从冻结事实恢复
因当前消息附件来源下载或导入尚未就绪而创建的等待中 Agent Job MUST 持久化与初始准入决策兼容的安全依赖事实。附件状态变化后，系统 MUST 仅使用冻结依赖身份和刷新后的来源、可读性状态重新评估 Gate，不得重新解析原始消息、重新运行输出意图识别或纳入决策冻结后出现的新候选；现有 `file_turn_dependencies` payload MUST 保持向后兼容，使已持久化的等待中 Job 可以继续恢复。

#### Scenario: 当前消息附件处理完成后恢复
- **WHEN** 等待中 Agent Job 的当前消息附件完成导入或可读内容生成
- **THEN** 系统以冻结依赖身份和刷新后的状态重新评估原 Gate，并按既有规则释放 Job 或发送安全通知
- **AND** 系统不得因工作区新增文件或消息文字重新解析而改变本轮绑定集合

#### Scenario: 部署前创建的等待中 Job 恢复
- **WHEN** 当前实现 读取既有持久化的 `file_turn_dependencies`
- **THEN** 系统 MUST 无需数据迁移即可恢复等价的文件依赖并完成 Gate 重新评估
- **AND** 不得因缺少新内部类型或字段而拒绝、扩展或猜测依赖

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

**清单、目录与精确读取**

### Requirement: Job 创建时冻结精确文件清单
非空文字经准入后，File Service MUST 冻结 schema v5 Job File Manifest 与 hash，包含 Job/workspace、`workspace_catalog_revision_id` 以及本轮确定性绑定的精确 File/Version 工作集；不得复制全部工作区目录。需转换文档的可物化项 MUST 同时冻结 Markdown Representation ID、kind、format、size、SHA-256、创建时间与安全物化名。只自动物化本轮已绑定且能力就绪的直接文本或表示；时段发现保持元数据。其余版本通过冻结目录分页后精确选择。源/表示身份固定，授权在操作时重新校验。

Manifest MUST 区分 source_received_at、version_created_at、representation_created_at 与 observed_at。source_received_at 来自原 message_attachment 创建时间并沿版本/表示保持不变，Agent 生成文件为 null。非空机器时间使用 UTC RFC 3339 并进入 canonical hash；不能生成、读取、投影或恢复 Manifest v1–v4。无文件 Job MUST 使用合法空文件上下文。

#### Scenario: 新版本或新表示产生
- **WHEN** Job 冻结 source V3、representation R1 后出现 V4 或 R2
- **THEN** 当前 Job 继续物化 V3/R1，新版本只进入后续目录与 Job

#### Scenario: 大目录小工作集
- **WHEN** 工作区目录有 1000 个 ACTIVE 文件，本轮只有两个精确输入
- **THEN** Manifest 只保存目录 revision 与这两个输入，Runtime 只预检和自动物化这两个

#### Scenario: 自动物化整批超限
- **WHEN** 本轮自动物化超过 40 个不同版本或其实际文本/Markdown 超过 224 MiB
- **THEN** 创建 Job 和 Outbox 前完整拒绝并要求缩小范围，不启动只有部分输入的执行

#### Scenario: 表示被替换或旧 schema 到达
- **WHEN** 请求使用不属于精确 source Version 的表示或旧 Manifest schema
- **THEN** 在对象读取与模型调用前失败关闭，不投影、不计算旧 hash

#### Scenario: 无来源生成文件
- **WHEN** 文件由 Agent 生成而非聊天附件导入
- **THEN** source_received_at 为 null，version_created_at 非空，不把生成时间说成上传时间

### Requirement: 机器文件时间必须保持 UTC canonical 表达
Job File Manifest、File MCP 响应和 Runtime 文件上下文中的 `source_received_at`、`version_created_at`、`representation_created_at`、`observed_at` 与非空 `expires_at` MUST 输出为带时区的 UTC RFC 3339，并 MUST 表示与持久化事实相同的 instant。Asia/Shanghai 只可用于自然周期计算或展示层本地化，MUST NOT 写入机器协议、不可变快照或 hash 输入。

#### Scenario: UTC 来源时间进入 Runtime
- **WHEN** 持久化来源接收时间为 `2026-08-19T04:49:29+00:00`
- **THEN** Manifest、File MCP 和 Runtime 文件上下文均返回等价 UTC RFC 3339
- **AND** 不把该值改写成 `2026-08-19T12:49:29+08:00`

#### Scenario: Manifest consumer 复算 hash
- **WHEN** Runtime 对 schema 支持的 Manifest 使用返回的 canonical 时间字段复算 hash
- **THEN** 复算结果与冻结的 `manifest_hash` 一致
- **AND** 响应序列化不得在 hash 校验后改变时间 canonical 表达

### Requirement: 工作区文件目录支持有界一致分页发现
File Service SHALL提供只读工作区目录发现能力，使用当前RUNNING Job的Principal、Publication、workspace和Manifest冻结的`workspace_catalog_revision_id`解析授权范围，并以游标分页返回默认20、最多50项安全元数据。查询 MUST只接受代码注册的名称、格式、来源接收时间和可读状态过滤，结果 MUST包含精确`file_id + version_id`、安全显示名、格式、大小、机器时间、可读状态、`observed_at`和冻结目录revision；MUST NOT包含正文、对象位置、Bucket、凭据或跨工作区数据。模型输入 MUST NOT声明workspace、tenant或revision身份。

工作区目录 MUST具有不可变revision身份和时间化成员事实。ACTIVE成员、逻辑名或选中版本发生变化时 MUST在同一事务创建下一revision并保留仍被Job引用的旧revision查询能力；不得为每个Job复制整个目录。分页cursor MUST绑定workspace、过滤摘要、`workspace_catalog_revision_id`和最后排序键。同一Job在当前目录变化后 MUST仍按冻结revision无重复无漏项地继续分页；新成员或新版本只可由后续Job的新revision发现。现有`task_workspace_list_files` MUST继续只列当前Job初始Manifest/工作集语义，新目录发现 MUST使用独立Tool identifier和schema hash；当该Tool返回空`items`时，响应 MUST包含`job_initial_manifest_empty`机器原因、`job_initial_manifest`结果范围以及必须继续调用`task_workspace_search_files`的有界参数提示，且不得因此读取目录、增加Manifest条目或扩大授权。

#### Scenario: 分页发现1000个ACTIVE文件
- **WHEN** 授权Job以limit 50遍历一个含1000个ACTIVE文件的工作区且目录revision保持不变
- **THEN** 每页最多返回50个不含正文的精确元数据项和不透明下一页cursor
- **AND** 各页按确定性顺序无重复无漏项

#### Scenario: 翻页期间当前目录发生变化
- **WHEN** Agent取得冻结revision的第一页后另一个事务上传新文件并创建下一revision
- **THEN** 原Job使用旧cursor继续得到旧revision的下一页且无重复无漏项
- **AND** 新文件只对冻结新revision的后续Job可见

#### Scenario: 查询尝试声明workspace或对象位置
- **WHEN** Tool参数包含workspace ID、tenant ID、catalog revision ID、Bucket、对象键或任意URL
- **THEN** 封闭Schema在数据库或对象存储访问前拒绝

#### Scenario: 冻结版本后来不再是当前版本
- **WHEN** Job冻结目录中的V3在分页后被工作区V4取代，但V3内容仍可用且当前主体仍有权访问
- **THEN** Agent可精确选择V3并由工作集事实冻结V3
- **AND** File Service不得静默替换为V4

### Requirement: 每个Job输入物化工作集最多40项且选择事实只追加
每个Job自动物化与运行中按需物化的输入按`file_id + version_id`去重后 MUST不超过40项。运行中追加选择 MUST保存不可变Job工作集事实，包含Job/Snapshot、workspace、`workspace_catalog_revision_id`、精确File/Version、适用时的精确Representation身份与hash、选择来源、序号和时间；重复选择或物化同一版本 MUST幂等返回同一事实与既有Sandbox输入，不得重复计数、改写初始Manifest、Manifest hash或Runtime request digest。

只有Job冻结兼容工作区发现Tool时，`file_prepare_materialization`才 MAY把Manifest外但属于冻结目录revision的精确版本原子加入输入工作集。加入前 MUST实时复核Job状态、当前主体、tenant、Session、Publication、Tool schema hash、workspace/revision归属、精确Version内容可用性、Representation血缘、40项上限以及Runtime Sandbox预留结果；追加选择只授予本次受治理读取所需动作，不得自动授予EDIT、COMMIT或DELIVER。

#### Scenario: Agent选择目录搜索结果
- **WHEN** 兼容Job从目录结果取得当前精确File/Version并请求准备物化，当前工作集只有7项
- **THEN** File Service原子记录第8个追加工作集事实并准备受控物化
- **AND** 初始Manifest和Runtime request digest保持不变

#### Scenario: 第41个输入被拒绝
- **WHEN** 自动与按需输入去重后已有40个不同File/Version，Agent再选择一个不同版本
- **THEN** File Service返回`job_file_working_set_limit_exceeded`
- **AND** 不创建追加事实、transfer或Sandbox文件

#### Scenario: 重复物化同一版本
- **WHEN** 同一Job再次请求已经成功物化的相同File/Version
- **THEN** Runtime返回既有安全handle或等价幂等结果
- **AND** 输入计数、Sandbox文件数和字节用量均不重复增加

#### Scenario: 旧Job尝试动态晋升
- **WHEN** 历史Job未冻结兼容工作区发现Tool却请求物化Manifest外File/Version
- **THEN** File Service沿用Manifest-only边界并在读取内容前拒绝

#### Scenario: 冻结版本内容已经不可用
- **WHEN** Agent选择冻结目录revision中的V3，但V3内容已按生命周期清理或当前授权已撤销
- **THEN** File Service在创建transfer前失败关闭
- **AND** 不自动改用V4或其它Representation

### Requirement: 原始文件与Agent可读表示使用不同身份和动作
File Service MUST 将 PDF、DOCX、PPTX、XLSX、PNG、JPEG、WebP 保存为原始 File Version，将同一 run 的 MARKDOWN、DOCLING_JSON、OCR_LAYOUT_JSON 保存为独立不可变 Representation。原件动作仅为 READ_METADATA、RETAIN、DELIVER；仅最终 Markdown 可受控 MATERIALIZE，原件/图片 asset/两种 JSON 不得进入 Agent Sandbox。Manifest 只携带最终 Markdown 精确身份与大小/hash，不携带 OCR 正文、坐标、picture asset ID 或对象位置。表示不能成为原件当前版本、获得编辑/提交动作或冒充原件交付。

#### Scenario: 总结后发送原件
- **WHEN** Agent 读取 PDF/Office 派生 Markdown 后用户要求原样发送
- **THEN** Delivery 读取精确原始 File Version，不发送表示或重新运行处理

#### Scenario: 用户要求修改 DOCX 版式
- **WHEN** 用户要求直接编辑 DOCX 原件
- **THEN** 说明当前只支持读取派生文字与生成受支持文本，不能把 Markdown 改动声称为 DOCX 新版本

#### Scenario: 物化同 run 的 JSON
- **WHEN** Runtime 将 OCR_LAYOUT_JSON 或 DOCLING_JSON 替换进 Markdown 物化请求
- **THEN** File Service 在返回字节前拒绝，同源或同 run 不扩大动作

### Requirement: 本 Job 可只读召回未挂接当前工作区的保留版本
当本轮确定性绑定命中「不在当前 `ACTIVE` 工作区 `task_workspace_file` 上、但仍在聊天附件保留期内」的精确版本时，File Service MUST 允许将该版本冻结进 **当前 Agent Job File Manifest**。该召回初始仅冻结 METADATA，不自动物化；后续精确选择仍可受控读取。该召回 MUST NOT 把已 `EXPIRED` / `CLEANED` 的工作区改回 `ACTIVE`，MUST NOT 把历史文件重新 `link` 为当前工作区活动文件，也 MUST NOT 把 360 天附件库暴露为模型可浏览的目录。

历史召回项的允许动作 MUST 排除 `EDIT` 和 `COMMIT`。用户若要求在召回内容基础上保存或修改，后续提交 MUST 写入当前 `ACTIVE` 工作区的新文件或新版本，MUST NOT 把新字节写回已清理工作区中的原 File ID。物化时 MUST 重新检查当前用户、租户、Business Application 访问以及私聊所有者或同群会话边界。正文已按保留策略清理、File/Version ID 仍在的条目 MAY 作为元数据进入清单；读取正文 MUST 失败关闭为内容不可用，MUST NOT 从旧钉盘引用自动重新导入。

若时段召回命中且当前 Session 没有 `ACTIVE` 工作区，系统 MUST 创建本周期的空活动工作区，仅作为该 Job 的 File MCP 容器，仍 MUST NOT 把历史文件 `link` 进去。若时段召回未命中，系统 MUST NOT 仅为空窗说明创建工作区。

#### Scenario: 工作区已到期仍可把保留附件写入本 Job 清单
- **WHEN** 上一自然周的任务工作区已清理，`task_workspace_file` 为 `REMOVED`，用户本周询问「上周的文件」，且附件仍在 360 天保留期内
- **THEN** File Service 把该精确版本冻结进本 Job Manifest
- **AND** 旧工作区状态保持非 `ACTIVE`
- **AND** 当前工作区活动文件集合不增加该历史文件

#### Scenario: 历史召回项不能提交回旧文件
- **WHEN** Agent 对仅因时段召回进入清单、且未挂接当前工作区的 File ID 调用 `file_create_commit_intent`
- **THEN** File Service 拒绝提交
- **AND** 不在已清理工作区创建新版本

#### Scenario: 无活动工作区但召回命中
- **WHEN** Session 当前没有 `ACTIVE` 工作区，时段硬证据命中至少一份仍可访问的保留附件
- **THEN** 系统创建本周期空的 `ACTIVE` 工作区并冻结含历史项的 Job Manifest
- **AND** 不把命中附件重新 `link` 为该工作区活动文件

#### Scenario: 正文已清理只保留身份
- **WHEN** 时段召回命中的 Version ID 仍在但版本或文件状态为 `CONTENT_UNAVAILABLE`
- **THEN** 该条目可以元数据进入本 Job Manifest
- **AND** 不得把对象字节或提取文本写入沙盒

### Requirement: 跨会话保留候选必须在查询时仍有效
跨会话历史附件候选 MUST 在每次查询时同时校验附件可用终态、附件 `expires_at`、binding `retention_expires_at`、文件状态、版本状态以及至少一条未过期的 `file_retention_fact`。缺少或过期的保留事实 MUST fail closed；Cleanup Worker 延迟 MUST NOT 延长候选可见性或正文访问期。

#### Scenario: 保留事实已过期但清理尚未执行
- **WHEN** 文件和对象仍标记为可用，但当前时间已不早于保留事实或 binding 的到期时间
- **THEN** 历史候选查询不返回该 File/Version
- **AND** 不因 Cleanup Worker 延迟允许 Agent 发现或读取正文

#### Scenario: 历史版本没有保留事实
- **WHEN** 旧附件存在 File/Version binding 但没有可验证的有效保留事实
- **THEN** 历史候选查询不返回该版本
- **AND** 系统不补造保留事实或假定无限期有效

#### Scenario: 附件生命周期不可用
- **WHEN** 附件状态为失败、拒绝、处理中或附件内容已经到期
- **THEN** 历史候选查询不返回其绑定版本

### Requirement: File MCP对未就绪或失败表示失败关闭
File Service 的 `file_prepare_materialization` MUST 在读取对象或返回传输控制信息之前确认目标精确版本具有可物化的 Agent 可读内容。当所需 Markdown 表示仍为处理中时，工具 MUST 返回稳定错误码 `file_readable_content_not_ready`；当处理已失败、无文字或内容不可用时，MUST 返回 `file_processing_failed` 或与现有安全拒绝一致的稳定码。错误结果 MUST 只包含错误码、安全文件名和有界状态短语，MUST NOT 包含正文片段、对象键、Docling task ID、重试次数、内部队列名或原始异常。`file_get_metadata` 和 `task_workspace_list_files` MAY 返回有界可读性状态（如 `PENDING`、`AVAILABLE`、`FAILED`），以便 Agent 发现文件存在，但 MUST NOT 把处理中文档描述为可读取正文。`file_deliver_version` 在原件已保存且具备 `DELIVER` 时 MUST NOT 因 Markdown 未就绪而拒绝。系统提示 MUST 规定：收到上述未就绪或失败码时不得推测文件内容、不得根据文件名编造正文，并告知用户可读内容尚未生成或生成失败。

#### Scenario: 按需物化处理中的文档
- **WHEN** RUNNING Job 对可读性仍为 `PENDING` 的文档版本调用 `file_prepare_materialization`
- **THEN** File Service 在创建传输前拒绝，错误码为 `file_readable_content_not_ready`
- **AND** 审计只保留文件身份、错误码和有界状态，不含正文或内部处理器标识

#### Scenario: 按需物化已失败的文档
- **WHEN** 目标版本的 processing run 已 `FAILED` 或可读性为 `UNAVAILABLE`/`NO_TEXT`
- **THEN** `file_prepare_materialization` 返回 `file_processing_failed` 或等价稳定码
- **AND** 不返回空 Markdown 冒充成功

#### Scenario: 查询处理中文件的元数据
- **WHEN** Agent 对处理中文档调用 `file_get_metadata` 或在 `task_workspace_list_files` 中看到该文件
- **THEN** 结果包含安全文件名、精确版本和有界可读性状态
- **AND** 不包含可物化路径、对象位置或派生正文

#### Scenario: 交付原件不依赖表示
- **WHEN** 原件已保存且 Manifest 授予 `DELIVER`，Agent 调用 `file_deliver_version`
- **THEN** File Service 按原始 File Version 排队交付
- **AND** 不因 Markdown 表示仍为 `PENDING` 而拒绝

### Requirement: File MCP 对内容已清理的历史召回项失败关闭
`task_workspace_list_files` MUST 只列出当前 Agent Job File Manifest 快照中的条目，其中可以包含本轮时段召回、未挂接当前活动工作区的保留版本。列表和 `file_get_metadata` MUST 返回有界元数据（安全文件名、File/Version ID、`source_received_at`、版本状态），MUST NOT 返回对象键、凭据或正文。系统 MUST NOT 把 File MCP 列表扩大为当前工作区全部历史文件或 Session 内 360 天附件库；调试用全量目录不在本能力范围。

当目标精确版本或文件状态为 `CONTENT_UNAVAILABLE` 时，`file_prepare_materialization` MUST 在读取对象或返回传输控制信息之前拒绝，稳定错误码 MUST 为既有 `file_content_unavailable`（或与其安全语义一致、文案为「文件内容已不可用，请重新发送文件」的稳定码）。该拒绝 MUST NOT 使用 `file_manifest_item_denied` 冒充「不在清单中」。错误结果 MUST 只包含错误码、安全文件名和有界状态短语。系统提示 MUST 规定：收到该错误码时不得推测或编造正文，不得把「内容已清理」说成「用户没发过这份文件」。

对仅因时段召回进入清单的条目，`file_create_commit_intent` MUST 拒绝；`file_deliver_version` 在原件仍可用且清单授予 `DELIVER` 时 MUST 仍可排队交付。

#### Scenario: 列表可见已清理正文的历史项
- **WHEN** 本 Job 快照包含一份 `CONTENT_UNAVAILABLE` 的时段召回版本
- **THEN** `task_workspace_list_files` 仍返回其安全文件名、版本状态和 `source_received_at`
- **AND** 不返回可物化路径或对象位置

#### Scenario: 物化已清理正文不得报清单外
- **WHEN** RUNNING Job 对快照内 `CONTENT_UNAVAILABLE` 版本调用 `file_prepare_materialization`
- **THEN** File Service 在创建传输前拒绝，错误码为 `file_content_unavailable`
- **AND** 不得返回 `file_manifest_item_denied`

#### Scenario: 历史召回项禁止提交
- **WHEN** Agent 对未挂接当前活动工作区的时段召回 File ID 调用 `file_create_commit_intent`
- **THEN** File Service 拒绝
- **AND** 不创建 staging 对象或新版本

#### Scenario: 快照外历史附件对 File MCP 不可见
- **WHEN** 同一 Session 存在仍在保留期但未写入当前 Job 快照的附件
- **THEN** `task_workspace_list_files` 不返回该附件
- **AND** 使用其 File/Version ID 的物化请求被拒绝

**沙盒、流式传输与提交**

### Requirement: 每个 Agent Job 使用隔离临时沙盒
Runtime MUST为每个Agent Job创建独立Job Sandbox，并只把当前Job已授权工作集、ONES查询结果和代码派生证据按各自规则写入该目录。Sandbox MUST固定总文件上限64和总容量224MiB，并分别限制`inputs`最多40个文件、`work/outputs`合计最多16个文件、`tmp`及内部安全余量最多8个文件；目录、marker和不可见控制元数据不得被模型用来规避普通文件计数。PDF、Office、图片原始二进制、Docling JSON和OCR Layout JSON MUST NOT进入Agent Sandbox。

模型提交的路径 MUST 为安全相对路径；若 bundled CLI 在权限回调前解析为绝对路径，Runtime 仅可将词法上精确属于本次随机 Sandbox 根、规范化和符号链接检查均通过的路径还原为相对路径。沙盒外绝对路径、相邻前缀和模型可见绝对路径能力仍须拒绝。

自动物化、File MCP按需物化、Runtime Write/Edit、日志证据扫描生成的临时`work/`证据包和内部临时文件 MUST共享同一Sandbox预算与原子预留器。Runtime在写入第一个自动物化字节前 MUST对整批输入重新预留实际文件数与Manifest冻结大小；按需物化、写入和日志证据扫描 MUST在创建目标文件前预留对应分区名额和剩余容量。失败或完整性校验不通过 MUST删除不完整文件并释放预留。重复物化同一`file_id + version_id` MUST复用已有输入和handle，不重复占用文件数或字节。Claude Code Agent只可在该沙盒内使用`Read`、`Grep`、`Glob`、`Write`和`Edit`，以及在当前Job冻结只读物化能力时使用Runtime派生的`scan_log_evidence`；写/编辑动作仍受代码固定`text-v2`格式矩阵限制。Bash、Web、NotebookEdit、沙盒外路径、符号链接逃逸和其它开放执行能力 MUST保持不可用。Job成功、失败、取消或超时后 MUST清理沙盒，Runtime异常退出后 MUST由恢复扫描清理无RUNNING Job归属的残留目录。

#### Scenario: Agent读取PDF派生Markdown
- **WHEN** Job获得受控PDF source Version及其Markdown representation
- **THEN** Runtime只在安全inputs路径物化经过大小和SHA-256校验的Markdown
- **AND** 本地副本不改变MinIO、原始版本或representation

#### Scenario: Agent在沙盒内编辑文本输出
- **WHEN** Job按冻结文本策略获得可写TXT或Markdown并调用Edit
- **THEN** Runtime只允许规范化后仍位于该Job沙盒的目标路径
- **AND** 本地修改不直接改变MinIO或文件版本

#### Scenario: Agent尝试写沙盒外路径
- **WHEN** `Write`或`Edit`目标通过绝对路径、`..`、符号链接或其它方式离开Job Sandbox
- **THEN** Runtime在文件系统副作用前拒绝并记录安全工具结果

#### Scenario: Agent尝试读取原始二进制
- **WHEN** Agent或Runtime请求把PDF、Office或图片source Version直接物化到沙盒
- **THEN** File Service拒绝并只允许Manifest冻结的Markdown representation路径

#### Scenario: Agent在沙盒内编辑Markdown
- **WHEN** `text-v2` Job获得受控`.md`文件并调用`Edit`
- **THEN** Runtime只允许规范化后仍位于该Job沙盒且format允许`EDIT`的目标路径
- **AND** 本地修改不直接改变MinIO或文件版本

#### Scenario: Agent尝试编辑LOG
- **WHEN** Agent对沙盒内`.log`调用`Write`或`Edit`
- **THEN** Runtime在文件系统副作用前以稳定只读格式错误拒绝
- **AND** 不允许通过改名、绝对路径或handle复用绕过

#### Scenario: Agent读取Office派生Markdown
- **WHEN** Job工作集获得受控DOCX source Version及其Markdown representation
- **THEN** Runtime只在安全`inputs`路径物化经过大小和SHA-256校验的Markdown并计为一个输入
- **AND** 原始DOCX、Docling JSON和内嵌图片不进入Sandbox

#### Scenario: File MCP物化达到输入上限
- **WHEN** Sandbox已经成功物化40个不同File/Version输入且Agent请求第41个
- **THEN** Runtime与File Service在创建目标文件前拒绝`job_file_working_set_limit_exceeded`
- **AND** 不创建transfer残留、Sandbox文件或第41个有效工作集输入

#### Scenario: 输入文件数未满但容量不足
- **WHEN** 下一份Markdown会使Sandbox实际文件总量超过224MiB
- **THEN** 统一预算在下载字节前拒绝并返回安全容量错误
- **AND** 不因File MCP路径不同而绕过Write/Edit使用的容量边界

#### Scenario: Agent在沙盒内生成输出
- **WHEN** 40个输入均已占用且`work/outputs`仍有分区名额和总字节余量
- **THEN** Runtime允许在16个输出/工作文件上限内创建受支持文本
- **AND** 输入文件数不得消耗输出分区名额

#### Scenario: 日志扫描证据包占用工作分区
- **WHEN** Runtime准备为已物化LOG生成一个证据包
- **THEN** 证据包在读取首个输入字节前原子预留一个`work/outputs`文件名额和代码固定的最大容量
- **AND** 不得挤占输入分区名额、绕过224MiB总容量或把未完成文件暴露给模型

### Requirement: Runtime 通过受控文件桥完成物化和提交
Runtime MUST通过File Service受控流式接口下载Job初始Manifest或追加工作集中的精确文本File Version或精确Markdown Representation，并上传Agent显式选中的受支持沙盒文本文件。PDF、Office、图片原始二进制和Docling JSON不得进入Agent Sandbox。File MCP只创建物化或提交意图并返回不透明标识，流式传输不得把完整文件字节直接嵌入初始模型上下文、MCP传输控制JSON或普通Tool审计；Agent通过授权Read/Grep实际读取并进入SDK消息的片段由 execution-delivery 的完整审计专用链处理。Runtime不得获得MinIO凭据、Bucket、对象键或可供模型使用的上传URL。

Python Runtime MUST使用代码注册的进程内File MCP bridge代理Job冻结的部署固定File Service工具，并在远端ToolResult交回模型前处理隐藏传输控制信息。bridge MUST使用当前Job File Principal JWT和固定内部流式路径；文档传输控制信息还 MUST绑定精确representation ID、source Version、size和SHA-256。bridge不得接受模型提供的URL、Header、Token、绝对路径、对象位置或冻结目录revision外的representation；SDK消息返回后再处理的旁路不满足本要求。

Agent Worker MUST验证Manifest v5 hash后，将schema v5文件上下文原样传给当前受支持 Runtime 协议，MUST NOT投影、生成或读取Manifest v1-v4。对所有`auto_materialize=true`项，Control Plane MUST在创建Job和outbox前按不同File/Version数量及待进入Sandbox的实际字节执行完整预检；Runtime MUST在首次模型请求前先为全部不同File/Version取得File Service基于冻结事实签发的隐藏传输控制及精确预期大小，在任何下载发生前整批预留，再主动物化全部精确文本版本或Markdown表示。任何prepare、整批预留或下载失败均使Job失败关闭且不得形成部分可见输入。其余文件只能由Agent先查询Manifest冻结的目录revision，再以精确File/Version请求并追加工作集；File Service从同一冻结事实解析可用文本版本或Markdown representation。

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

#### Scenario: Agent尝试提交LOG沙盒文件
- **WHEN** Agent把`.log`路径或handle传给输出选择器或提交工具
- **THEN** Runtime与File Service均在接收正文前拒绝
- **AND** 不创建Commit Intent、staging、版本或Delivery

#### Scenario: Agent按需物化仍在处理的文档
- **WHEN** Agent 对 Manifest 中一份可读表示未就绪的候选调用 `file_prepare_materialization`
- **THEN** File Service 在读取对象前拒绝并返回稳定未就绪错误码
- **AND** Runtime 不把该结果升级为自动物化失败，也不向模型提供伪造正文

#### Scenario: 自动物化预检失败
- **WHEN** 计划自动物化的输入超过40个不同File/Version或实际Markdown总大小会突破224MiB
- **THEN** Control Plane在Job和outbox创建前完整拒绝并要求缩小工作集
- **AND** 不物化子集、不启动Runtime且不产生不完整Manifest

### Requirement: Runtime 显式选择单个沙盒输出
仅当当前Job冻结`file_create_commit_intent`和允许写入的文件格式策略时，Runtime SHALL注册代码自有的`select_sandbox_output`工具。该工具 MUST只接受当前Job Sandbox中安全相对`.txt/.md`路径，在返回不透明sandbox entry handle前校验路径边界、常规文件、无符号链接、format、15 MiB上限、UTF-8和无BOM输出；不得接受`.log`、返回正文、扫描目录或在Job结束时自动选择或提交其它文件。已物化且允许编辑的输入继续使用其既有handle。
#### Scenario: Agent选择新生成的TXT
- **WHEN** Agent在`outputs/`或`work/`生成合法TXT并显式调用`select_sandbox_output`
- **THEN** Runtime只为该精确文件创建本Job有效的不透明handle并返回安全元数据
- **AND** 后续提交意图只能上传该handle映射的文件
#### Scenario: Agent未选择其它草稿
- **WHEN** Job Sandbox中还存在未选择的其它文件并结束执行
- **THEN** Runtime不扫描、不上传且不提交这些文件
- **AND** finally清理整个Job Sandbox
#### Scenario: Agent选择新生成的Markdown
- **WHEN** Agent在`outputs/`或`work/`生成合法无BOM UTF-8 `.md`并显式调用`select_sandbox_output`
- **THEN** Runtime只为该精确文件创建本Job有效且绑定`MARKDOWN`的不透明handle并返回安全元数据
- **AND** 后续提交意图只能上传该handle映射的文件
#### Scenario: Agent选择LOG
- **WHEN** Agent对`outputs/`、`work/`或已物化输入中的`.log`调用`select_sandbox_output`
- **THEN** Runtime以格式只读错误拒绝
- **AND** 不通过改名或复制来源LOG自动获得提交授权

### Requirement: 文件提交必须显式且使用两阶段流式协议
Agent MUST 为每个需要持久化的沙盒文件显式创建 File Commit Intent，Job 结束不得自动扫描或提交全部变化。File MCP 调用只登记目标文件、新文件元数据或基础版本并返回不透明 Commit ID；Runtime MUST 通过受控内部流式接口把对应文件上传给 File Service。模型上下文和 MCP JSON MUST NOT 包含完整文件、Base64、上传凭据或 MinIO 地址，Commit ID 单独 MUST NOT 构成上传授权。

#### Scenario: 用户只要求分析文件
- **WHEN** Agent 在沙盒中创建草稿但用户没有要求修改、生成或保存文件
- **THEN** Agent 不创建提交意图
- **AND** 草稿随 Job 沙盒清理

#### Scenario: 用户明确要求修改文件
- **WHEN** 用户明确要求修改既有文件且 Agent 完成编辑
- **THEN** 该请求授权 Agent 创建一次对应文件提交意图，无需二次确认
- **AND** Runtime 流式上传所选沙盒文件

#### Scenario: 新文件逻辑名已经存在
- **WHEN** Agent 未提供 `file_id/base_version_id` 且请求的新文件显示名已被当前工作区活动文件占用
- **THEN** File Service 在创建 Commit Intent 和上传字节前返回 `file_logical_name_conflict`
- **AND** 不创建 staging 对象、文件版本、自动改名或覆盖现有文件

### Requirement: 提交暂存、校验和终结保持原子可恢复
File Service MUST在流式接收时计算内容哈希，并按Job冻结策略执行format、允许操作、逻辑扩展名、15 MiB大小和UTF-8校验；`.log` MUST在创建Commit Intent和接收正文前拒绝。终结前 MUST重新校验Job、工作区、文件归属、基础版本、format不变性和配额。暂存对象只有在对象完整且文件版本元数据事务成功后才能成为可见文件版本；失败或超时暂存不得进入文件列表或当前指针，并 MUST由`file-worker`可重试清理。
#### Scenario: 对象接收完成但数据库事务失败
- **WHEN** 合法TXT或Markdown暂存对象完整写入后文件版本事务回滚
- **THEN** 对象保持不可见待清理状态
- **AND** 文件列表和当前版本不发生变化
#### Scenario: 暂存对象清理暂时失败
- **WHEN** MinIO删除发生瞬时错误
- **THEN** File Service保留待清理事实并由`file-worker`重试
- **AND** 不错误标记为已删除
#### Scenario: LOG提交在接收正文前拒绝
- **WHEN** 调用方尝试为`.log` sandbox handle创建Commit Intent或上传新内容
- **THEN** File Service返回稳定的只读格式错误
- **AND** 不创建staging对象、文件版本或Delivery
#### Scenario: 修改既有文件时format发生变化
- **WHEN** Commit Intent引用既有File/Base Version但所选sandbox文件扩展名或format与基础版本不同
- **THEN** File Service在上传前拒绝
- **AND** 不把重命名LOG视为可写TXT或Markdown

### Requirement: Commit ID 提供严格幂等边界
相同 Commit ID、相同提交元数据和相同内容哈希的重试 MUST 只返回同一个 File Version ID。成功响应丢失后，Runtime MUST 能用原 Commit ID 恢复同一结果；相同 Commit ID 被用于不同文件、基础版本、元数据或内容哈希时 MUST 拒绝，不得创建重复版本或覆盖首次绑定事实。

#### Scenario: 成功响应在网络中丢失
- **WHEN** File Service 已创建版本但 Runtime 未收到响应并用原 Commit ID 重试
- **THEN** File Service 返回原 File Version ID
- **AND** 不创建第二个版本

#### Scenario: Commit ID 被复用于不同内容
- **WHEN** 调用者以同一 Commit ID 上传不同哈希内容
- **THEN** File Service 拒绝并记录不含文件正文的安全冲突审计

#### Scenario: 默认交付提交返回精确恢复回执
- **WHEN** 默认交付的新文件版本提交成功，或 Runtime 以同一 Commit ID 恢复成功结果
- **THEN** 回执返回同一 `file_id`、`version_id`、内容摘要、`delivery_id` 和当前 `delivery_status`
- **AND** `PENDING` 只表示交付已排队，Runtime 不需要列出工作区或再次调用显式交付来推断身份

#### Scenario: 同名检查后发生并发竞态
- **WHEN** 两个请求通过前置检查后竞争同一工作区逻辑名
- **THEN** 最多一个请求创建活动文件，另一个在发布事务中仍返回 `file_logical_name_conflict`
- **AND** 失败请求的 staging 进入可重试清理且不返回通用发布失败

### Requirement: 版本冲突由 Claude Code 显式处理
File Service MUST NOT对可写`.txt/.md`自动合并，也不得覆盖当前版本。已上传但因并发产生冲突的结果只能成为按工作区生命周期管理的Conflict Candidate，不得成为当前版本或Retained File。用户继续处理时，后续新Job SHALL同时物化最新版本和冲突候选，由Claude Code根据用户指令生成合并结果，并以最新版本为基础重新显式提交。只读`.log`不得产生编辑冲突候选。
#### Scenario: 群成员并发编辑 TXT
- **WHEN** 两个 Job 都基于 V3且第一个已提交 V4
- **THEN** 第二个结果成为冲突候选而不覆盖 V4
- **AND** File Service 不自动执行文本合并
#### Scenario: 群成员并发编辑Markdown
- **WHEN** 两个Job都基于同一Markdown V3且第一个已提交V4
- **THEN** 第二个结果成为冲突候选而不覆盖V4
- **AND** File Service不自动执行Markdown文本合并或渲染
#### Scenario: 两个Job读取同一LOG
- **WHEN** 两个Job并发物化同一`.log`精确版本
- **THEN** 两者可以按授权读取但都不能提交新版本
- **AND** File Service不创建LOG冲突候选

### Requirement: 文件提交结果与 Agent Job 终态分离
同一 Job 的每个 File Commit Intent MUST 独立记录成功、版本冲突或其它拒绝，部分失败不得回滚已成功版本。只要 Runtime 正常完成、持久化最终回复并准确说明各文件结果，Agent Job SHALL 保持 `SUCCEEDED`，系统 MUST NOT 为此新增 `PARTIAL` Job 终态；只有 Runtime 整体失败、超时或无法产生最终回复时才进入现有失败类终态。

#### Scenario: 三个文件中一个冲突
- **WHEN** 两个提交成功且一个提交发生版本冲突，Runtime 随后产生完整最终回复
- **THEN** Job 状态为 `SUCCEEDED`
- **AND** 三个提交分别保留精确结果且成功版本不回滚

### Requirement: ONES查询结果必须使用Job临时只读文件
Runtime SHALL 为当前 Job 已冻结授权的 ONES GraphQL 集合结果生成 work 下只读 Markdown 数据文件，使用统一 JobSandbox 原子容量/文件数预留及完整性校验，不形成持久 File Version。文件名 MUST 由代码生成，Provider 与模型不得指定路径。无 File MCP 的 ONES 查询 Job 只派生 Read/Glob/Grep，不授予 Write/Edit、Bash、提交或跨 Job 访问。清理 MUST 覆盖成功、失败、取消、超时及异常退出恢复扫描，且不得因此删除独立审计记录。

#### Scenario: 无文件工具的查询Job
- **WHEN** Job 仅冻结 ONES 集合工具
- **THEN** 模型仍可读取该 Job 结果文件，但无法写入、提交或读取其他 Job 文件

#### Scenario: 物化失败
- **WHEN** 文件数、容量或完整性校验不通过
- **THEN** 返回安全错误并回滚临时文件及预留，不返回成功文件位置

#### Scenario: Job结束
- **WHEN** Job 成功、失败、取消或超时
- **THEN** 查询结果随沙盒清理，恢复扫描清理无运行归属的残留目录

**日志证据与生命周期**

### Requirement: Runtime 对已物化 LOG 提供单次有界证据扫描
Runtime SHALL提供代码发布且schema固定的`scan_log_evidence`本地工具，在一次调用中逐文件顺序扫描当前Job已经物化的1至40个唯一`inputs/*.log`。当前 scanner 版本为 log-evidence-v2。工具 MUST只接受安全POSIX相对路径；字面词原始数组最多32项、每项128字符、合计4096 UTF-8字节；上下文行数0–20（默认3），证据数1–500（默认200）。MUST拒绝File/Version ID、对象键、URL、输出路径、解析Profile、时间格式、字段映射、正则、代码、Shell或其它可执行表达式。每个输入 MUST重新验证为当前Sandbox已提交的普通只读LOG且不是符号链接；工具不得读取沙盒外路径、调用网络、连接MinIO或扩大当前Job文件权限。

扫描器 MUST以有界内存遍历每个输入的全部字节，计算逐文件和总体的实际大小、已扫描字节、逻辑行数和内容SHA-256。候选证据 SHALL仅来自代码固定且版本化的通用故障/级别标志、调用方提供的字面关键词以及保守多行上下文；任何时间、级别、用户、操作或业务语义无法可靠确定时 MUST标记为未知或省略，不得猜测日志格式。扫描器 MUST把精确扫描事实与启发式证据选择分开报告。

#### Scenario: 扫描多个异构LOG
- **WHEN** 当前Job已经物化20个格式不同且合计不超过Sandbox剩余预算的有效UTF-8 LOG，并在一次调用中选择这些路径
- **THEN** 扫描器顺序读取每个文件到EOF并返回逐文件和总体的精确扫描字节与逻辑行数
- **AND** 未识别的时间、级别或业务字段标记为未知，不因格式不同拒绝整批扫描

#### Scenario: 请求未物化或非LOG路径
- **WHEN** `relative_paths`包含不存在路径、`work/`路径、非LOG文件、符号链接、绝对路径、反斜杠或`..`
- **THEN** Runtime在读取任何目标正文或创建证据包前完整拒绝该调用
- **AND** 不自动物化文件、不扫描其它输入且不产生部分成功结果

#### Scenario: 模型提交任意解析表达式
- **WHEN** Tool输入包含正则、脚本、Profile、字段映射、时间格式或未知字段
- **THEN** Runtime按固定schema在执行扫描前拒绝
- **AND** 不把该值解释、编译或传给文件系统工具

#### Scenario: 输入存在超长无界记录
- **WHEN** 单行超过256 KiB或候选多行块超过1 MiB/1024行的代码固定内部缓冲上限
- **THEN** 扫描器以稳定错误终止并清理未完成证据包
- **AND** 不截断该记录后声称扫描完整

### Requirement: 日志扫描输入容错不得扩大沙盒权限与预算
`scan_log_evidence` SHALL 在原始词项数量、长度和总 UTF-8 字节预算内按 `casefold()` 去重，保留首次出现的词及顺序；声明与执行 MUST 一致接受合规重复词。工具说明 MUST 明确仅使用当前 Job 精确物化的 `inputs/` POSIX 相对 LOG 路径，路径校验 MUST NOT 自动补全裸文件名或放宽越界限制。

#### Scenario: 大小写与完全重复关键词
- **WHEN** 合规 `literal_terms` 同时包含 `ERROR`、`error`、`ERROR`、`WARN`、`warn`
- **THEN** 工具使用去重后的 `ERROR`、`WARN` 完成一次扫描，与显式去重请求得到一致规范化参数和证据结果

#### Scenario: 重复词不能绕过预算
- **WHEN** 原始数组超过 32 项或 4096 UTF-8 字节，即使去重后低于上限
- **THEN** 工具仍以输入错误拒绝，不扫描文件

#### Scenario: 非法路径提供纠正提示而不猜测
- **WHEN** 输入裸文件名、绝对路径、反斜杠路径、路径穿越或非 LOG 扩展名
- **THEN** 工具拒绝并返回稳定路径错误及固定中文提示，要求使用物化结果中的 `inputs/` 路径；不得自动选择另一个文件

#### Scenario: 错误提示不泄露输入
- **WHEN** 输入包含敏感路径、关键词或日志片段
- **THEN** 工具的安全错误提示仅包含固定规则及示例，不回显这些内容

### Requirement: 日志证据包有界、可定位且不会伪装完整语义审查
成功扫描 SHALL在当前Job的`work/`分区生成一个确定命名的UTF-8 Markdown证据包，文件名由scanner版本、已物化输入身份/内容hash和规范化参数的摘要产生，文件最大4MiB。证据包 MUST记录scanner版本、输入身份安全摘要、逐文件和总体覆盖、候选/保留/省略计数、限制标志；每条保留证据 MUST包含输入相对路径、起止行、起止字节、精确片段hash、命中类型和当前Job授权下的原文片段。原文 MUST使用确定性转义或无法被原文闭合的代码块封装并标为不可信数据，日志中的指令、Tool名、Markdown或HTML不得改变Runtime安全规则或触发Tool调用。证据包不得改变原LOG、成为其新File Version或自动进入File Commit/Delivery。

达到条目或4MiB证据上限时，扫描器 MUST继续扫描所有选中输入到EOF，并设置`evidence_limit_reached=true`与省略候选计数；不得把有界选择描述为全部日志已经被语义理解。Tool JSON响应 MUST只返回证据包相对路径、大小、SHA-256、覆盖计数、候选/保留/省略计数和限制标志，不得包含证据正文。

#### Scenario: 证据候选超过包上限
- **WHEN** 全量扫描发现的候选证据无法全部放入条目或4MiB上限
- **THEN** 扫描器继续读取所有输入到EOF并成功返回完整字节覆盖统计
- **AND** 证据包明确记录限制命中和省略数量，Tool响应不包含被省略正文

#### Scenario: 相同请求在同一Sandbox重复执行
- **WHEN** scanner版本、规范化参数和所有输入身份/内容hash与先前成功请求完全相同
- **THEN** Runtime验证既有证据包大小与SHA-256后复用同一路径和结果
- **AND** 不重复扫描、不创建第二个工作文件或重复占用Sandbox预算

#### Scenario: 相同路径内容事实不一致
- **WHEN** 重复请求发现已物化输入的实际大小或SHA-256与Sandbox提交身份不一致
- **THEN** Runtime以完整性错误失败并拒绝复用既有证据包
- **AND** 不返回旧覆盖事实或旧证据作为当前结果

#### Scenario: 用户要求保存最终报告
- **WHEN** Agent读取证据包后生成用户要求的Markdown报告
- **THEN** Agent另行写入受支持的`outputs/`或`work/`Markdown，并显式执行既有选择输出与Commit Intent流程
- **AND** 扫描器不自动提交证据包、报告或原LOG

#### Scenario: 原日志包含提示注入样式文本
- **WHEN** 证据片段包含“忽略系统指令”、Tool名、Markdown围栏、HTML或类似可执行指示
- **THEN** 证据包将其封装并标记为不可信原文数据
- **AND** Runtime不把该内容提升为指令、工具授权或文件操作

### Requirement: 日志扫描失败与取消必须完整清理
Runtime MUST在创建日志证据包前执行原子Sandbox预留，并让扫描服从当前attempt的取消信号与剩余墙钟预算。容量不足、读取失败、内容完整性失败、写入失败、取消或超时 MUST删除未完成证据包、释放文件与字节预留并返回稳定安全错误；只有全部输入扫描完成且证据包flush、UTF-8和SHA-256校验成功后才能返回成功与`coverage_complete=true`。

#### Scenario: 200MiB输入后剩余容量不足
- **WHEN** 已物化输入和现有工作文件使Sandbox无法同时预留一个证据包与现有输出安全余量
- **THEN** Runtime在扫描首个输入字节前完整拒绝并返回Sandbox容量错误
- **AND** 不创建空文件、部分证据包或新的持久化对象

#### Scenario: 扫描中收到取消
- **WHEN** Runtime在读取输入或写入证据包期间收到Job取消或墙钟耗尽信号
- **THEN** 扫描器合作式停止、删除未完成内容并释放预留
- **AND** 不返回`coverage_complete=true`或可供模型读取的部分路径

#### Scenario: 所有输入和证据包校验成功
- **WHEN** 扫描器已经读取全部选中输入到EOF且证据包通过大小、UTF-8和SHA-256校验
- **THEN** Runtime原子发布证据包路径并返回`coverage_complete=true`
- **AND** 后续Job成功、失败、取消或超时时证据包仍随Sandbox统一清理

### Requirement: 文件内容按来源和提升事件独立保留
消息附件 MUST 独立于任务工作区保存，canonical 默认保留 360 天并从原始创建时间起算。工作区到期 SHALL 清理 Temporary Working File、未保留版本、Conflict Candidate 和派生内容，但不得删除仍在保留期内的消息附件。用户明确保存或精确版本成功交付时，该版本成为 Retained File，并按当时平台或租户 File Content Retention Policy冻结独立到期时间，默认 360 天；重复查看、下载、保存或再交付 MUST NOT 重置期限。

#### Scenario: 工作区到期但附件仍在保留期
- **WHEN** 引用消息附件的工作区到期而附件尚未达到 360 天
- **THEN** 系统清理工作区临时内容但保留该消息附件

#### Scenario: 同一文件产生两个保留版本
- **WHEN** V2和V3分别首次成功交付
- **THEN** 两个精确版本各自按首次提升时间冻结独立到期时间

### Requirement: 内部内容清理后不得从旧外部引用恢复
Retained File 内部内容到期后，系统 MAY 保留 File ID、Version ID、安全来源摘要、Job、交付和删除审计，但 MUST NOT 继续返回二进制或提取文本。即使关联钉盘文件仍存在且用户仍有权限，平台 MUST NOT 通过旧引用自动重新导入或继续处理；用户必须重新发送或上传，并形成新的消息附件、文件和工作区上下文。时段召回命中此类版本时，清单 MUST 只提供元数据；物化 MUST 返回内容不可用，不得改写为「清单外无权」。
#### Scenario: 钉盘文件仍然存在
- **WHEN** 平台已清理内部内容而用户再次引用旧 File ID
- **THEN** File Service 返回内容不可用
- **AND** 提示用户重新发送文件而不读取旧钉盘引用
#### Scenario: 时段召回命中已清理正文
- **WHEN** 用户询问「上周的文件内容」，绑定版本身份仍在但对象字节已按保留策略删除
- **THEN** 系统可列出安全文件名等元数据，或在需要正文时发出内容已清理的固定说明
- **AND** 物化拒绝使用稳定「内容不可用」错误码，不得从旧钉盘引用恢复正文

### Requirement: 图片派生资产和布局输出受工作区配额与清理约束
picture asset、item staging、OCR Layout JSON、Docling JSON和布局增强Markdown的实际字节 MUST 计入相应布局OCR Profile固定的派生内容配额；picture occurrence和asset不得占任务工作区逻辑文件名额。新提取、OCR或终结会突破任一冻结上限时 MUST 在发布可见Representation前拒绝或按Profile定义的明确PARTIAL路径终结，不得留下错误可见性。工作区到期或source内容不可用后，图片asset和布局派生内容 MUST 按既有非终态依赖、保留与可重试清理规则处理。

#### Scenario: 一份PPTX包含多张内嵌图片
- **WHEN** File Service为同一PPTX创建多个picture occurrence与处理asset
- **THEN** 工作区逻辑文件计数仍只计算PPTX原件一次
- **AND** 所有asset、staging和最终表示字节计入派生内容配额

#### Scenario: 派生内容将超过配额
- **WHEN** 下一个picture asset或最终OCR Layout JSON会使run/workspace超过冻结字节上限
- **THEN** File Service不发布超限对象或错误Representation事实
- **AND** processing run记录稳定安全错误或Profile规定的明确PARTIAL状态

#### Scenario: 工作区到期但图片item未终态
- **WHEN** 工作区到期而关联layout OCR parent或picture item仍非终态
- **THEN** 清理暂缓到处理进入终态且不延长原工作区到期时间
- **AND** 终态后立即按source/representation生命周期执行清理

### Requirement: File MCP 调用审计与统一 MCP Operation Audit 对齐
每次File MCP Tool调用 MUST 记录统一operation、attempt和event链，包含Job、内部用户、Agent/Application Publication、Tool identifier/schema hash、Workspace、File/Version、授权判定、Commit或Delivery关联、状态、耗时及有界摘要。普通文件操作审计 MUST 排除文件正文、完整Prompt、Principal JWT、MinIO或钉钉凭据、对象键和上传授权材料。

#### Scenario: 文件提交发生版本冲突
- **WHEN** File Tool完成暂存但基础版本不再是当前版本
- **THEN** 审计关联同一operation和提交意图并记录安全冲突结果
- **AND** 不保存文件正文或Secret

## 实现依据与验证边界

实现依据：`backend/app/modules/job/application/file_context.py`、`create_agent_job_service.py`；`backend/app/modules/attachments/service.py`；`backend/app/modules/file_workspace/{manifest_service,workspace_service,authorization,quota,text_format_policy,streaming_service,delivery_service,lifecycle_service,repository}.py`；`backend/app/python_runtime/{file_mcp_bridge,file_transfer,job_sandbox,log_evidence_scanner,ones_result_bridge}.py`。

对应测试包括 `backend/tests/test_agent_job_file_admission.py`、`test_file_context_resolver.py`、`test_file_workspace_core.py`、`test_file_workspace_contracts.py`、`test_file_workspace_repository.py`、`test_task_workspace_retention.py`、`test_log_evidence_scanner.py` 和 `test_task_file_workspace_group_acceptance.py`。本次依据代码与测试定义修正规格，未运行真实文件服务、对象存储、SDK/CLI、渠道传输或群聊 E2E；代码存在、Mock 与规格校验均不能替代这些环境验收。

实现差异：工作区按 Session 查找当前 ACTIVE 实例。群文件 owner 边界不等于跨不同 Session 自动共享同一工作区；同群跨成员共享必须以实际 Session 与当前授权验证，不得仅据群标识宣称已实现。
