# 钉钉 Phase 2 Provider 合同基线（2026-08-30）

## 1. 参考版本与可信边界

- npm 包：`dingtalk-mcp@1.1.21`
- npm tarball：`https://registry.npmjs.org/dingtalk-mcp/-/dingtalk-mcp-1.1.21.tgz`
- npm `dist.shasum`：`57fbd6062e82ec4905044f5553b8b0ac6f559eff`
- tarball SHA-256：`7dd9da218e8f05f323d20522a909604fcf77521a1f90efbf0a20a9d57744c137`
- 官方仓库：`https://github.com/open-dingtalk/dingtalk-mcp`
- 核对时仓库 HEAD：`12a87ec7c999945e734d9bc507ed875f11e0d339`
- 官方概述：`https://open.dingtalk.com/document/ai-dev/dingtalk-server-api-mcp-overview`

本基线只把官方包中的七个 YAML Profile 当作 method/path/Provider 字段参考。运行时不得读取或复制这些 YAML，不得消费 `ACTIVE_PROFILES`，也不得接受模型提供的 URL、Method、Header、Credential、Profile 或服务端身份字段。项目代码中的固定合同、Provider allowlist 和测试才是运行事实源。

Provider 鉴权投影同样属于固定合同：`https://api.dingtalk.com` 新版接口使用 `x-acs-dingtalk-access-token` Header；`https://oapi.dingtalk.com` 旧版接口使用 URL 查询参数 `access_token`，不得同时把 Token 放入 Header。Token 只能由服务端 Connector 凭据换取和注入，模型参数、MCP 响应、审计及业务日志都不得包含 Token。

## 2. Profile 权限基线

| Profile | 官方公开权限/配置 | Phase 2 门禁 |
|---|---|---|
| `dingtalk-contacts` | `qyapi_addresslist_search`、`qyapi_get_member` | 应用权限及通讯录可见范围都必须满足 |
| `dingtalk-department` | `qyapi_get_department_list`、`qyapi_get_department_member` | 应用权限及部门可见范围都必须满足 |
| `dingtalk-tasks` | `Todo.Todo.Read`、`Todo.Todo.Write` | 只读工具只要求 Read；mutation 要求 Write |
| `dingtalk-calendar` | `Calendar.Event.Read`、`Calendar.Event.Write`、`Calendar.EventSchedule.Read` | 读取要求 Read/Schedule.Read；mutation 要求 Write；固定 `calendarId=primary` |
| `dingtalk-notable` | `1.1.21` 包含该 Profile，但官方包 README/仓库权限表未列出精确权限代码 | 发布前必须在当前应用的开发者后台逐 endpoint 核验授权；未知或不足时只禁用该 Profile 工具并返回稳定缺权错误，不猜测权限名 |
| `dingtalk-robot-send-message` | 企业内机器人发送消息权限；需要 Connector `robot_code` | 仅允许当前来源群或当前私聊发起人；不启用 `Premium.Ding.Write`、自定义机器人 Token 或撤回能力 |
| `dingtalk-notice` | 官方权限表未列出精确权限代码；需要应用 Agent ID | 发布前必须在开发者后台核验工作通知发送/查询权限；Connector 必须配置正整数 `work_notification_agent_id`；不足时失败关闭 |

权限名称以当前企业自建应用开发者后台显示为最终事实。代码不得因为 Profile 其它 endpoint 已授权，就推断本表中缺失的权限也已授权。

## 3. 固定工具到官方 endpoint 的映射

下表“模型字段”只列模型可提供的有界业务参数；`unionId`、`staffId`、`operatorId`、`calendarId=primary`、`robotCode`、`openConversationId`、`agent_id` 和通知接收人均由服务端事实注入。

### 3.1 Contacts / Department

