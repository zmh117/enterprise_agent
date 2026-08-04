# 关键运行链路

## 1. 钉钉 Stream 消息到最终回复

```text
1. DingTalk SDK 把私聊／群聊消息交给固定 dingtalk-runtime。
2. Runtime 根据 Connector 配置和租约识别对应 Client，不选择 Agent。
3. Runtime 标准化消息并调用 api-server 的内部 Inbox API。
4. API 校验服务 Token、消息大小、Connector 状态、企业状态和 Corp ID。
5. 同一事务写入 channel_ingress_event 和 channel_ingress_outbox。
6. channel-dispatch-worker claim Outbox，经 RabbitMQ 取得 event ID。
7. ChannelDispatchService 恢复安全事件并调用 DingTalkStreamMessageService。
8. 解析“钉钉企业 + Staff ID”对应的启用内部用户；未知用户只形成候选。
9. BusinessApplicationResolver 按 Connector 和 routing key 命中活动 local deployment。
10. ChannelIngressService 注入 actor、会话键、应用 publication 和 reply route。
11. CreateAgentJobService 完成授权、快照和 Job Dispatch Outbox 事务。
12. job-dispatch-worker 发布 job_id；agent-worker 执行。
13. 成功或终态失败写入 artifact 和 delivery_outbox。
14. delivery-dispatch-worker 再次校验授权，分片并通过原 session webhook 或固定机器人投递。
```

群聊授权始终按当前消息实际发送人计算，不存在群级共享 ONES Token、应用访问权或默认 Team。

企业处于 `PENDING_VERIFICATION` 时，首条受信消息只用于固化 Corp ID，不创建身份候选或 Job。Corp ID 缺失／不一致、Connector 停用、身份未绑定或用户停用都必须在 Job 创建前失败关闭。

## 2. Webhook 到 Agent Job

```text
POST /webhooks/v1/{public_id}
  -> 查找已启用 Trigger Publication
  -> Bearer 认证
  -> body 大小、JSON schema、filter 和幂等检查
  -> 声明式 JSON Pointer 映射
  -> webhook_event + webhook_outbox 原子持久化
  -> webhook-worker
  -> 固定 service account + Agent Publication + Delivery Binding
  -> ChannelIngressService
  -> CreateAgentJobService
  -> 通用 Job 执行链
```

关键约束：

- 外部 payload 不能覆盖 service account、Agent、Tool、Scope、Connector、Secret 或 Delivery target；
- Grafana 只处理 `firing`，`resolved` 记录为 ignored 且不创建 Job；
- `202 Accepted` 只表示 Inbox/Outbox 已持久化，不代表 Agent 已完成；
- RabbitMQ 故障后由 Outbox 恢复，不要求发送方构造新事件 ID；
- Webhook Delivery 失败不重新运行 Agent。

## 3. 受控 Debug Job

管理端“发起调试”或 `/api/agent/jobs` 进入 `DebugJobAccessService`：

- 需要认证主体和 `agent.debug.execute` 等管理能力；
- 只允许选择服务端返回的 Application、Publication、Scope 和 Delivery option；
- 默认 Delivery 为 `none`，避免调试请求意外向外部发送结果；
- 创建后与钉钉／Webhook 共用同一 Job、Agent、Tool 和 Delivery 证据模型。

Debug API 不是公开匿名入口，也不能通过请求字段绕过业务应用、身份或 Tool 范围。

## 4. Job 创建事务

`CreateAgentJobService` 的顺序具有安全意义：

1. 规范化 requester、conversation、source channel、routing 和 reply route；
2. 检查 Business Application runtime 是否可用；
3. 检查应用访问和 Job create 权限；
4. 解析精确 Agent Publication，并验证 hash、模型连接和执行策略；
5. 校验入口／出口 Connector 与 Publication binding；
6. 计算会话隔离键和幂等键；
7. 冻结 Application／Agent／Model provenance；
8. 冻结当前外部 User ID 和默认 Team，但不冻结 Token；
9. 冻结内置 Tool 资源 scope 和 binding；
10. 创建或复用 Session；
11. 写入 Message、Job、Attachment 元数据和 Job Dispatch Outbox；
12. 提交后由独立 dispatcher 发布 RabbitMQ 消息。

如果请求带附件，Job 为 `WAITING_INPUT`，不会提前投递 Agent queue。

## 5. Agent Worker 执行

```text
RabbitMQ job_id
  -> 读取 agent_job
  -> 幂等检查终态和当前 claim
  -> Worker-start 业务授权复核
  -> RUNNING
  -> AgentContextBuilder
       ├─ 冻结 Agent Publication
       ├─ 会话摘要 + 最近消息 + READY 附件文本
       ├─ 当前可用内置 Tool 交集
       └─ 当前可用 API Capability 投影
  -> Claude Agent Runtime / stub
  -> 持久化 step、tool call、artifact、audit
  -> SUCCEEDED 或 RETRY_WAIT / FAILED / TIMEOUT
  -> enqueue Delivery
```

Agent 执行使用 Job 固定的配置，但以下事实不会被冻结绕过：

- 用户、角色、membership、应用访问是否仍有效；
- Tool／Capability Release 是否被紧急禁用；
- 外部身份、默认 Team、Team membership 和个人 Token 是否仍有效；
- 资源 revision、Secret version 和 runtime generation 是否可安全解析。

## 6. 内置只读 Tool 调用

模型可见 Tool 是多个集合的交集：

