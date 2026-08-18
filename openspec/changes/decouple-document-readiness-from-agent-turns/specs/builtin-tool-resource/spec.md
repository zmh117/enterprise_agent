## ADDED Requirements

### Requirement: File MCP对未就绪或失败表示失败关闭
File Service 的 `file_prepare_materialization` MUST 在读取对象或返回传输控制信息之前确认目标精确版本具有可物化的 Agent 可读内容。当所需 Markdown 表示仍为处理中时，工具 MUST 返回稳定错误码 `file_readable_content_not_ready`；当处理已失败、无文字或内容不可用时，MUST 返回 `file_processing_failed` 或与现有安全拒绝一致的稳定码。错误结果 MUST 只包含错误码、安全文件名和有界状态短语，MUST NOT 包含正文片段、对象键、Docling task ID、重试次数、内部队列名或原始异常。`file_get_metadata` 和 `task_workspace_list_files` MAY 返回有界可读性状态（如 `PENDING`、`AVAILABLE`、`FAILED`），以便 Agent 发现文件存在，但 MUST NOT 把处理中文档描述为可读取正文。`file_deliver_version` 在原件已保存且具备 `DELIVER` 时 MUST NOT 因 Markdown 未就绪而拒绝。系统提示 MUST 规定：收到上述未就绪或失败码时不得推测文件内容、不得根据文件名编造正文，并告知用户可读内容尚未生成或生成失败。

#### Scenario: 按需物化处理中的文档
- **WHEN** RUNNING Job 对可读性仍为 `PENDING` 的文档版本调用 `file_prepare_materialization`
- **THEN** File Service 在创建传输前拒绝，错误码为 `file_readable_content_not_ready`
- **AND** 审计只保留文件身份、错误码和有界状态，不含正文或内部处理器标识

#### Scenario: 按需物化已失败的文档
- **WHEN** 目标版本的 processing run 已 `FAILED` 或可读性为 `UNAVAILABLE`/`NO_TEXT`
- **THEN** `file_prepare_materialization` 返回 `file_processing_failed` 或等价稳定码
- **AND** 不返回空 Markdown 冒充成功

#### Scenario: 查询处理中文件的元数据
- **WHEN** Agent 对处理中文档调用 `file_get_metadata` 或在 `task_workspace_list_files` 中看到该文件
- **THEN** 结果包含安全文件名、精确版本和有界可读性状态
- **AND** 不包含可物化路径、对象位置或派生正文

#### Scenario: 交付原件不依赖表示
- **WHEN** 原件已保存且 Manifest 授予 `DELIVER`，Agent 调用 `file_deliver_version`
- **THEN** File Service 按原始 File Version 排队交付
- **AND** 不因 Markdown 表示仍为 `PENDING` 而拒绝
