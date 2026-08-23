## ADDED Requirements

### Requirement: Session、Job 与 Message 必须各自拥有明确事实
系统 SHALL 让 Agent Session 保存会话身份、路由边界与上下文游标，让 Agent Job 保存固定执行 provenance、授权/资源快照引用、状态、重试和结果事实，让 `agent_message` 保存有序的用户及助手消息正文。Job MAY 保存明确标注、具有版本和 hash 的不可变执行快照，但 MUST NOT 把当前可变配置或用户消息正文作为第二个可写事实源。

#### Scenario: 创建带用户消息的Job
- **WHEN** 受信 Channel event 通过创建 Job 所需的全部校验
- **THEN** 系统在同一事务中创建或解析 Session、持久化唯一有序 user message、创建引用该会话和消息事实的 Job，并创建 Job dispatch outbox
- **AND** Job 不再双写用户消息正文或旧来源影子字段

#### Scenario: 重试读取历史执行事实
- **WHEN** Worker 重试已创建的 Job
- **THEN** Worker 从 Job 固定的 provenance/快照引用和关联 message 读取执行输入
- **AND** 不从当前 Publication、当前路由配置或兼容影子列重新推导历史事实

#### Scenario: 读取迁移前历史Job
- **WHEN** 管理端读取缺少新 provenance 或消息关联的迁移前 Job
- **THEN** 系统返回明确的 `legacy_unattributed`、`legacy_message_unavailable` 或等效只读状态
- **AND** 不使用当前应用、用户映射或配置回填历史归属

### Requirement: 兼容列读写必须在 contract 前完全退出
系统 MUST 通过可重复的 parity 与引用完整性检查证明通用 Session/Job 字段和 `agent_message` 已覆盖仍需保留的历史事实，再停止旧列读回退和写双写；只有观察窗口内不存在旧列读取、写入和不一致后，contract migration 才能删除这些列。

#### Scenario: Parity 检查发现不一致
- **WHEN** 任一 Session/Job 兼容列与其通用事实、或 Job 消息影子与关联 user message 不一致
- **THEN** read/write cutover 与 contract 阶段失败关闭
- **AND** 系统输出仅包含记录标识和分类计数的安全核对证据

#### Scenario: 应用版本仍读取旧列
- **WHEN** 观察期遥测或静态查询清单显示仍有代码、脚本或报表读取兼容列
- **THEN** contract migration 不得执行
- **AND** 退役记录保持 `blocked` 并指明责任方

#### Scenario: 兼容退出完成
- **WHEN** parity、引用完整性、读切换、写切换、观察窗口、备份和回滚门禁全部通过
- **THEN** 系统可在单独授权的维护窗口执行 contract migration
- **AND** 新版本在旧列不存在时仍通过 Session、Job、Message 与重试验收

### Requirement: 不同执行阶段的运营表不得按名称合并
系统 SHALL 将 Webhook dispatch、Channel ingress、Job dispatch 与 Delivery outbox 视为不同事务边界的可靠发布事实，并 MUST 将 Runtime terminal ledger、invocation claim/event 视为幂等、所有权和恢复事实。表为空、行数较少或名称相似均不得单独构成合并或删除依据。

#### Scenario: 检查多个Outbox表
- **WHEN** schema consolidation 发现多个名称包含 `outbox` 的表
- **THEN** 系统分别登记其事务所有者、producer、consumer、幂等键和终态保留策略
- **AND** 不跨事务边界建立双写或用一个表替代另一个表

#### Scenario: Runtime恢复表当前为空
- **WHEN** 某 Runtime invocation claim/event 表在检查窗口内为零行
- **THEN** 退役评审仍须验证所有 Runtime 实现、失败恢复路径和协议契约
- **AND** 在恢复职责仍存在时保持该表及约束
