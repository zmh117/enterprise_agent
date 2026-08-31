# 七个启用 profile 的 Tool 契约矩阵

状态：`registered` 表示进入本系统治理目录；`excluded` 表示明确不开放；`resource` 表示官方静态说明资源而非 Provider operation；`legacy-id` 表示只为历史 Publication/Job 保留，不进入新 Publication。

## dingtalk-contacts

| 官方 Tool | 系统 identifier / 状态 | 当前且目标 Provider 契约 | 结论 |
|---|---|---|---|
| `currentDateTime` | `resource` | 本地时间资源 | 不注册为钉钉业务 Tool |
| `searchUser` | `dingtalk_search_users` | `POST /v1.0/contact/users/search`; `list/hasMore/totalCount` | registered |
| `getUserDetailByUserId` | `dingtalk_get_user` | `GET /v1.0/contact/users/batch/get?userIdList=[...]`; `userList/unauthorizedUserIdList` | registered；用最新 SDK 的 `BatchGetUser` 作单用户查询，返回安全基础详情并移除无效的 `language` 入参 |
| `getUserIdByMobile` | excluded | legacy `POST /topapi/v2/user/getbymobile` | 手机号属于不必要身份输入 |
| `getUserIdByUnionId` | excluded | legacy `POST /topapi/user/getbyunionid` | 平台主体解析不允许模型声明 unionId |
| `getDepartmentUsersByDepId` | `dingtalk_list_department_users` | legacy `POST /topapi/user/listid`; `result.userid_list` | registered；无已证实等价新接口 |

## dingtalk-department

| 官方 Tool | 系统 identifier / 状态 | 当前且目标 Provider 契约 | 结论 |
|---|---|---|---|
| `getDepartmentDetail` | `dingtalk_get_department` | legacy `POST /topapi/v2/department/get`; `result` | registered；无已证实等价新接口 |
| `searchDepartment` | `dingtalk_search_departments` | `POST /v1.0/contact/departments/search`; `list` | registered |
| `listSubDepartments` | `dingtalk_list_sub_departments` | legacy `POST /topapi/v2/department/listsub`; `result` list | registered；无已证实等价新接口 |
| `listSubDepartmentIds` | excluded | legacy `POST /topapi/v2/department/listsubid` | 已有有界详情列表，无需重复目录能力 |
| `getDepartmentParents` | excluded | legacy `POST /topapi/v2/department/listparentbydept` | 当前未纳入 |
| `getUserDepartmentParents` | excluded | legacy `POST /topapi/v2/department/listparentbyuser` | 当前未纳入 |

## dingtalk-notable

