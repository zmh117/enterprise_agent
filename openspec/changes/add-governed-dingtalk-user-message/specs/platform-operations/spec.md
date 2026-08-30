## ADDED Requirements

### Requirement: 官方用户批量机器人消息必须具有固定 Provider 合同和就绪门禁
平台 SHALL 为 `dingtalk_batch_send_message_to_users_by_robot` 维护代码固定的 Tool/schema/effect/policy、`dingtalk.robot.batch_send_message_to_users` operation、`POST /v1.0/robot/oToMessages/batchSend` endpoint、官方字段投影和唯一 worker handler。readiness MUST 验证当前 Connector App Credential、企业状态、robot code、所需钉钉权限配置和 handler 完整性；不得通过动态 Profile、任意 HTTP 工具或字段扩展改变官方目标范围。

平台 SHALL 明确记录官方 `dingtalk-mcp@1.1.21` YAML 没有声明 `userIds` 最大项数，并 MUST NOT 在没有正式契约证据时把固定人数阈值发布为官方限制。全局 Tool payload 字节边界和字段长度边界仍须生效。

#### Scenario: operation handler 缺失或漂移
- **WHEN** Manifest 注册新增 mutation 但 worker 缺少唯一匹配 handler，或 Tool/operation/schema/policy 不一致
- **THEN** readiness 失败关闭且平台不得发布或激活该 Tool

#### Scenario: Connector 缺少机器人发送能力
- **WHEN** 当前 Connector 没有可解析 robot code、Credential 或对应 Provider 权限
- **THEN** 新 Tool 精确报告不可用
- **AND** 不回退工作通知、其它 Connector 或自定义机器人 endpoint

#### Scenario: Provider 投影发生漂移
- **WHEN** handler 未把 `user_ids` 映射为 `userIds`、未把 `msg_param` 序列化为 `msgParam` JSON string、未固定 `msgKey=sampleMarkdown`，或允许模型覆盖 `robotCode`
- **THEN** 合同或 readiness 验证失败关闭
- **AND** 不创建 Provider attempt

### Requirement: 上线证据必须覆盖真实人员解析和单人及多人发送链
上线证据 SHALL 使用当前代码、新 Agent/Application Publication、明确角色 grant 和全新钉钉 Job，验证真实命中联系人搜索、两个同名候选消歧、单人消息、多人整批消息、取消链、重复点击和旧 Job 不可见。证据 MUST 关联 Job、Tool Call、Action Intent、卡片、唯一 Provider attempt 和外部结果，且不得保存完整 userId 列表、用户完整目录、手机号、邮箱、Secret、Token、消息正文或原始 Provider 响应。

#### Scenario: 真实同名搜索成功
- **WHEN** 当前 App 可见范围内存在两个同名员工且执行联系人搜索
- **THEN** 有界证据显示两个非空 userId 候选以及后续详情消歧成功
- **AND** 不再出现因字符串列表投影导致的 `dingtalk_response_invalid`

#### Scenario: 当前 Job 的详情 Tool 被实际使用
- **WHEN** 新 Job Snapshot 已授权 `dingtalk_get_user` 且搜索结果需要消歧
- **THEN** 证据显示 Agent 在本轮实际调用详情 Tool
- **AND** 不因历史 Job 的拒绝结果跳过当前授权 Tool

#### Scenario: 单用户消息同意
- **WHEN** 原用户确认向一个明确 userId 发送
- **THEN** 证据显示唯一 Provider attempt 的接收人数为一且真实目标收到机器人消息

#### Scenario: 多用户消息整批同意
- **WHEN** 原用户明确选择多个目标并确认一次
- **THEN** 证据显示只创建一个 Intent、一张确认卡和一个 Provider batch attempt
- **AND** attempt 的有界结果表明冻结目标数量一致且真实目标均收到机器人消息

#### Scenario: 用户取消
- **WHEN** 原用户取消单人或多人确认卡
- **THEN** Intent 为拒绝终态、消息 Provider attempt 为零且卡片不可再次执行

#### Scenario: 旧 Job 验证隔离
- **WHEN** 新代码已部署但旧 Job 或旧 Publication 未包含新增 Tool
- **THEN** 新能力不可见且旧消息/工作通知语义不发生变化
