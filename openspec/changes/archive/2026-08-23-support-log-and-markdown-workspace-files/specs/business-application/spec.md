## ADDED Requirements

### Requirement: Application Publication 冻结文件格式策略版本
每个启用任务工作区的 Business Application Publication MUST 冻结代码注册的 `file_format_policy_version`，并把该版本纳入 canonical snapshot、schema version、hash、发布校验、运行时就绪和审计。历史 Publication 缺少该字段时 MUST 稳定解释为 TXT-only `text-v1`；平台 MUST NOT 因部署支持新格式而追溯扩大旧 Publication。`text-v2` MUST 只在所选 Agent Publication、Runtime protocol 和精确 File MCP Tool schema hash 均声明支持时允许发布，并由新 Job Snapshot继续冻结。

#### Scenario: 历史 Publication 在新版本部署后运行
- **WHEN** 一个历史 Publication 没有 `file_format_policy_version`且平台已部署 `text-v2`
- **THEN** Resolver仍把该Publication解释为`text-v1`
- **AND** 由它创建的新Job不能导入LOG或使用Markdown写能力

#### Scenario: 新 Publication 启用扩展文本格式
- **WHEN** 管理员发布引用兼容Runtime和File MCP schema的`text-v2` Application Publication
- **THEN** 新Job冻结`text-v2`及其格式操作矩阵
- **AND** 既有Publication、Job和重试保持原策略版本

#### Scenario: Runtime或Tool schema不支持新策略
- **WHEN** 草稿选择`text-v2`但Agent Publication的Runtime protocol或任一必需File MCP Tool schema hash不兼容
- **THEN** 保存或发布以字段级配置错误失败关闭
- **AND** 系统不自动升级Agent Publication、替换Tool hash或回退为宽松策略
