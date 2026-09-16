# task-file-workspace Specification

## Purpose
TBD - created by archiving change add-governed-task-file-workspaces. Update Purpose after archive.
## Requirements
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

### Requirement: 私聊与群聊工作区具有确定归属
私聊任务工作区 MUST 归当前内部用户私有。群聊任务工作区 SHALL 由同一受信企业、Connector 和外部群会话共享，但每次操作 MUST 使用当前消息实际发送人的内部身份重新校验业务应用访问和同群边界。File Service MUST NOT 复制或同步钉钉逐成员 ACL，也 MUST NOT 将群聊解释为共享内部身份或共享个人外部凭据。

#### Scenario: 同群成员继续编辑
- **WHEN** 同一受信群会话中的另一名已绑定内部用户发起新 Job 且拥有当前业务应用访问权
- **THEN** 该 Job 可以获得群工作区的授权文件清单并提交新版本

#### Scenario: 跨群文件 ID 被提交
- **WHEN** 当前 Job 提供另一个群、私聊、租户或会话的文件 ID
- **THEN** File Service 在读取内容或对象存储前拒绝

#### Scenario: 个人来源文件进入群工作区
- **WHEN** Agent 通过个人 ONES 或其他个人凭据取得文件并准备放入群工作区
- **THEN** 系统必须先取得来源用户明确确认并创建保留来源血缘的群共享副本
- **AND** 不共享个人凭据、不自动同步外部原件也不把群修改写回外部原件

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

### Requirement: 文件使用稳定身份和不可变版本
每个文件 MUST 具有稳定 File ID、一个或多个不可变 File Version 和至多一个当前版本指针。导入、生成、编辑和外部同步 MUST 创建新版本，不得原地改写历史对象。既有文件提交 MUST 提供 File ID 与基础版本 ID，且只有基础版本仍为当前版本时才能原子切换当前指针。

#### Scenario: 基础版本仍为当前版本
- **WHEN** Agent 基于 V3 提交内容且 V3 仍是当前版本
- **THEN** File Service 创建不可变 V4 并原子把当前版本指向 V4

#### Scenario: 基础版本已经变化
- **WHEN** Agent 基于 V3 提交内容但当前版本已是 V4
- **THEN** File Service 不覆盖 V4且返回版本冲突

