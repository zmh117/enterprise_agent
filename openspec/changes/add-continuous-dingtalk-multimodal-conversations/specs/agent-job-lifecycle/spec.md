## MODIFIED Requirements

### Requirement: Agent sessions and jobs are persisted
系统 SHALL 将稳定session、job、文本或多模态user message、assistant message、附件元数据/状态、重试、结果、来源、请求人、routing和reply route持久化到PostgreSQL；原始附件 MUST 保存到私有对象存储。

#### Scenario: New text request is accepted
- **WHEN** 已验证文本请求通过connector和权限检查
- **THEN** 系统原子解析或创建session并在发布job前持久化消息与job元数据

#### Scenario: New attachment request is accepted
- **WHEN** 已验证请求包含附件并通过检查
- **THEN** 系统持久化WAITING_INPUT job、user message和attachment后发布内部附件任务

#### Scenario: Agent result is produced
- **WHEN** Agent产生最终答案
- **THEN** 系统将assistant message关联原session/job并持久化结果、完成时间和投递产物

#### Scenario: Legacy DingTalk request is accepted
- **WHEN** 兼容入口使用旧字段发送文本请求
- **THEN** 系统持久化等价通用字段和稳定session归属并保留旧读取字段

### Requirement: Agent job status transitions are controlled
系统 SHALL 通过job应用服务控制WAITING_INPUT、PENDING、RUNNING、SUCCEEDED、FAILED和TIMEOUT。只有无附件或附件均终态且有可用输入的job才能进入PENDING。

#### Scenario: Attachment job waits
- **WHEN** job仍有下载或提取中的attachment
- **THEN** job保持WAITING_INPUT且不发布到Agent队列

#### Scenario: Attachment input becomes ready
- **WHEN** 所有attachment终态且存在文本或可用附件文本
- **THEN** 系统原子转PENDING并只发布一次

#### Scenario: No understandable input remains
- **WHEN** job只有不可理解图片或全部附件失败且无文本
- **THEN** 系统不调用模型并以安全结果完成失败投递

#### Scenario: Worker claims and completes job
- **WHEN** worker成功执行一个PENDING job
- **THEN** 系统依次记录RUNNING和SUCCEEDED及开始/完成时间

#### Scenario: Worker hits timeout
- **WHEN** worker超过执行超时
- **THEN** 系统记录TIMEOUT和安全超时原因

## ADDED Requirements

### Requirement: 附件任务与Agent任务只使用内部标识
系统 SHALL 让附件任务只携带attachment ID，让Agent任务继续只携带job ID和correlation ID；外部payload、媒体凭证和二进制 MUST 留在受控边界内。

#### Scenario: Attachment task is dispatched
- **WHEN** 入口发布附件处理任务
- **THEN** 消息只包含内部attachment ID和追踪标识

#### Scenario: Agent job is released
- **WHEN** WAITING_INPUT job被释放到Agent队列
- **THEN** 队列仍只包含job ID和correlation ID，worker从仓储构建输入
