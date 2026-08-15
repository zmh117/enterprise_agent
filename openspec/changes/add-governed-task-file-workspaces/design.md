## Context

本变更为 Agent 增加受治理的任务文件工作区，使钉钉私聊、群聊和已有聊天附件能够在多个 Job 间连续使用，并允许 Claude Code Agent 在受限沙盒内编辑纯文本文件、提交不可变版本和交付结果。

### Confirmed-current

- 当前附件入口以 `message_attachment`、`attachment_content` 等记录承载，`attachment-worker` 负责异步附件处理，并直接依赖 MinIO。
- 当前 Agent Runtime 为每次调用创建临时目录并在结束时清理，但它不是可跨 Job 延续的逻辑工作区，也没有受治理的文件版本、保留和提交模型。
- 当前 TypeScript Runtime 禁止 `Write`、`Edit`、`Bash`、`WebFetch` 等危险工具；容器保持只读，执行目录使用受限 tmpfs。
- 当前 Runtime 已经通过短时 Principal JWT 调用固定 MCP Server，并为 ONES MCP 实现服务端凭据解析。该身份传递模式可复用于 File MCP，但不得把 MinIO 凭据下发给 Runtime 或 Agent。
- 当前系统已有消息、Job、交付、审计、Outbox/RabbitMQ 和 Business Application Publication 治理边界；文件工作区必须接入这些边界，不能成为第二套执行或授权体系。

### Documented-intent introduced by this change

- 新增唯一文件事实入口 `file-service`。同一进程同时提供固定 File MCP 接口和受限内部流式传输接口。
- 现有 `attachment-worker` 被 `file-worker` 替代；保留原有附件队列和在途消息兼容性，不同时运行两个重复消费者。
- 逻辑工作区保存在 PostgreSQL 与 MinIO；每个 Job 的物理沙盒仍位于 Agent Runtime 容器内，并在 Job 终态后删除。
- 第一阶段仅支持 UTF-8 `.txt`，每文件最大 15 MiB；DOCX、XLSX、PPTX、PDF、OCR 和 Markdown 解析延后由 docling-server 统一承担。

## Goals / Non-Goals

### Goals

- 为私聊用户和群聊会话提供可跨多次追问延续的逻辑 Task Workspace。
- 由发布态 Business Application 冻结 DAY、WEEK、MONTH 自然周期保留策略，并允许前端修改草稿配置后重新发布。
- 让 File Service 成为文件元数据、版本、对象、保留、配额、审计与提交的唯一治理入口。
- 让 Agent 仅通过固定 File MCP 发现、物化、提交、保留和交付文件，且所有调用绑定 Principal、Job、Workspace 和精确版本。
- 在 Runtime 沙盒中有限开放 `Read`、`Grep`、`Write`、`Edit`，同时继续拒绝 Bash、Shell、Web、任意 MCP、任意 URL 和任意对象键访问。
- 保持聊天附件默认 360 天保留，并将 `attachment-worker` 平滑替换为 `file-worker`。
- 对提交、并发冲突、清理和交付提供可重试、幂等且可审计的处理。

### Non-Goals

- 第一阶段不解析或编辑 DOCX、XLSX、PPTX、PDF、图片、OCR 或 Markdown。
- 不感知钉钉在线编辑的实时内容变化，不向原钉盘文件回写，也不覆盖用户上传的原文件。
- 不建设通用网盘、目录继承 ACL、匿名分享、跨租户分享或公开下载链接。
- 不复制钉钉群成员 ACL 到文件数据库；也不把外部钉盘文件仍可访问视为内部副本已删除后的恢复来源。
- 不允许 Agent 获得 MinIO 凭据、Bucket 名、对象键、预签名 URL 或任意本地路径访问能力。
- 不允许 File Service 自动合并文本冲突；冲突由后续 Job 中的 Agent 显式处理。
- 不新增通用 HTTP、SQL、Shell、脚本、模板或任意 MCP 执行器。

## Decisions

### 1. File Service 是唯一文件事实入口，并在一个容器内提供两种协议

新增一个 `file-service` 容器，内部共享同一领域层、授权层、事务层和审计层：