### Requirement: 第一阶段文件类型和配额有界
任务工作区 SHALL 固定使用代码发布的 `text-v2` 直接文本规则：TXT和Markdown可读写，LOG只读；该规则不得由Business Application、Publication、Job或Runtime切换。文档处理关闭时只接受这些直接文本；启用`docling-layout-ocr-v2`时还接受PDF、DOCX、XLSX、PPTX、PNG、JPEG和WebP原件。文本文件和Agent可读Markdown单文件最大15MiB，文档源文件最大25MiB且PDF最多300页；每个工作区默认最多200个ACTIVE逻辑文件，平台硬上限1000个，默认计费容量2GiB且平台硬上限10GiB。新导入、处理或提交导致任一上限被突破时 MUST 在创建可见版本或表示前完整拒绝。系统 MUST 拒绝DOC、XLS、PPT、宏文件及其它未支持格式，且不得静默截断、猜测编码或降级到宽松解析器。
#### Scenario: 非UTF-8文本进入工作区
- **WHEN** TXT、LOG或Markdown内容是GBK、UTF-16或无效UTF-8
- **THEN** File Service使用安全错误拒绝
- **AND** 不猜测或自动转换编码
#### Scenario: 提交超过工作区临时配额
- **WHEN** 新版本或派生表示会使工作区计费临时内容超过冻结上限
- **THEN** File Service不创建对象可见性、文件版本、representation或错误的当前指针
#### Scenario: 受支持PDF到达
- **WHEN** 新任务工作区收到不超过25MiB和300页、MIME与结构合法的PDF且Publication冻结`docling-layout-ocr-v2`
- **THEN** File Service保存原件并异步生成布局Markdown和Docling JSON表示
- **AND** 原始PDF不直接进入Agent Sandbox
#### Scenario: 文档处理Profile未启用
- **WHEN** 工作区收到Office、PDF或图片但Publication的文档处理Profile为`NONE`
- **THEN** 系统返回明确未启用结果
- **AND** 不调用Docling或声称已解析
#### Scenario: UTF-8 LOG进入text-v2工作区
- **WHEN** `.log`内容为有效UTF-8、无NUL且不超过15 MiB，并命中冻结的`text-v2`
- **THEN** File Service保存不可变精确版本并标记format为`LOG`
- **AND** 允许的操作只包含读取和既有版本交付
#### Scenario: Markdown进入text-v2工作区
- **WHEN** `.md`内容为有效UTF-8且不超过15 MiB，并命中冻结的`text-v2`
- **THEN** File Service允许导入、读取、创建、编辑、提交和交付
- **AND** 内容始终作为不可信纯文本而不渲染HTML或抓取远程资源
#### Scenario: 未纳入策略的格式到达
- **WHEN** 新任务工作区链路收到`.markdown`、DOCX、XLSX、PPTX、PDF、图片或其它未注册格式
- **THEN** 系统返回明确不支持结果
- **AND** 不调用`docling-serve`、通用解析器或任意文件处理器
#### Scenario: 提交超过工作区字节配额
- **WHEN** 新版本、staging或派生表示会使工作区实际用量加有效预留超过当前tenant字节上限
- **THEN** File Service不创建对象可见性、文件版本、representation或错误的当前指针
#### Scenario: tenant没有配置覆盖
- **WHEN** tenant没有启用的工作区文件数量覆盖且兼容性预检已经通过
- **THEN** File Service使用默认200个 ACTIVE 逻辑文件的有效配额
- **AND** 不从Application Publication读取或推导另一个配额
#### Scenario: tenant尝试配置超过平台硬上限
- **WHEN** 管理员尝试把tenant工作区文件数量设置为1001或更大
- **THEN** 平台在保存配置前拒绝
- **AND** File Service的代码硬上限仍为1000
#### Scenario: tenant没有字节配额覆盖
- **WHEN** tenant没有启用的工作区字节覆盖
- **THEN** File Service使用默认2GiB计费内容上限
- **AND** 不从Application Publication读取或推导另一个容量
#### Scenario: tenant尝试配置超过字节硬上限
- **WHEN** 管理员尝试把tenant工作区字节配额设置为大于10GiB
- **THEN** 平台在保存配置前拒绝
- **AND** File Service消费端仍以10GiB代码硬上限失败关闭
#### Scenario: 降低配额后工作区暂时超限
- **WHEN** 工作区已有240个 ACTIVE 逻辑文件且tenant有效配额从300降低为200
- **THEN** 既有文件仍可按当前授权读取，但任何新增逻辑文件在创建对象可见性前被拒绝
- **AND** 新版本仅在不会继续增加其它已超限维度时才可终结
#### Scenario: 调用方尝试切换直接文本规则
- **WHEN** Revision、Publication、Job或Runtime请求携带`text-v1`、未知文本策略或文件策略选择字段
- **THEN** 系统在副作用前拒绝该字段
- **AND** 不建立运行时兼容或回退分支

### Requirement: Job 创建时冻结精确文件清单
File Service MUST 在非空文字触发Agent Job时，按当前用户、tenant、任务工作区、Business Application Publication和授权范围冻结schema v5 Job File Manifest。Manifest MUST 冻结`workspace_catalog_revision_id`、当前消息附件、明确引用和已选Job Working Set，而不得复制工作区全部目录；直接可读文本条目 MUST 指向当时精确File Version，需文档处理的条目 MUST 同时冻结原始File/Version ID与精确Markdown Representation ID、kind、size、SHA-256和安全物化名。该文字Job本轮确定性绑定且能力已就绪的附件、同一消息新上传附件和明确引用文件 SHALL 进入Working Set并自动物化；其他文件只通过冻结Catalog Revision分页提供不含正文、凭据和对象位置的元数据，由Agent精确选择。自动物化与按需物化累计最多40个不同输入版本，超出时 MUST 完整拒绝新增选择。清单冻结身份但不冻结授权，物化时 MUST 重新检查当前访问权。纯附件暂存事件 MUST NOT单独生成Manifest。

