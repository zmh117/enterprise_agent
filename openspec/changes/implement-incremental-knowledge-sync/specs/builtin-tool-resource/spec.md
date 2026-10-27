## MODIFIED Requirements

### Requirement: 知识资源与固定目录检索必须执行当前双重授权
系统 SHALL 通过已验证、已发布且当前启用的知识资源和代码固定 `knowledge_list_bases`、`knowledge_search` 提供读取。发布 SHALL 只确认知识库及其来源、存储、模型和分块配置可用，不冻结成员、数量或内容摘要；正常内容更新不得改变发布修订或要求重新发布。Knowledge MCP MUST 验证自身 audience/scope、RUNNING Job、冻结工具合同、当前用户/应用/角色 KB 范围及资源发布配置；目录可见 MUST NOT 被解释为所有文档可读，命中 MUST 再校验当前文档版本及用户 ONES 可读权限。新工具、收录、索引和目录变化 MUST NOT 自动扩大旧 Publication 或 Job 权限。

#### Scenario: 发现当前知识库
- **WHEN** 当前 Job 获准调用知识目录
- **THEN** 每页最多返回 50 个当前可用知识库的安全身份、名称和状态，提供有界续页，不返回正文或文档计数

#### Scenario: 授权或发布配置变化
- **WHEN** 用户/应用/角色 KB 权限撤销、资源停用或发布配置变化
- **THEN** 目录或检索失败关闭，不回退旧配置；普通内容更新不触发发布配置变化错误

#### Scenario: 来源事项不可读
- **WHEN** 向量候选对应事项未通过当前用户 ONES 可读性校验
- **THEN** 不返回该事项引用，也不以服务账号或知识库授权代替个人权限

#### Scenario: 内容独立生效
- **WHEN** 已发布知识库新增文档完成向量处理
- **THEN** 该文档可参与检索，资源发布修订及未变更文档保持不变
