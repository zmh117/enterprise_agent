## MODIFIED Requirements

### Requirement: 角色详情按授权区组织
系统 SHALL 在角色详情中提供“基本信息”“成员”“管理后台权限”“Application 使用与数据范围”“有效权限预览”“操作记录”区域，并 MUST 根据当前操作者的分区权限将无权编辑的区域设为只读。页面 MUST NOT 提供 API Capability、MCP Tool 或 Resource Mapping 编辑区。

#### Scenario: 业务授权管理员打开复合角色
- **WHEN** 操作者只能编辑 Application 使用与数据范围授权区
- **THEN** 页面允许修改 Application 和数据范围，只读显示管理后台权限和当前 Publication 安全上限，且提交不得包含其它区域修改

### Requirement: 角色授权使用勾选和明确层级配置
系统 SHALL 使用中文名称、风险说明和层级选择器配置代码拥有的管理权限、Application 使用权限、环境、基地和车间范围，不得要求普通管理员输入原始 `resource_type`、`resource_code`、`action`、`priority`、MCP Tool 编码或 Resource Deployment ID。

#### Scenario: 当前只有 local 环境
- **WHEN** 管理员配置 Application 数据范围且系统只有 `local`
- **THEN** 页面显式展示并允许勾选 `local` 根节点，不展示虚假的多环境切换器

#### Scenario: 存在未保存修改
- **WHEN** 管理员切换页签或离开含有未提交勾选的角色页面
- **THEN** 页面提示存在未保存修改，防止意外丢失

#### Scenario: 客户端提交任意权限代码
- **WHEN** 客户端提交不属于服务端代码拥有目录的管理权限字符串
- **THEN** 后端拒绝整个授权区，不把任意字符串持久化为权限

### Requirement: 管理端提供安全的有效权限模拟
系统 SHALL 允许有权操作者按“用户 + Application + 数据范围”模拟授权决策，并 MUST 返回最终允许或拒绝、来源角色、Application 授权来源、数据范围来源和当前 Publication MCP 安全上限摘要。响应 MUST NOT 包含凭据、敏感条件、Tool 参数、内部 Resource 引用或未脱敏原始策略。

#### Scenario: 用户缺少 Application 授权
- **WHEN** 管理员模拟已绑定但没有业务角色的用户访问某 Application
- **THEN** 页面显示“未获得该 Application 的使用权限”，而不是暴露底层 Agent、MCP 或 Resource 策略错误

#### Scenario: Application Publication 未允许 Tool
- **WHEN** 用户有 Application 权限但当前 Publication 未发布目标 MCP Tool
- **THEN** 模拟结果显示被 Publication 安全上限阻止，且不提供在角色页面直接启用 Tool 的操作

## ADDED Requirements

### Requirement: 角色页面展示代码拥有权限目录
系统 SHALL 从服务端读取代码拥有的管理权限目录和风险元数据，按读/写/发布/高风险操作分组显示；前端本地常量只能用于显示兜底，不得成为授权事实源。

#### Scenario: 服务端新增管理权限
- **WHEN** 新版本注册一个新的管理权限代码
- **THEN** `platform-admin` 自动获得该权限，其他角色默认不获得，角色页面按服务端目录显示该项

### Requirement: 角色页面只读展示 Publication 运行上限
系统 SHALL 在 Application 授权摘要中只读展示当前激活 Publication 的 MCP Tool 和 Resource kind 上限，且 MUST 明确说明角色只能授予 Application 使用和数据范围，不能扩大发布上限。

#### Scenario: Publication 收紧 Tool 集合
- **WHEN** Application 激活的新 Publication 移除一个 MCP Tool
- **THEN** 角色页面更新只读上限摘要，角色成员不再能调用该 Tool，且角色记录无需改写