Job File Manifest、File MCP文件列表/元数据和Runtime自动物化元数据 MUST 明确区分：原始聊天附件进入平台的`source_received_at`、精确原始版本产生的`version_created_at`、representation产生时间以及Manifest冻结或查询发生的`observed_at`。`source_received_at` MUST 取平台创建原始`message_attachment`记录的时间并在后续版本/表示中保持不变；无聊天附件来源的Agent生成文件 MUST 返回`null`。持久化、Manifest hash、File MCP列表/元数据、Runtime Manifest和自动物化元数据中的非空机器时间 MUST 使用表示同一瞬时的UTC RFC 3339；面向用户陈述时才按用户显示时区转换，不得把`Z`或`+00:00`墙钟直接解释为本地时间。系统 MUST NOT使用File Worker导入完成时间、processing run时间、representation时间、工作区引用时间、Manifest条目时间或含义模糊的`created_at`回答“上传时间”。Manifest schema v5 MUST 把Catalog Revision、Working Set、源身份、表示身份、来源接收时间和版本创建时间纳入不可变payload及其hash；系统不得生成、读取、投影或恢复schema v1-v4。
#### Scenario: 暂存文本附件已经完成导入
- **WHEN** 后续非空文字创建Job前，暂存文本附件已经形成可用精确版本
- **THEN** 创建事务认领附件并立即把该版本加入Working Set并冻结为自动物化项
#### Scenario: 暂存文档仍在处理
- **WHEN** 后续非空文字未绑定该文档
- **THEN** 系统立即创建可执行Job且不自动物化处理中文档
- **AND** 该文档继续作为冻结Catalog Revision中的元数据候选
#### Scenario: 其他Job在执行期间产生新表示
- **WHEN** 当前Job清单冻结source V3和representation R1后，同一source Version产生R2或文件产生V4
- **THEN** 当前Job继续物化R1并继续把V3用于原件身份
- **AND** R2或V4只进入后续Catalog Revision和Job清单
#### Scenario: 冻结后用户权限被撤销
- **WHEN** 文件和representation仍在Job File Manifest中但当前用户或应用访问已失效
- **THEN** File Service拒绝物化或交付
- **AND** 不把冻结清单解释为长期访问授权
#### Scenario: 查询最近一小时上传的文件
- **WHEN** 用户要求处理最近一小时上传的工作区文件
- **THEN** Agent使用File Service返回的`observed_at`作为边界，只选择`source_received_at`不早于该边界减一小时的文件
- **AND** 不把后续编辑版本或新representation误判为新上传文件
#### Scenario: Agent生成文件没有上传时间
- **WHEN** 工作区文件由Agent生成且没有聊天附件来源
- **THEN** File Service返回`source_received_at=null`和非空`version_created_at`
- **AND** Agent不把该文件归入“最近上传的附件”集合
#### Scenario: Manifest尝试替换Representation
- **WHEN** 模型或Runtime尝试以Manifest外的representation ID替换冻结表示
- **THEN** File Service在读取内容前拒绝
#### Scenario: 暂存附件已经完成导入且本轮绑定
- **WHEN** 后续非空文字本轮绑定了已形成可用精确版本且所需能力已就绪的暂存附件
- **THEN** 创建事务只认领被绑定附件并把该版本冻结为自动物化项
#### Scenario: 暂存附件仍在导入且本轮绑定
- **WHEN** 本轮绑定附件的来源导入尚未进入安全终态
- **THEN** 系统可保持该 Job 等待来源终态
- **AND** 来源终态后重新执行能力门禁；表示未就绪且需要 `READABLE_CONTENT` 时不得完成自动物化并释放到 Agent 队列
#### Scenario: 暂存文档正在生成表示但本轮未绑定
- **WHEN** 工作区有文档可读性仍为 `PENDING`，用户发送无文件依赖的非空文字
- **THEN** 系统立即冻结不含该文档自动物化项的 Manifest 并创建可执行 Job
- **AND** 该文档仍可作为元数据候选，不得因此让 Job 等待
#### Scenario: 其他 Job 在执行期间提交新版本
- **WHEN** 当前 Job 的清单冻结 V3 后另一个 Job 提交 V4
- **THEN** 当前 Job 继续物化和处理 V3
- **AND** V4 只进入后续新 Job 的清单
#### Scenario: Agent 可见文件时间使用东八区
- **WHEN** File MCP、Runtime Manifest 或自动物化元数据返回 `source_received_at`、`version_created_at`、`representation_created_at` 或 `observed_at`
- **THEN** 非空值是 Asia/Shanghai RFC 3339（`+08:00`）
- **AND** 与存储瞬时表示同一时刻，且不改写 Manifest hash
#### Scenario: 时段召回的历史版本进入本 Job 清单
- **WHEN** 本轮时段硬证据绑定了一份未挂接当前活动工作区、仍在保留期的附件精确版本，且所需能力已就绪且窗口内唯一
- **THEN** File Service 把该版本冻结进本 Job Manifest，需要阅读时可以自动物化
- **AND** 该条目不得授予 `EDIT` 或 `COMMIT`
#### Scenario: 时段召回多份只冻结元数据
- **WHEN** 本轮时段硬证据命中多份文件且所需能力为 `METADATA`
- **THEN** Manifest 包含这些精确版本且 `auto_materialize=false`
- **AND** 不把 Session 中窗口外的附件一并写入清单
#### Scenario: 工作区包含1000个ACTIVE文件
- **WHEN** 新Job只有2个当前附件且冻结一个包含1000个成员的目录revision
- **THEN** Manifest只冻结目录revision ID和这2个精确输入，不复制其它998个目录条目
- **AND** Runtime只预检并自动物化这2个输入
#### Scenario: 本轮计划输入超过40项
- **WHEN** 同一文字请求确定性绑定41个不同File/Version
- **THEN** 系统发出固定缩小范围说明且不创建Agent Job
- **AND** 不删除、隐藏或静默丢弃已经进入工作区的文件
#### Scenario: 计划Markdown超过Sandbox容量
- **WHEN** 计划自动物化的40个合规Markdown实际大小合计超过224MiB
- **THEN** Job创建前完整拒绝并要求缩小工作集
- **AND** 不创建只物化部分输入的Job或Sandbox
#### Scenario: 无附件文字Job
- **WHEN** 普通文字消息创建不包含文件的Agent Job
- **THEN** 系统仍创建合法schema v5空文件上下文且Working Set为空
- **AND** 不投影成旧Manifest或因文件上下文为空拒绝模型执行
#### Scenario: 旧Manifest进入当前服务
- **WHEN** 数据库或Runtime请求出现schema v1、v2、v3或v4 Manifest
- **THEN** 当前服务以稳定合同错误失败关闭
- **AND** 不读取旧payload、不计算旧hash且不执行模型