- Streamable HTTP File MCP：供 Agent 进行受治理的控制面操作；
- 内部流式 REST：供 Runtime 和 `file-worker` 传输文件字节；
- PostgreSQL：保存文件身份、不可变版本、工作区引用、Job 快照、提交意图、保留事实与审计关联；
- MinIO：保存原始和派生对象；只有 File Service 的基础设施适配器解析并持有 Secret Reference。

File MCP 不直接访问 MinIO，也不成为独立容器。File MCP Handler 调用与内部 REST 相同的应用服务，因此不存在绕过版本、配额、生命周期或审计的第二入口。

备选方案及否决理由：

- 独立 `file-mcp` 直接持有 MinIO 凭据：会形成第二个文件事实入口，版本与生命周期容易失配。
- Runtime 使用 JWT 换取临时 MinIO 凭据：泄露面扩大，Agent 可绕过 File Service 的对象键和配额治理。
- File Service 只做代理、不管理元数据：无法实现精确版本、冲突检测、保留与删除证明。

### 2. `file-worker` 替代而不是叠加 `attachment-worker`

`file-worker` 是现有附件异步处理职责的演进版本：

- 继续消费现有附件队列和兼容的消息格式；
- 从外部渠道拉取附件时，字节必须流入 File Service，而不是自行写 MinIO；
- 承担工作区到期、未引用 staging 对象、孤儿对象和超期内容的异步清理；
- 为附件导入、清理和补偿使用受限的内部服务身份；
- 不持有 MinIO Secret，不执行文档解析。

上线时停止旧 `attachment-worker` 后再启用 `file-worker` 消费相同队列，防止重复消费。若队列协议必须扩展，应保持旧字段可读并以版本化新字段补充。

交付职责仍由现有 delivery worker 承担，因为文件处理重试和渠道交付重试具有不同的状态机、限流和故障域。

备选方案及否决理由：

- 同时保留两个 Worker：会产生重复下载、重复对象和队列所有权不清。
- 把交付并入 `file-worker`：会耦合文件生命周期与渠道限流，影响独立重试。

### 3. 数据模型分离逻辑工作区、文件身份、不可变版本和 Job 快照

建议新增下列领域记录，最终表名可遵循仓库现有命名规则，但语义不得合并：

| 记录 | 关键职责 |
|---|---|
| `task_workspace` | 会话内逻辑任务工作区、所有者类型、状态、发布态保留策略、自然周期边界和到期时间 |
| `managed_file` | 稳定文件身份、租户、所有权范围、当前版本指针和删除状态 |
| `managed_file_version` | 不可变版本、父版本、内容摘要、大小、编码、对象引用、来源和保留状态 |
| `task_workspace_file` | 工作区中的逻辑文件名、用途、当前选中版本和临时/保留属性 |
| `agent_job_file_snapshot` | Job 创建时冻结的 File Manifest 头记录 |
| `agent_job_file_snapshot_item` | Job 可见的精确 file/version、显示名、来源和允许动作 |
| `file_commit_intent` | `commit_id`、目标、base version、元数据摘要、状态和幂等结果 |
| `file_object_staging` | 上传中的临时对象、摘要、大小、创建时间和清理状态 |
| `file_retention_fact` | 版本保留理由、保留截止时间和对应业务事件 |
| `file_external_reference` | 钉钉消息附件或外部文件标识与内部精确版本的来源关联 |

约束：

- 同一 `agent_session` 最多一个 ACTIVE 工作区；会话可以先后拥有多个工作区。
- 文件版本只追加不覆盖；`managed_file.current_version_id` 通过乐观并发条件推进。
- Job 快照项冻结后不可修改；后续工作区变化不影响运行中的 Job。
- 对象引用只在基础设施层和数据库内部出现，不进入 MCP 模型可见结果、JWT、日志或业务审计正文。
- staging 对象在版本发布前对 Agent、搜索和下载均不可见。
- 删除采用状态机和异步物理清理；已到期内容不可凭旧的钉钉引用重新导入或恢复。

### 4. 工作区按自然周期到期，文件版本按独立保留事实存活

Business Application 草稿允许配置 `DAY`、`WEEK` 或 `MONTH`，发布时冻结到 Publication Revision。未配置时使用 `WEEK`。

所有自然周期按 `Asia/Shanghai` 计算：

