## ADDED Requirements

### Requirement: 知识分析沿用既有聊天模型而向量化保持本地
系统 SHALL 保持知识 Embedding 在本地或内网执行，不因聊天模型故障而回退到外部 Embedding 服务。用户已明确接受：经双重授权获得的检索引用、ONES 正文及其上下文可以进入 Agent 现有配置的聊天模型，包括外部模型；本地 Embedding MUST NOT 被描述为全文链路不外发。

知识能力 MUST 复用现有模型连接、Publication 冻结版本、Runtime 签名和模型映射规则。系统 MUST NOT 为知识工具另设强制内网模型认可文件、internal_only 发布门禁或 Session/摘要/产物继承机制，也不为此升级 Runtime 协议或扩大 Runtime 数据库读取权限。

#### Scenario: 本地 Embedding 配合外部聊天模型
- **WHEN** Agent 配置合法且可用的外部聊天模型，并满足知识工具发布依赖
- **THEN** 允许发布和按既有模型配置执行，不要求新增部署认可；向量化仍使用内部 Embedding

#### Scenario: 模型冻结与 Runtime 隔离
- **WHEN** 已发布 Agent 使用知识能力
- **THEN** 仍按既有固定模型版本、签名请求和最小数据库权限执行，不允许知识参数覆盖模型连接或凭据

#### Scenario: Embedding 服务不可用
- **WHEN** 本地 Embedding 调用失败
- **THEN** 返回安全依赖错误，不将查询或文档转发外部 Embedding，也不解释为无相关记录

### Requirement: 允许外部聊天不得放宽知识读取和诊断边界
Agent Envelope 与 Application 有效工具子集选择任一知识工具时，MUST 同时包含 knowledge_list_bases、knowledge_search 和 ones_get_work_item_detail；发布前校验完整依赖，不把已知缺项延迟为 Job 运行失败。Worker MUST 在模型或摘要处理前验证当前业务应用 Job、知识工具与详情 Tool 的有效授权；具体命中仍需 KB 与本人 ONES 双重校验。移除强制内网聊天限制 MUST NOT 绕过这些条件，也不自动注册或授权新工具。

通用日志、指标和外部遥测 MUST NOT 新增检索 query、向量、业务正文、被拒绝候选或凭据。既有受控运行记录的访问、保留和导出合同保持生效。

#### Scenario: 应用子集缺少详情工具
- **WHEN** 应用选择 knowledge_search 但没有 ones_get_work_item_detail
- **THEN** 发布拒绝，不自动授予详情权限

#### Scenario: 执行前权限被撤销
- **WHEN** 当前 Job 的知识工具或详情 Tool grant 已失效
- **THEN** Worker 在解析模型和生成历史摘要前拒绝，外部聊天获准不代表读取获准

#### Scenario: 知识工具未成套选择
- **WHEN** Agent 或应用只选择 knowledge_list_bases 或只选择 knowledge_search，即使已有详情工具
- **THEN** 发布前返回明确的工具依赖错误，不自动补选或授予缺少工具
