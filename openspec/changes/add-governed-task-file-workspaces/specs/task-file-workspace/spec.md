## ADDED Requirements

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

#### Scenario: 普通文字连续问答
- **WHEN** Session 没有活动任务工作区且用户只提出普通文字问题
- **THEN** 系统创建 Agent Job 但不创建任务工作区

#### Scenario: Agent 怀疑用户开始新任务
- **WHEN** Session 已有活动工作区且新请求可能属于另一任务但用户没有明确说明
- **THEN** Agent 必须先询问是否切换
- **AND** 系统不得静默复用或关闭任一工作区

#### Scenario: 过期工作区后的新文件请求
- **WHEN** 先前工作区已经关闭或过期且用户再次请求处理文件
- **THEN** 系统创建新任务工作区
- **AND** 不自动恢复旧工作区或旧文件内容

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
新的任务工作区链路第一阶段 MUST 只接受 UTF-8 `.txt`，允许输入包含 UTF-8 BOM但 Agent 输出 MUST 为无 BOM UTF-8。单文件最大 15 MiB，每个工作区最多 20 个逻辑文件，尚未成为保留文件的工作版本和冲突候选合计最多 100 MiB。新提交导致任一上限被突破时 MUST 在创建正式版本前完整拒绝。既有聊天附件兼容能力不因该范围被删除；第一阶段 MUST NOT 部署或调用 `docling-serve`。

#### Scenario: 非 UTF-8 TXT 进入工作区
- **WHEN** `.txt` 内容是 GBK、UTF-16 或无效 UTF-8
- **THEN** File Service 使用安全错误拒绝
- **AND** 不猜测或自动转换编码

#### Scenario: 提交超过工作区临时配额
- **WHEN** 新版本会使工作区计费临时内容超过 100 MiB
- **THEN** File Service 不创建对象可见性、文件版本或错误的当前指针

#### Scenario: 下一阶段文档类型到达
- **WHEN** 新任务工作区链路收到 DOCX、XLSX、PPTX、PDF、Markdown 或图片 OCR处理请求
- **THEN** 第一阶段返回明确不支持结果
- **AND** 不调用 `docling-serve` 或声称已解析

### Requirement: Job 创建时冻结精确文件清单
File Service MUST 在非空文字触发 Agent Job 时，按当前用户、租户、任务工作区和授权范围冻结 Job File Manifest，其中每个文件指向当时的精确版本。该文字 Job 原子认领的未消费附件、同一消息新上传附件和明确引用文件 SHALL 自动物化；其他文件只提供不含正文、凭据和对象位置的元数据，由 Agent 按需选择。清单冻结版本但不冻结授权，物化时 MUST 重新检查当前访问权。纯附件暂存事件 MUST NOT 单独生成 Manifest。

Job File Manifest、File MCP 文件列表/元数据和 Runtime 自动物化元数据 MUST 明确区分：原始聊天附件进入平台的 `source_received_at`、精确版本产生的 `version_created_at` 以及 Manifest 冻结或查询发生的 `observed_at`。`source_received_at` MUST 取平台创建原始 `message_attachment` 记录的时间，并在后续版本中保持不变；无聊天附件来源的 Agent 生成文件 MUST 返回 `null`。所有非空时间 MUST 是带时区的 UTC RFC 3339。系统 MUST NOT 使用 File Worker 导入完成时间、版本创建时间、工作区加入时间、Manifest 条目创建时间或含义模糊的 `created_at` 回答“上传时间”。新的 Manifest schema MUST 把来源接收时间和版本创建时间冻结进不可变条目及其 hash；旧 schema 可兼容读取但不得虚构缺失时间。

#### Scenario: 暂存附件已经完成导入
- **WHEN** 后续非空文字创建 Job前，暂存附件已经形成可用精确版本
- **THEN** 创建事务认领附件并立即把该版本冻结为自动物化项

#### Scenario: 暂存附件仍在导入
- **WHEN** 后续非空文字创建 Job时，认领附件尚未全部进入安全终态
- **THEN** 系统先冻结工作区与待处理集合并保持 Job等待
- **AND** 全部终态后才完成不可变 Manifest并释放同一个 Job

#### Scenario: 其他 Job 在执行期间提交新版本
- **WHEN** 当前 Job 的清单冻结 V3 后另一个 Job 提交 V4
- **THEN** 当前 Job 继续物化和处理 V3
- **AND** V4 只进入后续新 Job 的清单

#### Scenario: 冻结后用户权限被撤销
- **WHEN** 文件仍在 Job File Manifest 中但当前用户或应用访问已失效
- **THEN** File Service 拒绝物化
- **AND** 不把冻结清单解释为长期访问授权

