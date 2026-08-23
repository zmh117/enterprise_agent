## MODIFIED Requirements

### Requirement: Job 创建时冻结精确文件清单
File Service MUST 在非空文字触发 Agent Job 时，按当前用户、租户、任务工作区和授权范围冻结 Job File Manifest，其中每个文件指向当时的精确版本。自动物化集合 SHALL 仅包含本轮确定性绑定命中、且所需能力已经就绪的条目：直接可读文本指向当时精确 File Version；需要 `READABLE_CONTENT` 的文档还 MUST 冻结精确 Markdown Representation ID、kind、size、SHA-256 和安全物化名。同一消息新上传且被本轮绑定的附件、明确引用文件以及 Resolver 命中的工作区版本在就绪后自动物化；其他文件只提供不含正文、凭据和对象位置的元数据，可由 Agent 按需选择。系统 MUST NOT 把 Session 或工作区中全部未挂接 Job 的附件自动列入物化集合。清单冻结版本但不冻结授权，物化时 MUST 重新检查当前访问权。纯附件暂存事件 MUST NOT 单独生成 Manifest。工作区可以同时包含 READY、处理中和失败的不同精确版本；工作区本身 MUST NOT 处于统一的 PROCESSING 状态，也 MUST NOT 因此拒绝创建无该依赖的 Job。

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
- **WHEN** 用户要求处理最近一小时上传的工作区文件
- **THEN** Agent 使用 File Service 返回的 `observed_at` 作为边界，只选择 `source_received_at` 不早于该边界减一小时的文件
- **AND** 不把后续编辑产生的新版本误判为新上传文件

#### Scenario: Agent 生成文件没有上传时间
- **WHEN** 工作区文件由 Agent 生成且没有聊天附件来源
- **THEN** File Service 返回 `source_received_at=null` 和非空 `version_created_at`
- **AND** Agent 不把该文件归入“最近上传的附件”集合