- DAY：创建当日结束；
- WEEK：创建所在自然周结束；
- MONTH：创建所在自然月结束。

这不是滚动 24 小时、7 天或 30 天。已有工作区继续使用创建时冻结的发布态策略，前端修改只影响后续发布及使用该新 Revision 创建的工作区。

工作区到期时：

- 删除工作区临时引用和无其他保留事实的临时版本内容；
- 不删除仍被聊天附件 360 天保留、用户明确保留或交付记录引用的版本；
- 清除逻辑引用与物理对象必须分别记录状态，以便重试与孤儿核对；
- 如果内部 360 天副本已经清理，即使钉盘在线文件仍存在且用户仍有权限，也拒绝继续处理。

聊天附件保留默认值为 360 天，必须配置化但不得由模型临时改变。第一阶段不把工作区到期等同于所有文件版本到期。

### 5. 私聊与群聊授权使用平台事实，不复制外部 ACL

私聊工作区的所有者是平台用户，只有该用户及绑定其身份运行的 Agent Job 可访问。

群聊工作区的所有者范围是受信任的群会话。群内人员可编辑群工作区文件，但每次调用都必须：

- 使用真实发送者对应的平台 Principal；
- 校验当前会话、租户、Business Application 和渠道绑定仍有效；
- 校验 Job 属于该群会话并在其冻结 File Manifest 中拥有对应版本与动作；
- 记录实际操作者，而不是只记录机器人或群标识。

File Service 不保存或同步钉钉群成员列表，也不独立解释钉钉文件 ACL。消息入口已经验证的群会话成员事实是本次 Job 的授权前提；如果身份或会话事实失效，默认拒绝。

### 6. Principal JWT 只携带平台身份和最小文件作用域

Runtime 调用 File MCP 和流式文件接口时使用平台签发的短时 Principal JWT。建议有效期不超过 300 秒，并至少绑定：

- `sub` / principal 类型；
- `tenant_id`；
- `agent_id`、`job_id`、`session_id`、`workspace_id`；
- `aud=file-service`；
- 代码注册的最小文件 scope；
- `exp`、`jti` 和签发信息。

JWT 不携带 MinIO Access Key、Secret Key、Bucket、对象键、预签名 URL 或钉钉凭据。File Service 验签后仍需回读 Job、Workspace、Manifest、Publication Revision 和当前资源状态，不能把 JWT 当成完整授权快照。

`file-worker` 使用平台服务身份调用附件导入与清理接口，权限与用户 Agent scope 分离。该服务身份仍由平台身份边界签发和审计，不能退化为共享 Internal API Token。

平台身份边界 MUST 使用独立于用户/Job Principal 的 Service Principal Key Ring。现有平台 API 中的身份模块持有该服务签名私钥，并通过固定内部身份接口按需签发 TTL 不超过 300 秒的 JWT；File Service 只读取对应公开 JWKS。`file-worker` 与 Delivery Worker 分别持有不同的、仅用于向平台身份接口换取短时 JWT 的 bootstrap credential，任何一个 Worker 都不得持有服务签名私钥、另一角色的 bootstrap credential 或预先生成的长期 JWT 文件。

本地Compose还需要先把MinIO基础设施凭据建立为平台`encrypted_db` Secret，否则File Service会按默认拒绝保持unready。该首次启动动作由一次性Migrator完成：它只挂载Master Key与两个角色隔离的Docker Secret，不取得MinIO endpoint、Bucket或对象路径；缺失时创建、相同值时幂等保留、不同值时失败并要求显式轮换。长期运行的Worker、Runtime与Delivery不继承这些bootstrap Secret，生产可关闭此本地初始化。

服务 JWT 使用固定信任域：`iss=enterprise-agent-service-identity`、`aud=file-service-internal`，并令 `sub` 与 `azp` 同为调用角色。`file-worker` Token 冻结附件导入与内容清理两个固定 scope；Delivery Worker Token 只冻结精确版本交付读取 scope。File Service 必须验证 Token 的完整角色 scope 集合并复核当前接口所需 scope 属于该集合，不能要求同一个 File Worker Token 在两个接口上分别等于互斥的单 scope，也不能接受集合外 scope。

