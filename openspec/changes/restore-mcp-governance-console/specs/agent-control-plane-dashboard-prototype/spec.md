## REMOVED Requirements

### Requirement: 原型提供Agent应用平台静态Shell
**Reason**: 管理 Shell 已进入真实治理阶段，静态原型导航会与当前 MCP 控制面产生错误语义。

**Migration**: 使用认证后的管理 Shell 和权限感知导航；已退役的 API Capability 菜单不迁移。

### Requirement: Dashboard明确区分原型数据与真实运行数据
**Reason**: Dashboard 将只展示真实、范围过滤后的服务端聚合，不再使用静态原型指标。

**Migration**: 删除本地 fixture 和“原型数据”卡片，改为安全聚合 API 的时间戳与数据范围说明。

### Requirement: Dashboard展示目标控制面全景
**Reason**: 原全景包含 Capability Gateway 和独立 API Platform，二者已在 MCP 基线中退役。

**Migration**: Dashboard 改为展示 Channel、Application、Agent Runtime、MCP Server、Resource 和 Delivery 的当前链路摘要。

### Requirement: 原型不得执行真实业务或网络行为
**Reason**: 真实 Dashboard 必须读取服务端安全聚合和执行受控刷新，不能继续禁止全部网络行为。

**Migration**: 仅允许调用认证、授权且固定用途的 Dashboard API；Dashboard 本身不提供通用命令执行。

## ADDED Requirements

### Requirement: Dashboard 展示真实且范围过滤的控制面摘要
系统 SHALL 通过专用管理 API 展示当前用户有权查看的 Agent、Application、Publication、Channel、Job、MCP Server、Tool、Resource 和 Credential 健康摘要，并 MUST 显示聚合时间和数据范围说明。

#### Scenario: 平台管理员查看总览
- **WHEN** 平台管理员打开 Dashboard
- **THEN** 页面从真实 API 加载全局治理摘要，不使用静态 fixture 或伪造记录

#### Scenario: 受限管理员查看总览
- **WHEN** 用户只拥有部分 Application 或管理域读取权限
- **THEN** API 只聚合允许对象，且不得通过总数、名称或错误详情泄露不可见对象

### Requirement: Dashboard 展示当前 MCP 运行链路
系统 SHALL 以可读摘要展示 `Channel/Debug → Application Publication → Agent Runtime → MCP Server/Tool → Resource Generation → Delivery` 的当前链路和异常位置，并 MUST NOT 展示已退役 API/Internal Platform 为运行节点。

#### Scenario: Resource Generation 异常
- **WHEN** 某可见 Application 的当前资源 Generation 不可用
- **THEN** Dashboard 标出受影响 Application、异常阶段和脱敏原因，不显示连接密码或 Tool 输入

### Requirement: Dashboard 只允许安全读取和刷新
Dashboard SHALL 只执行认证后的聚合读取和受控刷新，不得接受任意查询表达式、数据库查询、URL 或运行命令，也不得从聚合卡片直接绕过对象页面的写操作确认。

#### Scenario: 用户刷新 Dashboard
- **WHEN** 用户点击刷新
- **THEN** 页面重新读取固定聚合 API 并更新获取时间，不触发发布、资源切换或运行命令

## MODIFIED Requirements

### Requirement: 原型支持桌面和窄屏评审
系统 SHALL 在桌面和窄屏下保持导航、卡片、运行链路、表格和身份关系可读，状态信息 MUST 不只依赖颜色表达。

#### Scenario: 窄屏查看 Dashboard
- **WHEN** 用户在移动端宽度查看 Dashboard
- **THEN** 侧栏可收起且内容按单列或纵向流程排列
- **AND** 不出现阻止阅读的横向页面溢出

#### Scenario: 使用辅助技术识别状态
- **WHEN** 用户通过键盘或辅助技术浏览 Dashboard
- **THEN** 导航、状态、受限动作和图标具有可理解的文本或无障碍名称
- **AND** 运行状态可由文字、Badge 或图标共同识别

