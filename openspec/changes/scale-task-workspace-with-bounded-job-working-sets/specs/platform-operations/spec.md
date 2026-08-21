## ADDED Requirements

### Requirement: 工作区文件数量使用受治理tenant运行配置
平台 Runtime Config SHALL注册非敏感整数`FILE_WORKSPACE_ACTIVE_FILE_LIMIT`，定义默认值200、适用`file-service`且代码硬上限1000。Runtime Config scope SHALL增加`tenant`，但只有代码显式声明tenant-compatible的定义才可使用；scope code MUST从已认证管理上下文中的平台tenant身份校验，不得由普通业务请求或Agent输入覆盖。

管理员创建、修改、禁用tenant覆盖时 MUST经过现有平台配置管理权限、乐观revision和配置审计。File Service有效配置诊断 MUST返回脱敏的值、来源和revision；Job审计 MUST记录观察到的有效值与revision，但公开健康检查不得暴露tenant目录或文件身份。

#### Scenario: tenant使用默认配额
- **WHEN** 没有启用的tenant覆盖且兼容上线门禁已通过
- **THEN** File Service有效配置返回文件数量上限200及definition-default来源
- **AND** 代码仍对任何结果应用1000硬上限

#### Scenario: 管理员设置tenant覆盖
- **WHEN** 授权管理员把目标tenant上限从200改为500并提供正确expected revision
- **THEN** 平台保存新revision并写入不含文件身份的配置审计
- **AND** 后续File Service有效快照对该tenant使用500

#### Scenario: 非兼容定义尝试tenant scope
- **WHEN** 管理员对未声明tenant-compatible的其它Runtime Config key提交tenant scope
- **THEN** 平台在保存前拒绝
- **AND** 不扩大该配置在其它tenant或服务中的作用范围

### Requirement: 提升tenant工作区配额前必须通过兼容预检
平台在把任一tenant有效工作区文件数量从20或更低提升到20以上前，MUST只读检查该tenant所有启用且使用任务工作区的Agent/Application Publication是否冻结兼容的`task_workspace_search_files`及必要File MCP Tool。任一不兼容发布 MUST阻止提升，并返回有界、非敏感的Application/Publication身份和修复原因；预检 MUST NOT原地修改或自动重发任何Publication。

#### Scenario: 所有启用Publication均兼容
- **WHEN** 目标tenant的启用任务工作区Application均冻结兼容Tool且配额值不超过1000
- **THEN** 管理员可发布新的tenant配额revision
- **AND** 审计同时记录预检结果摘要和配置变更

#### Scenario: 存在不兼容历史Publication
- **WHEN** 目标tenant仍有一个启用Application Publication缺少新发现Tool
- **THEN** 平台拒绝把有效上限提升到200
- **AND** 不修改该Publication、现有工作区或历史Job

#### Scenario: 回滚配额到20
- **WHEN** 运维把已启用大工作区的tenant有效上限降回20
- **THEN** 已完成Job、追加工作集事实和已有文件保持不变
- **AND** 超过20个ACTIVE文件的工作区保持可读但拒绝新增逻辑文件

### Requirement: 大工作区上线必须保存容量与全链证据
上线验收 MUST覆盖200和1000个ACTIVE文件、50个元数据候选、20个内容工作集项、并发目录revision变化、并发Job和Docling Representation状态，并记录Snapshot行数、Manifest大小、Job创建与搜索延迟、数据库查询计划以及工作集上限拒绝。生产就绪声明 MUST至少包含一次真实Runtime调用File MCP搜索、选择精确版本、物化可读内容并形成Agent结果或Delivery的全链证据；容器健康或单元测试单独不足以证明完成。

#### Scenario: 1000文件容量压测
- **WHEN** 测试工作区具有1000个ACTIVE文件且创建只绑定2个内容项的Job
- **THEN** Snapshot和Runtime Manifest仍受20内容项与50候选上限约束
- **AND** 证据记录搜索分页延迟、查询计划和数据库行数而不记录正文

#### Scenario: 真实全链验收
- **WHEN** 兼容Publication通过真实Python Runtime搜索并选择一份Docling可读文档
- **THEN** 证据证明精确Representation被物化、Agent读取并产生受治理结果或Delivery
- **AND** 未选中的工作区文件没有进入Sandbox
