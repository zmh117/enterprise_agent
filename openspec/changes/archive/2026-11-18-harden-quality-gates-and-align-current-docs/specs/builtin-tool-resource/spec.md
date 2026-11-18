## MODIFIED Requirements

### Requirement: MCP Server 与鉴权模式必须固定
Python Runtime SHALL 只连接部署固定的 `tool-mcp`、`file-mcp`、`ones-mcp`、`dingtalk-mcp`、`knowledge-mcp`，使用标准 Streamable HTTP。每个 Server MUST 在代码策略中声明唯一鉴权模式；`tool-mcp` 使用受信 Job context，文件、业务和知识 MCP 使用各自 Principal 合同。Runtime MUST NOT 直连业务数据库、Redis、Loki 或知识存储，也不得接受 payload 或 Tool 参数覆盖 Server URL、鉴权模式或 audience。

#### Scenario: 查询资源证据
- **WHEN** Runtime 调用 `query_database`
- **THEN** 固定 `tool-mcp` 执行受治理查询，数据库凭据不进入 Runtime

#### Scenario: 请求改写 Server
- **WHEN** Job 或 Tool Input 提供任意 MCP URL、auth mode 或 credential profile
- **THEN** 系统拒绝动态覆盖，不建立额外执行入口

## ADDED Requirements

### Requirement: 知识资源与固定目录检索必须执行当前双重授权
系统 SHALL 通过已验证、已发布且当前启用的知识资源和代码固定 `knowledge_list_bases`、`knowledge_search` 提供读取。Knowledge MCP MUST 验证自身 audience/scope、RUNNING Job、冻结工具合同、当前用户/应用/角色 KB 范围及资源发布事实；目录可见 MUST NOT 被解释为所有文档可读，检索命中 MUST 再校验当前用户 ONES 可读权限。新工具、收录、索引和目录变化 MUST NOT 自动扩大旧 Publication 或 Job 权限。

#### Scenario: 发现当前知识库
- **WHEN** 当前 Job 获准调用知识目录
- **THEN** 每页最多返回 50 个当前可用知识库的安全身份、名称和状态，提供有界续页，不返回正文或文档计数

#### Scenario: 授权或发布事实变化
- **WHEN** 用户/应用/角色 KB 权限撤销、资源停用或当前发布版本变化
- **THEN** 目录或检索失败关闭，不回退旧版本继续返回结果

#### Scenario: 来源事项不可读
- **WHEN** 向量候选对应事项未通过当前用户 ONES 可读性校验
- **THEN** 不返回该事项引用，也不以服务账号或知识库授权代替个人权限

### Requirement: 知识检索必须有界且只返回可读引用
`knowledge_search` SHALL 接受明确 `knowledge_base_id`、1–2000 字符非空查询和默认 10、范围 1–20 的 `top_k`，不得允许覆盖身份、Team、filter、collection、向量或服务地址。目录和检索 SHALL 受最多 120 秒及当前 Job 剩余预算共同约束。检索 SHALL 只返回文档/修订/索引/来源/工作项引用、编号、分数和每项最多三条证据位置/hash，不返回缓存标题、摘要或正文；获取最新正文 SHALL 使用已有 ONES 详情工具。零命中、受限部分结果和依赖失败 MUST 分别表达，认证材料、查询原文和业务正文不得复制到普通安全摘要或日志。

#### Scenario: 合法检索
- **WHEN** 合同、索引与当前权限均有效且存在可读命中
- **THEN** 返回当前版本的有界引用与证据位置，正文仍通过受治理 ONES 详情工具取得

#### Scenario: 预算或依赖失败
- **WHEN** 总预算耗尽、依赖异常或读取投影不完整
- **THEN** 返回稳定失败；正常有界搜索产生部分结果时明确 `partial`，不能将依赖失败报告为空库
