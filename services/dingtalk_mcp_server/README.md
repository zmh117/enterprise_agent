# Governed DingTalk MCP

该服务是企业 Agent 的固定业务 MCP Server。当前发布代码内声明的 28 个
Tool：18 个只读 Tool 直接走 Principal、Job Snapshot、角色/Application 授权和统一
MCP 审计；10 个 mutation 只创建待确认 Action Intent，不直接写入钉钉。原用户在
互动卡片中同意后，独立 Worker 再次授权并按固定 operation dispatcher 执行。

## Phase 2 边界

- 固定卡片模板：`0ad7c643-7e30-4797-8284-da5ef89d3841.schema`。
- Provider method/path、输入输出 Schema、Profile、effect、operation、risk 和 target
  policy 全部由代码目录固定；运行时不加载官方 YAML 或动态 Profile。
- Tool 参数不接受当前 actor 身份 ID、Union ID、operator ID、primary calendar ID、
  robot code、openConversationId、Agent ID、URL、Method、Header 或凭据；官方用户
  批量消息 Tool 只接受显式收件人 `user_ids` 和 `msg_param={title,text}`。
- 当前本人待办、本人主日历、本人 AI 表格 operator、当前来源会话、企业机器人 Code
  和本人工作通知目标由服务端事实注入；按姓名发送由 Agent 显式执行搜索、必要时详情
  消歧再传入 userId，MCP 服务不隐式查人。删除、撤回、DING、任意群和结构修改能力
  未注册。
- 卡片使用同一企业应用的 Stream 回调，`outTrackId` 等于 Action Intent ID，并禁止转发。
- 服务端强制校验 Runtime lease、Connector、corp、点击人、意图签名、revision 和状态；端侧按钮状态不构成授权。
- `agree` 才进入 Provider 执行队列；`reject` 永不执行；`revise` 只返回“不支持”
  卡片提示，不会生成新意图。
- Provider 写入结果不确定时进入 `FAILED_UNCERTAIN`，禁止自动重放，以免重复创建待办。

## 运行组件

- `dingtalk-mcp`：Principal JWT 鉴权、输入校验、Action Intent 准备与 MCP 审计。
- `dingtalk-runtime`：每个 Client ID 的唯一 Stream 生命周期，同时接收机器人消息和卡片回调。
- `api-server`：内部 `/api/admin/managed-channels/runtime/card-actions` 快速确认端点。
- `external-action-worker`：卡片 Outbox 和已批准 Provider 操作的 claim/执行/结果更新。

生产启用前必须通过管理端配置并验证钉钉企业、Stream Connector、当前用户外部
身份、业务应用 Tool 授权和钉钉开发者后台权限。工作通知 Tool 还要求 Connector
配置正整数 `work_notification_agent_id`；管理 API 只返回配置状态和尾号提示。
凭据只使用平台 Secret 引用；不要把 Client Secret、Access Token 或原始业务消息
写入参数、日志、审计或此文档。

## 固定 Profile 与权限

- `dingtalk-contacts` / `dingtalk-department`：通讯录搜索、成员和部门读取权限及
  可见范围。
- `dingtalk-tasks`：`Todo.Todo.Read`；mutation 另需 `Todo.Todo.Write`。
- `dingtalk-calendar`：Calendar Read/Schedule Read；mutation 另需 Calendar Write。
- `dingtalk-notable`：逐 endpoint 在当前企业应用后台核验，平台不猜测权限代码。
- `dingtalk-robot-send-message`：企业机器人当前会话/用户批量发送权限；用户批量 Tool
  要求 Connector 配置企业机器人 Code，并固定调用官方 batch endpoint。
- `dingtalk-notice`：工作通知发送/查询权限和 Connector Agent ID。

权限不足统一失败关闭，不会回退到其它 Connector、Credential 或 endpoint。服务和
Compose 不消费 `ACTIVE_PROFILES`、`ROBOT_ACCESS_TOKEN`、官方 YAML 或动态 Provider
配置。官方参考版本和精确 endpoint 基线见当前 OpenSpec change 的 provider contract
artifact。

真实 E2E 必须使用明确授权的测试用户和目标，覆盖新 Publication / 新 Job、代表性只读
调用，以及每类 mutation 的 Job → 卡片 → 同意/拒绝 → 唯一 Provider attempt →
结果卡片；证据不得包含 Secret、Token 或无界业务正文。
