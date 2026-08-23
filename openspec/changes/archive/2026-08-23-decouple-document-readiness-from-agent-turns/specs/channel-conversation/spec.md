## ADDED Requirements

### Requirement: 每条文字消息按确定性证据绑定文件依赖
系统 MUST 在创建 Agent Job 或给出本轮系统说明之前，为当前非空文字解析本轮依赖的精确 `file_version` 以及所需能力。绑定 MUST 只使用下列硬证据，且按此优先顺序命中即停：当前消息自身附件；钉钉引用/回复目标消息上已持久化的附件；当前任务工作区内规范化后全等（含扩展名）且唯一的 `display_name`；代码注册的近指代词且工作区内最近一次来源导入成功的文件版本唯一。系统 MUST NOT 使用隐式意图分类器、语义相似度或「刚上传过文件」本身作为绑定证据。无硬证据时本轮文件依赖集合 MUST 为空。近指代或多个同名命中无法得到唯一版本时，系统 MUST 发出固定澄清说明且 MUST NOT 创建 Agent Job、MUST NOT 猜测绑定。

本轮所需能力 MUST 属于 `METADATA`、`ORIGINAL` 或 `READABLE_CONTENT`。当前消息带附件且同时有非空问题时默认 `READABLE_CONTENT`，除非文字命中代码注册的元数据或原件模式。问文件名、大小、格式或上传时间只要求 `METADATA`；要求转发或下载原件只要求 `ORIGINAL`；总结、抽取、统计或询问正文要求 `READABLE_CONTENT`。能力拿不准时 MUST 偏向 `READABLE_CONTENT`；绑定对象拿不准时 MUST 偏向不绑定。钉钉 `originalMsgId` MUST 随用户消息持久化，以便解析被引消息上的附件；系统 MUST NOT 只把引用正文拼进 prompt 而不建立文件绑定。

#### Scenario: 本条消息同时上传文档并提问
- **WHEN** 用户在同一条钉钉消息中发送受支持文档和非空问题
- **THEN** 系统把该消息附件的精确版本列入本轮依赖
- **AND** 所需能力为 `READABLE_CONTENT`，除非文字只命中元数据或原件模式

#### Scenario: 用户回复带文件的历史消息
- **WHEN** 用户通过钉钉引用一条已成功导入附件的历史消息并发送非空文字
- **THEN** 系统用持久化的 `originalMsgId` 解析到被引消息附件的精确版本并列入本轮依赖
- **AND** 不把工作区里其它未引用文件自动列入本轮依赖

#### Scenario: 文字出现精确文件名
- **WHEN** 用户文字包含工作区中恰好一份文件的完整显示名（含扩展名）
- **THEN** 系统绑定该文件当前精确版本
- **AND** 子串、无扩展名或工作区内重名 MUST 不自动绑定

#### Scenario: 近指代指向唯一最近活动文件
- **WHEN** 用户文字命中代码注册近指代词，且当前工作区最近一次来源导入成功的文件版本唯一
- **THEN** 系统绑定该版本
- **AND** 不扫描其它会话或其它工作区

#### Scenario: 近指代在多份文件之间歧义
- **WHEN** 用户说「这个表」但工作区存在多份最近导入且无法唯一确定的表格文件
- **THEN** 系统通过原 reply route 发出固定澄清说明
- **AND** 不创建 Agent Job，也不把任一候选标为已消费

#### Scenario: 无硬证据的后续问题
- **WHEN** 用户刚上传过文档，随后发送不含附件、引用、精确文件名或近指代的普通问题
- **THEN** 本轮文件依赖集合为空
- **AND** 系统不得因工作区存在处理中文档而拒绝创建 Agent Job

### Requirement: 文件能力未就绪时用系统说明结束本轮
当本轮依赖需要某精确版本的 `READABLE_CONTENT`，且该版本可读性为 `PENDING` 或处理失败终态时，系统 MUST 通过原 reply route 发送固定中文 Markdown 说明，MUST NOT 调用模型，MUST NOT 把该轮释放到 `agent.jobs`。说明 MUST 只包含安全文件名和允许的状态短语（正在生成可读内容 / 可读内容生成失败），MUST NOT 包含对象键、Docling task ID、堆栈、内部 run ID 或 `agent_runtime_error` JSON。需要 `METADATA` 或 `ORIGINAL` 且原件已安全入库时，系统 MUST NOT 因 Markdown 表示未就绪而阻挡本轮。纯附件且无非空文字的行为保持既有暂存、不回复。

#### Scenario: 处理中询问文档内容
- **WHEN** 本轮已绑定一份 `readability_status=PENDING` 的文档且所需能力为 `READABLE_CONTENT`
- **THEN** 系统不创建或不释放 Agent Job 到 Agent 队列
- **AND** 用户收到固定说明：该文件正在生成可读内容，其它问题可以继续发送

