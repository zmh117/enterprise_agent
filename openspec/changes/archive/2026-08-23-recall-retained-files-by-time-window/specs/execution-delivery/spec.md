## MODIFIED Requirements

### Requirement: Agent Job 固定文件清单但实时复核访问
Agent Job 创建事务 MUST 固定任务工作区ID和Job File Manifest中的精确File/Version ID，并将该清单以有界、无正文、无凭据形式交给所选Runtime。自动物化集合 MUST 只包含本轮确定性绑定且所需能力已经就绪的精确版本或 Markdown 表示；当前工作区其它文件以及时段召回但无需立即阅读的保留版本只提供不含正文、凭据和对象位置的元数据候选。Runtime按需物化时 MUST 由File Service重新检查RUNNING Job、当前内部用户、Business Application访问、私聊所有者或同群会话边界；不得读取清单外或之后产生的版本。处理中文档 MUST NOT 仅因出现在工作区就被写入 `auto_materialize=true`。

Job File Manifest MAY 包含未挂接当前 `ACTIVE` 工作区、但仍在聊天附件保留期内且本轮时段硬证据已绑定的精确版本。这类条目仍属于当前 Job 的冻结清单，Runtime 读取它们 MUST 视为清单内访问，MUST NOT 要求旧工作区重新变为 `ACTIVE`。系统 MUST NOT 因此授权 Runtime 枚举 Session 内全部历史附件。

#### Scenario: 执行期间当前版本变化
- **WHEN** Job固定V3后另一Job提交V4
- **THEN** 当前Runtime仍只物化V3
- **AND** 基于V3的后续提交按正常并发规则得到冲突

#### Scenario: 无关Job不自动物化处理中文档
- **WHEN** 工作区存在一份 `PENDING` 可读表示的文档，新 Job 的本轮依赖集合为空
- **THEN** Manifest 不得把该文档标为自动物化
- **AND** 该 Job 仍可执行

#### Scenario: 历史召回项在本 Job 清单内可按需读取
- **WHEN** 本 Job Manifest 含一份时段召回的保留版本，内容仍为 `AVAILABLE`，Agent 使用冻结的 File/Version ID 调用物化
- **THEN** File Service 在复核 RUNNING Job、当前用户和会话归属后允许物化
- **AND** 不得因该文件未挂接当前工作区而返回清单外拒绝

#### Scenario: 未写入本 Job 清单的历史附件仍不可读
- **WHEN** 同一 Session 另有一份仍在保留期但不在当前 Job Manifest 中的历史附件
- **THEN** Runtime 使用其 File/Version ID 请求物化必须被拒绝
- **AND** 不得把 360 天附件库当作当前工作区目录
