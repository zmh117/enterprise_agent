## ADDED Requirements

### Requirement: 用户搜索必须正确投影官方 userId 列表
`dingtalk_search_users` SHALL 接受官方 `searchUser` 返回的字符串 userId 列表，并把每个非空字符串投影为只含稳定 `user_id` 的声明结果；只有 Provider 实际返回声明对象时才 MAY 投影其中允许的名称和组织字段。系统 MUST 根据 `hasMore`、`totalCount`、页大小及 Provider 游标生成有界分页事实，MUST NOT 为字符串记录生成空 ID、伪造姓名或把真实命中误报为 `dingtalk_response_invalid`。

#### Scenario: 同名关键词命中两个 userId
- **WHEN** Provider 对 `dingtalk_search_users` 返回两个字符串 userId 且 `hasMore=false`
- **THEN** Tool 返回两个非空 `user_id`、`returned=2` 和 `truncated=false`
- **AND** 不返回 Provider 未提供的姓名、手机号、邮箱或其它扩展字段

#### Scenario: Provider 表示仍有下一页
- **WHEN** Provider 返回有界 userId 列表且 `hasMore=true`
- **THEN** Tool 返回当前页并明确 `truncated=true`
- **AND** Agent 不得把当前页描述为完整企业搜索结果

#### Scenario: Provider 返回无法投影的成员项
- **WHEN** 搜索列表成员既不是非空 userId 字符串也不是声明的用户对象
- **THEN** Tool 返回稳定的 Provider 合同错误
- **AND** 不生成空 userId 或根据其它字段猜测目标

### Requirement: 姓名目标必须由 Agent 显式解析并在歧义时由用户选择
当请求使用姓名而不是明确 userId 时，Agent SHALL 先调用当前 Job 已授权的 `dingtalk_search_users`。若候选不能唯一识别，Agent SHALL 再调用当前 Job 已授权的 `dingtalk_get_user`，并在必要时调用部门只读 Tool，展示稳定 userId、姓名、职务和有界部门信息，等待用户选择。选择完成前 MUST NOT 调用消息 mutation；搜索或详情失败时 MUST NOT 回退到当前发送人、首个候选或工作通知。

每次 Tool Call MUST 按当前 Job Snapshot 独立授权。Agent MUST NOT 因其它 Job 或历史轮次曾返回 `Tool is not authorized`，跳过当前 Job 实际可用的详情 Tool。用户直接提供明确 userId 时，Agent MAY 直接调用批量发送 Tool，MCP 服务不得隐式追加搜索或逐人详情请求。

#### Scenario: 两名用户具有相同姓名
- **WHEN** 搜索命中两个候选且详情显示同名或搜索结果不足以区分
- **THEN** Agent 调用详情并展示有界区分信息，请求用户选择目标
- **AND** 在选择完成前消息 mutation、Action Intent 和发送 Provider attempt 均为零

#### Scenario: 当前 Job 已授权详情 Tool
- **WHEN** 本轮 Job Snapshot 包含 `dingtalk_get_user`，但历史 Job 曾拒绝该 Tool
- **THEN** Agent 仍按本轮授权调用详情 Tool 进行消歧
- **AND** 不把历史拒绝描述为当前 Job 的能力事实

#### Scenario: 搜索返回稳定错误
- **WHEN** 用户搜索返回权限、合同或 Provider 错误
- **THEN** Agent 报告搜索未完成且不声称当前发送人是唯一候选
- **AND** 不调用工作通知或任何消息 mutation 作为回退

### Requirement: 用户批量机器人消息必须一一映射官方固定 Tool
系统 SHALL 注册 `dingtalk_batch_send_message_to_users_by_robot`，对应官方 `batchSendMessageToUsersByRobot`。模型可见输入只包含非空稳定 `user_ids` 数组和 `msg_param` 对象，其中 `msg_param` 只含有界 `title` 与 `text`。该 Tool MUST 声明 `effect=mutation`、受支持确认策略、代码固定 `dingtalk.robot.batch_send_message_to_users` operation 和显式 userId 集合目标策略。

Provider 投影 MUST 把 `user_ids` 原样映射为 `userIds`，把模型对象 `msg_param` 按官方 `extendType=json` 语义序列化为 `msgParam` JSON string，从当前 Connector 服务端注入 `robotCode`，固定 `msgKey=sampleMarkdown`，并调用 `POST /v1.0/robot/oToMessages/batchSend`。Tool MUST NOT 接受姓名、unionId、手机号、部门、全员标志、群标识、robot code、msgKey、Connector、URL、Method、Header 或 Credential。

#### Scenario: 使用明确 userId 批量发送
- **WHEN** 已授权 Agent 以一个或多个明确 userId 和合法 `msg_param` 调用该 Tool
- **THEN** 系统准备一个整批 Action Intent 和一张确认卡
- **AND** 首次调用不执行机器人发送 Provider 请求

#### Scenario: 官方字段被服务端固定
- **WHEN** 系统把已确认 Intent 投影为 Provider 请求
- **THEN** `userIds` 保持冻结成员和顺序，`msgParam` 是冻结 `msg_param` 的等价 JSON string，`robotCode` 来自当前 Connector，`msgKey` 等于 `sampleMarkdown`
- **AND** 模型不能覆盖上述服务端字段、endpoint 或 Credential