bootstrap credential 只用于平台身份接口认证，使用独立随机值、角色隔离挂载、常量时间比较和有界读取；不得作为 File Service Internal API Token。客户端按需缓存短时 JWT，并在到期前刷新；签发和拒绝写入不含 credential/JWT 的安全审计。Compose 启动前的密钥初始化只生成服务签名密钥、公开 JWKS 和两份角色 bootstrap credential，不生成静态 Service JWT。

备选方案及否决理由：

- JWT 直接携带 MinIO 临时凭据：扩大凭据暴露面并允许绕过治理。
- 仅凭 `commit_id` 上传：commit id 是业务标识，不是认证凭据。
- File Service 自签用户身份：会形成第二身份签发中心。
- 把一次性生成的 Service JWT 作为 Compose Secret：JWT 最长 300 秒，启动后必然过期，无法形成稳定运行链路。
- 向两个 Worker 挂载同一 bootstrap token 或服务签名私钥：扩大横向冒用与签名能力泄露面。

### 7. Job 创建时冻结 File Manifest，Runtime 按需物化精确版本

Job 创建时建立不可变 File Manifest：

- 当前消息附件和用户显式引用自动加入；
- 工作区其他文件由 Agent 根据任务选择，但只能从 Manifest 可见集合中选择；
- 每项冻结精确 `file_id`、`version_id`、显示名、来源和允许动作；
- 创建快照和实际物化时均重新检查授权、到期、删除和内容存在状态。

Agent 通过 Runtime 代码注册的本地 File MCP bridge 请求物化。该 bridge 只代理 Job 冻结的 File Service 工具，不接受模型提供的 Server URL；它先调用部署固定的远端 File MCP，再在 ToolResult 返回模型之前拦截隐藏的受控传输描述。Runtime 内部的 file-transfer coordinator 验证描述后，使用当前 Job 的 File Principal JWT 经内部流式接口把内容写入当前 Job 沙盒的安全相对路径。模型只能看到逻辑文件句柄、沙盒内安全相对路径、大小和摘要，不能看到传输描述、JWT 或文件字节。

下载哪些候选文件由 Agent 根据任务判断，但以下边界不可由模型改变：

- 只能下载 Manifest 中的精确版本；
- 文件名必须由 Runtime 规范化并防止路径穿越、符号链接和特殊设备；
- 单文件、工作区总量和沙盒容量均由平台强制；
- Runtime 不接受 File MCP 返回的任意 URL，也不直接访问 MinIO。

### 8. 受限开放 Write/Edit，并由 Runtime 文件桥接器提交

仅当 Job Manifest 声明文件编辑能力时，Claude Code Agent 可在当前 Job 沙盒内使用：

- `Read`、`Grep`；
- 受路径、后缀、大小和配额约束的 `Write`、`Edit`。

继续拒绝 `Bash`、`Shell`、`NotebookEdit`、`WebFetch`、`WebSearch`、任意 MCP、任意 URL 和沙盒外路径。容器根文件系统保持只读；仅挂载 Job 专属可写 tmpfs。沙盒容量必须配置为足以容纳最多 100 MiB 未保留工作区内容及提交暂存开销，并通过磁盘配额和进程级限制强制，而不是依靠提示词。

Agent 只提交显式标记的输出，不自动扫描并提交沙盒全部改动。Runtime 仅为文件 Job 代码注册 `select_sandbox_output`：它只接受当前沙盒下的安全相对 TXT 路径，校验常规文件、符号链接、大小和 UTF-8 后生成不透明 sandbox entry handle，不读取正文到模型上下文。物化输入已有由 Runtime 登记的 handle，不需要再次选择。File MCP 提交工具只接受该逻辑 handle；Runtime bridge 在远端提交意图返回模型前，将 handle 映射为已验证的精确本地文件并流式上传。远端 File Service 不接受模型提供的绝对路径。

由于远程 MCP 不能直接读取 Runtime 本地文件，Python 与 TypeScript Runtime 使用 Claude SDK 支持的进程内 MCP Server 作为预模型 bridge：模型调用的 `mcp__files__*` 先进入 Runtime 代码，再由 Runtime 使用标准 MCP Client 转发到部署固定的 File Service。测试必须驱动真实 Runtime executor/SDK 工具处理循环，证明 File MCP 工具结果会触发受控下载、提交意图会触发流式上传；仅手工调用 coordinator 的测试只能作为单元测试，不能作为 Runtime 接线或端到端完成证据。不得退化为在 Tool JSON 中放入文件全文，也不得在 SDK 消息消费后才处理传输描述。