### Requirement: 每个 Agent Job 使用隔离临时沙盒
Runtime MUST为每个Agent Job创建独立Job Sandbox，并只把当前Job工作集已授权的精确文本File Version或精确Markdown Representation物化到该目录。Sandbox MUST固定总文件上限64和总容量224MiB，并分别限制`inputs`最多40个文件、`work/outputs`合计最多16个文件、`tmp`及内部安全余量最多8个文件；目录、marker和不可见控制元数据不得被模型用来规避普通文件计数。PDF、Office、图片原始二进制、Docling JSON和OCR Layout JSON MUST NOT进入Agent Sandbox。

自动物化、File MCP按需物化、Runtime Write/Edit和内部临时文件 MUST共享同一Sandbox预算与原子预留器。Runtime在写入第一个自动物化字节前 MUST对整批输入重新预留实际文件数与Manifest冻结大小；按需物化和写入 MUST在创建目标文件前预留对应分区名额和剩余容量。失败或完整性校验不通过 MUST删除不完整文件并释放预留。重复物化同一`file_id + version_id` MUST复用已有输入和handle，不重复占用文件数或字节。Claude Code Agent只可在该沙盒内使用`Read`、`Grep`、`Glob`、`Write`和`Edit`，且写/编辑动作仍受代码固定`text-v2`格式矩阵限制；Bash、Web、NotebookEdit、沙盒外路径、符号链接逃逸和其它开放执行能力 MUST保持不可用。Job成功、失败、取消或超时后 MUST清理沙盒，Runtime异常退出后 MUST由恢复扫描清理无RUNNING Job归属的残留目录。
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
File Service MUST NOT对可写`.txt/.md`或后续Office类型自动合并，也不得覆盖当前版本。已上传但因并发产生冲突的结果只能成为按工作区生命周期管理的Conflict Candidate，不得成为当前版本或Retained File。用户继续处理时，后续新Job SHALL同时物化最新版本和冲突候选，由Claude Code根据用户指令生成合并结果，并以最新版本为基础重新显式提交。只读`.log`不得产生编辑冲突候选。
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