#### Scenario: 空目标或非法控制字段
- **WHEN** Tool 参数包含空 `user_ids`、空标识、非法 `msg_param`、群/部门/全员字段或网络控制字段
- **THEN** schema 或规范化在 Provider I/O 和 Intent 创建前拒绝整个请求

### Requirement: 未经证实的官方人数上限不得固化
官方 Tool 合同没有声明 `userIds` 最大项数时，系统 MUST NOT 把“最多 20 人”或其它经验值描述为官方限制，也 MUST NOT 对数组自动截断、排序、去重或拆分为多个发送请求。系统 SHALL 使用既有 Tool payload 字节上限、字段长度限制和 Provider 合同错误保持请求有界；完全相同的有序参数 MUST 生成稳定 Intent 复用键。

#### Scenario: 多人列表在全局 payload 边界内
- **WHEN** 非空 `user_ids` 与 `msg_param` 通过固定 schema 和全局 payload 字节限制
- **THEN** 系统保留成员及顺序并准备单个整批 Intent
- **AND** 不因未证实的固定人数阈值拒绝、截断或拆批

#### Scenario: 请求超过全局 payload 字节限制
- **WHEN** Tool 参数超过平台既有最大 payload 字节数
- **THEN** 系统在 Intent 创建和 Provider I/O 前失败关闭
- **AND** 不通过拆批绕过限制

### Requirement: 整批消息必须经一次确认并至多提交一次
系统 SHALL 把冻结的 `user_ids`、`msg_param`、Tool/schema/operation、Connector 与 robot code 关联存入一个有界 Action Intent，并向原 actor 发送一张确认卡。卡片 SHALL 展示操作类型、收件人数、可安全展示的候选名称或 userId 尾号以及标题正文。用户同意后，worker MUST 重新验证 actor/外部身份、企业、Connector/Credential、Publication、角色、Job Snapshot、Tool/schema/effect/policy、operation handler 和 robot code，全部满足后才可提交至多一次固定 batch 请求。

系统 MUST NOT 在发送 Tool 内隐式搜索人员或强制逐一详情预查。Provider 超时、断连或结果无法判定时 MUST 进入安全的不确定终态且不得自动重放；重复点击不得产生第二次 Provider 提交。

#### Scenario: 原用户确认整批发送
- **WHEN** 原 actor 对等待中的批量消息卡点击同意且执行前治理事实仍有效
- **THEN** worker 对冻结输入提交一次固定 batch 请求
- **AND** Intent、卡片、MCP 审计与唯一 Provider attempt 可关联

#### Scenario: 原用户取消
- **WHEN** 原 actor 对等待中的卡点击取消
- **THEN** Intent 进入拒绝终态且发送 Provider attempt 为零
- **AND** 后续重复点击不能执行

#### Scenario: 确认后授权或 Connector 漂移
- **WHEN** 确认后 actor 身份、Publication、角色、Job Tool 合同、Connector 或 robot code 任一不再匹配冻结事实
- **THEN** worker 在 batch endpoint 前失败关闭
- **AND** 不改投其它身份、Connector、收件人或消息类型

### Requirement: 机器人单聊和工作通知不得互相替换
系统 SHALL 把“发消息/私信”解释为机器人消息语义，把“工作通知”解释为工作通知语义。缺少用户批量机器人消息能力、搜索失败或同名歧义未解决时，Agent MUST 报告无法继续，MUST NOT 自动调用 `dingtalk_send_work_notification`、当前来源消息或其它写入 Tool。

#### Scenario: 用户要求向一名或多名同事发私信
- **WHEN** 每个姓名目标已经唯一解析为 userId 且新增 Tool 可用
- **THEN** Agent 调用 `dingtalk_batch_send_message_to_users_by_robot`
- **AND** 不调用 `dingtalk_send_work_notification`

#### Scenario: 目标消息 Tool 未发布
- **WHEN** 当前 Job Snapshot 不包含 `dingtalk_batch_send_message_to_users_by_robot`
- **THEN** Agent 明确报告当前 Job 缺少该能力
- **AND** 不使用语义不同的 Tool 替代

### Requirement: 现有消息能力和历史快照必须保持兼容
现有 `dingtalk_send_robot_message` SHALL 继续只面向当前来源群或当前私聊发起人，`dingtalk_send_work_notification` SHALL 继续只面向当前用户本人。新增 Tool、代码部署或 Provider 权限变化 MUST NOT 改变现有 Tool schema、operation、target policy、历史 Publication、旧 Job 或既有 Intent；只有新 Publication、角色 grant 和新 Job 的精确交集才可暴露官方用户批量消息 Tool。

#### Scenario: 旧 Job 请求向另一名用户发送
- **WHEN** 旧 Job 只冻结当前来源会话消息和本人工作通知 Tool
- **THEN** Runtime 不暴露新增用户批量消息 Tool
- **AND** Agent 不把旧 Tool 解释成等价的任意人员发送能力

#### Scenario: 新 Job 精确授权批量消息
- **WHEN** 新 Agent/Application Publication、角色和 Job Snapshot 均包含新增 Tool 的一致合同
- **THEN** Runtime 只向该 Job 暴露新增能力
- **AND** 未获授权的其它 Job 保持不变
