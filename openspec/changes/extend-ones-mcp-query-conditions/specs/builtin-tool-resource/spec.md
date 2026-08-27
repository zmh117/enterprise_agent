## ADDED Requirements

### Requirement: ONES MCP必须按当前Team解析受管查询条件
系统 SHALL 提供只读 `ones_resolve_query_conditions`，只允许按名称查询受管快照中的状态和单选/多选自定义字段选项。快照 MUST 固定 schema version、来源 Team、采集时间和内容摘要，调用时 MUST 与当前 ONES Principal 的默认 Team 匹配；系统 MUST NOT 返回整份字典、人员列表、项目列表、迭代列表、凭据或原始抓取响应。

#### Scenario: 按中文名称解析严重程度
- **WHEN** 当前 Principal Team 与快照一致且用户按字段中文名和选项中文名查询
- **THEN** Tool 返回有界候选的字段 UUID、字段名、选项 UUID 和选项名
- **AND** Provider 筛选键保留在 MCP 服务端，不暴露给 Agent
- **AND** 同名候选全部保留且不自动选择第一项

#### Scenario: 字典Team与当前Principal不一致
- **WHEN** 当前 Principal 的默认 Team 与受管快照来源 Team 不一致
- **THEN** Tool 在返回任何映射前失败关闭
- **AND** 不尝试其他 Team、不回退到个人抓取文件或旧快照

#### Scenario: 查询人员项目或迭代静态字典
- **WHEN** Agent 需要解析人员、项目、迭代或事项类型
- **THEN** 系统要求使用对应实时 ONES 查询 Tool
- **AND** 受管条件快照不提供这些静态映射

### Requirement: ONES工作项查询必须通过独立Tool支持受校验的自定义选项筛选
系统 SHALL 提供 `ones_query_work_items_with_custom_options`，在既有标准筛选之上要求至少一个且数量有界的 `custom_option_filters`，每项只包含字段 UUID 与一个或多个选项 UUID。系统 MUST 保持 `ones_query_work_items` 的输入契约与 schema hash 不变，并在当前 Team 的受管字典中验证字段、字段类型和选项归属，再确定性转换为固定 GraphQL `filterGroup` 的 `_<field_uuid>_in` 条件；MUST NOT 接受 Agent 提交的原始筛选键、任意 GraphQL 文本或自由 JSON。

#### Scenario: 查询指定自定义选项的工作项
- **WHEN** 调用方提交字典中存在的单选或多选字段 UUID 及其合法选项 UUID
- **THEN** `ones_query_work_items_with_custom_options` 使用集中保存的固定 GraphQL 文档和已校验变量查询工作项
- **AND** 结果继续遵守既有条数、响应大小、字段投影和审计限制

#### Scenario: 选项不属于指定字段
- **WHEN** 调用方把一个合法选项 UUID 放到另一个字段 UUID 下
- **THEN** ONES MCP 在访问 Provider 前拒绝请求
- **AND** 审计不记录整份字典或未投影的业务响应

#### Scenario: 提交任意Provider筛选键
- **WHEN** 调用方提交原始 `filterGroup`、自定义筛选键或自由 JSON
- **THEN** Tool 输入校验拒绝请求
- **AND** 不构造或执行动态 GraphQL 文档

#### Scenario: 历史标准查询契约保持稳定
- **WHEN** 发布新的自定义选项查询 Tool
- **THEN** `ones_query_work_items` 的输入 schema 与 schema hash 保持不变
- **AND** 旧 Publication 与旧 Job 不会因本次新增能力发生契约漂移

### Requirement: ONES MCP必须按UUID批量查询安全用户摘要
系统 SHALL 提供只读 `ones_get_users_by_uuids`，只接受唯一、有界的用户 UUID 列表，并使用固定 REST `POST /project/api/project/team/{team_uuid}/users` 查询当前 Principal 默认 Team。输出 MUST 只包含用户 UUID 与姓名。

#### Scenario: 批量反查用户UUID
- **WHEN** 当前用户提交一个或多个合法用户 UUID
- **THEN** Tool 使用当前个人 ONES Token 调用固定 Team users REST 接口
- **AND** 返回顺序稳定的 UUID 与姓名列表以及有界统计信息

#### Scenario: Provider返回额外个人字段
- **WHEN** ONES 响应包含邮箱、手机号、部门、公司、头像、MFA 或邀请人等字段
- **THEN** Tool 不在输出、日志或审计中投影这些字段
- **AND** 只保留 UUID 与姓名

#### Scenario: 用户UUID列表非法或超限
- **WHEN** 输入为空、重复、格式非法或超过上限
- **THEN** Tool 在访问 ONES 前返回稳定输入错误

### Requirement: ONES查询条件快照必须由个人抓取安全派生
系统 SHALL 通过确定性同步步骤从本地忽略的查询条件 YAML 生成运行快照，且生成结果 MUST 排除人员、项目、迭代、Header、Token、Cookie、邮箱、手机号、部门和原始响应。生产、Mock 和测试代码 MUST NOT 在运行时读取 `ones_mock/ones/`。

#### Scenario: 同步更新后的查询条件字典
- **WHEN** 维护者运行同步步骤处理结构合法且 Team 元数据完整的源 YAML
- **THEN** 生成结果只包含允许的状态、自定义选项和非敏感版本元数据
- **AND** 相同输入生成字节一致的结果和摘要

#### Scenario: 源字典缺少作用域或字段语义
- **WHEN** 源 YAML 缺少 Team、采集日期、自定义字段中文名或合法选项结构
- **THEN** 同步失败且不改写已存在的运行快照

#### Scenario: 架构测试检查Mock目录依赖
- **WHEN** 测试扫描生产、Mock 和测试运行时代码
- **THEN** 不存在对 `ones_mock/ones/` 的文件读取或导入
- **AND** 只有显式维护同步脚本可以把该目录作为人工触发的输入
