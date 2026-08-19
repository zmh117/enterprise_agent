## ADDED Requirements

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

## MODIFIED Requirements

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

### Requirement: Job 创建时冻结精确文件清单
File Service MUST 在非空文字触发 Agent Job 时，按当前用户、租户、任务工作区和授权范围冻结 Job File Manifest，其中每个文件指向当时的精确版本。自动物化集合 SHALL 仅包含本轮确定性绑定命中、且所需能力已经就绪的条目：直接可读文本指向当时精确 File Version；需要 `READABLE_CONTENT` 的文档还 MUST 冻结精确 Markdown Representation ID、kind、size、SHA-256 和安全物化名。同一消息新上传且被本轮绑定的附件、明确引用文件、Resolver 命中的当前工作区版本，以及时段硬证据命中且唯一、能力已就绪的保留版本，在就绪后自动物化；其他文件只提供不含正文、凭据和对象位置的元数据，可由 Agent 按需选择。系统 MUST NOT 把 Session 或工作区中全部未挂接 Job 的附件自动列入物化集合，也 MUST NOT 把 360 天附件库中未被本轮绑定的文件写入清单。清单冻结版本但不冻结授权，物化时 MUST 重新检查当前访问权。纯附件暂存事件 MUST NOT 单独生成 Manifest。工作区可以同时包含 READY、处理中和失败的不同精确版本；工作区本身 MUST NOT 处于统一的 PROCESSING 状态，也 MUST NOT 因此拒绝创建无该依赖的 Job。

时段硬证据命中的保留版本即使当前 `task_workspace_file` 不是 `ACTIVE`，只要仍在聊天附件保留期内且归属边界一致，MUST 允许写入本 Job Manifest。这些历史项默认 `auto_materialize=false`，且 MUST NOT 获得 `EDIT` 或 `COMMIT`。

Job File Manifest、File MCP 文件列表/元数据和 Runtime 自动物化元数据 MUST 明确区分：原始聊天附件进入平台的 `source_received_at`、精确版本产生的 `version_created_at` 以及 Manifest 冻结或查询发生的 `observed_at`。`source_received_at` MUST 取平台创建原始 `message_attachment` 记录的时间，并在后续版本中保持不变；无聊天附件来源的 Agent 生成文件 MUST 返回 `null`。持久化与 Manifest hash 仍使用同一瞬时；面向 Agent 的 File MCP 列表/元数据、Runtime Manifest 和自动物化元数据中的非空时间 MUST 投影为 Asia/Shanghai RFC 3339（偏移固定 `+08:00`），MUST NOT 把 UTC 墙钟（`Z` 或 `+00:00`）当作北京时间对用户陈述。系统 MUST NOT 使用 File Worker 导入完成时间、版本创建时间、工作区加入时间、Manifest 条目创建时间或含义模糊的 `created_at` 回答“上传时间”。新的 Manifest schema MUST 把来源接收时间和版本创建时间冻结进不可变条目及其 hash；旧 schema 可兼容读取但不得虚构缺失时间。

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

#### Scenario: 冻结后用户权限被撤销
- **WHEN** 文件仍在 Job File Manifest 中但当前用户或应用访问已失效
- **THEN** File Service 拒绝物化
- **AND** 不把冻结清单解释为长期访问授权

#### Scenario: 查询最近一小时上传的文件
- **WHEN** 用户要求处理最近一小时上传的、已出现在本 Job 快照中的工作区文件
- **THEN** Agent 使用 File Service 返回的 `observed_at` 作为边界，只选择 `source_received_at` 不早于该边界减一小时的文件
- **AND** 不把后续编辑产生的新版本误判为新上传文件
- **AND** 「最近一小时」本身 MUST NOT 把快照外的 360 天附件库拉进本 Job

#### Scenario: Agent 生成文件没有上传时间
- **WHEN** 工作区文件由 Agent 生成且没有聊天附件来源
- **THEN** File Service 返回 `source_received_at=null` 和非空 `version_created_at`
- **AND** Agent 不把该文件归入“最近上传的附件”集合

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