### 9. 提交采用意图、staging、校验和不可变版本发布

提交流程：

1. Agent 调用 File MCP 创建提交意图，声明目标文件或新文件、`base_version_id`、显示名和逻辑 sandbox entry handle。
2. File Service 验证 Principal、Job、Manifest、工作区、明确写入意图、配额和并发基线，生成 `commit_id`。
3. Runtime 使用相同 Principal JWT、`commit_id` 和内部映射的本地文件，经流式接口上传字节。
4. File Service 边接收边计算摘要和大小，验证 `.txt`、15 MiB 限制和 UTF-8；允许输入 BOM，但规范化输出不写 BOM。
5. 字节先进入不可见 staging；验证通过后写入不可变版本对象并在数据库事务中发布新版本、推进当前版本指针、记录审计和 Outbox。
6. 跨 PostgreSQL/MinIO 事务失败时，staging 或孤儿版本对象由 `file-worker` 根据数据库引用事实清理。

模型和 MCP JSON 永远不承载完整文件内容。

提交幂等键是 `commit_id`。同一个 `commit_id` 只有在目标、base version、元数据摘要和内容摘要全部一致时返回同一 `version_id`；任何不一致都拒绝，不能覆盖旧结果。

### 10. 并发冲突不自动合并

修改已有文件时，File Service 比较 `base_version_id` 与当前版本：

- 相同：发布新不可变版本并推进当前指针；
- 不同：保存本次已验证内容为不可见或受限可见的 conflict candidate，不推进当前指针，并返回结构化冲突结果；
- 后续 Job 的 Manifest 可同时包含最新版本与 conflict candidate，由 Agent 在沙盒内显式合并并再次提交。

即使第一阶段只有 TXT，File Service 也不做自动三方合并，避免丢失语义和隐藏冲突。

### 11. 文件级提交结果独立，不新增 PARTIAL Job 状态

一次 Job 可提交多个文件，每个提交意图分别成功、冲突或失败。只要 Runtime 最终答复成功，Job 仍为 `SUCCEEDED`；最终结果和审计明确列出每个文件的结果。

只有 Runtime 执行本身失败、取消或超时时，Job 才进入现有相应终态。文件提交失败不能通过创建新的 `PARTIAL` Job 状态改变既有执行语义。

用户明确要求“修改”“生成”文件时，视为允许提交对应结果，不再追加一次确认；仅分析、总结或含义不明时不提交，必要时由 Agent澄清。用户说明“只留在工作区”时不触发默认交付。

### 12. 钉钉交付复用现有 Delivery 状态机并固定精确版本

钉钉会话中的修改或生成请求，默认将每个成功提交的精确 `version_id` 作为新钉钉文件交付到同一会话；不覆盖输入文件。

File Service 仅提供受控的版本读取能力，现有 Delivery Worker 负责渠道发送。Outbox/Delivery 记录必须冻结：

- `file_id`、`version_id`；
- 目标会话与请求消息；
- Job、Principal、Publication Revision；
- 幂等键和交付尝试。

交付失败独立重试相同版本，不重新运行 Agent，也不自动改为最新版本。交付失败不回滚已成功提交的内部版本。

### 13. 第一阶段限制由服务端和 Runtime 双重强制

第一阶段约束：

- MIME/扩展名只允许 `.txt`；
- 内容必须可按 UTF-8 解码；输入可有 BOM，Agent 输出和新版本使用无 BOM UTF-8；
- 单文件最大 15 MiB；
- 每工作区最多 20 个逻辑文件；
- 每工作区未保留内容最大 100 MiB；
- 聊天附件默认保留 360 天；
- 工作区保留为 DAY/WEEK/MONTH 自然周期，默认 WEEK。

入口导入、物化和提交均校验限制。不能只在前端或 Agent 提示词中校验。超过限制时返回结构化、可本地化且不泄露对象细节的错误。

## Risks / Trade-offs

