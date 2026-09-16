## ADDED Requirements

### Requirement: ONES查询结果必须使用Job临时只读文件
Runtime SHALL 为当前 Job 已冻结授权的 ONES GraphQL 集合结果生成 work 下只读 Markdown 数据文件，使用统一 JobSandbox 原子容量/文件数预留及完整性校验，不形成持久 File Version。文件名 MUST 由代码生成，Provider 与模型不得指定路径。无 File MCP 的 ONES 查询 Job 只派生 Read/Glob/Grep，不授予 Write/Edit、Bash、提交或跨 Job 访问。清理 MUST 覆盖成功、失败、取消、超时及异常退出恢复扫描，且不得因此删除独立审计记录。

#### Scenario: 无文件工具的查询Job
- **WHEN** Job 仅冻结 ONES 集合工具
- **THEN** 模型仍可读取该 Job 结果文件，但无法写入、提交或读取其他 Job 文件

#### Scenario: 物化失败
- **WHEN** 文件数、容量或完整性校验不通过
- **THEN** 返回安全错误并回滚临时文件及预留，不返回成功文件位置

#### Scenario: Job结束
- **WHEN** Job 成功、失败、取消或超时
- **THEN** 查询结果随沙盒清理，恢复扫描清理无运行归属的残留目录