### Requirement: 文件内容按来源和提升事件独立保留
消息附件 MUST 独立于任务工作区保存，canonical 默认保留 360 天并从原始创建时间起算。工作区到期 SHALL 清理 Temporary Working File、未保留版本、Conflict Candidate 和派生内容，但不得删除仍在保留期内的消息附件。用户明确保存或精确版本成功交付时，该版本成为 Retained File，并按当时平台或租户 File Content Retention Policy冻结独立到期时间，第一阶段默认 360 天；重复查看、下载、保存或再交付 MUST NOT 重置期限。

#### Scenario: 工作区到期但附件仍在保留期
- **WHEN** 引用消息附件的工作区到期而附件尚未达到 360 天
- **THEN** 系统清理工作区临时内容但保留该消息附件

#### Scenario: 同一文件产生两个保留版本
- **WHEN** V2和V3分别首次成功交付
- **THEN** 两个精确版本各自按首次提升时间冻结独立到期时间

#### Scenario: 历史附件补齐到期时间
- **WHEN** 迁移发现旧附件缺少到期事实
- **THEN** 系统按原始创建时间加有效策略回填
- **AND** 不在 schema migration 事务中直接删除已到期对象

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

### Requirement: 文件提交结果与 Agent Job 终态分离
同一 Job 的每个 File Commit Intent MUST 独立记录成功、版本冲突或其它拒绝，部分失败不得回滚已成功版本。只要 Runtime 正常完成、持久化最终回复并准确说明各文件结果，Agent Job SHALL 保持 `SUCCEEDED`，系统 MUST NOT 为此新增 `PARTIAL` Job 终态；只有 Runtime 整体失败、超时或无法产生最终回复时才进入现有失败类终态。

#### Scenario: 三个文件中一个冲突
- **WHEN** 两个提交成功且一个提交发生版本冲突，Runtime 随后产生完整最终回复
- **THEN** Job 状态为 `SUCCEEDED`
- **AND** 三个提交分别保留精确结果且成功版本不回滚

