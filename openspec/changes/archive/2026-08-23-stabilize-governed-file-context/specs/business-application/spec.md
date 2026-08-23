## ADDED Requirements

### Requirement: 文档处理 Profile 必须在控制面闭合依赖
Business Application 草稿选择 `docling-text-v1` 时，系统 MUST 在保存草稿、发布校验和激活前同时验证任务工作区、File MCP、消息附件、连续会话、所需 File MCP 读取工具以及所选 Python Agent Publication 的文件上下文 Runtime 兼容性。任一依赖缺失时 MUST 返回稳定字段级错误且不得创建部分草稿、Publication 或 Deployment；历史不可变快照不得被追溯改写。

#### Scenario: Docling Profile 缺少任务工作区
- **WHEN** 客户端提交 `document_processing_profile_code=docling-text-v1` 且 `workspace_enabled=false`
- **THEN** 后端以任务工作区字段级错误拒绝保存
- **AND** 不把错误推迟到附件 Job 创建阶段

#### Scenario: Docling Profile 缺少 File MCP 或读取工具
- **WHEN** Docling Profile 已选择但 File MCP 未启用、Agent Publication 未冻结所需读取工具或 Application 未选择这些工具
- **THEN** 后端以对应 feature、Agent Publication 或 MCP Tool 字段级错误拒绝保存和发布

#### Scenario: Docling Profile 会话依赖关闭
- **WHEN** Docling Profile 已选择但消息附件或连续会话任一关闭
- **THEN** 后端以对应 `session_policy` 字段级错误拒绝保存

#### Scenario: 管理端选择 Docling Profile
- **WHEN** 管理员在组成配置中选择 `docling-text-v1`
- **THEN** 前端同时开启任务工作区、File MCP、消息附件和连续会话并选择当前 Agent Publication 可用的必需 File MCP 读取工具
- **AND** Agent Publication 缺少 Runtime 或工具能力时展示阻塞原因而不宣称配置可运行

#### Scenario: 既有历史 Publication 被读取
- **WHEN** 历史 Publication 含有先前允许的 Docling 组合
- **THEN** 系统保持其 snapshot、hash 和历史 Job 不变
- **AND** 更严格校验只约束新草稿、新 Publication 和新激活操作
