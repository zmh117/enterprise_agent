## Why

当前 `dingtalk_search_users` 已暴露真实 Provider 响应投影问题：官方 `searchUser` 命中结果可为 userId 字符串列表，而现有实现曾把它投影为空用户对象并返回 `dingtalk_response_invalid`。同时当前 Job 只有“当前来源会话机器人消息”和“本人工作通知”，没有官方 `dingtalk-robot-send-message` Profile 中按 `userIds` 批量发送企业机器人单聊的能力，导致 Agent 即使搜索到人员也无法调用正确的发送 Tool，甚至错误改用工作通知。

本 change 需要先修复联系人命中合同，再按官方 `dingtalk-mcp@1.1.21` 的 `batchSendMessageToUsersByRobot` 设计提供一一映射的受治理 Tool。官方行为与项目治理层必须分开说明：Tool 参数和 Provider 请求遵循官方合同；Action Intent、确认卡、Publication/Job 授权和审计是本平台额外的安全边界。

## What Changes

- 修复 `dingtalk_search_users` 对官方 `searchUser` 返回的 userId 字符串列表、`hasMore` 和 `totalCount` 的固定投影；命中结果只返回 Provider 已声明的字段，人员详情继续由 Agent 显式调用 `dingtalk_get_user` 获取。
- 新增固定 mutation Tool `dingtalk_batch_send_message_to_users_by_robot`，一一映射官方 `batchSendMessageToUsersByRobot`：模型提供非空 `user_ids` 和 `msg_param={title,text}`；服务端从当前 Connector 注入 `robotCode`，并固定 `msgKey=sampleMarkdown`。
- Provider 调用固定为 `POST /v1.0/robot/oToMessages/batchSend`；系统不得加载动态 YAML、接受任意 URL/Method/Header/Credential，或把用户 Tool 参数改造成部门、全员、群、自定义机器人或 DING 发送。
- 人名请求由 Agent 按当前 Job 实际可用 Tool 编排：先 `dingtalk_search_users`，候选不能唯一识别时再调用 `dingtalk_get_user` 及必要的部门只读 Tool，得到明确 userId 后调用批量发送 Tool。MCP 服务不得在一次发送调用中隐式搜索、自动选人或执行 N+1 用户预查。
- 同名候选必须由用户明确消歧；不得根据当前发送人、昵称、历史 Job 的授权结论或模型猜测自动选择。若用户已直接提供明确 userId，则无需强制执行额外详情预查。
- 复用现有 Action Intent、确认卡、MCP 审计和 external action worker：一批调用只创建一个 Intent 和一张卡，确认后最多提交一次官方 batch Provider 请求；超时或结果不确定时不得自动重放。
- “发消息/私信”不得回退、替换或降级为 `dingtalk_send_work_notification`。现有 `dingtalk_send_robot_message` 的当前来源会话语义、`dingtalk_send_work_notification` 的本人工作通知语义及其历史 schema hash 保持不变。
- 保留历史 Tool identifier `dingtalk_send_robot_message`，但其面向用户的能力名称、描述和确认操作文案必须明确为“当前钉钉来源会话”，并指出它不支持按姓名或任意 userId 定向发送；不得因它与官方 Profile `dingtalk-robot-send-message` 名称相似而把两者描述为同一能力。
- 官方 1.1.21 YAML 未声明 `userIds` 数量上限，因此本 change 不宣称“官方最多 20 人”，也不新增臆测的固定人数上限；非空数组、标识格式和既有 Tool payload 字节上限继续提供平台有界性，Provider 的正式限制只在获得官方契约证据后另行固化。
- 本 change 只开放官方企业机器人用户批量发送；撤回、自定义机器人、DING、任意群发送不在本次范围。新增 Tool 仅通过新 Agent/Application Publication、角色 grant 和全新 Job 获得。
- apply 前对账仍在进行的 `expand-governed-dingtalk-mcp-phase-2`，先闭环并同步联系人命中修复，再实施本 change，避免两个 active change 同时声明冲突边界。

## Capabilities

### New Capabilities

- `dingtalk-targeted-user-message`: 定义官方企业机器人用户批量发送 Tool 的固定参数映射、模型驱动的人员解析链、整批一次确认和消息类型隔离。

### Modified Capabilities

- `identity-access`: 区分 Action Intent 的 actor/确认人与官方 `userIds` 收件人集合，禁止用当前发送人、姓名首个匹配或历史授权判断替代目标。
- `channel-conversation`: 保留当前来源会话机器人消息，同时增加独立的官方用户批量单聊语义，明确它不替代普通结果投递或工作通知。
- `platform-operations`: 增加官方 batch endpoint 的固定 handler、就绪门禁、联系人真实命中回归以及单人/多人确认 E2E。

## Impact

- 影响 `backend/app/shared/dingtalk_tool_contracts.py`、Tool Manifest、Publication/角色目录和 Job Snapshot；新增一个 Tool 与内部 operation，不修改现有消息 Tool schema。
- 影响 `services/dingtalk_mcp_server/provider.py`、联系人只读投影、mutation catalog、Provider client、worker dispatcher、确认摘要和审计安全摘要。
- Agent 编排测试必须覆盖“搜索 → 必要时详情消歧 → 批量发送”，并证明当前 Job 已授权的 `dingtalk_get_user` 会被实际使用，而不会复用历史 Job 的拒绝结论。
- 自动化和真实钉钉证据覆盖官方参数投影、单人/多人整批确认、拒绝、重复点击、Provider 不确定失败、旧 Publication/Job 隔离和敏感字段不落日志；不得把未经证实的人数上限描述为官方事实。
