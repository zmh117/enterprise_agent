## ADDED Requirements

### Requirement: 大工作区Application Publication必须冻结兼容文件发现Tool
新建或发布启用任务工作区的Application Publication时，若其面向的tenant有效工作区文件上限可能超过20，系统 MUST要求所选Agent Publication Tool Envelope包含`task_workspace_search_files`固定identifier/schema hash，并要求Application显式选择该Tool及既有必要File MCP Tool。缺少兼容Tool时发布或Job创建 MUST失败关闭，不得回退为全工作区Manifest或不完整文件认知。

工作区文件数量配额属于平台/tenant治理策略，Application Publication MUST NOT保存、复制或覆盖默认200、tenant有效值或平台硬上限1000。Publication只冻结是否具备有界发现和物化能力。

#### Scenario: 发布兼容大工作区Application
- **WHEN** Agent Tool Envelope包含新发现Tool且Application显式选择全部必要File MCP Tool
- **THEN** 发布校验允许形成新的不可变Application Publication
- **AND** Publication保存精确Tool identifier/schema hash但不保存tenant配额数值

#### Scenario: 缺少发现Tool却面向大工作区
- **WHEN** tenant有效上限超过20且Application Publication未冻结兼容发现Tool
- **THEN** 系统拒绝发布或拒绝在超过20个ACTIVE文件的工作区创建Job
- **AND** 不把数百个文件写回Manifest作为兼容fallback

#### Scenario: tenant配额后来发生变化
- **WHEN** 已发布Application保持不变而tenant配额从200降低到100
- **THEN** Publication身份和Tool Snapshot保持不变
- **AND** File Service按当前tenant有效配额处理后续文件创建并在Job审计记录配置revision

#### Scenario: 历史Publication处理小工作区
- **WHEN** 历史Publication没有新发现Tool且当前工作区ACTIVE文件数不超过20
- **THEN** 系统保持既有Manifest-only兼容行为
- **AND** 不向该Job授予运行中动态选择Manifest外文件的能力
