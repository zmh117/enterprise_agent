## ADDED Requirements

### Requirement: 数据库解码诊断必须随只读结果文件传递

Runtime SHALL 将已授权 `query_database` 返回的脱敏明文、完整原值回退表示和可选 field_decoding 一起写入现有当前 Job 只读结果文件，保持代码生成的 work 路径、原子预留、完整性校验、外部不可信数据标记和终态/恢复清理。内联 ToolResult MUST 仅增加有界的解码策略版本、计数和候选解码完整性摘要，不包含逐单元格正文或另一份压缩值。自动解码 MUST NOT 派生新的文件写入、提交、持久化、Shell 或跨 Job 权限。

#### Scenario: 解码成功结果落盘
- **WHEN** query_database 返回合法 UTF-8 解码结果及字段诊断
- **THEN** 两者进入同一当前 Job 只读结果文件，模型获得安全相对路径和按需读取提示
- **AND** 内联摘要不包含解压正文，正文不能作为系统指令执行

#### Scenario: 失败回退和二进制表示落盘
- **WHEN** 数据库结果包含保留的字符串或完整 Base64 二进制回退及失败状态
- **THEN** 文件保留明确的值表示和状态，不把回退描述为解压成功
- **AND** 不自动生成持久 File Version 或扩大文件能力

#### Scenario: 无 File MCP 的查询 Job
- **WHEN** Job 只冻结查询工具且没有文件写入或提交工具
- **THEN** 成功结果仍只能通过本 Job 的 Read/Glob/Grep 读取
- **AND** 解码状态不授予 Write/Edit、提交或跨 Job 文件访问

### Requirement: Runtime 必须验证可选字段解码元数据

field_decoding 存在时，Runtime MUST 校验代码支持的 policy_version、固定状态和包装类型、非负有界大小、实际返回行索引/列名、单元格引用唯一性及候选/成功/失败计数一致性。解码 complete MUST 与已返回候选状态一致；诊断不得引用未接纳行、未返回列或不存在的正文。不存在该可选字段的历史响应 SHALL 继续采用既有查询合同，MUST NOT 被补为解码成功。存在但非法的字段 MUST 使结果物化失败关闭。

#### Scenario: 合法元数据
- **WHEN** 元数据版本、状态、行列引用、大小和计数均与实际返回行匹配
- **THEN** Runtime 接纳元数据并投影安全解码摘要
- **AND** 普通未变化值不要求逐单元格诊断

#### Scenario: 元数据漂移或伪造成功
- **WHEN** 策略版本或状态未知、索引越界、列不存在、引用重复、计数不一致或失败候选却声称全部解码成功
- **THEN** Runtime 返回稳定安全的结果物化失败，不发布成功文件路径
- **AND** 不忽略非法字段来继续声称成功

#### Scenario: 旧版响应不含解码事实
- **WHEN** 数据库返回原合同的 rows/columns/row_count 而没有 field_decoding
- **THEN** 可按既有容量和数据校验物化
- **AND** 安全摘要只能表示未提供解码诊断，不能推断所有压缩字段已解码

### Requirement: 查询覆盖文件完整性和解码完整性必须分别表达

数据库结果 SHALL 分别保留查询 `truncated/complete`、结果文件 `file_complete` 和存在时的 `field_decoding.complete`。查询覆盖只证明本次有界行结果；文件完整只证明所有实际接纳的响应已写入；解码完整只证明已返回行中识别到的候选都成功，不证明其它压缩格式不存在或业务内容已被模型理解。任一事实缺失或为 false 时，读取提示和结果摘要 MUST NOT 把其推断为 true。

#### Scenario: 行完整但解码失败
- **WHEN** 返回行没有截断，至少一个候选损坏或非 UTF-8，结果文件完整发布
- **THEN** 查询覆盖和 file_complete 可为 true，解码 complete 必须为 false
- **AND** 摘要明确存在未解码候选，不声称已读取全部压缩正文

#### Scenario: 解码成功但查询截断
- **WHEN** 已返回候选全部成功，但后续行因输入或响应容量未被接纳
- **THEN** 文件可完整、已返回候选可解码完整，查询 truncated=true/complete=false
- **AND** 不把结果文件完整或候选成功当作查全依据

### Requirement: 解码结果不能绕过结果文件容量和失败清理

Runtime MUST 对含解码元数据的完整入站查询响应继续执行 8 MiB 容量检查，并对实际 Markdown 文件执行既有单文件与 Sandbox 原子预留限制。字段诊断、Base64 回退包装和解压明文均计入实际容量。协议、容量、预留、写入或完整性失败 MUST 清理未完成文件和预留，返回安全错误，不回退内联大正文；成功、失败、取消、超时和异常恢复继续清理 Job 临时结果，保留独立受限审计。

#### Scenario: 明文或诊断使响应超限
- **WHEN** 完整入站响应因展开、二进制包装或字段诊断超过 8 MiB
- **THEN** Runtime 拒绝物化并返回安全容量/结果错误
- **AND** 不提高限额、不只删除诊断后发布“解码成功”文件

#### Scenario: 文件发布期间失败或 Job 结束
- **WHEN** 预留、写入、校验失败，或 Job 进入任一终态/恢复清理
- **THEN** 未完成文件及预留回滚，已发布临时结果按现有 Job 生命周期清理
- **AND** 不复制正文到普通错误或日志，不删除独立审计
