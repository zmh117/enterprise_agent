## ADDED Requirements

### Requirement: Stream 消息携带并校验企业上下文
系统 MUST 从受信钉钉 Stream 消息提取应用连接、`senderCorpId`、`chatbotCorpId`、`senderStaffId`、`senderNick`、事件时间和稳定事件 ID，并在进入身份解析前校验连接所属企业；企业字段不得由客户端管理请求或消息正文覆盖。

#### Scenario: 已验证企业收到正常消息
- **WHEN** 启用连接收到 SDK 认证消息，且两个 Corp ID 与所属 `ACTIVE` 企业一致
- **THEN** 系统将企业内部 ID 和受信身份字段写入规范化 Channel Event，继续身份解析

#### Scenario: 消息缺少 Staff ID
- **WHEN** 受信事件缺少可用 `senderStaffId`
- **THEN** 系统拒绝身份解析且不创建候选、身份、观察或 Agent Job

### Requirement: 待验证企业消息只能形成验证证据
所属企业为 `PENDING_VERIFICATION` 时，Stream worker MUST 将满足条件的受信测试消息交给企业验证流程，并 MUST 阻止其进入普通 Channel Dispatch、身份发现、Application Access 和 Agent Job 流程。

#### Scenario: 待验证消息完成 Corp ID 验证
- **WHEN** 同一受信测试消息包含非空且相等的 `senderCorpId` 与 `chatbotCorpId`
- **THEN** 系统固化企业 Corp ID 并确认消息，不创建 Channel Outbox、身份候选或 Agent Job

#### Scenario: 待验证消息包含业务问题
- **WHEN** 测试消息正文同时看起来像普通 Agent 请求
- **THEN** 系统仍只执行企业验证，不调用模型或 API Capability，并提示管理员验证成功后重新发送业务消息

### Requirement: Corp ID 不一致时失败关闭并治理告警
已验证企业的任何应用连接收到缺失或不匹配的 Corp ID 时，系统 MUST 拒绝该消息、阻止身份与 Job 写入并产生安全治理告警；系统不得自动修改企业或连接归属。

#### Scenario: 后续应用实际属于另一企业
- **WHEN** 新应用连接收到的受信消息 Corp ID 与所选企业不同
- **THEN** 系统拒绝消息并把连接标记为企业校验错误，告警不包含消息正文或认证材料

#### Scenario: 重连后收到不匹配消息
- **WHEN** Stream 重连成功后第一条消息的 Corp ID 与企业不一致
- **THEN** 重连状态不得绕过企业校验，系统仍拒绝分发

### Requirement: 非活动企业不处理业务 Stream 消息
所属企业为 `DISABLED` 或 `ARCHIVED` 时，系统 MUST 停止或拒绝其全部应用连接的业务入口；已有连接心跳或 SDK 回调不得使企业自动恢复。

#### Scenario: 企业停用时仍收到 SDK 回调
- **WHEN** 停用动作与在途 Stream 消息并发
- **THEN** 消息在持久化 Job 前重新校验企业状态并失败关闭

#### Scenario: 只重新启动 Runtime
- **WHEN** 管理员重启已停用或归档企业的连接 Runtime
- **THEN** 系统不恢复业务处理，必须完成显式企业恢复和 Corp ID 复验

### Requirement: 企业校验参与 Stream 幂等确认
Stream 重试和重连 MUST 使用稳定事件 ID 保持企业验证与业务分发幂等；同一事件不得既被用作企业验证又在重试时创建业务 Job。

#### Scenario: 企业验证事件被重投
- **WHEN** 完成企业验证的测试事件再次到达
- **THEN** 系统返回已有验证确认且不进入业务分发

#### Scenario: 正常业务事件被重投
- **WHEN** `ACTIVE` 企业的同一业务事件重复到达
- **THEN** 系统复用现有 Channel Event 或 Job 结果，不重复更新昵称审计、观察记录或创建 Job
