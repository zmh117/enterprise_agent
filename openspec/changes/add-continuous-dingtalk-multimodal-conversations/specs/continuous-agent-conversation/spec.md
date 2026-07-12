## ADDED Requirements

### Requirement: 钉钉群聊和私聊使用稳定且隔离的会话身份
系统 SHALL 根据归一化Channel类型、connector、project、会话类型和外部身份生成稳定session key，并原子解析或创建Agent session。群聊会话 MUST 以外部群conversation为边界，私聊会话 MUST 以请求人与机器人身份为边界。

#### Scenario: 同一群聊连续发送消息
- **WHEN** 同一connector、project和钉钉群conversation先后发送两个不同事件
- **THEN** 系统将两条消息关联到同一Agent session，并分别创建幂等的Agent job

#### Scenario: 同一用户连续私聊机器人
- **WHEN** 同一用户通过同一connector和project连续私聊同一机器人
- **THEN** 系统将这些消息关联到该用户的同一私聊session

#### Scenario: 群聊和私聊标识发生碰撞
- **WHEN** 一个群聊和一个私聊出现相同外部conversation文本标识
- **THEN** 系统因会话类型和参与方不同而创建不同session，不共享聊天上下文

#### Scenario: 不同项目或connector使用相同外部会话
- **WHEN** 相同外部conversation ID出现在不同project或connector
- **THEN** 系统创建隔离session，不跨project或connector复用消息

### Requirement: 会话消息保持幂等顺序和发送人归属
系统 SHALL 为session内消息分配单调顺序，保存外部消息ID、消息角色、发送人稳定身份、展示名、消息类型和创建时间，并通过外部事件幂等阻止重复消息。

#### Scenario: 群内不同成员依次提问
- **WHEN** 两名群成员在同一群session中先后发送消息
- **THEN** 系统按确定顺序保存两条消息，并在每条消息上保留各自发送人身份

#### Scenario: 钉钉重投同一消息
- **WHEN** connector重复投递相同外部事件或消息ID
- **THEN** 系统返回已有处理结果，不新增session、message、attachment或Agent job

### Requirement: Agent获得有界连续会话上下文
系统 SHALL 在执行job前读取该job所属session的滚动摘要、摘要游标后的最近消息和可用附件文本，并在配置的消息数、单附件和总上下文预算内构造conversation context。

#### Scenario: 用户追问上一轮结论
- **WHEN** 用户在同一session中提出依赖上一轮问题和回答的追问
- **THEN** Agent上下文包含有界的前序用户/助手消息或覆盖这些消息的滚动摘要

#### Scenario: 群聊上下文被注入
- **WHEN** Agent为群session构建上下文
- **THEN** 每条历史用户消息都带发送人归属，且不会混入其他群、私聊、project或connector的消息

#### Scenario: 上下文超过预算
- **WHEN** 可用历史消息和附件文本超过配置预算
- **THEN** 系统优先保留当前问题和最近消息，使用滚动摘要覆盖更早内容，并明确标记被截断的附件片段

### Requirement: 滚动摘要可并发安全地推进
系统 SHALL 使用摘要版本和覆盖到的消息sequence原子更新滚动摘要；摘要生成失败 MUST NOT 阻止使用最近消息窗口执行当前job。

#### Scenario: 多个job同时触发摘要
- **WHEN** 同一session的两个job并发尝试推进摘要
- **THEN** 系统只提交基于当前版本的有效摘要，不倒退摘要游标或覆盖较新的摘要

#### Scenario: 摘要服务不可用
- **WHEN** 滚动摘要生成超时或失败
- **THEN** 系统记录安全失败事件，并使用受限最近消息窗口继续构建Agent上下文

### Requirement: 会话读取遵守访问控制与审计
系统 SHALL 在读取历史消息或附件文本前校验当前请求对session、project和connector范围的访问权限，并记录不含消息正文的上下文读取审计事件。

#### Scenario: 请求尝试读取其他私聊session
- **WHEN** 当前请求人没有目标私聊session的访问权限
- **THEN** 系统拒绝读取且不向Agent上下文泄漏任何目标消息或附件内容

#### Scenario: 合法上下文读取
- **WHEN** worker为授权job读取所属session历史
- **THEN** 系统返回有界上下文并记录session、job、消息范围和截断状态的安全审计摘要