| 官方 Tool | 系统 identifier / 状态 | 目标 Provider 契约 | 结论 |
|---|---|---|---|
| `notableSupportedSearchFilters` | `dingtalk_get_aitable_supported_search_filters` | 固定官方静态资源 | registered；不访问 Provider，返回有界条件格式说明 |
| `notableSupportedFieldInfo` | `dingtalk_get_aitable_supported_field_info` | 固定官方静态资源 | registered；不访问 Provider，返回有界字段类型/属性说明 |
| `notableRecordValuesFormat` | `dingtalk_get_aitable_record_values_format` | 固定官方静态资源 | registered；不访问 Provider，返回有界记录值格式说明 |
| `queryNotables` | `dingtalk_search_aitables` | `POST /v2.0/storage/dentries/search?operatorId=...`; `items/nextToken` | registered；`operatorId` 由当前 Job 主体解析；按最新 `storage_2.0` 响应而非名称推断容器；当前治理子集只接受名称关键词，不开放模型指定创建者过滤条件 |
| `getNotableSheet` | `dingtalk_get_aitable_sheet` | `GET /v1.0/notable/bases/{base}/sheets/{sheet}?operatorId=...`; object `id/name` | registered；operator 由当前 Job 身份注入 |
| `getNotableAllSheets` | `dingtalk_list_aitable_sheets` | `GET /v1.0/notable/bases/{base}/sheets?operatorId=...`; `value` | registered；真实官方 MCP 对照可见同一 base 的数据表 |
| `listNotableRecords` | `dingtalk_list_aitable_records` | `POST /v1.0/notable/bases/{base}/sheets/{sheet}/records/list?operatorId=...`; `records/hasMore/nextToken` | registered；当前治理子集仅开放分页，不开放模型提供任意 filter |
| `getNotableRecord` | `dingtalk_get_aitable_record` | `GET /v1.0/notable/bases/{base}/sheets/{sheet}/records/{record}?operatorId=...`; object `id/fields` | registered |
| `insertNotableRecords` | `dingtalk_insert_aitable_records` | `POST /v1.0/notable/bases/{base}/sheets/{sheet}/records?operatorId=...`; `value[].id` | registered；Action Intent 冻结资源与当前 operator，确认后重授权 |
| `updateNotableRecords` | `dingtalk_update_aitable_records` | `PUT /v1.0/notable/bases/{base}/sheets/{sheet}/records?operatorId=...`; `value[].id` | registered；Action Intent 冻结资源与当前 operator，确认后重授权 |
| `getNotableAllFields` | `dingtalk_list_aitable_fields` | `GET /v1.0/notable/bases/{base}/sheets/{sheet}/fields?operatorId=...`; `value` | registered |
| `updateNotableSheetName` | `dingtalk_update_aitable_sheet` | `PUT /v1.0/notable/bases/{base}/sheets/{sheet}?operatorId=...`; object `id/name` | registered；逐次确认 |
| `createNotableSheet` | `dingtalk_create_aitable_sheet` | `POST /v1.0/notable/bases/{base}/sheets?operatorId=...`; object `id/name` | registered；逐次确认，可带有界字段定义 |
| `deleteNotableSheet` | excluded | `DELETE /v1.0/notable/.../sheets/{sheet}?operatorId=...` | 删除能力排除 |
| `deleteNotableRecords` | excluded | `POST /v1.0/notable/.../records/delete?operatorId=...` | 删除能力排除 |
| `createNotableField` | `dingtalk_create_aitable_field` | `POST /v1.0/notable/.../fields?operatorId=...`; object `id/name/type/property` | registered；逐次确认 |
| `deleteNotableField` | excluded | `DELETE /v1.0/notable/.../fields/{field}?operatorId=...` | 删除能力排除 |
| `updateNotableField` | `dingtalk_update_aitable_field` | `PUT /v1.0/notable/.../fields/{field}?operatorId=...`; object `id` | registered；逐次确认 |

## dingtalk-calendar

| 官方 Tool | 系统 identifier / 状态 | Provider 契约 | 结论 |
|---|---|---|---|
| `createEvent` | `dingtalk_create_calendar_event` | `POST /v1.0/calendar/users/{union}/calendars/primary/events` | registered |
| `updateEvent` | `dingtalk_update_calendar_event` | `PUT /v1.0/calendar/users/{union}/calendars/primary/events/{event}` | registered |
| `getEvent` | `dingtalk_get_calendar_event` | `GET .../events/{event}` | registered |
| `getAttendees` | `dingtalk_list_calendar_attendees` | `GET .../events/{event}/attendees`; `attendees/nextToken` | registered |
| `getCalendarView` | `dingtalk_list_calendar_events` | `GET .../eventsview`; `events/nextToken` | registered |
| `deleteEvent` | excluded | `DELETE .../events/{event}` | 删除能力排除 |
| `addAttendee` | excluded | `POST .../events/{event}/attendees` | 当前未纳入 |
| `removeAttendee` | excluded | `POST .../events/{event}/attendees/batchRemove` | 当前未纳入 |

## dingtalk-tasks

| 官方 Tool | 系统 identifier / 状态 | Provider 契约 | 结论 |
|---|---|---|---|
| `queryTasks` | `dingtalk_list_todos` | `POST /v1.0/todo/users/{union}/org/tasks/query`; `todoCards/nextToken` | registered |
| `createTask` | `dingtalk_create_todo` | `POST /v1.0/todo/users/{union}/tasks` | registered；当前治理子集只支持本人待办的标题、描述和截止时间，不开放任意执行人/参与人 |
| `updateTask` | `dingtalk_update_todo` | `PUT /v1.0/todo/users/{union}/tasks/{task}` | registered；当前治理子集只更新标题、描述和截止时间，完成状态由独立 Tool 处理 |
| `updateExecutorsTaskStatus` | `dingtalk_complete_todo` | `PUT /v1.0/todo/users/{union}/tasks/{task}/executorStatus` | registered；只把当前本人 executor 标记完成，不替他人更新或重新打开 |
| `deleteTask` | excluded | `DELETE /v1.0/todo/users/{union}/tasks/{task}` | 删除能力排除 |

