## Context

平台现有 `ones-mcp` 已证明固定 Streamable HTTP MCP、Business Principal JWT、Job/Publication/Tool/RBAC 实时复核和统一 `mcp_operation_audit` 的治理路径，但全部 Tool 都是查询。现有 `dingtalk-runtime` 以租约保证每个 Connector 只有一个 Stream Client，只接机器人消息；后端已有钉钉企业 App Secret 解析、Access Token 获取、消息投递和统一内部用户到 `user_external_identity` 的映射。

本 change 引入第一个外部副作用 Tool。用户重新导入并发布的互动卡片模板 ID 为 `0ad7c643-7e30-4797-8284-da5ef89d3841.schema`，创建与回调必须使用同一 Client ID，回调 topic 固定为 `/v1.0/card/instances/callback`。官方待办合同使用 `POST https://api.dingtalk.com/v1.0/todo/users/{unionId}/tasks`；`unionId` 必须由当前 Job 用户的受信钉钉身份解析，不能由模型传入。

## Goals / Non-Goals

**Goals:**

- 交付可运行的 `dingtalk-mcp` 骨架和一个真实 MVP Tool：为当前用户创建本人钉钉待办。
- 首次 Tool Call 只创建待确认 Action Intent；同意后异步执行，拒绝不执行。
- 将确认要求建成与 Provider 无关的代码合同，使未来 ONES mutation 无法绕过。
- 保持 Secret、Provider Token、Principal JWT 和原始回调载荷不进入模型、Tool 参数、Job、日志和审计。
- 对重复 Tool Call、重复卡片点击、worker 重启和 Provider 超时保持幂等或失败关闭。

**Non-Goals:**

- 本轮不提供钉钉文档、聊天、日历、AI 表格、待办更新/完成/删除等 Tool。
- 本轮不新增 ONES mutation Tool，只建立其必须复用的确认合同和回归门禁。
- 本轮不建设钉钉用户 OAuth/DWS Profile；MVP 使用当前企业 App Connector 和当前用户已验证的钉钉 `union_id`。
- 本轮不允许模型选择 `userId`、`unionId`、企业、Connector、Provider URL、HTTP 方法、Header 或 Token。
- “补充并重新生成”需要创建修订 Agent Job，不纳入本轮可执行链；若模板回传 `revise`，控制面返回稳定的暂不支持结果且不改变或执行原意图。该能力列入下一阶段。

## Decisions

### 1. 将准备和执行拆成持久 Action Intent

`dingtalk_create_todo` 在有效 RUNNING Job 内完成 Principal 与 Tool 复核后，规范化 `subject`、`description`、`due_time`，保存 `external_action_intent`，并返回 `confirmation_required`、安全摘要和意图 ID。它不得调用待办 Provider。

状态机为：

```text
PENDING_CONFIRMATION
  -> APPROVED -> EXECUTING -> SUCCEEDED | FAILED
  -> REJECTED
  -> EXPIRED
```

同一 `job_id + tool_identifier + normalized_arguments_hash` 唯一；Runtime 或模型重试返回已有意图。确认后 payload 不可修改，revision 不匹配、终态重复点击和过期点击均不重复执行。

备选方案是 Tool 内阻塞等待用户点击。该方案会占用 Runtime turn、Principal JWT 和 MCP HTTP 会话，无法跨重启恢复，因此不采用。

### 2. `dingtalk-mcp` 负责业务 Provider；`dingtalk-runtime` 只负责 Stream 回调

`dingtalk-mcp` 复用 `ones-mcp` 的固定 Server、Principal、Tool registry 和审计结构。其伴随 worker 从 PostgreSQL claim 已批准意图，重新复核用户、Application、Tool/schema、Connector、企业与身份后调用固定待办 endpoint。

`dingtalk-runtime` 只在现有同一个 `DWClient` 上注册 `TOPIC_CARD`，将有限字段 `outTrackId/userId/corpId/actionIds/params` 交给内部控制 API，并用 API 返回的 `cardUpdateOptions/cardData/userPrivateData` ACK。它不创建 Job、不判断 RBAC、不调用 MCP/Provider。

备选方案是在 `dingtalk-runtime` 内直接执行待办。该方案会把身份、授权和 Provider 副作用塞入连接生命周期进程，破坏 PostgreSQL 事实源，因此不采用。

### 3. 卡片投放使用 Outbox，ACK 只做状态转换

创建 Action Intent 与 `external_action_card_outbox` 在同一事务提交。worker 在事务外获取 App Access Token，按固定模板创建并投放给原始 `senderStaffId`，`outTrackId=intent_id`、`callbackType=STREAM`、`supportForward=false`。公开卡片只包含安全摘要；私有数据只包含 opaque intent token 和 revision，不包含业务凭据。

同意/拒绝回调只在短事务中校验 Connector、corp、点击人、opaque token、revision 和当前状态，并返回卡片 ACK。Provider 调用由批准后的 worker 完成，绝不在 Stream ACK 窗口内执行。

