# unbound-dingtalk-identity-discovery Specification

## Purpose
TBD - created by archiving change add-unbound-dingtalk-identity-discovery. Update Purpose after archive.
## Requirements
### Requirement: 未绑定钉钉消息形成安全发现候选

系统 SHALL 只为通过渠道认证和规范化、已持久化且明确因钉钉身份从未绑定、身份已停用或解绑、或所属用户已停用而被拒绝的新消息创建发现候选，并 MUST NOT 因此创建 Agent Job、发布 Job 消息、调用模型或 API Capability。

#### Scenario: 从未绑定用户发送私聊消息

- **WHEN** 部署本功能后，一个没有历史钉钉身份的用户向已启用机器人发送私聊消息
- **THEN** 系统 SHALL 返回现有未授权提示、创建或更新该用户的发现候选，且不得创建 Agent Job

#### Scenario: 从未绑定用户发送群聊消息

- **WHEN** 部署本功能后，一个没有历史钉钉身份的用户在群聊中向已启用机器人发送消息
- **THEN** 系统 SHALL 创建或更新同一身份候选并记录安全群会话标识，且不得触发 Agent 执行

#### Scenario: 不符合身份发现条件的入口失败

- **WHEN** 钉钉事件因连接器认证失败、格式错误、缺少 `senderStaffId` 或非身份授权原因被拒绝
- **THEN** 系统 MUST NOT 创建身份发现候选，且不得泄露事件是否对应现有人员

### Requirement: 候选按租户和钉钉用户聚合且幂等

系统 SHALL 以钉钉企业租户和 `senderStaffId` 唯一聚合候选，并 SHALL 以来源渠道事件唯一标识保证候选消息写入幂等。

#### Scenario: 同一用户经多个会话和机器人发消息

- **WHEN** 同一企业租户内同一 `senderStaffId` 通过私聊、群聊或不同机器人发送多条消息
- **THEN** 系统 SHALL 只展示一个候选人，并在其最近消息中保留各消息的会话和机器人来源

#### Scenario: 不同租户使用相同用户 ID

- **WHEN** 两个企业租户出现相同的 `senderStaffId`
- **THEN** 系统 SHALL 创建两个相互隔离的候选人

#### Scenario: 同一渠道事件重复投递

- **WHEN** DingTalk Runtime 重复投递同一个渠道事件
- **THEN** 系统 SHALL 返回相同拒绝语义且不得增加第二条候选消息、第二次观察计数或任何 Agent Job

### Requirement: 管理员查看和筛选未绑定用户

系统 SHALL 在“用户与外部身份”导航组下提供“人员管理”和“未绑定钉钉用户”，并 SHALL 在 `/users/dingtalk-discovery` 统一展示私聊与群聊候选。

#### Scenario: 查看候选列表

- **WHEN** 具备 `identity:manage` 权限的管理员打开未绑定钉钉用户页面
- **THEN** 系统 SHALL 按最近接收时间倒序稳定分页展示最新消息、消息时间、钉钉用户名、用户 ID、群 ID、所属机器人和身份状态

#### Scenario: 筛选会话类型

- **WHEN** 管理员选择全部、私聊、群聊或两者筛选
- **THEN** 系统 SHALL 只返回符合该候选最近保留消息会话构成的候选人

#### Scenario: 搜索候选

- **WHEN** 管理员按钉钉用户名、用户 ID、群 ID或机器人关键字搜索
- **THEN** 系统 SHALL 在当前可见候选范围内返回匹配结果，并保持稳定排序和分页

#### Scenario: 展开最近消息

- **WHEN** 管理员展开一个候选人
- **THEN** 系统 SHALL 展示该候选跨私聊、群聊和机器人的最近安全消息摘要及其来源

### Requirement: 候选消息内容有界且安全

系统 SHALL 为每个候选最多保留最近 20 条发现消息，文本或 Markdown 摘要最多保留 1,000 个 Unicode 字符；附件只允许保存并返回经过白名单校验的类型、名称和大小。

#### Scenario: 文本超过长度上限

- **WHEN** 未绑定用户发送超过 1,000 个字符的文本或 Markdown 消息
- **THEN** 系统 SHALL 截断安全纯文本摘要并返回明确的内容已截断标志

#### Scenario: 收到附件消息

- **WHEN** 未绑定用户发送图片、文件、音频或视频
- **THEN** 系统 SHALL 只展示安全的附件类型、名称和大小，不提供预览、下载或内容提取

#### Scenario: 候选收到超过二十条消息

- **WHEN** 同一候选累计收到超过 20 条幂等的新消息
- **THEN** 系统 SHALL 只保留最近 20 条投影消息，同时保持正确的累计观察次数

#### Scenario: 管理端展示外部可控内容