```text
代码已注册且已发布
∩ Agent Publication 已选择
∩ Application Publication 已冻结
∩ 当前用户／角色允许
∩ 当前应用和数据范围允许
∩ Job execution binding 有效
∩ Resource / Handler 未被禁用
```

典型数据库调用：

```text
Agent 先调用 context/ER 或 schema directory
  -> 从授权目录解析 environment/base/workshop
  -> 仅引用目录中存在的表和字段
  -> Internal API Platform 校验结构化地址
  -> SQLGlot 单语句与只读 AST 校验
  -> 车间表前缀／schema 可见性校验
  -> 方言正确的行数上限
  -> 只读账号 + timeout + row/byte caps
  -> 有界规范化结果
```

如果 schema directory 不具备回答问题所需字段，Agent 应回答“不具备诊断证据”，不能猜表名。

## 7. API Capability 暴露与调用

API Capability 在进入模型 Tool Catalog 前必须满足：

```text
Agent Capability Envelope 包含精确 ACTIVE Release
∩ Application Capability Allowlist 包含同一 Release
∩ 当前用户可访问应用
∩ 当前用户有启用的外部身份
∩ 默认 Team 有效
∩ 当前 Connection Revision 下个人 Token 有效
∩ Release / Handler / Connection 均未禁用
```

缺少个人身份或凭据时，能力在暴露前隐藏，并向模型提供安全的不可用提示；执行入口仍再次校验，防止暴露后状态变化的 TOCTOU 问题。

调用步骤：

1. 模型只能提交 Capability 公开 Input Schema；
2. Runtime 校验 Job、Release、主体快照和实时撤销；
3. Mapping Plan 从公开输入、固定常量和系统上下文生成请求；
4. Executor 只访问 Connection 冻结 Origin 下的相对路径；
5. 注入当前用户 Token，不允许跨 Origin redirect；
6. 按错误类型决定不重试或对 `QUERY` 进行最多两次有限退避重试；
7. 原始响应只在 attempt 内存中存在；
8. Mapping Plan 生成并校验有界 Normalized Capability Output；
9. 仅规范化结果进入 Tool Call 和模型上下文；
10. attempt 只持久化状态、耗时、大小、hash 和安全错误码。

Agent 可以用前一个 Capability 的规范化输出组织下一次公开输入，但平台不提供 Handler-to-Handler 隐式管道；每次调用都独立重新授权。

## 8. 重试与失败

### Job 执行状态

```text
PENDING -> RUNNING -> SUCCEEDED
                 |-> RETRY_WAIT -> RUNNING
                 |-> FAILED
                 +-> TIMEOUT
```

Agent retry 由 PostgreSQL 的 Job 与 Outbox 到期状态驱动。旧 RabbitMQ retry/dead queue 属于迁移兼容范围，不是当前唯一事实源。

### Job Dispatch Outbox

```text
PENDING -> RUNNING -> PUBLISHED
                 |-> RETRY_WAIT -> RUNNING
                 +-> DEAD
```

Publisher confirm 成功后才标记 `PUBLISHED`。claim 超时可恢复；人工 replay 受次数和精确记录限制。

### Delivery Outbox

```text
PENDING -> RUNNING -> SUCCEEDED / SKIPPED
                 |-> RETRY_WAIT -> RUNNING
                 |-> FAILED
                 +-> DEAD
```

每个 attempt 和 chunk 都有幂等键。Delivery 前重新校验业务应用和原 binding；权限已撤销时失败关闭，不把结果发送给旧目标。

## 9. 附件链路

```text
DingTalk attachment metadata
  -> 短时 download code AES-GCM 密文
  -> message_attachment + RabbitMQ attachment_id
  -> attachment-worker
  -> 下载 / magic bytes / 大小 / 格式检查
  -> MinIO private object
  -> 受限文本提取
  -> attachment_content
  -> 清除下载凭据
  -> 所有附件终态后，Job WAITING_INPUT -> PENDING
  -> 创建 Job Dispatch Outbox
```

附件状态主路径：

```text
PENDING -> DOWNLOADING -> EXTRACTING -> READY
                                +----> stored_not_interpreted
任意处理中状态 -----------------> REJECTED / FAILED
```

不支持的格式、宏、嵌入对象、加密／损坏文档和超限文件必须拒绝。图片当前不进入视觉模型。

## 10. 排障证据链

钉钉“无回复”时不要只看容器健康：

```text
dingtalk-runtime connection/client
  -> channel_ingress_event
  -> channel_ingress_outbox
  -> channel dispatch queue/worker
  -> agent_job + job_dispatch_outbox
  -> agent-worker + step/tool-call/artifact
  -> delivery_outbox + attempt/chunk
  -> external adapter response
```

Webhook：

```text
webhook_event auth/filter/status
  -> webhook_outbox
  -> webhook-worker
  -> agent_job
  -> tool-call/audit
  -> delivery_outbox/attempt/chunk
```

统一使用 `correlation_id`、event ID、job ID、tool call ID 和 delivery outbox ID 串联证据，不以“服务在运行”代替业务闭环证明。

## 关键源文件

- `backend/app/modules/job/application/create_agent_job_service.py`
- `backend/app/modules/job/application/job_dispatch_service.py`
- `backend/app/modules/agent/application/agent_executor.py`
- `backend/app/modules/agent/application/agent_context_builder.py`
- `backend/app/modules/api_capability/application/runtime.py`
- `backend/app/modules/delivery/application/delivery_dispatch_service.py`
- `backend/app/modules/attachments/service.py`
- `backend/app/modules/managed_channel/application/service.py`
- `backend/app/modules/webhook/application/ingress_service.py`
