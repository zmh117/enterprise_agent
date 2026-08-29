## ADDED Requirements

### Requirement: 外部操作卡片必须通过持久 Outbox 投放
系统 SHALL 以独立 Card Outbox 保存创建、投放和结果更新意图，并使用 claim lease、attempt、退避、终态与安全错误摘要。数据库事务中 MUST NOT 获取 Access Token 或调用卡片 API。

#### Scenario: worker 投放卡片后崩溃
- **WHEN** Provider 已接受投放但本地终态尚未提交
- **THEN** 恢复器使用同一 `outTrackId` 对账或幂等重试，不生成新意图 ID

### Requirement: 外部 mutation worker 必须有独立全局并发上限
Action worker SHALL 使用跨实例数据库 claim 和可配置全局并发上限处理已批准意图；Compose scale 数量不得替代 claim、lease、heartbeat 或 readiness。

#### Scenario: 两个 worker 同时扫描同一意图
- **WHEN** 两个实例竞争同一 `APPROVED` 行
- **THEN** 只有一个实例获得有效 claim 并进入 Provider 调用

### Requirement: 确认、Provider 与卡片结果必须形成同一审计链
系统 SHALL 以 Action Intent ID、MCP call、Agent Tool Call、Job、Session、actor、Connector、Tool/schema 和 Provider attempt 串联准备、投放、点击、授权复核、执行与结果更新；不得保存 Secret 或原始无界回调。

#### Scenario: 创建待办成功
- **WHEN** 用户确认且 Provider 执行成功
- **THEN** 审计可从 Agent Tool Call 追溯到卡片点击和唯一 Provider attempt