### Requirement: 原始文件与Agent可读表示使用不同身份和动作
File Service MUST 把PDF、DOCX、PPTX、XLSX、PNG、JPEG和WebP作为受治理原始File Version保存，并把Docling Markdown与Docling JSON作为关联该精确版本的不可变Representation保存。原始文档动作 SHALL 限于`READ_METADATA`、`RETAIN`和`DELIVER`；Markdown representation只允许受控`MATERIALIZE`，Docling JSON第一阶段不得向Agent物化。系统不得把representation提升为原文件版本、允许原始二进制进入沙盒，或允许Agent直接编辑/提交Office、PDF和图片版本。
#### Scenario: Agent总结PDF
- **WHEN** Job Manifest冻结一个PDF source Version及其Markdown representation
- **THEN** Runtime物化Markdown而不物化PDF二进制
- **AND** Agent使用Read、Grep或Glob按需读取Markdown
#### Scenario: 用户要求转发原始PDF
- **WHEN** 用户要求交付Manifest中具有DELIVER动作的原始PDF版本
- **THEN** Delivery通过File Service读取精确source Version并发送原件
- **AND** 不发送Markdown representation
#### Scenario: 用户要求直接修改DOCX
- **WHEN** 用户要求保留原版式直接修改DOCX
- **THEN** 系统说明第一阶段只支持读取派生文字和生成新的受支持文本文件
- **AND** 不把Markdown修改伪装成DOCX新版本

### Requirement: 本 Job 可只读召回未挂接当前工作区的保留版本
当本轮确定性绑定命中「不在当前 `ACTIVE` 工作区 `task_workspace_file` 上、但仍在聊天附件保留期内」的精确版本时，File Service MUST 允许将该版本冻结进 **当前 Agent Job File Manifest**。该召回 MUST NOT 把已 `EXPIRED` / `CLEANED` 的工作区改回 `ACTIVE`，MUST NOT 把历史文件重新 `link` 为当前工作区活动文件，也 MUST NOT 把 360 天附件库暴露为模型可浏览的目录。

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

<!-- Integrated from archived change: `2026-08-23-stabilize-governed-file-context/specs/task-file-workspace` -->

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

<!-- Integrated from archived change: `2026-08-23-stabilize-governed-file-context/specs/task-file-workspace` -->

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

<!-- Integrated from archived change: `2026-08-23-stabilize-governed-file-context/specs/task-file-workspace` -->

### Requirement: 文件发现候选不得等同于正文绑定
系统 MUST 只对当前消息附件、显式 File/Version ID、引用消息以及消息中出现的完整文件名建立执行前文件能力依赖。时间窗口匹配 MUST 只返回最多 20 个不含正文、凭据和对象位置的 `METADATA` 候选，即使窗口内只有一个文件也不得由 Runtime 预物化正文。部分或近似文件名 MUST NOT 直接形成正文依赖；Agent 选择候选后 MUST 使用精确 File/Version ID 进入受治理物化流程。

#### Scenario: 时间窗口只有一个正文候选
- **WHEN** 用户请求读取上周文件内容且窗口内只有一个仍可访问文件
- **THEN** Job 文件上下文只携带该文件的 `METADATA + TIME_WINDOW` 候选
- **AND** Runtime 不在模型判断前自动物化正文

#### Scenario: 时间窗口候选超过上限
- **WHEN** 合法时间窗口内有超过 20 个仍可访问文件
- **THEN** 系统返回缩小范围的安全通知
- **AND** 不创建携带超限候选或正文的 Agent Job

#### Scenario: 消息只出现部分文件名
- **WHEN** 工作区存在 `production-diagnosis.docx` 而用户只写“diagnosis 文件”
- **THEN** 系统不得把该部分匹配直接绑定为正文依赖
- **AND** Agent 只能从有界元数据中选择精确 File/Version ID

<!-- Integrated from archived change: `2026-08-23-stabilize-governed-file-context/specs/task-file-workspace` -->

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

<!-- Integrated from archived change: `2026-08-23-scale-task-workspace-with-bounded-job-working-sets/specs/task-file-workspace` -->

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

<!-- Integrated from archived change: `2026-08-23-scale-task-workspace-with-bounded-job-working-sets/specs/task-file-workspace` -->

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

