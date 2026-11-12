## ADDED Requirements

### Requirement: ONES 消息必须自动有界读取历史时间线
ones_list_work_item_messages SHALL 只接受 work_item_uuid，在当前 Job 和本人默认 Team 授权下调用固定 GET messages；内部每页 count=100，以上一页末条 send_time 作为下一页排他 max，按唯一微秒时间严格倒序收集至 has_next=false、1000 条或 50 页。模型 MUST NOT 传 limit、cursor、since、max 或 Provider 地址。90 秒和 8 MiB 规范化结果预算 MUST 限制读取；协议、权限、网络或预算失败不得发布部分成功文件。结果 SHALL 经既有 Job 只读临时文件传递，结束清理。

#### Scenario: 多页包含早期关键评论
- **WHEN** 第一页 has_next=true 且更早一页记录关键处理结论
- **THEN** 服务自动以精确排他 max 读取后续页，保留评论、状态变更等安全投影及时间顺序

#### Scenario: 达到数量或页数上限
- **WHEN** 收集达 1000 条或 50 页且仍有后续
- **THEN** 返回实际收集数、覆盖起止时间、页数及对应未完整原因，不把当前页 count 当作全量总数

#### Scenario: 分页异常或失败
- **WHEN** 重复 UUID、非递减边界、空续页、页条数错误、后续权限/网络错误或预算耗尽
- **THEN** 有界安全失败，不发布之前的页面为完整集合，不输出原始响应、认证信息或内部 URL

### Requirement: ONES 详情与消息必须披露内容完整性
详情 SHALL 显式返回 description_truncated 和 related_items_truncated；消息正文 SHALL 保留脱敏、安全纯文本和 16000 字符单条上限，并逐条记录 text_truncated。消息结果及 Runtime 摘要 MUST 包含消息集合完整性、正文截断计数、整体 complete、incomplete_reasons、页数与覆盖起止时间。安全投影的 complete MUST NOT 代表附件正文完整或模型已阅读整个临时文件；Agent 对未读取部分必须明确说明。

#### Scenario: 长评论被截断
- **WHEN** 已收齐消息但某条评论超过正文上限
- **THEN** messages_complete=true，text_truncated_count 大于零，complete=false，摘要和文件均保留正文截断原因

#### Scenario: 完整消息投影
- **WHEN** has_next=false 且正文未截断
- **THEN** complete=true，并说明仅覆盖所取时间线及安全投影，附件内容未读取
