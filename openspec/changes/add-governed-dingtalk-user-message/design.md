## Context

正在实施的 `expand-governed-dingtalk-mcp-phase-2` 已建立固定 DingTalk Tool 合同、Business Principal、Action Intent、确认卡和 operation dispatcher，并把现有 `dingtalk_send_robot_message` 收敛为当前来源会话、把 `dingtalk_send_work_notification` 收敛为当前用户本人。真实联系人验收发现官方 `searchUser` 命中结果可为字符串 userId 列表，而旧 Provider 投影器只接受对象，导致真实命中产生 `dingtalk_response_invalid`。

官方 `dingtalk-mcp@1.1.21` 的 `dingtalk-robot-send-message` Profile 声明 `batchSendMessageToUsersByRobot`：必填 `userIds` 数组，`robotCode` 来自环境配置，`msgKey` 默认 `sampleMarkdown` 且不需要模型转换，`msgParam` 为包含 `title` 与 `text` 的对象，固定调用 `POST https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend`。该 YAML 没有声明 `userIds` 的最大项数。

本设计的官方基线固定为 [open-dingtalk/dingtalk-mcp](https://github.com/open-dingtalk/dingtalk-mcp) 与 [dingtalk-mcp 1.1.21 npm tarball](https://registry.npmjs.org/dingtalk-mcp/-/dingtalk-mcp-1.1.21.tgz)，实施时不得用其它版本、后台显示文案或经验值静默改写该合同。

本 change 只把上述官方能力以项目固定 Tool 合同接入现有治理链。官方参数/endpoint 与平台治理必须保持两层：前者不得改造成自创语义；后者继续负责 Job 授权、Action Intent、卡片确认、幂等、审计和安全失败。

## Goals / Non-Goals

**Goals:**

- 正确处理官方联系人搜索返回的字符串 userId、`hasMore` 和 `totalCount`，不伪造详情字段。
- 让 Agent 能按当前 Job 工具集执行“搜索 → 必要时详情消歧 → 官方批量发送”的显式多 Tool 编排。
- 提供与 `batchSendMessageToUsersByRobot` 一一映射、支持单个或多个明确 userId、整批受确认的企业机器人单聊 Tool。
- 明确官方 Tool 合同与平台 Action Intent 治理层的边界，保持现有消息能力和历史快照兼容。

**Non-Goals:**

- 不在 MCP 服务端实现“输入姓名后自动搜索并发送”的隐式流水线。
- 不声称未经官方契约证明的固定人数上限，不把平台偏好包装成官方限制。
- 不修改现有当前来源会话消息或本人工作通知 Tool 的输入 schema、operation 或目标策略。
- 不引入官方 Profile 中的撤回、自定义机器人或 DING，也不开放部门、全员、按群名或任意群发送。
- 不引入动态 YAML/Profile、通用 HTTP 执行器、用户 OAuth，或把正文、完整 userId 列表、Secret、Token、原始 Provider 响应写入普通日志和审计。

## Decisions

### 1. 固定 Tool 一一映射官方 `batchSendMessageToUsersByRobot`

新增项目命名的 `dingtalk_batch_send_message_to_users_by_robot`，内部 operation 固定为 `dingtalk.robot.batch_send_message_to_users`。模型可见输入使用项目 snake_case，但不得改变官方含义：

| 项目 Tool 输入/事实 | 官方请求字段 | 来源与约束 |
|---|---|---|
| `user_ids` | `userIds` | 模型提供的非空稳定 userId 数组，保持顺序和成员不变 |
| `msg_param.title` | `msgParam` JSON string 中的 `title` | 模型提供的有界标题；Provider 边界按官方 `extendType=json` 序列化 |
| `msg_param.text` | `msgParam` JSON string 中的 `text` | 模型提供的有界 Markdown 文本；Provider 边界按官方 `extendType=json` 序列化 |
| Connector `robot_code` | `robotCode` | 服务端事实注入，模型不可覆盖 |
| 固定常量 `sampleMarkdown` | `msgKey` | 服务端固定，模型不可覆盖 |

Tool 不接受姓名、unionId、手机号、部门、全员标志、群标识、robot code、msgKey、Connector、URL、Method、Header 或 Credential。模型输入中的 `msg_param` 保持对象；Provider client 仅在固定 batch endpoint 边界把它序列化为官方要求的 JSON string。现有 `dingtalk_send_robot_message(title,text)` 保持当前来源会话合同与 schema hash；为避免其项目历史 identifier 与官方 Profile 名称相似造成误解，只修改面向用户的能力名称、描述和确认操作文案，明确其目标是“当前钉钉来源会话”且不支持任意 userId，不重命名 identifier 或修改输入合同。

### 2. 人员解析由 Agent 显式编排，不由发送 Tool 隐式完成

`dingtalk_search_users` 对字符串成员投影为 `{"user_id": value}`，对声明对象只投影白名单字段，并根据 `hasMore`、`totalCount` 和游标产生分页事实。搜索只负责发现；`dingtalk_get_user` 负责详情。

当用户按姓名请求发送时，Agent 必须基于当前 Job Snapshot 中本轮实际可用的 Tool 编排：

```text
姓名请求
  -> dingtalk_search_users
  -> 候选能否唯一识别？
       是：取得 user_id
       否：dingtalk_get_user / 必要的部门只读 Tool -> 用户选择
  -> dingtalk_batch_send_message_to_users_by_robot
  -> Action Intent 确认
  -> 官方 batch endpoint
```

每次 Tool Call 独立进行当前 Job 授权；Agent 不得把其它 Job 或历史轮次的“未授权”结论当成本轮事实。若用户已提供明确 userId，官方发送 Tool 可直接准备，不强制执行逐人详情预查。MCP 服务端不自动搜索、不自动选中首个同名用户，也不执行 N+1 详情调用。

### 3. 不臆造官方人数上限，使用既有有界载荷治理

schema 要求 `user_ids` 至少一个元素且每项为非空稳定标识，但不声明未经官方文档证明的 `maxItems=20`。平台继续使用既有 Tool 参数/Action Intent payload 字节上限、标题正文长度限制、Provider 超限错误映射和审计摘要保证持久化与执行有界。

不对 `user_ids` 自动排序、去重或截断，因为这些变换会改变官方请求的输入语义。完全相同的有序输入生成稳定参数 hash；空数组或超出全局 payload 字节上限的请求在 Provider I/O 与 Intent 创建前拒绝。若后续获得正式官方数量上限，应以独立证据更新固定合同和测试，不从经验结果反推。

### 4. 一批一次确认，一次 Provider 提交

首次调用只创建一个 Action Intent 和一张确认卡，不调用发送 endpoint。服务端冻结规范化 `user_ids`、`msg_param`、Connector、robot code 关联和 schema/operation 事实；模型不能覆盖 `_target` 或执行事实。卡片展示操作“批量发送机器人单聊”、收件人数、可安全展示的候选名称或 userId 尾号，以及标题和正文，用户对整批进行一次同意或取消。

确认后 worker 重新验证原 actor、钉钉外部身份、企业、Connector/Credential、Publication、角色、Job Snapshot、Tool/schema/effect/policy、operation handler 和 robot code，然后最多提交一次固定 batch 请求。它不强制逐个调用用户详情 endpoint；人员名称消歧已经在 Agent 编排阶段完成，直接 userId 是官方 Tool 的合法输入。Provider 超时、连接中断或结果无法判定时进入 `FAILED_UNCERTAIN`，不得自动重放。

### 5. actor 与收件人集合分离

Action Intent 的 actor 和唯一确认人仍是原始内部用户及其钉钉身份；`user_ids` 是独立的外部收件人集合，不能获得确认权限。系统不得以当前发送人、昵称、姓名首个匹配、JWT、Credential 或历史候选替换收件人。发送前 actor 换绑、Connector/robot code/授权漂移会阻断执行，但不会改投其它身份或收件人。

### 6. 消息类型之间不得自动替换

当前来源群/私聊发起人使用现有 `dingtalk_send_robot_message`；明确 userId 集合使用新增 `dingtalk_batch_send_message_to_users_by_robot`；只有用户明确要求“工作通知”才使用 `dingtalk_send_work_notification`。搜索失败、同名尚未选择、批量 Tool 未发布或授权缺失时直接报告限制，不创建语义不同的写入 Intent。

该边界同时由 Tool 描述、Job Snapshot 授权和编排回归验证。模型能力会影响能否正确规划多步调用，但 Tool 不存在时任何模型都无法完成；Tool 已存在时也必须验证 Agent 不复用历史授权结论并能继续调用详情与发送。

### 7. 新 Publication 和全新 Job 才获得新增能力

代码部署后必须创建新 Agent Publication、Application Publication 和角色 grant；新的 Job Snapshot 才能冻结新增 Tool。worker readiness 校验 Tool/operation/handler 一一对应以及 Connector robot code/权限。旧 Publication、旧 Job 和历史 Intent 不自动获得或改用该能力。

## Risks / Trade-offs

- [同名候选缺少区分字段] → Agent 显式调用详情和必要的部门查询并要求用户选择；仍无法区分时停止，不自动选人。
- [模型规划能力不足或复用历史结论] → Tool 描述明确调用顺序，增加全新 Job 的多 Tool 编排回归；每次 Tool Call 仍由 Runtime 独立授权。
- [批量目标扩大误发半径] → 卡片展示整批目标和人数，只有原 actor 可确认，Provider 只允许一次提交；不自动截断、缩小或替换目标。
- [官方未声明数组上限] → 不编造 `20`；使用全局 payload 字节边界并保留 Provider 限制错误，获得正式文档后再固化数量上限。
- [机器人发送结果不确定] → Intent 进入 `FAILED_UNCERTAIN`，禁止自动重放并提示人工核对。
- [两个 active change 边界冲突] → 先完成并同步/归档 Phase 2，再以新 canonical baseline 校验本 change。

## Migration Plan

1. 在 Phase 2 范围修复联系人字符串 userId 与分页投影，增加真实响应合同测试并完成全新真实 Job 验收。
2. 同步并归档 `expand-governed-dingtalk-mcp-phase-2`，重新读取相关 canonical Requirement；如有冲突先修订本 change。
3. 新增官方映射 Tool、Manifest、Provider client、mutation normalizer、worker handler、卡片摘要和审计回归，保持现有 Tool 合同不变。
4. 重建受影响服务，运行定向测试、相关后端测试层、Ruff、Compose、strict OpenSpec、migration/schema 与 readiness 验证。
5. 创建新 Agent/Application Publication 和角色 grant，用全新 Job 验证搜索、必要时详情消歧、单人/多人批量发送、取消、重复点击、旧 Job 隔离和真实外部结果。

回滚时撤销新增 Tool 的 Application/角色授权并停止创建包含该 Tool 的新 Job；旧消息与工作通知 Tool 不受影响。未确认 Intent 自然过期，已确认或执行中的 Intent 按现有状态机完成或进入人工核对，不删除历史。

## Open Questions

- 实施前仍需在当前钉钉开发者后台核验该企业机器人 batch endpoint 的实际权限名称和当前 App 可用性；该现场核验不改变官方 Tool 参数，也不得用经验值臆造人数上限。
