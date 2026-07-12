## ADDED Requirements

### Requirement: 群聊和私聊使用稳定且隔离的会话身份
系统 SHALL 根据Channel、connector、project、会话类型和外部身份生成稳定session key并原子解析或创建session。群聊 MUST 以外部群conversation为边界，私聊 MUST 以请求人和机器人身份为边界。

#### Scenario: 同一群聊连续提问
- **WHEN** 同一connector、project和群conversation先后发送不同事件
- **THEN** 系统将消息关联到同一session，并为每个新事件创建幂等job

#### Scenario: 同一用户连续私聊
- **WHEN** 同一用户通过同一connector和project连续私聊同一机器人
- **THEN** 系统复用该用户的私聊session

#### Scenario: 会话标识跨范围碰撞
- **WHEN** 相同外部标识出现在不同会话类型、project或connector
- **THEN** 系统创建隔离session且不共享上下文

### Requirement: 会话消息保持幂等顺序和发送人归属
系统 SHALL 为session内消息分配单调sequence，保存外部消息ID、角色、发送人身份、展示名、类型和时间，并通过外部事件幂等阻止重复消息。

#### Scenario: 群内不同成员依次提问
- **WHEN** 两名群成员在同一群session中先后发送消息
- **THEN** 系统按确定顺序保存两条消息并保留各自发送人

#### Scenario: 钉钉重投同一消息
- **WHEN** connector重复投递相同事件或消息ID
- **THEN** 系统返回已有结果且不新增session、message、attachment或job

### Requirement: Agent获得有界连续上下文
系统 SHALL 从PostgreSQL读取当前session的滚动摘要、摘要游标后的最近消息和可用附件文本，并按配置的消息数、单附件和总上下文预算构造conversation context。

#### Scenario: 用户追问上一轮结论
- **WHEN** 同一session中的问题依赖前序问题和回答
- **THEN** Agent上下文包含相关最近消息或覆盖这些消息的滚动摘要

#### Scenario: 群聊上下文被注入
- **WHEN** Agent为群session构建上下文
- **THEN** 历史用户消息带发送人归属且不混入其他群、私聊、project或connector内容

#### Scenario: 上下文超过预算
- **WHEN** 历史消息和附件文本超过配置预算
- **THEN** 系统优先保留当前问题与最近消息，使用摘要覆盖更早内容并标记截断

### Requirement: 滚动摘要可并发安全推进并允许降级
系统 SHALL 使用摘要版本和覆盖到的message sequence原子更新摘要；摘要失败 MUST NOT 阻止使用最近消息窗口执行当前job。

#### Scenario: 并发job更新摘要
- **WHEN** 同一session的两个job并发推进摘要
- **THEN** 系统只提交当前版本的有效摘要且不倒退摘要游标

#### Scenario: 摘要生成失败
- **WHEN** ConversationSummarizer超时或失败
- **THEN** 系统记录安全失败并使用受限最近消息窗口继续

### Requirement: 连续上下文读取遵守权限和审计
系统 SHALL 在读取历史消息或附件文本前校验session、project、connector和请求人权限，并记录不含正文的读取审计。

#### Scenario: 请求读取其他私聊
- **WHEN** 请求人没有目标私聊session权限
- **THEN** 系统拒绝读取且不泄漏消息、摘要或附件内容

#### Scenario: 合法上下文读取
- **WHEN** worker为授权job读取所属session历史
- **THEN** 系统返回有界上下文并审计消息范围和截断状态