| 固定 Tool | 官方工具参考 | Method / Path | 模型字段与固定投影 |
|---|---|---|---|
| `dingtalk_search_users` | `searchUser` | `POST https://api.dingtalk.com/v1.0/contact/users/search` | `query`、`offset`、`page_size<=50`、`exact_match`；固定投影 `queryWord/offset/size`，仅当 `exact_match=true` 时增加 `fullMatchField=1` |
| `dingtalk_get_user` | `getUserDetailByUserId` | `POST https://oapi.dingtalk.com/topapi/v2/user/get` | `user_id`、`language`；投影为 `userid/language` |
| `dingtalk_list_department_users` | `getDepartmentUsersByDepId` | `POST https://oapi.dingtalk.com/topapi/user/listid` | `department_id`；投影为 `dept_id` |
| `dingtalk_search_departments` | `searchDepartment` | `POST https://api.dingtalk.com/v1.0/contact/departments/search` | `query`、`offset`、`page_size<=50`；投影为 `queryWord/offset/size` |
| `dingtalk_get_department` | `getDepartmentDetail` | `POST https://oapi.dingtalk.com/topapi/v2/department/get` | `department_id`、`language`；投影为 `dept_id/language` |
| `dingtalk_list_sub_departments` | `listSubDepartments` | `POST https://oapi.dingtalk.com/topapi/v2/department/listsub` | `parent_department_id`、`language`；投影为 `dept_id/language` |

联系人响应只允许稳定用户 ID、union ID、名称、职务、部门 ID、激活/管理员状态等声明字段；手机号、邮箱、家庭地址及未知扩展字段必须删除。部门响应只投影稳定 ID、名称、父 ID 和有界组织属性。

### 3.2 Tasks

| 固定 Tool | 官方工具参考 | Method / Path | 模型字段与固定投影 |
|---|---|---|---|
| `dingtalk_list_todos` | `queryTasks` | `POST https://api.dingtalk.com/v1.0/todo/users/{unionId}/org/tasks/query` | `cursor`、`is_done`、有界 `role_types`；服务端注入当前 `unionId` |
| `dingtalk_create_todo` | `createTask` | `POST https://api.dingtalk.com/v1.0/todo/users/{unionId}/tasks` | 保持既有 `subject/description/due_time`；服务端注入当前 `unionId`，不接受任意执行人/参与人 |
| `dingtalk_update_todo` | `updateTask` | `PUT https://api.dingtalk.com/v1.0/todo/users/{unionId}/tasks/{taskId}` | `task_id/subject/description/due_time`；服务端注入当前 `unionId`，不接受执行人/参与人或 `done` |
| `dingtalk_complete_todo` | `updateTask` | `PUT https://api.dingtalk.com/v1.0/todo/users/{unionId}/tasks/{taskId}` | `task_id/subject`；服务端固定 `done=true` 并注入当前 `unionId` |

### 3.3 Calendar

| 固定 Tool | 官方工具参考 | Method / Path | 模型字段与固定投影 |
|---|---|---|---|
| `dingtalk_get_calendar_event` | `getEvent` | `GET https://api.dingtalk.com/v1.0/calendar/users/{unionId}/calendars/{calendarId}/events/{eventId}` | `event_id/max_attendees<=50`；服务端注入当前 `unionId` 与 `primary` |
| `dingtalk_list_calendar_events` | `getCalendarView` | `GET https://api.dingtalk.com/v1.0/calendar/users/{unionId}/calendars/{calendarId}/eventsview` | `time_min/time_max/page_size<=50/cursor/max_attendees<=50`；窗口不超过 31 天 |
| `dingtalk_list_calendar_attendees` | `getAttendees` | `GET https://api.dingtalk.com/v1.0/calendar/users/{unionId}/calendars/{calendarId}/events/{eventId}/attendees` | `event_id/page_size<=50/cursor` |
| `dingtalk_create_calendar_event` | `createEvent` | `POST https://api.dingtalk.com/v1.0/calendar/users/{unionId}/calendars/{calendarId}/events` | `title/description/start_time/end_time/time_zone/all_day/location`；不接受参与人、重复规则、会议或扩展配置 |
| `dingtalk_update_calendar_event` | `updateEvent` | `PUT https://api.dingtalk.com/v1.0/calendar/users/{unionId}/calendars/{calendarId}/events/{eventId}` | `event_id` 及有界标题、描述、起止时间、时区、全天、地点；body `id` 固定等于 path `eventId` |

### 3.4 AI 表格 / Notable