#### Scenario: 查询最近一小时上传的文件
- **WHEN** 用户要求处理最近一小时上传的工作区文件
- **THEN** Agent 使用 File Service 返回的 `observed_at` 作为边界，只选择 `source_received_at` 不早于该边界减一小时的文件
- **AND** 不把后续编辑产生的新版本误判为新上传文件

#### Scenario: Agent 生成文件没有上传时间
- **WHEN** 工作区文件由 Agent 生成且没有聊天附件来源
- **THEN** File Service 返回 `source_received_at=null` 和非空 `version_created_at`
- **AND** Agent 不把该文件归入“最近上传的附件”集合

### Requirement: 每个 Agent Job 使用隔离临时沙盒
Runtime MUST 为每个 Agent Job 创建独立 Job Sandbox，并只把当前 Job 已授权的精确版本物化到该目录。Claude Code Agent 只可在该沙盒内使用 `Read`、`Grep`、`Write` 和 `Edit`；Bash、Web、NotebookEdit、沙盒外路径、符号链接逃逸和其它开放执行能力 MUST 保持不可用。Job 成功、失败、取消或超时后 MUST 清理沙盒，Runtime 异常退出后 MUST 由恢复扫描清理无运行中 Job 归属的残留目录。

#### Scenario: Agent 在沙盒内编辑 TXT
- **WHEN** Job 获得受控本地文件并调用 `Edit`
- **THEN** Runtime 只允许规范化后仍位于该 Job 沙盒的目标路径
- **AND** 本地修改不直接改变 MinIO 或文件版本

#### Scenario: Agent 尝试写沙盒外路径
- **WHEN** `Write` 或 `Edit` 目标通过绝对路径、`..`、符号链接或其它方式离开 Job 沙盒
- **THEN** Runtime 在文件系统副作用前拒绝并记录安全工具结果

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
File Service MUST 在流式接收时计算内容哈希并执行类型、15 MiB 大小和 UTF-8校验，在终结前重新校验 Job、工作区、文件归属、基础版本和配额。暂存对象只有在对象完整且文件版本元数据事务成功后才能成为可见文件版本；失败或超时暂存不得进入文件列表或当前指针，并 MUST 由 `file-worker` 可重试清理。

#### Scenario: 对象接收完成但数据库事务失败
- **WHEN** 暂存对象完整写入后文件版本事务回滚
- **THEN** 对象保持不可见待清理状态
- **AND** 文件列表和当前版本不发生变化

#### Scenario: 暂存对象清理暂时失败
- **WHEN** MinIO 删除发生瞬时错误
- **THEN** File Service 保留待清理事实并由 `file-worker` 重试
- **AND** 不错误标记为已删除

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
File Service MUST NOT 对 `.txt` 或后续 Office 类型自动合并，也不得覆盖当前版本。已上传但因并发产生冲突的结果只能成为按工作区生命周期管理的 Conflict Candidate，不得成为当前版本或 Retained File。用户继续处理时，后续新 Job SHALL 同时物化最新版本和冲突候选，由 Claude Code 根据用户指令生成合并结果，并以最新版本为基础重新显式提交。

#### Scenario: 群成员并发编辑 TXT
- **WHEN** 两个 Job 都基于 V3且第一个已提交 V4
- **THEN** 第二个结果成为冲突候选而不覆盖 V4
- **AND** File Service 不自动执行文本合并

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
Retained File 内部内容到期后，系统 MAY 保留 File ID、Version ID、安全来源摘要、Job、交付和删除审计，但 MUST NOT 继续返回二进制或提取文本。即使关联钉盘文件仍存在且用户仍有权限，平台 MUST NOT 通过旧引用自动重新导入或继续处理；用户必须重新发送或上传，并形成新的消息附件、文件和工作区上下文。

#### Scenario: 钉盘文件仍然存在
- **WHEN** 平台已清理内部内容而用户再次引用旧 File ID
- **THEN** File Service 返回内容不可用
- **AND** 提示用户重新发送文件而不读取旧钉盘引用

### Requirement: 文件提交结果与 Agent Job 终态分离
同一 Job 的每个 File Commit Intent MUST 独立记录成功、版本冲突或其它拒绝，部分失败不得回滚已成功版本。只要 Runtime 正常完成、持久化最终回复并准确说明各文件结果，Agent Job SHALL 保持 `SUCCEEDED`，系统 MUST NOT 为此新增 `PARTIAL` Job 终态；只有 Runtime 整体失败、超时或无法产生最终回复时才进入现有失败类终态。

#### Scenario: 三个文件中一个冲突
- **WHEN** 两个提交成功且一个提交发生版本冲突，Runtime 随后产生完整最终回复
- **THEN** Job 状态为 `SUCCEEDED`
- **AND** 三个提交分别保留精确结果且成功版本不回滚