<!-- Integrated from archived change: `2026-08-23-add-governed-office-embedded-image-layout-ocr/specs/task-file-workspace` -->

### Requirement: 布局OCR派生表示与原件保持不同身份
File Service MUST 把`docling-layout-ocr-v2`产生的`MARKDOWN`、`DOCLING_JSON`和`OCR_LAYOUT_JSON`保存为绑定同一精确source Version与processing run的不同不可变Representation；每个run必须严格使用其冻结Profile对应的Schema。只有最终Markdown SHALL 具有受控`MATERIALIZE`动作；Docling JSON、OCR Layout JSON、picture asset和Office原件不得进入Agent Sandbox、成为File Version、改变current version、获得编辑/提交动作或作为原件交付。

#### Scenario: Job使用布局增强Markdown
- **WHEN** Job Manifest冻结Office source Version及布局Profile的最终Markdown Representation
- **THEN** Runtime物化Markdown并保留原件File/Version身份用于授权、保留和Delivery
- **AND** 不物化另外两种JSON或图片asset

#### Scenario: 用户要求转发原始PPTX
- **WHEN** 用户要求交付具有DELIVER动作的精确PPTX source Version
- **THEN** Delivery通过File Service发送PPTX原件
- **AND** 不发送布局Markdown、OCR Layout JSON或内嵌图片asset

<!-- Integrated from archived change: `2026-08-23-add-governed-office-embedded-image-layout-ocr/specs/task-file-workspace` -->

### Requirement: Job Manifest继续只冻结Agent可读Markdown
需布局OCR的Manifest条目 MUST 冻结原始File/Version ID及最终Markdown Representation ID、kind、size、SHA-256和安全物化名；MUST NOT包含OCR正文、坐标、picture asset ID、对象键、Base64、Docling JSON或OCR Layout JSON。Manifest冻结身份但不冻结授权，物化时 MUST 重新复核source与Representation访问权。布局Profile不得要求Runtime协议新增图片或JSON content类型。

#### Scenario: 本轮布局OCR已经可用
- **WHEN** 本轮Office附件的布局Profile run已`SUCCEEDED`或具有合规Markdown的`PARTIAL`
- **THEN** Manifest冻结精确最终Markdown并按既有规则自动或按需物化
- **AND** 同一run的其它Representation只保留为不可物化事实

#### Scenario: 模型替换Markdown表示
- **WHEN** 模型或Runtime尝试用同run的OCR Layout JSON、Docling JSON或另一run的Markdown替换Manifest冻结表示
- **THEN** File Service在返回内容前拒绝
- **AND** 不因Profile或source相同而放宽精确Representation绑定

<!-- Integrated from archived change: `2026-08-23-add-governed-office-embedded-image-layout-ocr/specs/task-file-workspace` -->

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

<!-- Integrated from archived change: `2026-08-23-converge-single-current-file-rule/specs/task-file-workspace` -->

### Requirement: 入站附件只通过任务工作区形成Agent可读内容
所有消息附件 MUST 先由File Service形成受管原件和不可变版本。TXT、LOG和Markdown只按固定`text-v2`规则形成直接可读内容；Office、PDF和图片只在Publication启用`docling-layout-ocr-v2`时形成受治理Representation。Channel、API和Agent上下文构建器不得进程内提取DOCX、XLSX、PPTX或Markdown正文，也不得从独立附件正文缓存向模型注入内容。

#### Scenario: DOCX附件到达
- **WHEN** 用户发送合法DOCX且应用启用`docling-layout-ocr-v2`
- **THEN** 附件经File Service、processing队列和固定Docling Profile形成Markdown Representation
- **AND** Channel/API进程不使用Office库直接提取正文

#### Scenario: 旧附件正文缓存仍存在
- **WHEN** 部署前预检发现`attachment_content`或等价旧提取正文事实
- **THEN** 破坏性开放测试重置必须删除这些事实后才允许当前migration完成
- **AND** 当前运行代码不读取或回填该缓存
