## ADDED Requirements

### Requirement: File MCP 对内容已清理的历史召回项失败关闭
`task_workspace_list_files` MUST 只列出当前 Agent Job File Manifest 快照中的条目，其中可以包含本轮时段召回、未挂接当前活动工作区的保留版本。列表和 `file_get_metadata` MUST 返回有界元数据（安全文件名、File/Version ID、`source_received_at`、版本状态），MUST NOT 返回对象键、凭据或正文。系统 MUST NOT 把 File MCP 列表扩大为当前工作区全部历史文件或 Session 内 360 天附件库；调试用全量目录不在本能力范围。

当目标精确版本或文件状态为 `CONTENT_UNAVAILABLE` 时，`file_prepare_materialization` MUST 在读取对象或返回传输控制信息之前拒绝，稳定错误码 MUST 为既有 `file_content_unavailable`（或与其安全语义一致、文案为「文件内容已不可用，请重新发送文件」的稳定码）。该拒绝 MUST NOT 使用 `file_manifest_item_denied` 冒充「不在清单中」。错误结果 MUST 只包含错误码、安全文件名和有界状态短语。系统提示 MUST 规定：收到该错误码时不得推测或编造正文，不得把「内容已清理」说成「用户没发过这份文件」。

对仅因时段召回进入清单的条目，`file_create_commit_intent` MUST 拒绝；`file_deliver_version` 在原件仍可用且清单授予 `DELIVER` 时 MUST 仍可排队交付。

#### Scenario: 列表可见已清理正文的历史项
- **WHEN** 本 Job 快照包含一份 `CONTENT_UNAVAILABLE` 的时段召回版本
- **THEN** `task_workspace_list_files` 仍返回其安全文件名、版本状态和 `source_received_at`
- **AND** 不返回可物化路径或对象位置

#### Scenario: 物化已清理正文不得报清单外
- **WHEN** RUNNING Job 对快照内 `CONTENT_UNAVAILABLE` 版本调用 `file_prepare_materialization`
- **THEN** File Service 在创建传输前拒绝，错误码为 `file_content_unavailable`
- **AND** 不得返回 `file_manifest_item_denied`

#### Scenario: 历史召回项禁止提交
- **WHEN** Agent 对未挂接当前活动工作区的时段召回 File ID 调用 `file_create_commit_intent`
- **THEN** File Service 拒绝
- **AND** 不创建 staging 对象或新版本

#### Scenario: 快照外历史附件对 File MCP 不可见
- **WHEN** 同一 Session 存在仍在保留期但未写入当前 Job 快照的附件
- **THEN** `task_workspace_list_files` 不返回该附件
- **AND** 使用其 File/Version ID 的物化请求被拒绝