- **WHEN** 候选昵称、文本或附件名称包含 HTML、Markdown 或脚本字符
- **THEN** 前端 SHALL 仅按纯文本展示，不得执行 HTML、Markdown、脚本或外部链接

### Requirement: 发现接口不得暴露原始事件和敏感材料

系统 MUST 使用专用响应白名单，并 MUST NOT 通过候选接口、页面、日志或审计返回或记录原始渠道事件、`sessionWebhook`、下载凭据、临时 URL、Secret、Token、模型 API Key、完整附件内容或消息正文日志。

#### Scenario: 管理员查询候选详情

- **WHEN** 管理员请求候选详情和最近消息
- **THEN** 响应 SHALL 只包含候选身份、来源、安全摘要和时间等白名单字段

#### Scenario: 候选处理失败

- **WHEN** 投影、查询或绑定操作失败
- **THEN** 日志和审计 SHALL 只记录候选 ID、目标资源、结果、安全错误码和追踪信息，不得记录消息正文或凭据

### Requirement: 消息时间、候选排序和保留期使用安全时间语义

系统 SHALL 优先将有效的钉钉 `createAt` 作为消息展示时间、缺失或无效时使用服务端接收时间，并 SHALL 使用服务端接收时间进行候选排序、活动窗口判断和清理。

#### Scenario: 钉钉消息时间有效

- **WHEN** 事件包含格式有效的钉钉 `createAt`
- **THEN** 页面 SHALL 将其显示为消息时间，同时候选活动窗口仍以服务端接收时间计算

#### Scenario: 钉钉消息时间缺失或异常

- **WHEN** 事件不含有效 `createAt` 或其值不能安全解析
- **THEN** 系统 SHALL 使用服务端接收时间作为展示时间，且不得因外部异常时间戳错误置顶或永久保留候选

### Requirement: 候选保留三十天且不回填历史

系统 SHALL 只观察本功能部署后新进入身份拒绝分支的消息，并 SHALL 仅展示最近一次服务端接收时间在 30 天内的候选；过期清理只能删除发现投影。

#### Scenario: 功能首次部署

- **WHEN** 数据库中已经存在部署前的钉钉渠道事件
- **THEN** 系统 MUST NOT 扫描这些事件或据此创建候选

#### Scenario: 候选三十天没有新消息

- **WHEN** 候选最近一次服务端接收时间早于 30 天
- **THEN** 列表和徽标 SHALL 立即排除该候选，后台 SHALL 可幂等清理其候选和投影消息

#### Scenario: 清理发现投影

- **WHEN** 后台清理过期候选
- **THEN** 系统 MUST NOT 删除或修改原始渠道事件、审计事件、Agent Job 或投递记录

### Requirement: 候选绑定只使用服务端可信身份

系统 SHALL 允许管理员通过内部候选 ID 将从未绑定候选关联到已启用自然人用户，并 SHALL 在服务端重新读取和校验租户、Connector、`senderStaffId`、候选版本和目标用户版本。

#### Scenario: 绑定到现有自然人用户

- **WHEN** 管理员选择已启用自然人用户并使用当前版本提交候选绑定
- **THEN** 系统 SHALL 使用候选的服务端可信身份创建钉钉绑定，不得接受客户端覆盖租户、Connector 或用户 ID

#### Scenario: 客户端伪造身份字段

- **WHEN** 客户端在 URL、路由状态、表单或请求中提交与候选不同的租户、Connector、`senderStaffId` 或昵称
- **THEN** 系统 SHALL 忽略或拒绝这些字段，且不得将伪造身份绑定到任何用户

#### Scenario: 目标用户不可绑定

- **WHEN** 目标是服务账号、已停用用户、不存在用户或版本已过期
- **THEN** 系统 SHALL 拒绝绑定并返回中文可操作错误，不得修改候选或身份

#### Scenario: 候选来源 Connector 已失效

- **WHEN** 候选最近可信来源 Connector 已停用、删除或与租户不匹配
- **THEN** 系统 SHALL 拒绝绑定并要求刷新或修复渠道配置，不得猜测其它 Connector

### Requirement: 人员管理承接选择、新建和绑定

系统 SHALL 从发现列表只携带内部候选 ID 进入现有人员管理流程，并 SHALL 复用现有人员创建、人员详情和钉钉绑定界面。

#### Scenario: 选择现有人员

- **WHEN** 管理员对待绑定候选点击“去绑定”并选择一个可用自然人用户
- **THEN** 系统 SHALL 打开该用户详情中的钉钉绑定面板，并以只读方式显示服务端加载的候选身份字段

#### Scenario: 新建人员并继续绑定

