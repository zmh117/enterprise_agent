## ADDED Requirements

### Requirement: Agent Session 必须使用通用 Channel 身份事实
系统 SHALL 以通用 `source_channel`、Connector ID、外部 conversation ID、内部 requester ID、会话类型、Project、Business Application ID、Application Publication ID 和 execution scope hash 作为 Agent Session 的持久化及复用事实。完成 contract 后，系统 MUST NOT 读取或写入钉钉专用 conversation/user 影子列来补全这些事实。

#### Scenario: 钉钉事件创建新会话
- **WHEN** 一个通过身份和应用路由校验的钉钉事件需要创建 Agent Session
- **THEN** 系统将钉钉来源归一为通用 Channel、Connector、conversation 与 requester 字段
- **AND** 后续上下文读取不依赖钉钉专用影子列

#### Scenario: 通用会话事实缺失
- **WHEN** contract 后的新入站事件无法唯一解析通用 Connector、conversation、requester、应用 Publication 或执行范围
- **THEN** 系统在创建 Session 和 Job 前失败关闭
- **AND** 不得通过旧影子字段或当前可变配置猜测缺失事实

## MODIFIED Requirements

### Requirement: 应用会话上下文按业务应用隔离
系统 MUST 将稳定 Business Application ID、命中的 Application Publication ID 和 execution scope hash 纳入会话复用边界，并 SHALL 按该 Publication 中已接线的 Session Policy 构造会话。Application Publication 或 execution scope 变化时 MUST 创建新会话，历史会话保持只读可追溯。

#### Scenario: 同一钉钉会话命中不同应用
- **WHEN** 两条事件具有相同外部 conversation ID 但命中不同 Business Application
- **THEN** 系统创建或复用不同的 Agent Session
- **AND** 两个应用的最近消息与会话摘要不相互泄露

#### Scenario: 同一应用升级Publication
- **WHEN** 同一应用激活新 Publication 后收到同一外部会话的新消息
- **THEN** 系统为新 Publication 创建新 Agent Session
- **AND** 旧 Session、消息和摘要保持历史只读，不进入新 Publication 的上下文

#### Scenario: 应用执行范围发生变化
- **WHEN** 同一应用 Publication 的有效 execution scope hash 与既有 Session 不同
- **THEN** 系统创建隔离 Session 并按新范围重新执行授权和上下文边界校验
