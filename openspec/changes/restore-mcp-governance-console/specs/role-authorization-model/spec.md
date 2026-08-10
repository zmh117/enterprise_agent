## MODIFIED Requirements

### Requirement: 自定义角色统一承载管理能力和业务访问能力
系统 SHALL 使用同一个自定义角色聚合代码拥有的管理后台权限、Application 使用权限和数据范围，且 MUST 将“平台管理角色”和“业务访问角色”仅作为模板或用途标签，不得作为互斥授权主体类型。角色 MUST NOT 保存 API Capability、MCP Tool 或 Resource Mapping 授权。

#### Scenario: 复合自定义角色生效
- **WHEN** 管理员为一个自定义角色同时配置运行记录查看权限和生产诊断 Application 使用权限
- **THEN** 该角色的启用成员同时获得两类权限，且运行时 MCP 集合仍受当前 Application Publication 和数据范围约束

### Requirement: 角色成员关系支持状态和失效时间
系统 SHALL 允许人员账号和服务账号加入一个或多个角色，并 MUST 只展开启用角色、启用成员关系且尚未到期的成员关系。成员有效期为空时表示长期有效，到期后 MUST 立即停止参与新的权限决策。

#### Scenario: 临时成员到期
- **WHEN** 某成员关系的失效时间已经到达
- **THEN** 系统在新的授权决策中忽略该成员关系，并在管理端显示“已到期”

#### Scenario: 服务账号加入业务角色
- **WHEN** 管理员把服务账号加入仅包含 Application 使用和数据范围的角色
- **THEN** 系统允许该成员关系参与非交互式业务入口授权

#### Scenario: 服务账号加入管理角色
- **WHEN** 管理员尝试把服务账号加入包含任一 Web 管理权限的角色
- **THEN** 系统拒绝保存并提示服务账号不能获得 Web 管理能力

### Requirement: 多角色权限按允许并集和拒绝优先求值
系统 SHALL 合并用户全部有效角色的管理权限、Application 使用允许和数据范围，并 MUST 让命中的高级显式拒绝优先于任一用户直接允许或角色允许。系统 MUST 为最终结果保留可安全展示的来源信息，且 MUST NOT 通过角色并集合成 MCP Tool 授权。

#### Scenario: 两个角色提供不同数据范围
- **WHEN** 用户通过两个有效角色获得同一 Application 下两个不同基地的允许范围
- **THEN** 用户对该 Application 的有效数据范围为两个基地的并集

#### Scenario: 高级拒绝覆盖角色允许
- **WHEN** 用户的角色允许某 Application 但用户主体命中该 Application 或数据范围的高级拒绝例外
- **THEN** 系统拒绝对应访问并在安全解释中标记存在高级拒绝，不暴露原始敏感策略内容

#### Scenario: 两个角色面对同一 Publication
- **WHEN** 用户的多个角色都允许同一 Application
- **THEN** 可调用 MCP Tool 仍只来自当前激活 Publication，不因角色数量增加而扩大

### Requirement: 角色授权按独立授权区进行并发控制
系统 SHALL 至少将角色基本信息、成员关系、管理后台权限、Application 使用与数据范围划分为独立授权区，每个授权区 MUST 使用独立 revision 或等价并发控制。一个授权区的保存 MUST 在单个数据库事务中原子完成，且不得覆盖操作者无权编辑的其它授权区。

#### Scenario: 两名管理员编辑不同授权区
- **WHEN** 平台权限管理员保存管理后台权限，同时业务授权管理员保存同一角色的 Application 范围
- **THEN** 两次操作分别按各自 revision 提交且互不覆盖

#### Scenario: 授权区版本冲突
- **WHEN** 管理员使用过期 revision 提交授权区修改
- **THEN** 系统拒绝该次修改并要求刷新，不得静默覆盖新配置

### Requirement: 授权编辑不得扩大到操作者可授权范围之外
系统 SHALL 将操作者的运行使用权限与可授权管理范围分开计算。非 `platform-admin` 操作者只能配置被明确委派给自己的管理对象、Application 和数据范围，并 MUST NOT 通过创建、复制、编辑或分配角色实现自我提权，亦不得在角色中写入 MCP Tool 或 Resource Deployment。

#### Scenario: 超出委派范围
- **WHEN** 业务授权管理员尝试把未委派给自己的 Application 或基地加入角色
- **THEN** 系统拒绝整个授权区提交并返回中文字段错误

#### Scenario: 复制角色包含越权项
- **WHEN** 管理员复制的来源角色包含超出其可授权范围的 Application、管理权限或数据范围
- **THEN** 系统要求移除越权项后才能创建新角色，不得静默保留

#### Scenario: 客户端注入 Tool 权限
- **WHEN** 客户端在角色授权请求中提交 MCP Tool 或 Resource Deployment 标识
- **THEN** 系统拒绝这些不属于角色模型的字段且不改变角色