- **WHEN** 管理员在候选上下文选择“新建人员并继续绑定”
- **THEN** 系统 SHALL 使用钉钉昵称预填显示名称、要求用户名，并保持邮箱和密码可选，创建成功后继续打开绑定面板

#### Scenario: 新建人员后绑定失败

- **WHEN** 人员创建成功但随后的候选绑定因冲突、并发或 Connector 状态失败
- **THEN** 系统 SHALL 保留已创建人员和当前候选上下文、显示中文错误并允许重试，不得秘密删除人员

### Requirement: 历史身份只能由原人员恢复

系统 SHALL 识别与候选相同租户和 `senderStaffId` 的停用或已解绑历史身份，以及其停用所属用户，并 SHALL 禁止将该候选绑定到其它人员。

#### Scenario: 已解绑身份再次发消息

- **WHEN** 一个软解绑的钉钉身份发送新消息
- **THEN** 候选 SHALL 显示原人员和“需恢复”状态，只提供前往原人员详情的操作

#### Scenario: 所属用户或身份已停用

- **WHEN** 候选对应身份或所属用户处于停用状态
- **THEN** 系统 SHALL 显示具体不可用状态，并要求管理员在原人员详情显式恢复适用对象

#### Scenario: 尝试把历史身份绑定给另一人员

- **WHEN** 客户端对存在历史归属的候选提交其它目标用户
- **THEN** 系统 SHALL 返回冲突错误，且不得转移、覆盖或创建重复身份

### Requirement: 绑定或恢复后立即隐藏且不回放消息

系统 SHALL 在每次候选列表、详情和计数查询时核对当前身份与用户状态；身份和所属用户均启用后 SHALL 立即排除候选，并 SHALL 只允许绑定后的新消息进入正常 Agent 流程。

#### Scenario: 候选绑定成功

- **WHEN** 管理员成功绑定候选
- **THEN** 页面 SHALL 返回发现列表、显示中文成功提示并立即刷新列表与徽标，候选 SHALL 不再出现

#### Scenario: 历史身份恢复成功

- **WHEN** 管理员使原用户和对应钉钉身份恢复为可用状态
- **THEN** 下一次候选查询和计数 SHALL 立即排除该候选

#### Scenario: 绑定后发送新消息

- **WHEN** 已完成绑定且启用的用户发送一条新钉钉消息
- **THEN** 系统 SHALL 按现有授权和路由规则处理这条新消息，不得回放候选中任何旧消息

### Requirement: 页面和徽标使用有界轮询

系统 SHALL 在发现页面处于前台时每 15 秒刷新候选，在管理端前台每 30 秒刷新侧边徽标，并 SHALL 提供手动刷新；第一版不得为此新增 WebSocket 或 SSE。

#### Scenario: 发现页面保持前台

- **WHEN** 管理员持续查看发现页面
- **THEN** 页面 SHALL 每 15 秒刷新，并允许管理员随时手动刷新

#### Scenario: 页面进入后台后恢复

- **WHEN** 浏览器页面不可见后重新进入前台
- **THEN** 系统 SHALL 在后台暂停定时请求，并在恢复前台时立即刷新

#### Scenario: 候选数量超过九十九

- **WHEN** 当前可见候选人数超过 99
- **THEN** 侧边菜单徽标 SHALL 显示 `99+`，且计数 SHALL 与列表使用相同的身份状态和 30 天过滤条件

### Requirement: 发现与绑定复用统一管理安全控制

候选列表、详情和计数 SHALL 要求已认证 Session 与 `identity:manage` 权限；绑定 SHALL 额外要求 CSRF、乐观并发和安全审计，且本变更不得新增权限模型。

#### Scenario: 无权限读取候选

- **WHEN** 未认证用户或不具备 `identity:manage` 权限的用户请求候选列表、详情或计数
- **THEN** 系统 SHALL 拒绝请求，且不得通过响应差异泄露候选是否存在

#### Scenario: 缺少 CSRF 的候选绑定

- **WHEN** 浏览器会话发起候选绑定但缺少有效 CSRF 凭据
- **THEN** 系统 SHALL 拒绝请求且不得修改用户、身份或候选

#### Scenario: 审计候选绑定结果

- **WHEN** 管理员的候选绑定成功或失败
- **THEN** 系统 SHALL 审计操作者、候选、目标用户、动作、结果和安全错误码，且不得记录消息正文或敏感材料

### Requirement: 第一版不提供回复和人工处置

系统 SHALL NOT 在未绑定钉钉用户页面提供发送消息、回复、忽略、人工删除或批量处置能力。

#### Scenario: 管理员查看候选操作

- **WHEN** 管理员查看待绑定或需恢复的候选
- **THEN** 页面 SHALL 只提供查看、筛选、刷新、去绑定或前往原人员恢复等身份管理操作