- **远程 MCP 与本地沙盒字节桥接复杂。** 先实现 SDK 兼容性切片和端到端测试；失败时只能增加代码注册的 Runtime coordinator，不能传全文或开放 URL。
- **PostgreSQL 与 MinIO 无分布式事务。** 使用 staging、不可变对象、数据库可见性和 Outbox 补偿；所有清理必须可重试并以数据库引用为准。
- **替换 Worker 存在在途消息重复风险。** 保持队列协议兼容，切换时单消费者所有权，附件导入使用来源幂等键。
- **群聊授权依赖入口身份事实。** 每次调用重新验证平台会话与实际 sender，失效即拒绝；不以缓存群成员列表延长授权。
- **开放 Write/Edit 增加 Runtime 风险。** 只对文件 Job 开放，限制路径、类型、大小、inode/磁盘容量和工具集合，结束后无条件清理沙盒。
- **自然周期会令临近周期末创建的工作区很快到期。** 这是已选择的业务语义；前端应展示准确到期时间，不将其描述为滚动天数。
- **360 天保留提高存储成本。** 通过内容摘要、配额、保留事实和运营指标观察容量；第一阶段不以去重改变文件身份语义。
- **不感知钉钉在线编辑可能产生认知差异。** UI 和结果消息明确内部版本是导入时快照；后续阶段另行设计外部变更同步。

## Migration Plan

### Phase 0: 兼容性与安全切片

1. 固化当前附件队列契约、来源幂等键和在途消息处理测试。
2. 验证 TypeScript Runtime 对 File MCP 控制结果与本地流式传输 coordinator 的接入点。
3. 验证 `.txt` 15 MiB、100 MiB 工作区和提交暂存开销下的 tmpfs/配额配置。
4. 在不接触真实凭据的 Mock MinIO、Mock DingTalk 和 Mock identity 环境完成失败注入。

### Phase 1: Expand

1. 增加文件、版本、工作区、Job 快照、提交、保留和 staging 表以及必要索引/约束。
2. 部署 `file-service`，先仅接收影子或测试流量；MinIO Secret 只配置给该容器。
3. 为现有 `message_attachment` 增加到内部 file/version 的兼容关联，不删除旧列和旧读取路径。
4. 增加 File MCP 固定工具清单、Principal JWT 校验、授权和审计。

### Phase 2: Worker 切换与 Runtime 启用

1. 部署支持旧队列格式的 `file-worker`，暂停旧 `attachment-worker` 消费后再切换消费者。
2. 对来源幂等键和已有附件执行可重复的关联/回填；不重复下载已完整存在且摘要匹配的对象。
3. 按 Business Application Revision 灰度启用工作区与 File Manifest。
4. 仅对灰度文件 Job 开放受限 Write/Edit 和 transfer coordinator；其他 Job 保持当前只读工具集。
5. 启用精确版本交付与独立重试。

### Phase 3: Contract

1. 在队列积压归零、旧 Worker 停止、回填核对通过并保留回滚窗口后，移除 `attachment-worker` Compose 服务和其 MinIO 凭据。
2. 移除已无读取方的旧附件对象直读路径，但保留消息附件业务记录和 360 天语义。
3. 启用到期清理、孤儿核对和运营告警，并记录删除证据。

### Rollback

- Expand 阶段仅新增结构和旁路能力，可关闭发布态文件工作区开关并恢复旧附件读取路径。
- Worker 切换期间保留旧镜像和队列协议；回滚前必须停止 `file-worker`，再恢复单一 `attachment-worker` 消费者，避免双消费者。
- 已由 File Service 发布的不可变版本不得回滚删除；回滚仅停止新入口，既有版本按保留策略继续治理。
- 数据库迁移采用 expand/contract；未完成回填、核对、备份和审批前不得执行破坏性 contract。

## Open Questions

没有阻塞规格的问题。以下为实现阶段通过基准测试确定的运维参数，不改变上述业务语义：

- Runtime tmpfs 的具体默认容量与并发 Job 密度；它必须覆盖 100 MiB 工作区上限、输入/输出副本和安全余量。
- staging 与孤儿对象清理扫描间隔、告警阈值和批量大小。
- 工作区与附件容量指标触发扩容或限流的运营阈值。
