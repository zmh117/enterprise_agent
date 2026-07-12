## MODIFIED Requirements

### Requirement: Agent sessions and jobs are persisted
系统 SHALL 在相关生命周期事件之前或期间，将稳定Agent session、Agent job、文本或多模态user message、assistant message、附件元数据与处理状态、重试元数据、结果摘要、失败原因、来源Channel元数据、请求人身份、routing context和reply route持久化到PostgreSQL。原始附件二进制 MUST 保存到私有对象存储而不是PostgreSQL。

#### Scenario: New text diagnostic request is accepted
- **WHEN** 一个已验证Channel文本请求通过connector和权限检查
- **THEN** 系统原子解析或创建稳定Agent session，持久化Agent job、user message、来源元数据、请求人、routing和reply route后再发布job

#### Scenario: New attachment diagnostic request is accepted
- **WHEN** 一个已验证Channel请求包含附件并通过connector和权限检查
- **THEN** 系统先持久化稳定session、等待输入的job、user message和attachment记录，再发布内部附件处理任务

#### Scenario: Agent result is produced
- **WHEN** Agent执行完成并产生最终答案
- **THEN** 系统将assistant message关联到原session和job，并持久化结果摘要、完成时间及可投递结果产物

#### Scenario: Legacy DingTalk request is accepted
- **WHEN** 一个现有钉钉兼容入口请求使用旧字段
- **THEN** 系统持久化等价通用Channel字段和稳定session归属，同时为现有读取路径保留向后兼容钉钉字段

### Requirement: Agent job status transitions are controlled
系统 SHALL 通过job应用服务控制状态转换，并至少支持WAITING_INPUT、PENDING、RUNNING、SUCCEEDED、FAILED和TIMEOUT状态。只有不含附件或附件均到达终态且存在可用输入的job才能进入PENDING。

#### Scenario: Attachment job waits for input
- **WHEN** 新job关联一个或多个仍处于下载、扫描或提取中的attachment
- **THEN** 系统保持job为WAITING_INPUT且不发布到Agent执行队列

#### Scenario: Attachment input becomes ready
- **WHEN** WAITING_INPUT job的所有attachment到达终态且文本或至少一个附件内容可用
- **THEN** 系统原子将job转为PENDING并只发布一次到Agent队列

#### Scenario: Worker claims pending job
- **WHEN** Agent worker开始执行一个PENDING job
- **THEN** 系统将job状态改为RUNNING并记录开始时间

#### Scenario: Worker completes job
- **WHEN** Agent worker产生有效最终报告
- **THEN** 系统将job从RUNNING改为SUCCEEDED并记录完成时间

#### Scenario: Worker hits timeout
- **WHEN** Agent worker超过配置执行超时
- **THEN** 系统将job改为TIMEOUT并记录安全超时原因

## ADDED Requirements

### Requirement: 附件任务与Agent执行任务使用内部标识解耦
系统 SHALL 让附件处理任务只携带内部attachment ID，让Agent执行消息继续只携带job ID和correlation ID；外部Channel payload、媒体凭证和二进制 MUST 在入站持久化或消费后留在各自受控边界内。

#### Scenario: Attachment task is dispatched
- **WHEN** 入站服务为新attachment发布处理任务
- **THEN** 任务消息只包含内部attachment ID和追踪标识，不包含钉钉临时URL、token或文件二进制

#### Scenario: Agent job is released after extraction
- **WHEN** 附件协调服务把WAITING_INPUT job释放到Agent队列
- **THEN** Agent队列消息仍只包含job ID和correlation ID，worker从持久化仓储构建完整输入