#### Scenario: 处理失败后询问文档内容
- **WHEN** 本轮已绑定文档且可读性为 `NO_TEXT`、`UNAVAILABLE` 或处理 `FAILED`
- **THEN** 系统不调用模型
- **AND** 用户收到固定失败说明，而不是 Agent 运行时错误 JSON

#### Scenario: 处理中询问文件名
- **WHEN** 本轮绑定文档只需要 `METADATA` 且原件已形成 File Version
- **THEN** 系统创建 Agent Job 并允许回答元数据
- **AND** 不把未就绪 Markdown 自动物化进该 Job

## MODIFIED Requirements

### Requirement: Channel 文件输入绑定任务工作区
Channel ingress SHALL 把没有非空文字的受支持附件消息作为附件暂存事件：解析真实身份和 Business Application Publication，创建或复用当前 Channel Session 与活动任务工作区，持久化并异步导入附件，但 MUST NOT 创建 Agent Job、Job Dispatch、Result Delivery、占位文字指令或用户回复。同一 Session 中连续到达的纯附件消息 SHALL 进入同一任务工作区，各自形成精确文件版本候选。后续非空文字 MUST 只认领本轮确定性绑定命中的附件或版本；系统 MUST NOT 因出现非空文字就原子认领该 Session/工作区下全部 `job_id` 为空的附件。未被本轮绑定的附件 MUST 保持未挂接 Agent Job，其文件版本继续作为工作区候选。消息附件身份与任务工作区引用 MUST 分离，工作区过期不得提前删除仍在独立保留期内的原始附件。

#### Scenario: 连续发送多个纯附件消息
- **WHEN** 已授权用户在同一钉钉会话依次发送三个合法文件且都没有非空文字
- **THEN** 系统创建或复用当前任务工作区并异步导入三个附件
- **AND** 不创建 Agent Job、Job Dispatch、Result Delivery 或用户回复

#### Scenario: 后续无关文字不认领暂存附件
- **WHEN** 用户随后在同一 Session 发送不含附件、引用、精确文件名或近指代的非空文字
- **THEN** 系统创建一个 Agent Job 且不认领此前暂存附件
- **AND** 三个文件版本仍作为当前工作区的有界候选

#### Scenario: 后续文字显式绑定其中一个附件
- **WHEN** 用户随后发送引用了第二个暂存文件消息的非空文字，或文字包含该文件的精确显示名
- **THEN** 系统只认领被绑定的那一个附件
- **AND** 其余暂存附件继续保持未挂接 Agent Job

#### Scenario: 本轮绑定附件的来源仍在导入
- **WHEN** 本轮绑定的附件来源下载或导入尚未进入安全终态
- **THEN** 系统可为该绑定集合创建同一个 `WAITING_INPUT` Job
- **AND** File Worker 只在该绑定集合的来源状态全部进入安全终态后唤醒一次门禁，不为单个附件创建额外 Agent Job，也不得把未绑定附件并入该集合

#### Scenario: 工作区先于附件到期
- **WHEN** 任务工作区到期但关联消息附件仍在360天保留期内
- **THEN** 系统删除工作区临时内容并保留消息附件及其消息来源关系

### Requirement: File Worker 兼容现有附件队列
系统 MUST 用 `file-worker` 替换 `attachment-worker` 服务名，同时继续消费现有附件队列和兼容在途消息。File Worker SHALL 使用短期来源凭证下载附件并通过 File Service 内部流式接口导入，MUST NOT 获得 MinIO 凭据或直接写对象存储；附件下载终态仍须清除来源凭证。尚未被本轮绑定认领的纯附件只进入 `staged` 终态而不释放或创建 Job。已经绑定唯一 `WAITING_INPUT` Job 的**本轮绑定**附件集合在来源导入全部进入安全终态后，File Worker 才唤醒该 Job 一次；唤醒后 MUST 重新执行能力门禁，MUST NOT 仅因可读表示仍为 `PENDING` 而继续保持 `WAITING_INPUT` 或释放到 `agent.jobs`。

#### Scenario: 切换时存在旧附件消息
- **WHEN** 部署切换到 `file-worker` 时原附件队列仍有合法消息
- **THEN** File Worker 使用原幂等 attachment ID继续处理
- **AND** 不产生重复消息、附件、对象或 Job

#### Scenario: 来源导入完成后表示仍在处理
- **WHEN** 本轮 `WAITING_INPUT` Job 绑定的文档原件已保存但 Markdown 表示仍为 `PENDING`，且所需能力为 `READABLE_CONTENT`
- **THEN** 系统发送固定未就绪说明并安全终结该 Job，不发布到 Agent 队列
- **AND** 不把该终结表现为 `agent_runtime_error`
