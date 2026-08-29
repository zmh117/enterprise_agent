# Governed DingTalk MCP MVP live E2E evidence

- 验证日期：2026-08-29（Asia/Shanghai）
- 卡片模板：`0ad7c643-7e30-4797-8284-da5ef89d3841.schema`
- 验证范围：真实 DingTalk Stream 消息、Agent Job、`dingtalk_create_todo`、确认卡片同意/拒绝、Provider 待办、卡片终态更新
- 证据边界：仅记录安全 ID、状态、时间和有界测试标题；不记录 Secret、Access Token、Principal JWT、原始回调或无界业务消息

## 同意并执行

- Ingress 在 `2026-08-29T14:21:52.374263+00:00` 创建 Job `job_d4690599a6cd4651ac6caae198e51188`。
- Job 状态为 `SUCCEEDED`，只执行一次 `dingtalk_create_todo` Tool；Tool Call 状态为 `SUCCEEDED`，Server 为 `dingtalk-mcp`。
- Action Intent `action_15bf2cc1f21e4db882734ed57447edc7` 在 `2026-08-29T14:21:56.824733+00:00` 创建，revision 为 `1`。
- 卡片 `CREATE` Outbox 状态为 `SUCCEEDED`、attempt 为 `1`。
- `external_action.approved` 在 `2026-08-29T14:22:12.473253+00:00` 持久记录为 `APPROVED`。
- `external_action.executed` 在 `2026-08-29T14:22:13.077606+00:00` 持久记录为 `SUCCEEDED`。
- Intent 终态为 `SUCCEEDED`，`execution_attempts=1`，存在有界结果对象。
- 卡片 `RESULT_UPDATE` Outbox 状态为 `SUCCEEDED`、attempt 为 `1`。
- DingTalk 待办界面显示新待办 `Enterprise Agent 钉钉 MCP E2E 20260829-2`，创建时间为当天 22:22，创建人与执行人均为当前测试用户。

## 拒绝且不执行

- Ingress 在 `2026-08-29T14:27:08.936615+00:00` 创建 Job `job_b0566bf91dd344579ddcaecab6733772`。
- Job 状态为 `SUCCEEDED`，只执行一次 `dingtalk_create_todo` Tool；该 Tool Call 只准备待确认意图。
- Action Intent `action_cedde36e8df04e2aae356c7cae589796` 在 `2026-08-29T14:27:12.289171+00:00` 创建，revision 为 `1`。
- 卡片 `CREATE` Outbox 状态为 `SUCCEEDED`、attempt 为 `1`。
- `external_action.rejected` 在 `2026-08-29T14:27:14.995432+00:00` 持久记录为 `REJECTED`。
- Intent 终态为 `REJECTED`，`execution_attempts=0`、execution claim owner 为空、claim expiry 为空、结果对象不存在。
- 该 Job 的 `external_action.approved` 与 `external_action.executed` 审计数量均为 `0`，因此未进入 Provider mutation。
- DingTalk 卡片界面显示“状态：已取消，不会执行”，操作按钮为禁用态。

## 结论

真实链路 `DingTalk -> Runtime -> Inbox -> Job -> MCP -> Action Intent -> Card -> Callback -> Provider/Card Result` 的同意路径通过；拒绝路径在持久回调后终止，Provider 执行次数为零。MVP 的真实同意/拒绝 E2E 验收通过。