| 固定 Tool | 官方工具参考 | Method / Path | 模型字段与固定投影 |
|---|---|---|---|
| `dingtalk_search_aitables` | `queryNotables` | `POST https://api.dingtalk.com/v2.0/storage/dentries/search` | `query/page_size<=50/cursor`；服务端固定 `operatorId`、`dentryCategories=["alidoc"]` 和空 `creatorIds` |
| `dingtalk_list_aitable_sheets` | `getNotableAllSheets` | `GET https://api.dingtalk.com/v1.0/notable/bases/{baseId}/sheets` | `base_id`；服务端固定 `operatorId` |
| `dingtalk_get_aitable_sheet` | `getNotableSheet` | `GET https://api.dingtalk.com/v1.0/notable/bases/{baseId}/sheets/{sheetIdOrName}` | `base_id/sheet_id`；服务端固定 `operatorId` |
| `dingtalk_list_aitable_fields` | `getNotableAllFields` | `GET https://api.dingtalk.com/v1.0/notable/bases/{baseId}/sheets/{sheetIdOrName}/fields` | `base_id/sheet_id`；服务端固定 `operatorId` |
| `dingtalk_list_aitable_records` | `listNotableRecords` | `POST https://api.dingtalk.com/v1.0/notable/bases/{baseId}/sheets/{sheetIdOrName}/records/list` | `base_id/sheet_id/page_size<=100/cursor`；Phase 2 不开放官方任意结构 `filter` |
| `dingtalk_get_aitable_record` | `getNotableRecord` | `GET https://api.dingtalk.com/v1.0/notable/bases/{baseId}/sheets/{sheetIdOrName}/records/{recordId}` | `base_id/sheet_id/record_id` |
| `dingtalk_insert_aitable_records` | `insertNotableRecords` | `POST https://api.dingtalk.com/v1.0/notable/bases/{baseId}/sheets/{sheetIdOrName}/records` | `base_id/sheet_id/records[].fields`；记录数、字段数、键长和值深度/字节均受代码上限约束 |
| `dingtalk_update_aitable_records` | `updateNotableRecords` | `PUT https://api.dingtalk.com/v1.0/notable/bases/{baseId}/sheets/{sheetIdOrName}/records` | `base_id/sheet_id/records[].id/fields`；准备前与执行前用当前 operator 二次预检 |

### 3.5 Robot / Work notice

| 固定 Tool | 官方工具参考 | Method / Path | 模型字段与固定投影 |
|---|---|---|---|
| `dingtalk_send_robot_message` | `sendMessageToGroupByRobot` 或 `batchSendMessageToUsersByRobot` | 群：`POST https://api.dingtalk.com/v1.0/robot/groupMessages/send`；私聊：`POST https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend` | 仅 `title/text`；服务端按当前来源类型选择 endpoint，并注入 `robotCode`、当前 `openConversationId` 或当前发起人 `staffId`，固定 `msgKey=sampleMarkdown`；Provider 边界按官方 `extendType=json` 将 `{title,text}` 序列化为 `msgParam` JSON string |
| `dingtalk_send_work_notification` | `sendNotice` | `POST https://oapi.dingtalk.com/topapi/message/corpconversation/asyncsend_v2` | 仅 `title/text`；服务端注入 `agent_id` 与当前发起人 `userid_list`，固定 `to_all_user=false` 且不发送部门列表 |
| `dingtalk_get_work_notification_progress` | `getSendProgress` | `POST https://oapi.dingtalk.com/topapi/message/corpconversation/getsendprogress` | `task_id`；只允许查询同 actor/企业/Connector 的平台发送记录，服务端注入 `agent_id` |
| `dingtalk_get_work_notification_result` | `getSendResult` | `POST https://oapi.dingtalk.com/topapi/message/corpconversation/getsendresult` | `task_id`；关联约束同上，服务端注入 `agent_id` |

## 4. 明确排除的官方能力

固定目录不得注册：删除待办、更新任意执行人状态、删除日程、增删日程参与人、创建/更新/删除 AI 表格 sheet 或 field、删除记录、机器人/通知撤回、自定义机器人 Webhook、DING、任意用户/群/部门/全员发送，以及任何通用 Raw HTTP/YAML/Profile 工具。

## 5. 升级规则

升级官方包、变更 endpoint/字段或新增权限时，必须先更新本基线和固定 Provider 合同测试，再显式更新项目合同与 schema hash。包版本、环境变量或钉钉后台权限变化不得自动扩大 Tool 目录。