### 4. 确认 actor 来自回调与持久身份事实的交集

Action Intent 保存原始 `actor_user_id`、`source_connector_id`、DingTalk enterprise 和目标 `senderStaffId`。回调中的 `userId` 必须等于目标外部 subject，Connector/corp 必须匹配原意图，且该外部身份仍唯一映射到同一启用内部用户。卡片禁止转发只是端侧防护，不能替代服务端校验。

### 5. mutation 是代码 Manifest 的强制属性

Tool 定义新增 `effect=read|mutation` 与 `confirmation_policy=none|external_action_card_v1`。规则如下：

- `effect=read` 必须使用 `confirmation_policy=none`；
- `effect=mutation` 必须使用非空、代码注册的确认策略；
- `tool-mcp` 基础设施 Tool 继续全部只读；
- 业务 Application/角色只能选择已发布且确认策略完整的 mutation Tool；
- Job 快照在既有 input schema hash 之外独立冻结 effect 与 policy；任一漂移时准备或执行均失败关闭，且不会使历史只读 Publication 因 hash 算法变化而整体失效。

这条门禁同时适用于未来 `ones-mcp` mutation；仅在 Tool 实现里“记得发卡片”不构成授权。

### 6. MVP 待办 Provider 合同收敛为本人任务

输入仅允许：

- `subject`：1..200 字符；
- `description`：可选，最多 2000 字符；
- `due_time`：可选，带时区 ISO-8601，规范化为 Unix 毫秒。

执行时 creator 与唯一 executor 都使用服务端解析的当前用户 `union_id`。Provider host/path/method 固定；响应只保留 task ID 和安全状态。MVP 不支持任意执行人、参与人、详情 URL 或优先级伪字段。

### 7. 升级计划按风险边界分阶段

1. **MVP 后第一阶段**：将模板升级为通用字段并把组件 `disabledWhileForward=true`，增加 `queued/executing/succeeded/failed` 展示和 live E2E；实现补充信息与修订 Agent Job。
2. **第二阶段**：增加只读联系人/待办查询，再增加待办更新、完成；每个 mutation 继续走同一 Action Intent。
3. **第三阶段**：增加用户 OAuth、文档与聊天，凭据进入 `external_identity_credential`，支持多企业和共享 Token refresh lock。
4. **第四阶段**：按具体 change 增加 ONES 创建/修改/评论/状态变更 Tool；Provider Adapter 复用确认执行器，不新增通用 Raw API。

## Risks / Trade-offs

- [模板实际发布版本与导出 JSON/截图不一致] → 代码拥有固定参数映射并提供 contract test；上线前必须用指定模板做一次真实创建、同意、拒绝验收，未知 action 失败关闭。
- [用户同意后权限被撤销] → worker 在 Provider I/O 前重新读取用户、角色、Application、Tool/schema、Connector 和身份，撤权则失败且不调用 Provider。
- [Provider 超时但实际已创建待办] → 以 Action Intent ID 作为平台幂等键并保存 Provider request evidence；MVP 对不确定超时进入 `FAILED_UNCERTAIN`/人工核对，不自动重试可能产生重复的创建请求。
- [同一 Client ID 多 Stream 实例抢回调] → 继续复用现有 Connector lease 和唯一 `dingtalk-runtime`，不新建第二条 Stream 连接。
- [确认卡被转发或回调伪造] → 投放禁止转发、服务端精确校验 actor/Connector/corp/token/revision，并且卡片回调只接受持有 runtime lease 的内部入口。
- [MVP 不支持修订] → `revise` 返回稳定安全结果，不执行旧 payload；后续以独立 change 实现修订 Job，避免在本轮隐式拼接 Prompt。

## Migration Plan

1. 先部署数据库 migration、代码 Manifest 与 API；mutation Tool 在 `dingtalk-mcp` 和 worker 未 READY 前不可发布或激活。
2. 部署 `dingtalk-mcp`、action worker 和带卡片 topic 的 `dingtalk-runtime`，但不把 Tool 加入任何活动 Publication。
3. 对测试 Connector 校验应用权限、指定模板、同 Client ID 回调与唯一 Stream lease。
4. 创建新的 Agent/Application Publication 和角色授权，仅向测试用户开放 `dingtalk_create_todo`。
5. 完成真实 Job -> 卡片 -> 同意/拒绝 -> Provider -> 卡片结果的 E2E 后再扩大范围。

回滚时先撤销 Application/角色中的 Tool，再停止 worker 和 MCP 服务；保留 migration 表与不可变历史记录。未确认意图批量转为 `EXPIRED`，已批准/执行中的意图不得删除或改写。

## Open Questions

- 指定模板的线上最新变量是否与截图中的通用 `providerName/operationName/targetName/detailText/statusText` 完全一致，需要部署时用真实模板读取/投放验证；代码不得根据旧导出 JSON 静默猜测。
- 钉钉创建待办接口对相同业务键是否提供官方端到端幂等 header/字段；在没有确认前，MVP 对网络不确定结果不自动重试创建。