## dingtalk-robot-send-message

| 官方 Tool | 系统 identifier / 状态 | Provider 契约 | 结论 |
|---|---|---|---|
| `sendMessageToGroupByRobot` | `dingtalk_send_message_to_group_by_robot` | `POST /v1.0/robot/groupMessages/send`; `processQueryKey` | registered；当前治理子集固定标题+正文的 markdown 普通消息；当前来源群由受信 Job route 补全；返回键只证明请求已受理，不宣称最终送达 |
| `batchSendMessageToUsersByRobot` | `dingtalk_batch_send_message_to_users_by_robot` | `POST /v1.0/robot/oToMessages/batchSend`; `processQueryKey/filteredStaffIdList/flowControlledStaffIdList/invalidStaffIdList` | registered；固定标题+正文的 markdown 普通消息；明确 `user_ids` 批量单聊；“全部匹配者”把全部已核实 ID 放入同一批，单数歧义才要求选择；按三类未受理名单并集计算受理数，结果不回显收件人 ID |
| 旧平台泛化 Tool | `dingtalk_send_robot_message` / legacy-id | 历史实现按当前群或当前私聊分派 | 新 Publication 排除，历史快照不改写 |
| `recallGroupMessageByRobot` | excluded | `POST /v1.0/robot/groupMessages/recall` | 撤回能力排除 |
| `batchRecallToUsersMessageByRobot` | excluded | `POST /v1.0/robot/oToMessages/batchRecall` | 撤回能力排除 |
| `sendMessageToGroupByCustomRobot` | excluded | legacy webhook +独立 access token | 不进入企业应用机器人凭据边界 |

## dingtalk-notice

| 官方 Tool | 系统 identifier / 状态 | Provider 契约 | 结论 |
|---|---|---|---|
| `sendNotice` | `dingtalk_send_work_notification` | legacy `POST /topapi/message/corpconversation/asyncsend_v2`; `task_id` | registered；当前仅本人目标，无已证实等价新接口；`task_id` 只证明异步任务已提交，最终结果由进度/结果接口回查 |
| `getSendResult` | `dingtalk_get_work_notification_result` | legacy `POST /topapi/message/corpconversation/getsendresult`; `send_result` 的无效/流控/失败/已读/未读用户和无效部门列表 | registered；仅从官方列表派生各类总数，列表最多返回 50 项并用 `truncated` 明示截断，不臆造发送状态 |
| `getSendProgress` | `dingtalk_get_work_notification_progress` | legacy `POST /topapi/message/corpconversation/getsendprogress`; `progress.progress_in_percent/status(0..2)` | registered |
| `recallNotice` | excluded | legacy `POST /topapi/message/corpconversation/recall` | 撤回能力排除 |

## 数量闭合

- 新 Publication 注册：35 个（21 read + 14 mutation）。
- legacy identifier：1 个，只供历史快照解析。
- 官方 profile 中的其余 Tool：全部被标为 excluded；不存在未分类项。
- 所有有界列表在裁剪前计算 `truncated`；Tool 输出要求存在非空的核心业务字段（例如部门名、待办标题、日程标题及起止时间、AI 表格/数据表/字段名与类型、记录字段）。
- 模型描述对官方能力和平台治理子集分别陈述：待办字段/目标、日程详情字段白名单与更新字段、AI 表格名称搜索/记录分页、机器人 markdown 格式均不得让模型误以为支持官方更广参数。
- 更新日程必须回显相同 `event_id`；AI 表格插入必须返回与请求数量一致且唯一的 record ID，更新必须返回与请求完全相同的 record ID 集合，否则按响应漂移失败关闭。
- AI 表格名称搜索和 notable v1 资源读写都由服务端注入当前 Job 的 `operatorId`；模型描述、Provider 签名、Action Intent 和 worker 重授权不得接受模型声明 operator。
